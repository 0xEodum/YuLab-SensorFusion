import { createServer } from "node:http";
import { createHash } from "node:crypto";
import { createInterface } from "node:readline";
import { mkdir, readFile, readdir, writeFile, rename } from "node:fs/promises";
import { basename, dirname, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";
import { chromium } from "@playwright/test";

const root = resolve(fileURLToPath(new URL("../../", import.meta.url)));
const catalogRoot = resolve(root, "frontend/public/catalog");

function fail(message) {
  process.stderr.write(`${message}\n`);
  process.exitCode = 1;
}

function parseArgs() {
  const args = process.argv.slice(2), result = {};
  for (let i = 0; i < args.length; i++) {
    if (args[i] === "--session") result.session = true;
    else if (args[i] === "--capabilities") result.capabilities = true;
    else if (["--request", "--output"].includes(args[i])) result[args[i].slice(2)] = args[++i];
    else throw new Error(`Unknown worker argument: ${args[i]}`);
  }
  if (!result.capabilities && !result.session && (!result.request || !result.output))
    throw new Error("Worker requires --request and --output");
  return result;
}

async function browserBundle() {
  const result = await build({
    entryPoints: [resolve(root, "workers/capture/browser.ts")],
    bundle: true,
    format: "esm",
    platform: "browser",
    target: "es2022",
    write: false,
    sourcemap: false,
    logLevel: "silent",
  });
  return result.outputFiles[0].text;
}

async function server(bundle) {
  const value = createServer(async (request, response) => {
    try {
      const url = new URL(request.url ?? "/", "http://127.0.0.1");
      if (url.pathname === "/") {
        response.setHeader("content-type", "text/html; charset=utf-8");
        response.end('<!doctype html><html><body><script type="module" src="/browser.js"></script></body></html>');
        return;
      }
      if (url.pathname === "/browser.js") {
        response.setHeader("content-type", "text/javascript; charset=utf-8");
        response.end(bundle);
        return;
      }
      if (url.pathname === "/favicon.ico") {
        response.statusCode = 204;
        response.end();
        return;
      }
      if (url.pathname.startsWith("/catalog/")) {
        const relative = decodeURIComponent(url.pathname.slice("/catalog/".length));
        const path = resolve(catalogRoot, relative);
        if (!path.startsWith(catalogRoot + sep)) throw new Error("Invalid catalog path");
        const bytes = await readFile(path);
        response.setHeader("content-type", path.endsWith(".json") ? "application/json" : "model/gltf-binary");
        response.end(bytes);
        return;
      }
      response.statusCode = 404;
      response.end("not found");
    } catch (error) {
      response.statusCode = 500;
      response.end(error instanceof Error ? error.message : String(error));
    }
  });
  await new Promise((accept, reject) => {
    value.once("error", reject);
    value.listen(0, "127.0.0.1", accept);
  });
  const address = value.address();
  if (!address || typeof address === "string") throw new Error("Worker server did not bind TCP");
  return { value, url: `http://127.0.0.1:${address.port}/` };
}

async function launch() {
  const attempts = [];
  const choices = [process.env.PLAYWRIGHT_CHANNEL || null, null, process.platform === "win32" ? "msedge" : null]
    .filter((value, index, values) => values.indexOf(value) === index);
  for (const channel of choices) {
    try {
      const browser = await chromium.launch({
        headless: true,
        channel: channel || undefined,
        args: process.env.PLAYWRIGHT_GPU === "1" ? [] : ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"],
      });
      return { browser, channel: channel || "playwright-chromium" };
    } catch (error) {
      attempts.push(`${channel || "playwright-chromium"}: ${error instanceof Error ? error.message.split("\n")[0] : String(error)}`);
    }
  }
  throw new Error(`No Chromium runtime available (${attempts.join("; ")})`);
}

function npy(bytes, descr, shape) {
  const magic = Buffer.from([0x93, 0x4e, 0x55, 0x4d, 0x50, 0x59, 1, 0]);
  const tuple = shape.length === 1 ? `${shape[0]},` : shape.join(", ");
  const body = `{'descr': '${descr}', 'fortran_order': False, 'shape': (${tuple}), }`;
  const padding = " ".repeat((16 - ((10 + Buffer.byteLength(body) + 1) % 16)) % 16);
  const header = Buffer.from(`${body}${padding}\n`, "ascii");
  const length = Buffer.alloc(2);
  length.writeUInt16LE(header.length);
  return Buffer.concat([magic, length, header, bytes]);
}

const sha256 = (bytes) => createHash("sha256").update(bytes).digest("hex");
async function artifact(output, name, bytes, mediaType) {
  await writeFile(resolve(output, name), bytes);
  return { id: name, sha256: sha256(bytes), byte_length: bytes.length, media_type: mediaType };
}

async function continuedThermalState(request, outputPath) {
  const environment = request.environment;
  if (environment.thermal_history !== "continued") {
    if (environment.thermal_state !== null)
      throw new Error("Equilibrated thermal capture must not reference prior state");
    return null;
  }
  const reference = environment.thermal_state;
  if (!reference || reference.media_type !== "application/json")
    throw new Error("Continued thermal capture requires a JSON thermal-state artifact");
  if (basename(reference.id) !== reference.id)
    throw new Error("Thermal-state artifact ID must be a file name");
  const artifactRoot = resolve(outputPath, "..");
  for (const entry of await readdir(artifactRoot, { withFileTypes: true })) {
    if (!entry.isDirectory() || entry.name.endsWith(".partial")) continue;
    const directory = resolve(artifactRoot, entry.name);
    const candidate = resolve(directory, reference.id);
    if (dirname(candidate) !== directory) continue;
    try {
      const bytes = await readFile(candidate);
      if (bytes.length === reference.byte_length && sha256(bytes) === reference.sha256)
        return bytes.toString("utf8");
    } catch (error) {
      if (error?.code !== "ENOENT") throw error;
    }
  }
  throw new Error("Referenced thermal-state artifact is unavailable or has the wrong hash");
}

async function run() {
  const args = parseArgs();
  const commands = args.session ? createInterface({ input: process.stdin, crlfDelay: Infinity }) : null;
  const commandIterator = commands?.[Symbol.asyncIterator]();
  const bundle = await browserBundle();
  const http = await server(bundle);
  const { browser, channel } = await launch();
  const version = browser.version();
  try {
    const page = await browser.newPage({ viewport: { width: 640, height: 384 }, deviceScaleFactor: 1 });
    page.on("console", (message) => {
      if (message.type() === "error") process.stderr.write(`browser: ${message.text()}\n`);
    });
    await page.goto(http.url, { waitUntil: "load" });
    await page.waitForFunction(() => typeof window.captureCapabilities === "function");
    if (args.capabilities) {
      const capabilities = await page.evaluate(() => window.captureCapabilities());
      process.stdout.write(`${JSON.stringify({
        protocol: "capture-worker.v1",
        browser: `Chromium ${version}`,
        channel,
        ...capabilities,
      })}\n`);
      return;
    }
    const captureOne = async (args) => {
      const requestPath = resolve(args.request);
      const outputPath = resolve(args.output);
      if (!requestPath.startsWith(root + sep) || !outputPath.startsWith(root + sep))
        throw new Error("Worker paths must remain inside the repository");
      const request = JSON.parse(await readFile(requestPath, "utf8"));
      await mkdir(outputPath, { recursive: true });
      const started = performance.now();
      const thermalState = await continuedThermalState(request, outputPath);
      const browserRequest = thermalState === null
        ? request
        : { ...request, _thermal_state_json: thermalState };
      const capture = await page.evaluate((value) => window.captureJob(value), browserRequest);
      const artifacts = {};
      artifacts.rgb = await artifact(outputPath, "rgb_png", Buffer.from(capture.rgb_png_base64, "base64"), "image/png");
      artifacts.rgb_raw = await artifact(outputPath, "rgb_raw_npy",
        npy(Buffer.from(capture.rgb_u8_base64, "base64"), "|u1", [capture.height, capture.width, 3]),
        "application/x-npy");
      artifacts.depth_preview = await artifact(outputPath, "depth_preview_png", Buffer.from(capture.depth_preview_png_base64, "base64"), "image/png");
      artifacts.instance_preview = await artifact(outputPath, "instance_preview_png", Buffer.from(capture.instance_preview_png_base64, "base64"), "image/png");
      artifacts.depth = await artifact(
        outputPath, "depth_npy",
        npy(Buffer.from(capture.depth_f32_base64, "base64"), "<f4", [capture.height, capture.width]),
        "application/x-npy",
      );
      artifacts.instance = await artifact(
        outputPath, "instance_npy",
        npy(Buffer.from(capture.instance_u32_base64, "base64"), "<u4", [capture.height, capture.width]),
        "application/x-npy",
      );
      if (capture.ir_calibration) {
        artifacts.ir_instance = await artifact(outputPath, "ir_instance_npy",
          npy(Buffer.from(capture.ir_instance_u32_base64, "base64"), "<u4", [capture.height, capture.width]),
          "application/x-npy");
        artifacts.ir_preview = await artifact(
          outputPath, "ir_preview_png",
          Buffer.from(capture.ir_preview_png_base64, "base64"),
          "image/png",
        );
        artifacts.ir_radiance = await artifact(
          outputPath, "ir_radiance_npy",
          npy(Buffer.from(capture.ir_radiance_f32_base64, "base64"), "<f4", [capture.height, capture.width]),
          "application/x-npy",
        );
        artifacts.ir_validity = await artifact(
          outputPath, "ir_validity_npy",
          npy(Buffer.from(capture.ir_validity_u8_base64, "base64"), "|b1", [capture.height, capture.width]),
          "application/x-npy",
        );
        artifacts.ir_saturation = await artifact(
          outputPath, "ir_saturation_npy",
          npy(Buffer.from(capture.ir_saturation_u8_base64, "base64"), "|b1", [capture.height, capture.width]),
          "application/x-npy",
        );
        artifacts.thermal_state = await artifact(
          outputPath, "thermal_state_json",
          Buffer.from(capture.thermal_state_json, "utf8"),
          "application/json",
        );
      }
      if (capture.lidar_calibration) {
        const pointShape = [capture.lidar_point_count];
        const beamShape = [capture.lidar_calibration.rows, capture.lidar_calibration.columns];
        const binary = (field) => Buffer.from(capture[field], "base64");
        artifacts.lidar_xyz = await artifact(outputPath, "lidar_xyz_npy",
          npy(binary("lidar_xyz_f32_base64"), "<f4", [capture.lidar_point_count, 3]), "application/x-npy");
        artifacts.lidar_intensity = await artifact(outputPath, "lidar_intensity_npy",
          npy(binary("lidar_intensity_f32_base64"), "<f4", pointShape), "application/x-npy");
        artifacts.lidar_beam_id = await artifact(outputPath, "lidar_beam_id_npy",
          npy(binary("lidar_beam_id_u32_base64"), "<u4", pointShape), "application/x-npy");
        artifacts.lidar_time_offset = await artifact(outputPath, "lidar_time_offset_npy",
          npy(binary("lidar_time_offset_f32_base64"), "<f4", pointShape), "application/x-npy");
        artifacts.lidar_validity = await artifact(outputPath, "lidar_validity_npy",
          npy(binary("lidar_validity_u8_base64"), "|b1", pointShape), "application/x-npy");
        artifacts.lidar_class_ref = await artifact(outputPath, "lidar_class_ref_npy",
          npy(binary("lidar_class_ref_u8_base64"), "|u1", pointShape), "application/x-npy");
        artifacts.lidar_beam_status = await artifact(outputPath, "lidar_beam_status_npy",
          npy(binary("lidar_beam_status_u8_base64"), "|u1", beamShape), "application/x-npy");
        artifacts.lidar_ideal_range = await artifact(outputPath, "lidar_ideal_range_npy",
          npy(binary("lidar_ideal_range_f32_base64"), "<f4", beamShape), "application/x-npy");
        artifacts.lidar_ideal_instance = await artifact(outputPath, "lidar_ideal_instance_npy",
          npy(binary("lidar_ideal_instance_u32_base64"), "<u4", beamShape), "application/x-npy");
        artifacts.lidar_ideal_class = await artifact(outputPath, "lidar_ideal_class_npy",
          npy(binary("lidar_ideal_class_u8_base64"), "|u1", beamShape), "application/x-npy");
        artifacts.lidar_range_preview = await artifact(outputPath, "lidar_range_preview_png",
          binary("lidar_range_preview_png_base64"), "image/png");
        artifacts.lidar_cloud_preview = await artifact(outputPath, "lidar_cloud_preview_png",
          binary("lidar_cloud_preview_png_base64"), "image/png");
        artifacts.lidar_topdown_preview = await artifact(outputPath, "lidar_topdown_preview_png",
          binary("lidar_topdown_preview_png_base64"), "image/png");
      }
      const result = {
        protocol: "capture-worker.v1",
        capture_id: request.plan.capture_id,
        sequence_id: request.plan.sequence_id,
        tick_s: capture.tick_s,
        width: capture.width,
        height: capture.height,
        renderer: `Chromium ${version} / ${capture.capabilities.renderer}`,
        device: capture.capabilities.vendor,
        browser_channel: channel,
        elapsed_ms: performance.now() - started,
        render_elapsed_ms: capture.elapsed_ms,
        timings_ms: capture.timings_ms,
        total_browser_ms: capture.total_browser_ms,
        geometry_cache: capture.geometry_cache,
        node_rss_bytes: process.memoryUsage().rss,
        browser_heap_bytes: await page.evaluate(() => performance.memory?.usedJSHeapSize ?? null),
        gpu_memory_bytes: null,
        resident_chunks: capture.resident_chunks,
        instance_ids: capture.instance_ids,
        posed_boxes: capture.posed_boxes,
        isolated_pixels: capture.isolated_pixels,
        truncated: capture.truncated,
        ir_calibration: capture.ir_calibration,
        lidar_calibration: capture.lidar_calibration,
        weather_calibration: capture.weather_calibration,
        lidar_point_count: capture.lidar_point_count,
        environment: request.environment,
        plan: request.plan,
        artifacts,
      };
      const metadata = Buffer.from(`${JSON.stringify(result, null, 2)}\n`);
      result.artifacts.metadata = await artifact(outputPath, "metadata_json", metadata, "application/json");
      await writeFile(resolve(outputPath, "result.json"), `${JSON.stringify(result, null, 2)}\n`);
      return result;
    };
    if (args.session) {
      // Read commands immediately so stdin arriving during browser startup is buffered.
      for await (const line of commandIterator) {
        const command = JSON.parse(line);
        const outputPath = resolve(command.output);
        if (!outputPath.startsWith(root + sep)) throw new Error("Worker paths must remain inside the repository");
        let response;
        try {
          await captureOne(command);
          response = { ok: true };
        } catch (error) {
          response = { ok: false, error: error instanceof Error ? error.message : String(error) };
        }
        const responsePath = resolve(outputPath, "worker-response.json");
        await writeFile(`${responsePath}.partial`, JSON.stringify(response));
        await rename(`${responsePath}.partial`, responsePath);
        if (!response.ok) break;
      }
    } else {
      const result = await captureOne(args);
      process.stdout.write(`${JSON.stringify(result)}\n`);
    }
  } finally {
    commands?.close();
    await browser.close();
    await new Promise((accept) => http.value.close(accept));
  }
}

run().catch((error) => fail(error instanceof Error ? (error.stack || error.message) : String(error)));

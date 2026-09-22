import { build } from "esbuild";
import { chromium } from "@playwright/test";
import { readFile, writeFile, mkdir } from "node:fs/promises";
import path from "node:path";
import { createHash } from "node:crypto";
import { createServer } from "node:http";
import { validatePayload } from "../packages/contracts/src/validate.ts";

const sourceRoot = process.argv[2];
if (!sourceRoot)
  throw new Error(
    "Usage: npm run assets:import -- <Generated source directory> [output directory]",
  );
const output = path.resolve(process.argv[3] ?? "frontend/public/catalog");
const projects = {
  f16: {
    project: "aircraft/f-16-aircraft",
    files: [
      "src/model/Airframe.tsx",
      "src/model/Part.tsx",
      "src/data/liveries.ts",
      "src/three/geometry.ts",
    ],
  },
  rq4: {
    project: "aircraft/rq-4-uav",
    files: [
      "src/components/GlobalHawk.tsx",
      "src/three/liveries.ts",
      "src/three/geometry.ts",
    ],
  },
  "ground-vehicle": { project: "AA/fk-2000-3d-model", files: ["src/model.ts"] },
};
const digest = (b) => createHash("sha256").update(b).digest("hex");
const sourceFiles = new Map();
for (const [id, p] of Object.entries(projects)) {
  p.hashes = [];
  for (const file of p.files) {
    const absolute = path.resolve(sourceRoot, p.project, file);
    let bytes;
    try {
      bytes = await readFile(absolute);
    } catch (e) {
      throw new Error(`${id}: missing source ${file}: ${e.code}`);
    }
    sourceFiles.set(absolute, bytes.toString());
    p.hashes.push({ path: file, sha256: digest(bytes) });
  }
}
const staticReact = path.resolve("tools/assets/static-react.mjs");
const aliases = {
  "source-f16": path.resolve(
    sourceRoot,
    projects.f16.project,
    projects.f16.files[0],
  ),
  "source-f16-liveries": path.resolve(
    sourceRoot,
    projects.f16.project,
    projects.f16.files[2],
  ),
  "source-rq4": path.resolve(
    sourceRoot,
    projects.rq4.project,
    projects.rq4.files[0],
  ),
  "source-rq4-liveries": path.resolve(
    sourceRoot,
    projects.rq4.project,
    projects.rq4.files[1],
  ),
  "source-vehicle": path.resolve(
    sourceRoot,
    projects["ground-vehicle"].project,
    "src/model.ts",
  ),
  react: staticReact,
  "react/jsx-runtime": staticReact,
  "@react-three/fiber": staticReact,
  "three/addons": path.resolve("node_modules/three/examples/jsm"),
  three: path.resolve("node_modules/three"),
};
const bundle = await build({
  entryPoints: ["tools/assets/import-browser.mjs"],
  bundle: true,
  write: false,
  format: "iife",
  jsx: "transform",
  jsxFactory: "StaticReact.createElement",
  jsxFragment: "StaticReact.Fragment",
  inject: [path.resolve("tools/assets/static-inject.mjs")],
  alias: aliases,
  plugins: [
    {
      name: "allowlisted-source",
      setup(builder) {
        builder.onLoad({ filter: /\.[tj]sx?$/ }, async (args) => {
          if (!args.path.startsWith(path.resolve(sourceRoot) + path.sep))
            return;
          const source = sourceFiles.get(args.path);
          if (source === undefined)
            throw new Error(`Source dependency not audited: ${args.path}`);
          // Preserve the source geometry names as semantic provenance without changing vertices.
          const contents = source.replace(
            /geometry=\{(G|geo)\.(\w+)\}/g,
            (_, obj, key) =>
              `geometry={Object.assign(${obj}.${key}, {name: '${key}'})}`,
          );
          return { contents, loader: args.path.endsWith("tsx") ? "tsx" : "ts" };
        });
      },
    },
  ],
  logLevel: "warning",
});
const server = createServer((req, res) => {
  res.setHeader(
    "Content-Type",
    req.url === "/bundle.js" ? "text/javascript" : "text/html",
  );
  res.end(
    req.url === "/bundle.js"
      ? bundle.outputFiles[0].contents
      : '<script src="/bundle.js"></script>',
  );
});
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
let browser;
try {
  browser = await chromium.launch({
    channel: process.env.PLAYWRIGHT_CHANNEL ?? "msedge",
    // Canvas livery rasterization must not switch between GPU and CPU backends.
    args: ['--disable-gpu','--disable-accelerated-2d-canvas'],
  });
  const page = await browser.newPage();
  page.on("pageerror", (e) => console.error(e));
  await page.goto(`http://127.0.0.1:${server.address().port}`);
  const results = await page.evaluate(() => window.importAssets());
  await mkdir(output, { recursive: true });
  const assets = [];
  const units = {
    length: "m",
    temperature: "K",
    angle: "rad",
    time: "s",
    world_frame: "east-up-south",
    matrix_layout: "row-major",
  };
  for (const result of results) {
    const p = projects[result.id],
      glb = Buffer.from(result.glb, "base64");
    const metadata = Buffer.from(
      JSON.stringify({ ...result.metadata, source_files: p.hashes }, null, 2) +
        "\n",
    );
    const artifact = (suffix, bytes, type) => ({
      id: `${result.id}-${suffix}`,
      sha256: digest(bytes),
      byte_length: bytes.length,
      media_type: type,
    });
    const record = {
      schema_version: "lab.v1",
      kind: "AssetRecord",
      asset_id: result.id,
      content_sha256: digest(glb),
      mesh: artifact("mesh", glb, "model/gltf-binary"),
      metadata: artifact("metadata", metadata, "application/json"),
      source: {
        project: p.project,
        revision: "content-addressed-source-files",
        sha256: digest(JSON.stringify(p.hashes)),
        adapter_version: "static-model.v1",
        use_permission:
          "User supplied catalog; authorized for this project. No independent third-party license assertion.",
      },
      units,
      scale_m_per_source_unit: 1,
      T_world_from_asset: [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
      contact_point_m: [0, 0, 0],
      class_name:
        result.id === "ground-vehicle" ? "ground_vehicle" : "aircraft",
      bounds: result.bounds,
      parts: result.parts,
      materials: result.materials,
      heat_sources: result.parts
        .filter((p) =>
          ["engine-surface", "exhaust-surface", "radiator-surface"].includes(p.semantic),
        )
        .map((p) => ({
          part_id: p.id,
          power_w: p.semantic === "exhaust-surface"
            ? 12_000
            : p.semantic === "radiator-surface"
              ? 2_500
              : 4_000,
          coupling_fraction: 1,
          operating_state: "running",
        })),
      thermal_model_version: "thermal-surface.v1",
    };
    validatePayload("AssetRecord", record);
    await writeFile(path.join(output, `${result.id}.glb`), glb);
    await writeFile(path.join(output, `${result.id}.metadata.json`), metadata);
    assets.push(record);
    console.log(
      `${result.id}: ${glb.length} bytes; ${result.metadata.validation.triangles} triangles; XYZ ${result.bounds.extent_m.map((v) => v.toFixed(3)).join(" / ")} m; ${record.content_sha256}`,
    );
  }
  await writeFile(
    path.join(output, "catalog.json"),
    JSON.stringify({ version: "asset-catalog.v1", assets }, null, 2) + "\n",
  );
} finally {
  await browser?.close();
  await new Promise((resolve) => server.close(resolve));
}

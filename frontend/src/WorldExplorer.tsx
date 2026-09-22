import { useEffect, useMemo, useRef, useState } from "react";
import {
  defaultWorldSpec,
  validateBookmark,
  type RigBookmark,
  aerodromeWorldSpec,
  aerodromeFixtures,
} from "@yulab/world";
import { loadCatalog, type Catalog } from "@yulab/assets";
import { validatePayload, type CaptureJob, type CaptureRequest, type RigSpec } from "@yulab/contracts";
import { WorldRuntime, type WorldStatus } from "./WorldRuntime";
import "./world.css";

const featureNames = {
  canyon: "Canyon arch",
  alpine: "Alpine ridge",
  islands: "Highland outcrops",
  coast: "Coastal bluff",
  aerodrome: "Aerodrome",
  harbor: "Harbor",
} as const;
// Read-only metrics plus the same navigation/rig operations used by the UI, opt-in for local acceptance.

export default function WorldExplorer() {
  const host = useRef<HTMLDivElement>(null),
    engine = useRef<WorldRuntime | null>(null);
  const [seed, setSeed] = useState(0),
    [draftSeed, setDraftSeed] = useState("0");
  const [location, setLocation] = useState(0),
    [view, setView] = useState("oblique");
  const [boundaries, setBoundaries] = useState(false),
    [pitch, setPitch] = useState<2 | 4>(4);
  const [navigation, setNavigation] = useState<"orbit" | "flight">("orbit");
  const [bookmarkName, setBookmarkName] = useState("Rig 1"),
    [bookmarks, setBookmarks] = useState<RigBookmark[]>([]);
  const [rigMessage, setRigMessage] = useState("");
  const [captureRig, setCaptureRig] = useState<RigSpec | null>(null);
  const [captureJob, setCaptureJob] = useState<CaptureJob | null>(null);
  const [captureError, setCaptureError] = useState("");
  const [aerodrome, setAerodrome] = useState(
    new URLSearchParams(window.location.search).get("site") === "aerodrome",
  );
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [catalogError, setCatalogError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    loadCatalog(controller.signal)
      .then(setCatalog)
      .catch((error) => {
        if (!controller.signal.aborted) setCatalogError(String(error));
      });
    return () => controller.abort();
  }, []);
  const [stats, setStats] = useState<WorldStatus>({
    ready: false,
    chunks: 0,
    triangles: 0,
    trees: 0,
    rocks: 0,
    milliseconds: 0,
    x: 0,
    z: 0,
    error: "",
  });
  const spec = useMemo(
    () =>
      aerodrome && catalog
        ? aerodromeWorldSpec(seed, catalog.assets)
        : defaultWorldSpec(seed),
    [seed, aerodrome, catalog],
  );
  useEffect(() => {
    if (!host.current) return;
    if (aerodrome && !catalog) return;
    let runtime: WorldRuntime | undefined;
    setStats((s) => ({ ...s, ready: false, triangles: 0, error: "" }));
    try {
      runtime = new WorldRuntime(
        spec,
        host.current,
        setStats,
        catalog ?? undefined,
      );
      engine.current = runtime;
      setCaptureRig(null);
      setCaptureJob(null);
      runtime.view(location, view);
      runtime.setPitch(pitch);
      runtime.chunks.setBoundaries(boundaries);
      setNavigation("orbit");
      if (new URLSearchParams(window.location.search).get("qa") === "1")
        window.worldQA = runtime;
      try {
        const saved: unknown = JSON.parse(
          localStorage.getItem(
            `strata-rigs-${aerodrome ? "aerodrome-" : ""}${seed}`,
          ) ?? "[]",
        );
        setBookmarks(
          Array.isArray(saved)
            ? saved.slice(0, 12).map((b) => validateBookmark(b, spec))
            : [],
        );
      } catch {
        setBookmarks([]);
        setRigMessage("Saved rig data could not be read.");
      }
    } catch (error) {
      setStats((s) => ({
        ...s,
        error: error instanceof Error ? error.message : String(error),
      }));
    }
    return () => {
      runtime?.dispose();
      engine.current = null;
      delete window.worldQA;
    };
    // World identity owns worker/cache lifetime; location changes only move the camera.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [spec]);
  useEffect(() => {
    engine.current?.view(location, view);
    setNavigation("orbit");
  }, [location, view]);
  useEffect(() => {
    engine.current?.setPitch(pitch);
  }, [pitch]);
  useEffect(() => {
    engine.current?.chunks.setBoundaries(boundaries);
  }, [boundaries]);
  const save = () => {
    try {
      const bookmark = engine.current!.bookmark(bookmarkName.trim());
      const next = [
        ...bookmarks.filter((b) => b.name !== bookmark.name),
        bookmark,
      ].slice(-12);
      localStorage.setItem(
        `strata-rigs-${aerodrome ? "aerodrome-" : ""}${seed}`,
        JSON.stringify(next),
      );
      setBookmarks(next);
      setCaptureRig(engine.current!.captureRig(bookmark.name));
      setRigMessage(`Saved ${bookmark.name}.`);
    } catch (error) {
      setRigMessage(error instanceof Error ? error.message : String(error));
    }
  };
  const restore = (b: RigBookmark) => {
    try {
      engine.current!.restore(b);
      setCaptureRig(engine.current!.captureRig(b.name));
      setPitch(b.pitch);
      setNavigation(b.navigation);
      setRigMessage(`Restored ${b.name}.`);
    } catch (error) {
      setRigMessage(error instanceof Error ? error.message : String(error));
    }
  };
  const canonical = (value: unknown): string => {
    if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
    if (value && typeof value === "object")
      return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonical((value as Record<string, unknown>)[key])}`).join(",")}}`;
    return JSON.stringify(value);
  };
  const digest = async (value: unknown) =>
    Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(canonical(value)))))
      .map((byte) => byte.toString(16).padStart(2, "0")).join("");
  const capture = async () => {
    if (!captureRig) return;
    setCaptureError("");
    setCaptureJob(null);
    const captureId = `capture-${Date.now().toString(36)}`;
    const environment = {
      schema_version: "lab.v1" as const, kind: "EnvironmentSpec" as const,
      environment_id: "clear-day", simulation_time_s: 0, solar_time_hour: 12,
      latitude_rad: 0.9, sun_direction_world: [0, 1, 0] as [number, number, number],
      ambient_temperature_k: 293.15, fog_extinction_per_m: 0,
      rain_mm_per_h: 0, snow_mm_per_h: 0,
      wind_m_per_s: [0, 0, 0] as [number, number, number], wetness: 0,
      parameter_set_version: "clear.v1", thermal_history: "equilibrated" as const,
      thermal_state: null,
    };
    const request: CaptureRequest = {
      schema_version: "lab.v1", kind: "CaptureRequest", world: spec,
      rig: captureRig, environment,
      plan: {
        schema_version: "lab.v1", kind: "CapturePlan", capture_id: captureId,
        sequence_id: `sequence-${Date.now().toString(36)}`,
        world_sha256: await digest(spec), rig_sha256: await digest(captureRig),
        environment_sha256: await digest(environment), simulation_time_s: 0,
        geometry_policy: "fixed-sensor-geometry", quality_version: "capture-quality.v1",
        seed_channels: { world: spec.seed, weather: 0, rgb: 0, ir: 0, lidar: 0 },
        modalities: ["rgb"],
      },
    };
    try {
      validatePayload("CaptureRequest", request);
      const response = await fetch("/api/v1/captures", {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify(request),
      });
      if (!response.ok) throw new Error(`Capture request failed (HTTP ${response.status})`);
      let job = await response.json() as CaptureJob;
      validatePayload("CaptureJob", job);
      setCaptureJob(job);
      while (!["succeeded", "failed", "cancelled"].includes(job.state)) {
        await new Promise((resolve) => setTimeout(resolve, 250));
        const status = await fetch(`/api/v1/jobs/${job.job_id}`, { cache: "no-store" });
        if (!status.ok) throw new Error(`Capture status failed (HTTP ${status.status})`);
        job = await status.json() as CaptureJob;
        validatePayload("CaptureJob", job);
        setCaptureJob(job);
      }
      if (job.state === "failed") throw new Error(job.error?.message ?? "Capture failed");
    } catch (error) {
      setCaptureError(error instanceof Error ? error.message : String(error));
    }
  };
  const cancelCapture = async () => {
    if (!captureJob) return;
    const response = await fetch(`/api/v1/jobs/${captureJob.job_id}/cancel`, { method: "POST" });
    if (response.ok) {
      const job = await response.json() as CaptureJob;
      validatePayload("CaptureJob", job);
      setCaptureJob(job);
    }
  };
  const validSeed = /^\d+$/.test(draftSeed) && Number(draftSeed) <= 4294967295;
  return (
    <main className="world-page">
      <header className="world-header">
        <a href="./">← Preset editor</a>
        <span>STRATA / CONNECTED WORLD</span>
        <span className="world-version">World explorer</span>
      </header>
      <section className="world-intro">
        <div>
          <p className="world-eyebrow">ONE LANDSCAPE, CONTINUOUS GROUND</p>
          <h1>A world beyond the edge.</h1>
          <p>
            2,048 × 2,048 metres. Arches, tunnels and outcrops on connected
            terrain.
          </p>
        </div>
        <div className="world-extent">
          <strong>256</strong>
          <span>chunks · 128 m each</span>
        </div>
      </section>
      <section className="world-panel" aria-label="Connected world preview">
        <div className="world-toolbar">
          <button
            aria-pressed={!aerodrome}
            onClick={() => {
              setAerodrome(false);
              setLocation(0);
            }}
          >
            Natural landscape
          </button>
          <button
            aria-pressed={aerodrome}
            disabled={!catalog}
            onClick={() => {
              setAerodrome(true);
              setLocation(0);
            }}
          >
            Open aerodrome
          </button>
          <span>
            {aerodrome
              ? "Airfield · 1,200 m runway · parked aircraft"
              : "Seeded landforms · continuous terrain"}
          </span>
        </div>
        <form
          className="world-toolbar"
          onSubmit={(e) => {
            e.preventDefault();
            if (validSeed) setSeed(Number(draftSeed));
          }}
        >
          <label>
            World seed
            <input
              type="number"
              min="0"
              max="4294967295"
              step="1"
              aria-label="Connected world seed"
              value={draftSeed}
              onChange={(e) => setDraftSeed(e.target.value)}
            />
          </label>
          <button type="submit" disabled={!validSeed}>
            Generate world
          </button>
          <label>
            Location
            <select
              aria-label="World location"
              value={location}
              onChange={(e) => setLocation(Number(e.target.value))}
            >
              {spec.features.map((f, i) => (
                <option value={i} key={f.id}>
                  {featureNames[f.type]} {i + 1}
                </option>
              ))}
            </select>
          </label>
          <label>
            View
            <select
              aria-label="World camera"
              value={view}
              onChange={(e) => setView(e.target.value)}
            >
              <option value="oblique">Landscape</option>
              <option value="detail">Landmark detail</option>
              <option value="top">From above</option>
              <option value="opening">Ground level</option>
            </select>
          </label>
          <label>
            Display detail
            <select
              aria-label="Display detail"
              value={pitch}
              onChange={(e) => setPitch(Number(e.target.value) as 2 | 4)}
            >
              <option value="4">Landscape · 4 m</option>
              <option value="2">Fine · 2 m</option>
            </select>
          </label>
          <label>
            Navigation
            <select
              aria-label="Navigation"
              value={navigation}
              onChange={(e) => {
                const n = e.target.value as "orbit" | "flight";
                setNavigation(n);
                engine.current?.setNavigation(n);
              }}
            >
              <option value="orbit">Orbit / pan</option>
              <option value="flight">Free flight</option>
            </select>
          </label>
          <label className="world-checkbox">
            <input
              type="checkbox"
              checked={boundaries}
              onChange={(e) => setBoundaries(e.target.checked)}
            />
            Chunk boundaries
          </label>
        </form>
        <div
          className="world-canvas"
          ref={host}
          aria-label="Connected terrain. Drag to orbit, scroll to zoom."
          data-seed={seed}
          data-location={location}
          data-ready={stats.ready}
          data-triangles={stats.error ? 0 : stats.triangles}
          data-features={spec.features.length}
          data-trees={stats.trees}
          data-rocks={stats.rocks}
        >
          {(stats.error || (aerodrome && catalogError)) && (
            <div role="alert">
              World preview unavailable: {stats.error || catalogError}
            </div>
          )}
          {!stats.ready && !stats.error && !catalogError && (
            <div className="world-loading">Loading terrain…</div>
          )}
        </div>
        <div className="world-status" role="status">
          <span>
            {stats.ready
              ? `${stats.chunks} connected chunks · ${pitch} m display detail`
              : "Preparing connected terrain…"}
          </span>
          <span>
            {stats.triangles.toLocaleString()} faces · {stats.trees} trees ·{" "}
            {stats.rocks} rocks · {stats.milliseconds} ms load
          </span>
        </div>
        <div className="world-toolbar world-rigs">
          <label>
            Rig pose name
            <input
              aria-label="Rig pose name"
              value={bookmarkName}
              maxLength={64}
              onChange={(e) => setBookmarkName(e.target.value)}
            />
          </label>
          <button
            onClick={save}
            disabled={!stats.ready || !bookmarkName.trim()}
          >
            Save rig pose
          </button>
          {bookmarks.map((b, i) => (
            <button key={i} onClick={() => restore(b)}>
              Restore {typeof b.name === "string" ? b.name : "invalid bookmark"}
            </button>
          ))}
          <span aria-live="polite">{rigMessage}</span>
        </div>
        <section className="capture-panel" aria-label="RGB and reference capture">
          <div className="world-toolbar">
            <button onClick={() => void capture()} disabled={!captureRig || Boolean(captureJob && ["queued", "running", "cancelling"].includes(captureJob.state))}>
              Capture RGB and references
            </button>
            <button onClick={() => void cancelCapture()} disabled={!captureJob || !["queued", "running", "cancelling"].includes(captureJob.state)}>
              Cancel capture
            </button>
            <span role="status" aria-label="Capture status">
              {captureError || (captureJob ? `Capture ${captureJob.state}` : captureRig ? "Rig ready for capture" : "Save a rig pose before capture")}
            </span>
          </div>
          {captureJob?.state === "succeeded" && captureJob.result && (
            <div className="capture-grid">
              {([
                ["RGB", captureJob.result.artifacts.rgb.id],
                ["Depth", captureJob.result.artifacts.depth_preview.id],
                ["Instance IDs", captureJob.result.artifacts.instance_preview.id],
              ] as const).map(([label, artifact]) => (
                <figure key={label}>
                  <img
                    src={`/api/v1/jobs/${captureJob.job_id}/artifacts/${artifact}`}
                    alt={`${label} capture ${captureJob.capture_id}`}
                    data-capture-id={captureJob.capture_id}
                    data-width={captureJob.result!.width}
                    data-height={captureJob.result!.height}
                  />
                  <figcaption>{label} · tick {captureJob.result!.tick_s.toFixed(3)} s</figcaption>
                </figure>
              ))}
            </div>
          )}
        </section>
        <section className="world-catalog" aria-label="Model catalog">
          <div>
            <h2>Objects at world scale</h2>
            <p>One unit is one metre. Original proportions, parked pose.</p>
          </div>
          {catalogError && (
            <p role="alert">Model catalog unavailable: {catalogError}</p>
          )}
          {!catalog && !catalogError && <p>Loading model catalog…</p>}
          <div className="catalog-grid">
            {catalog?.assets.map((a) => (
              <article key={a.asset_id}>
                <h3>
                  {a.asset_id === "f16"
                    ? "F-16"
                    : a.asset_id === "rq4"
                      ? "RQ-4 Global Hawk"
                      : "8×8 ground vehicle"}
                </h3>
                <p>
                  {a.bounds.extent_m[2].toFixed(1)} m long ·{" "}
                  {a.bounds.extent_m[0].toFixed(1)} m wide ·{" "}
                  {a.bounds.extent_m[1].toFixed(1)} m high
                </p>
                <button
                  disabled={!aerodrome || !stats.ready}
                  onClick={() => {
                    engine.current?.inspectAsset(a.asset_id);
                    setNavigation("orbit");
                  }}
                >
                  Inspect{" "}
                  {a.asset_id === "f16"
                    ? "F-16"
                    : a.asset_id === "rq4"
                      ? "RQ-4"
                      : "vehicle"}
                </button>
              </article>
            ))}
          </div>
          {aerodrome && (
            <div className="world-toolbar">
              <span>Visibility fixtures</span>
              {aerodromeFixtures.map((f) => (
                <button
                  key={f.id}
                  disabled={!stats.ready}
                  onClick={() => {
                    engine.current?.fixture(f.id);
                    setNavigation("orbit");
                  }}
                >
                  {f.name}
                </button>
              ))}
            </div>
          )}
        </section>
      </section>
      <footer className="world-footer">
        <p>
          Focus X {Math.round(stats.x)} m, Z {Math.round(stats.z)} m. Orbit:
          drag / scroll / right-drag. Flight: click canvas, W A S D to move, Q /
          E down / up, Shift for speed, drag to look.
        </p>
        <p>
          Terrain loads as you move. Rig poses are saved per seed in this
          browser. Sensor capture arrives in a later stage.
        </p>
      </footer>
    </main>
  );
}

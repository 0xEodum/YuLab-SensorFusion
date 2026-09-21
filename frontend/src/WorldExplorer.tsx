import { useEffect, useMemo, useRef, useState } from "react";
import {
  defaultWorldSpec,
  validateBookmark,
  type RigBookmark,
} from "@yulab/world";
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
  const spec = useMemo(() => defaultWorldSpec(seed), [seed]);
  useEffect(() => {
    if (!host.current) return;
    let runtime: WorldRuntime | undefined;
    setStats((s) => ({ ...s, ready: false, triangles: 0, error: "" }));
    try {
      runtime = new WorldRuntime(spec, host.current, setStats);
      engine.current = runtime;
      runtime.view(location, view);
      runtime.setPitch(pitch);
      runtime.chunks.setBoundaries(boundaries);
      setNavigation("orbit");
      if (new URLSearchParams(window.location.search).get("qa") === "1")
        window.worldQA = runtime;
      try {
        const saved: unknown = JSON.parse(
          localStorage.getItem(`strata-rigs-${seed}`) ?? "[]",
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
      localStorage.setItem(`strata-rigs-${seed}`, JSON.stringify(next));
      setBookmarks(next);
      setRigMessage(`Saved ${bookmark.name}.`);
    } catch (error) {
      setRigMessage(error instanceof Error ? error.message : String(error));
    }
  };
  const restore = (b: RigBookmark) => {
    try {
      engine.current!.restore(b);
      setPitch(b.pitch);
      setNavigation(b.navigation);
      setRigMessage(`Restored ${b.name}.`);
    } catch (error) {
      setRigMessage(error instanceof Error ? error.message : String(error));
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
          {stats.error && (
            <div role="alert">World preview unavailable: {stats.error}</div>
          )}
          {!stats.ready && !stats.error && (
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

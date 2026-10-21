"""Fit, tune and score the SF-14 temporal tracker on cached ensemble detections.

fit    measurement noise from TRAIN-split residuals (sensor detections vs eligible truth within a gate)
tune   coordinate search on TRAIN/VALIDATION clips; writes a frozen protocol (params, source and cache hashes)
score  TEST clips, once: refuses to run without an intact protocol or if a test report already exists
"""
import argparse
import dataclasses
import hashlib
import json
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import pickle
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
import numpy as np
from learning.temporal_evaluation import AVAILABILITY, CORRUPTIONS, evaluate_scenario, group_sequences, target
from learning.temporal_tracker import TrackerParams

SOURCES = ("backend/learning/temporal_tracker.py", "backend/learning/temporal_geometry.py",
           "backend/learning/temporal_evaluation.py", "backend/learning/decision_fusion.py", "backend/learning/evaluate.py",
           "tools/temporal-tracker.py")
SCENARIOS = ("clean",) + AVAILABILITY + CORRUPTIONS
RESIDUAL_GATE_M = 15.0
MIN_RESIDUAL_SCORE = 0.3
# Coordinate-search grid, fixed before any validation scoring. Order matters only for tie-breaking.
GRID = {"accel_sigma_m_per_s2": (0.2, 0.5, 1.0, 2.0), "confirm_hits": (1, 2), "gate_chi2": (9.21, 13.82),
        "score_smoothing": (0.0, 0.5, 0.8), "kappa_exponent": (0.5, 1.0, 2.0), "noise_scale": (0.75, 1.0, 1.5)}
_CACHE = {}


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_hashes():
    return {s: hashlib.sha256((ROOT / s).read_bytes().replace(b"\r\n", b"\n")).hexdigest() for s in SOURCES}


def load(paths, splits):
    frames = []
    for path in paths:
        payload = pickle.load(open(path, "rb"))
        frames += [f for f in payload["frames"] if f["split"] in splits]
    return group_sequences(frames)


def fit_sigmas(sequences):
    """Per-axis RMS position residual (m) per sensor on train frames; includes systematic bias by design."""
    residuals = {0: [], 1: [], 2: []}
    for frames in sequences.values():
        for frame in frames:
            truth = [t for t in frame["truth"] if t["eligible"]]
            for sensor, expert in enumerate(frame["scenarios"]["clean"]["experts"]):
                for box, cls, score in zip(expert["boxes"], expert["classes"], expert["scores"]):
                    if score < MIN_RESIDUAL_SCORE:
                        continue
                    options = [t["box"][[0, 2]] - box[[0, 2]] for t in truth if t["class"] == cls]
                    if options:
                        nearest = min(options, key=np.linalg.norm)
                        if np.linalg.norm(nearest) <= RESIDUAL_GATE_M:
                            residuals[sensor].append(nearest)
    return [float(np.sqrt(np.mean(np.square(residuals[s])))) for s in range(3)], {s: len(v) for s, v in residuals.items()}


def make_params(base_sigma, overrides):
    values = dict(overrides)
    scale = values.pop("noise_scale", 1.0)
    return TrackerParams(sensor_sigma_m=tuple(s * scale for s in base_sigma), **values)


def _init(paths, splits):
    _CACHE["sequences"] = load(paths, splits)


def _evaluate_one(args):
    params, scenario = args
    return scenario, evaluate_scenario(params, _CACHE["sequences"], scenario)


def objective(results):
    clean = results["clean"]["tracker_observed"]["map_3d"]
    macro = float(np.mean([results[s]["tracker_observed"]["map_3d"] for s in AVAILABILITY + CORRUPTIONS]))
    return 0.5 * (clean + macro), clean, macro


def static_objective(results):
    clean = results["clean"]["static"]["map_3d"]
    macro = float(np.mean([results[s]["static"]["map_3d"] for s in AVAILABILITY + CORRUPTIONS]))
    return 0.5 * (clean + macro), clean, macro


def run_all(pool, params):
    return dict(pool.map(_evaluate_one, [(params, s) for s in SCENARIOS]))


def jsonable(value):
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    if isinstance(value, (np.floating, np.integer)):
        return value.item()
    return value


def summarize(results):
    return {s: {k: v for k, v in r.items() if k != "step_ms"} | {"step_ms_p50": float(np.percentile(r["step_ms"], 50)),
            "step_ms_p95": float(np.percentile(r["step_ms"], 95))} for s, r in results.items()}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=("fit", "tune", "score"))
    p.add_argument("--cache", type=Path, nargs="+", required=True)
    p.add_argument("--protocol", type=Path, required=True)
    p.add_argument("--output", type=Path)
    p.add_argument("--workers", type=int, default=6)
    a = p.parse_args()
    if a.command == "fit":
        sigma, counts = fit_sigmas(load(a.cache, {"train"}))
        print(json.dumps({"sensor_sigma_m": sigma, "residual_counts": counts}))
        return
    if a.command == "tune":
        if a.protocol.exists():
            raise ValueError("Protocol already exists; tuning is not repeated against a frozen protocol")
        train = load(a.cache, {"train"})
        sigma, counts = fit_sigmas(train)
        best, trace = {"accel_sigma_m_per_s2": 0.5, "confirm_hits": 2, "gate_chi2": 9.21, "score_smoothing": 0.5,
                       "kappa_exponent": 1.0, "noise_scale": 1.0}, []
        started = time.perf_counter()
        with ProcessPoolExecutor(a.workers, initializer=_init, initargs=(a.cache, {"validation"})) as pool:
            static = static_objective(run_all(pool, make_params(sigma, best)))
            best_score = objective(run_all(pool, make_params(sigma, best)))[0]
            for sweep in range(2):
                for name, values in GRID.items():
                    for value in values:
                        candidate = best | {name: value}
                        if candidate == best:
                            continue
                        score = objective(run_all(pool, make_params(sigma, candidate)))
                        trace.append({"sweep": sweep, "change": {name: value}, "objective": score[0], "clean": score[1], "macro": score[2]})
                        print(trace[-1], flush=True)
                        if score[0] > best_score + 1e-9:
                            best, best_score = candidate, score[0]
        protocol = {"version": "sf14-tracker-protocol.v1", "selection": "validation clean+macro observed mAP; train fits noise only",
                    "fitted_sensor_sigma_m": sigma, "residual_counts": counts, "parameters": best, "grid": {k: list(v) for k, v in GRID.items()},
                    "validation_static_control": {"objective": static[0], "clean": static[1], "macro": static[2]},
                    "validation_selected": best_score, "trace": trace, "elapsed_s": time.perf_counter() - started,
                    "sources": source_hashes(), "caches": {str(c): sha256(c) for c in a.cache}}
        a.protocol.parent.mkdir(parents=True, exist_ok=True)
        a.protocol.write_text(json.dumps(jsonable(protocol), indent=2) + "\n")
        print("frozen", json.dumps(best), "validation objective", best_score, "static", static[0])
        return
    protocol = json.loads(a.protocol.read_text())
    if protocol["sources"] != source_hashes() or protocol["caches"] != {str(c): sha256(c) for c in a.cache}:
        raise ValueError("Sources or caches changed after the protocol froze; test scoring refused")
    output = a.output or a.protocol.with_name("test-report.json")
    if output.exists():
        raise ValueError("Test report exists; the test split is consumed once")
    params = make_params(protocol["fitted_sensor_sigma_m"], protocol["parameters"])
    with ProcessPoolExecutor(a.workers, initializer=_init, initargs=(a.cache, {"test"})) as pool:
        results = run_all(pool, params)
    report = {"protocol_sha256": sha256(a.protocol), "params": dataclasses.asdict(params), "objective": dict(zip(("combined", "clean", "macro"), objective(results))),
              "static_control": dict(zip(("combined", "clean", "macro"), static_objective(results))), "scenarios": summarize(results)}
    output.write_text(json.dumps(jsonable(report), indent=2) + "\n")
    print(json.dumps({k: report[k] for k in ("objective", "static_control")}))


if __name__ == "__main__":
    main()

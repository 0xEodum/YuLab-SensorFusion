"""Post-freeze controls for SF-14 (no tracker parameter or test-report change; labelled post hoc).

static@birth-score: the unchanged static consensus filtered to the tracker's birth threshold, so false
positives are compared at the same cutoff. Also breaks results out by clip variant and reports observed-only recall.
"""
import importlib.util
import json
from pathlib import Path
import sys
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
spec = importlib.util.spec_from_file_location("tt", ROOT / "tools/temporal-tracker.py")
tt = importlib.util.module_from_spec(spec); spec.loader.exec_module(tt)
from learning.evaluate import evaluate
from learning.temporal_evaluation import (AVAILABILITY, CORRUPTIONS, evaluate_scenario, run_sequence, static_prediction, target)

CACHES = [ROOT / "artifacts/sf14/cache-sf13.pkl", ROOT / "artifacts/sf14/cache-sf14.pkl"]
protocol = json.loads((ROOT / "docs/evidence/sf14-temporal/protocol.json").read_text())
params = tt.make_params(protocol["fitted_sensor_sigma_m"], protocol["parameters"])
cut = params.birth_min_score


def filtered(prediction):
    keep = prediction["scores"] >= cut
    return {k: v[keep] for k, v in prediction.items()}


def scores(sequences, scenario):
    static, held, targets = [], [], []
    for frames in sequences.values():
        for f in frames:
            p = static_prediction(f, scenario); static.append(p); held.append(filtered(p)); targets.append(target(f))
    return static, held, targets


def run(split, variant=None):
    sequences = {k: v for k, v in tt.load(CACHES, {split}).items() if variant is None or k.endswith(variant)}
    out = {}
    for scenario in tt.SCENARIOS:
        static, held, targets = scores(sequences, scenario)
        r = evaluate_scenario(params, sequences, scenario)
        observed = {"hits": 0, "positives": 0}
        for frames in sequences.values():
            outputs, _ = run_sequence(params, frames, scenario)
            from learning.temporal_evaluation import _matches
            for f, o in zip(frames, outputs):
                if not any(f["scenarios"][scenario]["available"]):
                    continue
                truth = target(f); hit = set()
                for x in o:
                    if x.observed:
                        hit |= {i for i, _ in _matches(x.box, x.cls, truth)}
                observed["hits"] += len(hit); observed["positives"] += len(truth["classes"])
        out[scenario] = {"static": r["static"]["map_3d"], "static_at_birth_score": evaluate(held, targets)["map_3d"],
                         "tracker": r["tracker_observed"]["map_3d"], "fp_static": r["static"]["false_positives"],
                         "fp_static_at_birth_score": evaluate(held, targets)["false_positives"], "fp_tracker": r["tracker_observed"]["false_positives"],
                         "observed_only_recall_available_frames": observed["hits"] / max(observed["positives"], 1),
                         "static_recall_available_frames": r["available_frames"]["static_recall"]}
    keys = ("static", "static_at_birth_score", "tracker")
    macro = {k: float(np.mean([out[s][k] for s in AVAILABILITY + CORRUPTIONS])) for k in keys}
    return {"scenarios": out, "clean": {k: out["clean"][k] for k in keys}, "macro": macro}


report = {"label": "post-freeze control; tracker parameters and test report unchanged", "birth_score_cutoff": cut,
          "validation": run("validation"), "test": run("test"),
          "test_clean_variant": run("test", "clean"), "test_drift_outages_variant": run("test", "drift-outages")}
(ROOT / "docs/evidence/sf14-temporal/post-freeze-controls.json").write_text(json.dumps(report, indent=2) + "\n")
for k in ("validation", "test", "test_clean_variant", "test_drift_outages_variant"):
    r = report[k]; c = r["scenarios"]["clean"]
    print(k, "clean", {a: round(b, 4) for a, b in r["clean"].items()}, "macro", {a: round(b, 4) for a, b in r["macro"].items()},
          "FP clean", c["fp_static"], c["fp_static_at_birth_score"], c["fp_tracker"], "rec", round(c["static_recall_available_frames"], 3), round(c["observed_only_recall_available_frames"], 3))

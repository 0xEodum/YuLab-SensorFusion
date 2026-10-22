"""SF-15 train/validation scale experiment, followed by one hash-gated sealed test.

Keeps the SF-Q architecture, loss, seeds, snapshots, preprocessing and evaluator.
Only the immutable training sample selection changes. Inference of clean sensor
experts is shared across sensor subsets; raw corruption is always reprocessed.
"""
from __future__ import annotations

import argparse
from collections import Counter
import gc
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time

os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
import numpy as np
import torch
from app.dataset import digest
from app.observation_input import load_observation_only
from app.scaling import compose, read
from learning.data import PROFILE, preprocess_arrays, supervision
from learning.decision_fusion import fuse, initialization_experts
from learning.model import Detector
from learning.runtime import GraphInference
from learning.matching import frame_overlaps
from learning.sensor_degradation import CORRUPTIONS, PROFILE as DEGRADATION, degrade
from learning.scaling_acceptance import make_freeze, assert_frozen

spec = importlib.util.spec_from_file_location("pilot", ROOT / "tools/learning-pilot.py")
pilot = importlib.util.module_from_spec(spec); spec.loader.exec_module(pilot)
GROUPS = ((11, 12, 13), (14, 15, 16), (17, 18, 19))
MODALITIES = ("rgb", "ir", "lidar")
SOURCES = ("tools/scale-ensemble.py", "tools/quality-pilot.py", "backend/learning/data.py",
           "backend/learning/model.py", "backend/learning/runtime.py", "backend/learning/decision_fusion.py",
           "backend/learning/decision_inference.py", "backend/learning/evaluate.py",
           "backend/learning/scaling_acceptance.py", "backend/learning/sensor_degradation.py",
           "tools/run-scale-experiment.py", "tools/generate-sf10-requests.ts", "backend/app/scaling.py")


def paths(run, historical=False):
    result = {}
    for seed in range(11, 20):
        for modality in MODALITIES:
            for snapshot in ("raw", "swa"):
                if historical:
                    if snapshot == "raw" and seed < 14:
                        base = "baseline-120" if seed == 11 else f"baseline-120-seed-{seed}"
                        path = ROOT / f"artifacts/sf-quality/{base}/runs/{modality}/best.pt"
                    else:
                        path = ROOT / f"artifacts/sf-quality/swa-seed-{seed}/{modality}/{'raw-best.pt' if snapshot == 'raw' else 'best.pt'}"
                else:
                    path = run / f"seed-{seed}" / modality / ("raw-best.pt" if snapshot == "raw" else "best.pt")
                result[(seed, modality, snapshot)] = path
    return result


def records(dataset, split):
    result = []
    for entry in read(dataset / "manifest.json")["captures"]:
        if entry["split"] != split: continue
        obs = read(dataset / entry["capture_id"] / "observation.json")
        origin = np.array(obs["rig"]["T_world_from_rig"]).reshape(4, 4)[:3, 3]
        result.append({**entry, "origin": origin.tolist(), "condition": int(entry["capture_id"].rsplit("-", 1)[1]) % 10})
    if not result: raise ValueError("Empty evaluation split")
    return result


def prepare_case(dataset, rows, case, cache):
    path = cache / f"{case}.pt"
    identity = {"dataset_sha256": digest(dataset / "manifest.json"), "capture_ids": [r["capture_id"] for r in rows],
                "preprocessing": PROFILE, "degradation": DEGRADATION}
    if path.exists():
        saved = torch.load(path, weights_only=True, map_location="cpu")
        if any(saved[k] != v for k, v in identity.items()): raise ValueError("Evaluation cache changed")
        return saved["features"]
    tensors = []
    for i, row in enumerate(rows):
        obs, arrays = load_observation_only(dataset, {"capture_id": row["capture_id"]})
        if case != "clean": obs, arrays = degrade(obs, arrays, case, row["capture_id"], seed=DEGRADATION["seed"])
        tensors.append(preprocess_arrays(obs, arrays)[0])
        if i % 100 == 0: print(f"prepare {case} {i}/{len(rows)}", flush=True)
    features = {k: torch.stack([f[k] for f in tensors]) for k in tensors[0]}
    cache.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(".pt.partial")
    torch.save({**identity, "features": features}, partial); os.replace(partial, path)
    return features


def report(predicted, actual, rows, device):
    matches = pilot.match_frames(predicted, actual, frame_overlaps(predicted, actual, device))
    result = pilot.evaluate(predicted, actual, matches)
    result["detections"] = sum(len(p["boxes"]) for p in predicted)
    result["frames"] = len(rows)
    result["independent_groups"] = len({r["group_id"] for r in rows})
    result["conditions"] = {}
    for condition in range(10):
        ids = [i for i, r in enumerate(rows) if r["condition"] == condition]
        value = pilot.evaluate([predicted[i] for i in ids], [actual[i] for i in ids], [matches[i] for i in ids])
        value["frames"] = len(ids)
        result["conditions"][str(condition)] = value
    result["condition_profiles"] = {}
    for profile, is_heldout in (("standard", False), ("heldout-environment", True)):
        ids = [i for i, r in enumerate(rows) if r["capture_id"].startswith("sf15h-") == is_heldout]
        if ids:
            value = pilot.evaluate([predicted[i] for i in ids], [actual[i] for i in ids], [matches[i] for i in ids])
            value["frames"] = len(ids)
            result["condition_profiles"][profile] = value
    return result


def evaluate(dataset, run, output, split, freeze=None, training_manifest=None):
    if output.exists(): raise ValueError("Evaluation report already exists")
    if split == "test":
        if freeze is None: raise ValueError("Sealed test requires freeze")
        assert_frozen(freeze)
        for path in (dataset / "manifest.json", training_manifest or (dataset / "manifest.json")):
            if str(path.resolve()) not in freeze["files"]:
                raise ValueError("Test dataset/training identity was not frozen")
    pilot.seed_all(11, fill=False); device = torch.device("cuda")
    rows = records(dataset, split)
    actual = pilot.meters([supervision(dataset, r, np.array(r["origin"])) for r in rows])
    all_paths = {"baseline": paths(run, True), "candidate": paths(run)}
    historical_freeze = read(ROOT / "docs/evidence/sf-quality/ensemble-freeze.json")
    historical_hashes = {r["path"]: r["sha256"] for r in historical_freeze["checkpoints"]}
    models = {}
    expected_train_sha = digest(training_manifest or (dataset / "manifest.json"))
    for method, mapping in all_paths.items():
        for key, path in mapping.items():
            if split == "test" and str(path.resolve()) not in freeze["files"]:
                raise ValueError("Test checkpoint was not frozen")
            if method == "baseline" and digest(path) != historical_hashes[path.relative_to(ROOT).as_posix()]:
                raise ValueError("Historical SF-Q checkpoint changed")
            saved = torch.load(path, weights_only=True, map_location="cpu")
            seed, modality, snapshot = key
            if saved["seed"] != seed or saved["preprocessing"] != PROFILE or saved["modality"] != modality:
                raise ValueError("Checkpoint identity mismatch")
            if method == "candidate" and saved["dataset_sha256"] != expected_train_sha:
                raise ValueError("Candidate training manifest changed")
            if method == "baseline" and saved["dataset_sha256"] != historical_freeze["protocol"]["dataset_sha256"]:
                raise ValueError("Historical training provenance changed")
            if saved.get("averaged_epochs", 0) != (60 if snapshot == "swa" else 0):
                raise ValueError("Snapshot policy mismatch")
            cfg = saved["config"]
            if any(cfg[k] != v for k,v in {"epochs":120, "lr":.001, "batch_size":32, "width":64}.items()):
                raise ValueError("Training recipe changed")
            model = Detector(modality).to(device).eval(); model.load_state_dict(saved["model"])
            model.graph_inference = GraphInference(model)
            models[(method, *key)] = model
    cases = {(method, group[0]): {} for method in all_paths for group in GROUPS}
    predictions_saved = {}
    started = time.perf_counter()
    reload_checked = 0
    for corruption in ("clean", *CORRUPTIONS):
        features = prepare_case(dataset, rows, corruption, dataset.parent / (dataset.name + "-eval-cache-" + split))
        features = {k: v.to(device) for k, v in features.items()}
        predicted = {key: pilot.infer(model, features, 32) for key, model in models.items()}
        if corruption == "clean":
            for key in models:
                method, seed, modality, snapshot = key
                if method != "candidate": continue
                saved = torch.load(all_paths[method][(seed, modality, snapshot)], weights_only=True, map_location="cpu")
                reloaded = Detector(modality).to(device).eval(); reloaded.load_state_dict(saved["model"])
                reloaded.graph_inference = GraphInference(reloaded)
                replay = pilot.infer(reloaded, features, 32)
                if any(not np.array_equal(a[k], b[k]) for a,b in zip(predicted[key], replay) for k in a):
                    raise ValueError("Checkpoint reload changed predictions")
                reload_checked += 1
                del replay, reloaded, saved
                gc.collect()
        for method in all_paths:
            for group in GROUPS:
                experts = []
                for i in range(len(rows)):
                    runs = [[[predicted[(method, seed, modality, snapshot)][i] for snapshot in ("raw", "swa")]
                             for modality in MODALITIES] for seed in group]
                    experts.append(initialization_experts(runs, [True]*3))
                for bits in (range(8) if corruption == "clean" else (7,)):
                    name = f"availability-{bits}" if corruption == "clean" else corruption
                    values = [fuse(frame, [bool(bits & (1 << m)) for m in range(3)]) for frame in experts]
                    cases[(method, group[0])][name] = report(values, actual, rows, device)
                    if name == "availability-7": predictions_saved[(method, group[0])] = values
                    print(split, method, group[0], name, round(cases[(method, group[0])][name]["map_3d"], 5), flush=True)
                if corruption == "clean":
                    for m, modality in enumerate(MODALITIES):
                        cases[(method, group[0])]["unimodal-" + modality] = report([e[m] for e in experts], actual, rows, device)
        del features, predicted
    included = [f"availability-{b}" for b in range(1, 7)] + list(CORRUPTIONS)
    methods = {}
    for method in all_paths:
        clean = [cases[(method, g[0])]["availability-7"]["map_3d"] for g in GROUPS]
        macro = [float(np.mean([cases[(method, g[0])][c]["map_3d"] for c in included])) for g in GROUPS]
        methods[method] = {"clean_mean": float(np.mean(clean)), "clean_sd": float(np.std(clean, ddof=1)),
                           "macro_mean": float(np.mean(macro)), "macro_sd": float(np.std(macro, ddof=1)),
                           "clean_values": clean, "macro_values": macro, "replicates": 3,
                           "all_missing_detections": sum(cases[(method, g[0])]["availability-0"]["detections"] for g in GROUPS)}
    value = {"profile": "sf15-matched-comparison.v1", "split": split, "methods": methods,
             "dataset_sha256": digest(dataset / "manifest.json"), "groups": GROUPS, "macro_cases": included,
             "frames": len(rows), "independent_layouts": len({r["group_id"] for r in rows}),
             "checkpoint_reload_exact_prediction_parity": reload_checked == 54,
             "reload_checked_checkpoints": reload_checked,
             "cases": {f"{m}-group-{s}": c for (m,s), c in cases.items()}, "elapsed_s": time.perf_counter()-started}
    pilot.write(output, value)
    for (method, seed), values in predictions_saved.items():
        pilot.write(output.parent / (output.stem + f"-{method}-{seed}-predictions.json"),
                    [{"capture_id": r["capture_id"], **{k: v.tolist() for k,v in p.items()}} for r,p in zip(rows, values)])
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("compose", "evaluate", "freeze"))
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sources", type=Path)
    parser.add_argument("--split", choices=("validation", "test"), default="validation")
    parser.add_argument("--freeze", type=Path)
    parser.add_argument("--decision", type=Path)
    parser.add_argument("--training-manifest", type=Path, help="Separate frozen training identity for additional test-only datasets")
    args = parser.parse_args()
    if args.stage == "compose":
        from concurrent.futures import ProcessPoolExecutor
        with ProcessPoolExecutor(max_workers=4) as pool:
            manifest = compose(read(args.sources), args.dataset, "sf15-scale", pool)
        print(json.dumps(manifest["counts"]), flush=True)
    elif args.stage == "evaluate":
        evaluate(args.dataset, args.run, args.output, args.split, read(args.freeze) if args.freeze else None, args.training_manifest)
    else:
        if args.output.exists(): raise ValueError("Freeze already exists")
        inputs = [args.dataset / "manifest.json", args.dataset / "sources.json", args.decision,
                  ROOT / "docs/evidence/sf15-scaling/protocol.json",
                  ROOT / "docs/evidence/sf-quality/ensemble-freeze.json"]
        for historical in (True, False): inputs.extend(paths(args.run, historical).values())
        inputs.extend(ROOT / s for s in SOURCES)
        asset_requests = ROOT / "artifacts/sf15/requests-asset-holdout.json"
        if asset_requests.exists(): inputs.append(asset_requests)
        pilot.write(args.output, make_freeze(inputs, read(args.decision)))


if __name__ == "__main__": main()

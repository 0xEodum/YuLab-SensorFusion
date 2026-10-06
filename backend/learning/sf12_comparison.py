"""Validation-only, paired SF-12 comparison. Model checkpoints are never selected here."""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import gc
import subprocess
import time
import numpy as np
import torch

from app.dataset import digest
from app.observation_input import load_observation_only
from . import data, essrf_data
from .sensor_degradation import CORRUPTIONS, SCENARIOS, PROFILE, degrade
from .essrf_model import ESSRF
from .essrf_evaluation import load_checkpoint, reliability_report
from .essrf_training import records, load, batch, meters, score, write
from .model import Detector, predictions
from .evaluate import evaluate, match_frames


def _prepare_one(job):
    dataset, capture_id, scenario = job
    obs, arrays = load_observation_only(Path(dataset), {"capture_id": capture_id})
    obs, arrays = degrade(obs, arrays, scenario, capture_id, seed=PROFILE["seed"])
    baseline, _ = data.preprocess_arrays(obs, arrays)
    return baseline, essrf_data.preprocess_arrays(obs, arrays)


def load_case(args, scenario, dataset_sha, rows, device):
    cache = torch.load(args.comparison_root / f"{scenario}.pt", weights_only=True, map_location="cpu")
    if cache["dataset_sha256"] != dataset_sha or cache["capture_ids"] != [r["capture_id"] for r in rows] or \
            cache["scenario"] != scenario or cache["degradation"] != PROFILE or \
            cache["preprocessing"] != {"baseline": data.PROFILE, "essrf": essrf_data.PROFILE}:
        raise ValueError("Comparison cache provenance mismatch")
    return tuple({k: v.to(device) for k, v in cache[p].items()} for p in ("baseline", "essrf"))


def prepare_suite(args, scenarios=CORRUPTIONS):
    dataset_sha, rows = records(args, "validation")
    if any(r["split"] != "validation" for r in rows):
        raise ValueError("Comparison accepts validation rows only")
    for scenario in scenarios:
        if scenario not in CORRUPTIONS:
            raise ValueError("Prepare only known comparison corruptions")
        path = args.comparison_root / f"{scenario}.pt"
        if path.exists():
            load_case(args, scenario, dataset_sha, rows, "cpu")
            continue
        jobs = [(str(args.dataset), r["capture_id"], scenario) for r in rows]
        if args.workers:
            with ProcessPoolExecutor(args.workers) as pool:
                values = list(pool.map(_prepare_one, jobs, chunksize=8))
        else:
            values = [_prepare_one(job) for job in jobs]
        value = {"dataset_sha256": dataset_sha, "capture_ids": [r["capture_id"] for r in rows],
                 "scenario": scenario, "degradation": PROFILE,
                 "preprocessing": {"baseline": data.PROFILE, "essrf": essrf_data.PROFILE}}
        for index, name in enumerate(("baseline", "essrf")):
            value[name] = {k: torch.stack([v[index][k] for v in values]) for k in values[0][index]}
        args.comparison_root.mkdir(parents=True, exist_ok=True)
        partial = path.with_suffix(".pt.partial")
        torch.save(value, partial)
        partial.replace(path)
        print(f"prepared {scenario}: {len(rows)} paired validation captures", flush=True)
        del values, value
        gc.collect()


def failure_inputs(features, bits, profile):
    result = dict(features)
    if profile == ESSRF.profile:
        available = torch.tensor([bool(bits & (1 << m)) for m in range(3)], device=features["rgb"].device)
        result["available"] = features["available"] & available
    elif profile == "baseline-v1":
        for m, name in enumerate(("rgb", "ir", "lidar")):
            if not bits & (1 << m):
                result[name] = torch.zeros_like(features[name])
                if name == "lidar":
                    result["point_valid"] = torch.zeros_like(features["point_valid"])
    else:
        raise ValueError("Unknown comparison model profile")
    return result


@torch.no_grad()
def score_baseline(model, features, targets, rows, size):
    model.eval()
    predicted = []
    for start in range(0, len(rows), size):
        ids = list(range(start, min(start + size, len(rows))))
        values = predictions(model(batch(features, ids)))
        for value in values:
            value["boxes"][:, :6] *= 200
        predicted.extend(values)
    actual = meters(targets)
    report = evaluate(predicted, actual, match_frames(predicted, actual))
    report["conditions"] = {}
    for condition in range(10):
        ids = [i for i, r in enumerate(rows) if r["condition"] == condition]
        report["conditions"][str(condition)] = evaluate([predicted[i] for i in ids], [actual[i] for i in ids])
    report["detections"] = sum(len(p["scores"]) for p in predicted)
    return report


def _models(args, device, dataset_sha):
    result = {}
    for seed in args.seeds:
        root = args.sf11 if seed == 11 else args.baseline_root / f"seed-{seed}"
        for modality in ("rgb", "ir", "lidar", "fusion"):
            path = root / "runs" / modality / "best.pt"
            saved = torch.load(path, weights_only=True, map_location=device)
            if saved["profile"] != "baseline-v1" or saved["preprocessing"] != data.PROFILE or \
                    saved["dataset_sha256"] != dataset_sha or saved["seed"] != seed or saved["modality"] != modality:
                raise ValueError("Baseline checkpoint provenance mismatch")
            cfg = saved["config"]
            model = Detector(modality, queries=cfg["queries"], width=cfg["width"]).to(device).eval()
            model.load_state_dict(saved["model"])
            result[f"baseline-{modality}-seed-{seed}"] = (model, saved, path)
        if args.essrf_run_root is not None:
            path = args.essrf_run_root / f"seed-{seed}" / "best.pt"
            model, saved = load_checkpoint(path, device, dataset_sha)
            if saved["seed"] != seed:
                raise ValueError("ESSRF seed mismatch")
            result[f"essrf-seed-{seed}"] = (model, saved, path)
    return result


def compare(args):
    """Same rows, unchanged labels, thresholds and evaluator across all 14 cases."""
    device = torch.device(args.device)
    dataset_sha, rows = records(args, "validation")
    if any(r["split"] != "validation" for r in rows):
        raise ValueError("Comparison accepts validation rows only")
    clean_essrf, targets, target_rows = load(args, "validation", device)
    if rows != target_rows:
        raise ValueError("Validation order mismatch")
    cache = torch.load(args.sf11 / "validation-observations.pt", weights_only=True, map_location="cpu")
    if cache["dataset_sha256"] != dataset_sha or cache["preprocessing"] != data.PROFILE:
        raise ValueError("Baseline cache provenance mismatch")
    clean_baseline = {k: v.to(device) for k, v in cache["features"].items()}
    models = _models(args, device, dataset_sha)
    result = {"version": "sf12-comparison.v1", "split": "validation", "dataset_sha256": dataset_sha,
              "capture_ids": [r["capture_id"] for r in rows], "degradation": PROFILE,
              "prediction_threshold": .05, "source_revision": subprocess.check_output(
                  ["git", "rev-parse", "HEAD"], text=True).strip(), "models": {}}
    for name, (_, saved, path) in models.items():
        result["models"][name] = {"checkpoint_sha256": digest(path), "checkpoint_epoch": saved["epoch"],
                                 "training_source_revision": saved["source_revision"],
                                 "seed": saved["seed"], "profile": saved["profile"],
                                 "config": saved["config"], "scenarios": {}}
    started = time.perf_counter()
    for scenario in SCENARIOS:
        if scenario.startswith("availability-"):
            bits = int(scenario.rsplit("-", 1)[1])
            baseline = failure_inputs(clean_baseline, bits, "baseline-v1")
            essrf = failure_inputs(clean_essrf, bits, ESSRF.profile)
        else:
            baseline, essrf = load_case(args, scenario, dataset_sha, rows, device)
        for name, (model, saved, _) in models.items():
            if saved["profile"] == ESSRF.profile:
                report, predicted = score(model, essrf, targets, rows, args.batch_size)
                report["detections"] = sum(len(p["scores"]) for p in predicted)
                if scenario == "availability-0" and report["detections"]:
                    raise ValueError("ESSRF all-unavailable input emitted detections")
            else:
                report = score_baseline(model, baseline, targets, rows, args.batch_size)
            result["models"][name]["scenarios"][scenario] = report
            print(f"{name} {scenario} AP {report['map_3d']}", flush=True)
        write(args.report, result)
        del baseline, essrf
    for name, (model, saved, _) in models.items():
        if saved["profile"] == ESSRF.profile:
            result["models"][name]["reliability"] = reliability_report(
                model, clean_essrf, targets, rows, args.batch_size, seed=PROFILE["seed"])
    result["elapsed_s"] = time.perf_counter() - started
    write(args.report, result)
    return result

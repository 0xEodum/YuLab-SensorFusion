"""Validation-only evaluation of an essrf-static-v1 checkpoint.

Reports every availability pattern, abstention, reliability calibration and
vacuity on labelled versus OOD corruptions, and reliability by condition.
"""
from __future__ import annotations


import numpy as np
import torch

from app.dataset import digest
from . import essrf_data, essrf_loss as L
from .essrf_model import ESSRF
from .essrf_training import batch, load, score, write

PATTERN_NAMES = {0: "none", 1: "rgb", 2: "ir", 3: "rgb+ir", 4: "lidar", 5: "rgb+lidar", 6: "ir+lidar", 7: "all"}


def load_checkpoint(path, device, dataset_sha):
    saved = torch.load(path, weights_only=False, map_location=device)
    if saved["profile"] != ESSRF.profile or saved["preprocessing"] != essrf_data.PROFILE or \
            saved["dataset_sha256"] != dataset_sha or saved["support"] != essrf_data.SUPPORT:
        raise ValueError("Checkpoint profile/preprocessing/dataset mismatch")
    config = saved["config"]
    model = ESSRF(queries=config["queries"], width=config["width"], samples=config["samples"],
                  layers=config["layers"], global_context=config.get("global_context", False)).to(device)
    model.load_state_dict(saved["model"]); model.eval()
    return model, saved


def calibration_bins(probability: np.ndarray, target: np.ndarray, bins: int = 10) -> dict:
    edges = np.linspace(0, 1, bins + 1)
    ece, rows = 0.0, []
    for low, high in zip(edges[:-1], edges[1:]):
        inside = (probability >= low) & ((probability < high) if high < 1 else (probability <= high))
        if inside.any():
            gap = abs(probability[inside].mean() - target[inside].mean())
            ece += inside.mean() * gap
            rows.append({"low": float(low), "high": float(high), "count": int(inside.sum()),
                         "mean_probability": float(probability[inside].mean()), "positive_rate": float(target[inside].mean())})
    return {"ece": float(ece), "brier": float(((probability - target) ** 2).mean()), "bins": rows}


def auroc(positive: np.ndarray, negative: np.ndarray) -> float | None:
    if not len(positive) or not len(negative):
        return None
    values = np.concatenate((positive, negative))
    ranks = values.argsort().argsort() + 1.0
    return float((ranks[:len(positive)].sum() - len(positive) * (len(positive) + 1) / 2) / (len(positive) * len(negative)))


@torch.no_grad()
def reliability_report(model, features, targets, rows, size, seed):
    """Labelled (known) corruption calibration and OOD vacuity under fixed augmentation."""
    device = features["rgb"].device
    packed = L.pack(targets, device)
    generator = torch.Generator(device=device).manual_seed(seed)
    mu, y, u_known, u_ood = [[] for _ in range(3)], [[] for _ in range(3)], [[] for _ in range(3)], [[] for _ in range(3)]
    by_condition = {str(c): [[] for _ in range(3)] for c in range(10)}
    for start in range(0, len(rows), size):
        ids = list(range(start, min(start + size, len(rows))))
        inputs = batch(features, ids); truth = L.select(packed, ids)
        clean = model(inputs)
        _, matched_clean, _ = L.detection(clean, truth, truth["counts"], inputs)
        for i, row in enumerate(ids):
            valid = matched_clean[i] >= 0
            for m in range(3):
                by_condition[str(rows[row]["condition"])][m].extend(clean["reliability"][i, valid, m].tolist())
        augmented, regions = L.augment(inputs, generator)
        out = model(augmented)
        _, matched, _ = L.detection(out, truth, truth["counts"], augmented)
        target, labelled, ood = L.reliability_targets(matched, truth, L.query_regions(out, augmented, regions),
                                                      out["available"])
        evidence = out["evidence"]
        strength = evidence.sum(-1) + 2
        mean = (evidence[..., 0] + 1) / strength
        vacuity = 2 / strength
        for m in range(3):
            mu[m].append(mean[..., m][labelled[..., m]].cpu()); y[m].append(target[..., m][labelled[..., m]].cpu())
            u_known[m].append(vacuity[..., m][labelled[..., m]].cpu()); u_ood[m].append(vacuity[..., m][ood[..., m]].cpu())
    report = {}
    for m, name in enumerate(("rgb", "ir", "lidar")):
        probability, positive = torch.cat(mu[m]).numpy(), torch.cat(y[m]).numpy()
        known, unknown = torch.cat(u_known[m]).numpy(), torch.cat(u_ood[m]).numpy()
        report[name] = {"labelled": int(len(probability)), "positive_rate": float(positive.mean()) if len(positive) else None,
                        "reliability_mean_calibration": calibration_bins(probability, positive) if len(probability) else None,
                        "vacuity_known_mean": float(known.mean()) if len(known) else None,
                        "vacuity_ood_mean": float(unknown.mean()) if len(unknown) else None,
                        "ood_vacuity_auroc": auroc(unknown, known),
                        "matched_clean_reliability_by_condition": {c: float(np.mean(v[m])) if v[m] else None
                                                                   for c, v in by_condition.items()}}
    return report


def evaluate_checkpoint(args) -> dict:
    device = torch.device(args.device)
    features, targets, rows = load(args, "validation", device)
    folder = args.run_root / f"seed-{args.seed}"
    model, saved = load_checkpoint(folder / "best.pt", device, digest(args.dataset / "manifest.json"))
    patterns = {}
    for bits in range(8):
        available = torch.tensor([bool(bits & 1), bool(bits & 2), bool(bits & 4)], device=device)
        report, predicted = score(model, features, targets, rows, args.batch_size, available=available)
        detections = sum(len(p["scores"]) for p in predicted)
        patterns[PATTERN_NAMES[bits]] = {"map_3d": report["map_3d"], "classes": report["classes"],
                                         "false_positives": report["false_positives"],
                                         "empty_scene_false_positives": report["empty_scene_false_positives"],
                                         "detection_ece_10_bins": report["detection_ece_10_bins"],
                                         "matched_center_error_m": report["matched_center_error_m"],
                                         "detections": detections, "routing": report["routing"]}
    if patterns["none"]["detections"]:
        raise ValueError("All-unavailable input emitted detections")
    result = {"checkpoint_epoch": saved["epoch"], "seed": saved["seed"], "patterns": patterns,
              "reliability": reliability_report(model, features, targets, rows, args.batch_size, seed=1234)}
    write(folder / "evaluation.json", result)
    return result

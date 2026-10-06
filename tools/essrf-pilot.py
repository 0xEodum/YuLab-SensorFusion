"""SF-12 CLI: essrf-static-v1 caches, support targets, tiny overfit and training.

The sealed SF-11 test split is never loaded by this tool.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
import os
from pathlib import Path
import sys

os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
import numpy as np
import torch
from learning import essrf_data
from learning.essrf_training import SPLITS, records, train, write
from learning.essrf_evaluation import evaluate_checkpoint


def _prepare_one(job):
    root, record = job
    observation = essrf_data.preprocess(Path(root), record["capture_id"])
    target = essrf_data.supervision(Path(root), record["capture_id"], np.array(record["origin"]))
    return observation, target


def prepare(args):
    for split in SPLITS:
        dataset_sha, rows = records(args, split)
        observation_path = args.output / f"{split}-observations.pt"
        supervision_path = args.output / f"{split}-supervision.pt"
        if observation_path.exists() and supervision_path.exists():
            continue
        with ProcessPoolExecutor(args.workers) as pool:
            results = list(pool.map(_prepare_one, [(str(args.dataset), r) for r in rows], chunksize=8))
        observations = {k: torch.stack([o[k] for o, _ in results]) for k in results[0][0]}
        args.output.mkdir(parents=True, exist_ok=True)
        # Observation and supervision caches are separate files; the model only reads the first.
        torch.save({"dataset_sha256": dataset_sha, "preprocessing": essrf_data.PROFILE,
                    "capture_ids": [r["capture_id"] for r in rows], "features": observations}, observation_path)
        torch.save({"dataset_sha256": dataset_sha, "capture_ids": [r["capture_id"] for r in rows],
                    "conditions": [r["condition"] for r in rows], "targets": [t for _, t in results]},
                   supervision_path)
        print(f"cached {split}: {len(rows)} captures", flush=True)
    support_distribution(args)


def support_distribution(args):
    """Publish train support statistics by condition before choosing contrast thresholds."""
    cache = torch.load(args.output / "train-supervision.pt", weights_only=False)
    report = {"version": essrf_data.SUPPORT["version"], "split": "train", "criteria": essrf_data.SUPPORT,
              "conditions": {}}
    for condition in range(10):
        stats = [t["support_stats"] for t, c in zip(cache["targets"], cache["conditions"]) if c == condition]
        stats = torch.cat(stats) if stats else torch.empty(0, 5)
        row = {"objects": len(stats)}
        for name, column in (("rgb_contrast", 1), ("ir_contrast", 3), ("lidar_hits", 4)):
            visible = stats[stats[:, column - 1] >= essrf_data.SUPPORT["min_visible_pixels"]] if column != 4 else stats
            values = visible[:, column].numpy()
            row[name] = {q: float(np.percentile(values, q)) for q in (10, 25, 50, 75, 90)} if len(values) else None
        if essrf_data.SUPPORT["rgb_min_contrast"] is not None:
            row["positive_rate_rgb_ir_lidar"] = essrf_data.support_targets(stats).float().mean(0).tolist()
        report["conditions"][str(condition)] = row
    write(args.output / "support-distribution.json", report)


def build_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["prepare", "support", "tiny", "train", "evaluate"])
    parser.add_argument("--dataset", type=Path, default=ROOT / "artifacts/sf11/pilot-3000")
    parser.add_argument("--sf11", type=Path, default=ROOT / "artifacts/sf11/learning")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/sf12/essrf")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--run-root", type=Path, default=ROOT / "artifacts/sf12/essrf/runs")
    parser.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    parser.add_argument("--seed", type=int, default=11)
    parser.add_argument("--epochs", type=int, default=40)
    parser.add_argument("--tiny-steps", type=int, default=600)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--lr", type=float, default=5e-4)
    parser.add_argument("--queries", type=int, default=16)
    parser.add_argument("--width", type=int, default=128)
    parser.add_argument("--samples", type=int, default=16)
    parser.add_argument("--layers", type=int, default=2)
    parser.add_argument("--subset-warmup", type=int, default=6)
    parser.add_argument("--reliability-warmup", type=int, default=4)
    parser.add_argument("--subset-weight", type=float, default=1.0)
    parser.add_argument("--schedule", choices=["curriculum", "legacy"], default="curriculum")
    parser.add_argument("--clean-epochs", type=int, default=8)
    parser.add_argument("--ramp-epochs", type=int, default=16)
    parser.add_argument("--full-sensor-probability", type=float, default=.7)
    parser.add_argument("--local-only", action="store_true", help="Attempt-2 ablation: no per-modality global context")
    parser.add_argument("--clean", action="store_true", help="Control: no dropout, corruption, warm-up or subset/reliability terms")
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args(); args.tiny = args.stage == "tiny"
    if args.stage == "prepare":
        prepare(args)
    elif args.stage == "support":
        support_distribution(args)
    elif args.stage == "evaluate":
        evaluate_checkpoint(args)
    else:
        train(args)


if __name__ == "__main__":
    main()

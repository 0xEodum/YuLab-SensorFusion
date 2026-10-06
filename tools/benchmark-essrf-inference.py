"""Measured batch-one observation-to-prediction latency; no labels or capture generation."""
from __future__ import annotations
import argparse
import gc
import json
import os
from pathlib import Path
import sys
import time
os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
import numpy as np
import torch
from app.dataset import digest
from app.observation_input import load_observation_only
from learning import data, essrf_data
from learning.essrf_evaluation import load_checkpoint
from learning.essrf_training import write
from learning.model import Detector, predictions, predictions_from_arrays


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=ROOT / "artifacts/sf11/pilot-3000")
    parser.add_argument("--sf11", type=Path, default=ROOT / "artifacts/sf11/learning")
    parser.add_argument("--essrf-checkpoint", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/sf12/inference-resources.json")
    parser.add_argument("--samples", type=int, default=30)
    args = parser.parse_args()
    torch.set_num_threads(2)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    index = json.loads((args.sf11 / "index.json").read_text())
    sha = digest(args.dataset / "manifest.json")
    if index["dataset_sha256"] != sha:
        raise ValueError("Dataset provenance mismatch")
    rows = [r for r in index["records"] if r["split"] == "validation"]
    ids = [rows[i]["capture_id"] for i in np.linspace(0, len(rows) - 1, args.samples, dtype=int)]
    report = {"device": torch.cuda.get_device_name() if device.type == "cuda" else "CPU", "torch": str(torch.__version__),
              "dataset_sha256": sha, "split": "validation", "capture_ids": ids, "cpu_threads": 2,
              "scope": "warm filesystem, batch one; includes raw observation read/validation, fixed preprocessing, H2D, forward, D2H/decode; excludes checkpoint load and capture generation", "models": {}}
    checkpoints = [("fusion", args.sf11 / "runs/fusion/best.pt"), ("ir", args.sf11 / "runs/ir/best.pt"),
                   ("essrf", args.essrf_checkpoint)]
    sync = torch.cuda.synchronize if device.type == "cuda" else lambda: None
    for name, path in checkpoints:
        if name == "essrf":
            model, saved = load_checkpoint(path, device, sha)
        else:
            saved = torch.load(path, weights_only=True, map_location="cpu")
            if saved["preprocessing"] != data.PROFILE or saved["dataset_sha256"] != sha:
                raise ValueError("Baseline checkpoint provenance mismatch")
            model = Detector(saved["modality"], queries=saved["config"]["queries"], width=saved["config"]["width"]).to(device)
            model.load_state_dict(saved["model"])
        model.eval()
        metadata = {"checkpoint_sha256": digest(path), "config": saved["config"], "source_revision": saved["source_revision"]}
        del saved
        gc.collect()
        if device.type == "cuda":
            torch.cuda.empty_cache(); torch.cuda.reset_peak_memory_stats()
        timings = {k: [] for k in ("read_ms", "preprocess_ms", "h2d_ms", "forward_ms", "d2h_decode_ms", "end_to_end_ms")}
        with torch.no_grad():
            for i, capture_id in enumerate([ids[0]] * 5 + ids):
                sync(); t0 = time.perf_counter()
                obs, arrays = load_observation_only(args.dataset, {"capture_id": capture_id}); t1 = time.perf_counter()
                features = essrf_data.preprocess_arrays(obs, arrays) if name == "essrf" else data.preprocess_arrays(obs, arrays)[0]
                t2 = time.perf_counter()
                inputs = {k: v.unsqueeze(0).to(device) for k, v in features.items()}; sync(); t3 = time.perf_counter()
                out = model(inputs); sync(); t4 = time.perf_counter()
                values = predictions_from_arrays(torch.cat((out["boxes"], out["probability"]), -1).cpu().numpy()) if name == "essrf" else predictions(out)
                for value in values:
                    value["boxes"][:, :6] *= 200
                t5 = time.perf_counter()
                if i >= 5:
                    for key, value in zip(timings, (t1-t0, t2-t1, t3-t2, t4-t3, t5-t4, t5-t0)):
                        timings[key].append(value * 1000)
                del inputs, out, features, obs, arrays
        report["models"][name] = {**metadata, "latency_ms": {k: {"p50": float(np.percentile(v, 50)),
            "p95": float(np.percentile(v, 95))} for k, v in timings.items()},
            "peak_allocated_bytes": torch.cuda.max_memory_allocated() if device.type == "cuda" else None,
            "peak_reserved_bytes": torch.cuda.max_memory_reserved() if device.type == "cuda" else None}
        del model
        gc.collect()
    write(args.output, report)
    print(json.dumps(report["models"], indent=2))


if __name__ == "__main__":
    main()

"""Export immutable SF-11 curves, reports, artifact hashes and inference isolation."""
from __future__ import annotations

import argparse
import importlib.metadata
import json
from pathlib import Path
import platform
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import torch
from app.dataset import digest
from learning.inference import infer_capture


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=ROOT / "artifacts/sf11/pilot-3000")
    parser.add_argument("--runs", type=Path, default=ROOT / "artifacts/sf11/learning")
    parser.add_argument("--output", type=Path, default=ROOT / "docs/evidence/sf11")
    args = parser.parse_args()
    torch.set_num_threads(2)
    args.output.mkdir(parents=True, exist_ok=True)
    names = ("rgb", "ir", "lidar", "fusion")
    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    artifacts = []
    for name in names:
        folder = args.runs / "runs" / name
        history = json.loads((folder / "history.json").read_text())
        axes[0].plot([h["epoch"] for h in history], [h["loss"] for h in history], label=name)
        axes[1].plot([h["epoch"] for h in history], [h["validation"]["map_3d"] for h in history], label=name)
        for file in ("history.json", "validation.json", "test.json", "runtime.json"):
            shutil.copy2(folder / file, args.output / f"{name}-{file}")
        artifacts.append({"modality": name, "checkpoint": str(folder / "best.pt"),
                          "sha256": digest(folder / "best.pt"),
                          "prediction_sha256": digest(folder / "test-predictions.json")})
    for ax, title, ylabel in zip(axes, ("Training objective", "Grouped validation 3D AP"), ("Loss", "mAP")):
        ax.set(title=title, xlabel="Epoch", ylabel=ylabel); ax.grid(alpha=.25); ax.legend()
    axes[1].set_ylim(0, 1)
    fig.tight_layout(); fig.savefig(args.output / "learning-curves.png", dpi=180); plt.close(fig)
    for file in ("coverage-before-training.json", "sf15-targets.json"):
        shutil.copy2(args.runs / file, args.output / file)
    for file in ("runtime.json", "validation.json", "history.json"):
        shutil.copy2(args.runs / "tiny/fusion" / file, args.output / f"tiny-{file}")
    # Physically observation-only copy: labels/truth/reference files never exist here.
    capture_id = "sf11-0000"
    source = args.dataset / capture_id
    isolated = ROOT / "artifacts/sf11/inference-isolated"
    directory = isolated / capture_id; directory.mkdir(parents=True, exist_ok=True)
    obs = json.loads((source / "observation.json").read_text())
    shutil.copy2(source / "observation.json", directory / "observation.json")
    for modality in ("rgb", "ir", "lidar"):
        for ref in obs[modality]["data"].values():
            if isinstance(ref, dict) and "artifact" in ref:
                name = ref["artifact"]["id"]; shutil.copy2(source / name, directory / name)
    comparisons = {}
    for name in names:
        checkpoint = args.runs / "runs" / name / "best.pt"
        first = infer_capture(args.dataset, {"capture_id": capture_id}, checkpoint, "cuda")
        second = infer_capture(isolated, {"capture_id": capture_id}, checkpoint, "cuda")
        comparisons[name] = {"identical_detections": first["detections"] == second["detections"],
                             "observation_preprocessing_and_inference_ms": second["latency_ms"],
                             "detections": len(first["detections"])}
        if not comparisons[name]["identical_detections"]:
            raise ValueError("Truth-free checkpoint inference changed predictions")
        (args.output / f"{name}-example-prediction.json").write_text(json.dumps(second, indent=2) + "\n")
    environment = {"python": sys.version, "executable": sys.executable, "platform": platform.platform(),
                   "torch_cuda": torch.version.cuda, "gpu": torch.cuda.get_device_name(),
                   "packages": {d.metadata["Name"]: d.version for d in importlib.metadata.distributions()}}
    evidence = {"dataset_sha256": digest(args.dataset / "manifest.json"),
                "checkpoints": artifacts, "inference_observation_only": comparisons,
                "isolated_file_names": sorted(p.name for p in directory.iterdir()), "environment": environment,
                "source_files": {str(p.relative_to(ROOT)): digest(p) for p in
                    [*sorted((ROOT / "backend/learning").glob("*.py")), ROOT / "tools/learning-pilot.py"]},
                "limits": ["single training seed", "static synthetic scenes; shared meshes/infrastructure",
                           "3D-only head", "fresh optional environment download failed; used recorded installed environment",
                           "resident inference timing excludes observation readback; separate example end-to-end timings included"]}
    (args.output / "artifact-manifest.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps(comparisons), flush=True)


if __name__ == "__main__":
    main()

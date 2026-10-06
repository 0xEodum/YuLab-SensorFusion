"""Export measured SF-12 comparison, failures, learning curves and artifact hashes."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import shutil
import sys
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.dataset import digest

ROBUST_CASES = [f"availability-{bits}" for bits in range(1, 7)] + [f"{m}-{f}" for m in
    ("rgb", "ir", "lidar") for f in ("known", "ood")]
NAMES = {f"availability-{i}": n for i, n in enumerate(("None", "RGB", "IR", "RGB + IR", "LiDAR",
    "RGB + LiDAR", "IR + LiDAR", "All sensors"))}
NAMES.update({f"{m}-{f}": f"{m.upper() if m != 'lidar' else 'LiDAR'} {f}" for m in
    ("rgb", "ir", "lidar") for f in ("known", "ood")})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--comparison", type=Path, default=ROOT / "artifacts/sf12/final-comparison.json")
    parser.add_argument("--runs", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "docs/evidence/sf12")
    args = parser.parse_args()
    report = json.loads(args.comparison.read_text())
    if report["split"] != "validation" or "elapsed_s" not in report:
        raise ValueError("Only completed validation comparisons can be published")
    args.output.mkdir(parents=True, exist_ok=True)
    models = report["models"]
    groups = {name: [models[f"{name}-seed-{s}"] for s in (11, 12, 13)] for name in
              ("essrf", "baseline-fusion", "baseline-ir", "baseline-rgb", "baseline-lidar")}
    for group in groups.values():
        if any(set(m["scenarios"]) != set(NAMES) for m in group):
            raise ValueError("Incomplete paired scenarios")
    summary = {"dataset_sha256": report["dataset_sha256"], "split": "validation", "seeds": [11, 12, 13],
               "uncertainty": "sample SD across three training seeds, not a validation-group confidence interval",
               "scenarios": {}, "robustness_macro": {}, "paired_essrf_minus_fusion": {}}
    for case in NAMES:
        summary["scenarios"][case] = {}
        for name, group in groups.items():
            values = [m["scenarios"][case]["map_3d"] for m in group]
            if any(v is None for v in values):
                raise ValueError("Undefined aggregate mAP in populated pilot validation")
            summary["scenarios"][case][name] = {"mean": float(np.mean(values)), "sample_sd": float(np.std(values, ddof=1)),
                                                 "by_seed": values}
    for name, group in groups.items():
        values = [float(np.mean([m["scenarios"][c]["map_3d"] for c in ROBUST_CASES])) for m in group]
        summary["robustness_macro"][name] = {"mean": float(np.mean(values)), "sample_sd": float(np.std(values, ddof=1)),
                                           "by_seed": values, "cases": ROBUST_CASES}
    for case in NAMES:
        values = np.array(summary["scenarios"][case]["essrf"]["by_seed"]) - \
                 np.array(summary["scenarios"][case]["baseline-fusion"]["by_seed"])
        summary["paired_essrf_minus_fusion"][case] = {"mean": float(values.mean()), "sample_sd": float(values.std(ddof=1)),
                                                     "by_seed": values.tolist()}
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n")
    shutil.copyfile(args.comparison, args.output / "comparison.json")
    for seed in (11, 12, 13):
        for name in ("history.json", "runtime.json", "validation.json"):
            shutil.copyfile(args.runs / f"seed-{seed}" / name, args.output / f"seed-{seed}-{name}")
    for source, name in ((ROOT / "artifacts/sf12/reproducibility.json", "reproducibility.json"),
                         (ROOT / "artifacts/sf12/sampling-determinism.json", "legacy-sampling-determinism.json"),
                         (ROOT / "artifacts/sf12/inference-resources.json", "inference-resources.json")):
        shutil.copyfile(source, args.output / name)
    # Actual failed/diagnostic controls, rather than only the selected result.
    controls = []
    folders = [("C1 clean Q128", "controls/c1-clean-q128/seed-11"),
               ("C2 clean Q16", "controls/c2-clean-q16/seed-11"),
               ("C3 legacy Q16", "controls/c3-full-q16/seed-11"),
               ("C4 clean Q32", "controls/c4-clean-q32/seed-11"),
               ("Attempt 2 local Q128", "runs/attempt-2-local-seed-11"),
               ("Non-deterministic curriculum Q16", "curriculum-q16/seed-11"),
               ("Non-deterministic curriculum Q32", "curriculum-q32/seed-11"),
               ("Deterministic curriculum Q16", "deterministic-q16/seed-11"),
               ("Deterministic curriculum Q32", "deterministic-q32/seed-11")]
    for label, folder in folders:
        root = ROOT / "artifacts/sf12/essrf" / folder
        runtime = json.loads((root / "runtime.json").read_text())
        history = json.loads((root / "history.json").read_text())
        controls.append({"label": label, "folder": str(root.relative_to(ROOT)), "runtime": runtime,
                         "history_sha256": digest(root / "history.json"), "checkpoint_sha256": digest(root / "best.pt"),
                         "last_epoch_map": history[-1]["validation"]["map_3d"]})
    (args.output / "controls.json").write_text(json.dumps(controls, indent=2, allow_nan=False) + "\n")
    colors = {"essrf": "#176b9b", "baseline-fusion": "#d17a21", "baseline-ir": "#616161"}
    labels = {"essrf": "ESSRF", "baseline-fusion": "Fusion baseline", "baseline-ir": "IR baseline"}
    cases = ["availability-7"] + ROBUST_CASES
    fig, ax = plt.subplots(figsize=(10, 9), layout="constrained")
    y = np.arange(len(cases))
    for i, name in enumerate(colors):
        means = [summary["scenarios"][c][name]["mean"] for c in cases]
        sd = [summary["scenarios"][c][name]["sample_sd"] for c in cases]
        ax.barh(y + (i - 1) * .24, means, height=.22, xerr=sd, label=labels[name], color=colors[name], capsize=2)
    ax.set(yticks=y, yticklabels=[NAMES[c] for c in cases], xlabel="Validation 3D mAP (mean and sample SD, 3 seeds)",
           title="SF-12 paired sensor degradation; fixed checkpoints, unchanged labels")
    ax.invert_yaxis(); ax.legend(loc="lower right"); ax.grid(axis="x", alpha=.2)
    fig.savefig(args.output / "degradation.png", dpi=180)
    fig.savefig(args.output / "degradation.svg")
    plt.close(fig)
    fig, axes = plt.subplots(1, 2, figsize=(11, 4), layout="constrained")
    for seed in (11, 12, 13):
        history = json.loads((args.runs / f"seed-{seed}/history.json").read_text())
        epoch = [r["epoch"] for r in history]
        axes[0].plot(epoch, [r["loss"] for r in history], label=f"Seed {seed}")
        axes[1].plot(epoch, [r["validation"]["map_3d"] for r in history], label=f"Seed {seed}")
    for ax in axes:
        ax.axvspan(0, 8, color="grey", alpha=.08)
        ax.axvspan(8, 24, color="grey", alpha=.16)
        ax.set_xlabel("Epoch (clean 1–8, ramp 9–24, final regime 24–40)"); ax.grid(alpha=.2)
    axes[0].set_ylabel("Training loss (NLL may be negative)")
    axes[1].set_ylabel("Clean validation 3D mAP"); axes[1].legend()
    fig.savefig(args.output / "learning-curves.png", dpi=180); plt.close(fig)
    matrix = ["| Scenario | ESSRF | Fusion | IR |", "| --- | ---: | ---: | ---: |"]
    for c in ["availability-7"] + ROBUST_CASES + ["availability-0"]:
        cells = []
        for n in colors:
            v = summary["scenarios"][c][n]
            cells.append(f"{v['mean']:.3f} ± {v['sample_sd']:.3f}")
        matrix.append(f"| {NAMES[c]} | " + " | ".join(cells) + " |")
    (args.output / "matrix.md").write_text("\n".join(matrix) + "\n", encoding="utf-8")
    paths = [p for p in args.output.iterdir() if p.is_file() and p.name != "artifact-manifest.json"]
    (args.output / "artifact-manifest.json").write_text(json.dumps({"files": [
        {"path": p.name, "sha256": digest(p), "bytes": p.stat().st_size} for p in sorted(paths)]}, indent=2) + "\n")
    print(json.dumps(summary["robustness_macro"], indent=2))


if __name__ == "__main__":
    main()

"""Export SF-15 comparison evidence and the preselected first ensemble bundle."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
import torch
from app.dataset import digest
from app.scaling import read
from learning.decision_inference import DecisionFusionPredictor
from learning.scaling_acceptance import assert_frozen


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def compact(report):
    # Full condition matrices and predictions remain in the immutable run root.
    for methods in report["cases"].values():
        for name, case in methods.items():
            if name != "availability-7":
                case.pop("conditions", None)
                case.pop("condition_profiles", None)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT / "artifacts/sf15")
    parser.add_argument("--output", type=Path, default=ROOT / "docs/evidence/sf15-scaling")
    parser.add_argument("--freeze", type=Path, help="Freeze the sealed test ran under (default: ROOT/freeze.json)")
    args = parser.parse_args()
    frozen = read(args.freeze or args.root / "freeze.json"); assert_frozen(frozen)
    selection = read(args.root / "selection.json")
    torch.set_num_threads(2)
    spec = importlib.util.spec_from_file_location("scale", ROOT / "tools/scale-ensemble.py")
    scale = importlib.util.module_from_spec(spec); spec.loader.exec_module(scale)
    volume = selection["scaled_contender_samples"]
    run = args.root / f"runs-{volume}"
    for historical, name in ((False, "scaled-model-bundle.json"), (True, "baseline-model-bundle.json")):
        mapping = scale.paths(run, historical)
        experts = []
        for seed in scale.GROUPS[0]:
            for snapshot in ("raw", "swa"):
                for modality in scale.MODALITIES:
                    path = mapping[(seed, modality, snapshot)]
                    experts.append({"path": path.relative_to(ROOT).as_posix(), "sha256": digest(path),
                                    "modality": modality, "seed": seed, "snapshot": snapshot})
        model = DecisionFusionPredictor([ROOT / e["path"] for e in experts], "cpu", [e["sha256"] for e in experts])
        bundle = {"profile": model.identity["profile"], "checkpoint_sha256": model.sha256,
                  "member_seeds": list(scale.GROUPS[0]), "training_samples": 2100 if historical else volume,
                  "training_sha256": torch.load(ROOT / experts[0]["path"], weights_only=True, map_location="cpu")["dataset_sha256"],
                  "averaged_epochs": 60, "consensus_iou": .1, "experts": experts,
                  "selection": "First predeclared ensemble, never the best test/validation seed group"}
        write(args.output / name, bundle)
        if historical == (selection["selected"] == "baseline"):
            write(args.output / "model-bundle.json", bundle)
        del model
    write(args.output / "selection.json", selection)
    for path in sorted(args.root.glob("validation-*.json")):
        if "predictions" not in path.name and "recheck" not in path.name: write(args.output / path.name, compact(read(path)))
    write(args.output / "test-report.json", compact(read(args.root / "test-report.json")))
    # Store portable relative identities in the exported freeze, preserving the local raw freeze too.
    exported = dict(frozen)
    exported["files"] = {Path(p).relative_to(ROOT).as_posix(): sha for p,sha in frozen["files"].items()}
    write(args.output / "freeze.json", exported)
    runtime = {}
    for folder in sorted(args.root.glob("runs-*")):
        items = []
        for path in sorted(folder.glob("seed-*/*/runtime.json")):
            value = read(path); value["run"] = path.parent.relative_to(ROOT).as_posix()
            items.append(value)
        runtime[folder.name] = {"trajectories": len(items), "optimizer_observed_exposures": sum(x["optimizer_observed_exposures"] for x in items),
            "optimizer_steps": sum(x["optimizer_steps"] for x in items), "train_cli_s": sum(x["cli_wall_s"] for x in items),
            "peak_allocated_bytes": max(x["peak_allocated_bytes"] for x in items),
            "peak_reserved_bytes": max(x["peak_reserved_bytes"] for x in items), "runs": items}
    write(args.output / "training-runtime.json", runtime)
    write(args.output / "experiment-state.json", read(args.root / "experiment-state.json"))
    selected = read(args.root / "test-report.json")["methods"][selection["selected"]]
    checks = {"selected": selection["selected"], "training_samples": selection["selected_training_samples"],
              "clean_target": selected["clean_mean"] >= .5, "macro_target": selected["macro_mean"] >= .35,
              "sample_sd_target": max(selected["clean_sd"], selected["macro_sd"]) <= .03,
              "all_missing_abstention": selected["all_missing_detections"] == 0,
              "checkpoint_reload_exact": read(args.root / "test-report.json")["checkpoint_reload_exact_prediction_parity"],
              "claims": "Static synthetic known-asset detector; no learned temporal/calibration or sim-to-real acceptance",
              "scope": "Volume-rule floors only (clean/macro/SD/abstention/reload); the frozen SF-11 target verdict is sf11_targets in results-summary.json"}
    checks["quality_pass"] = all(checks[k] for k in ("clean_target", "macro_target", "sample_sd_target", "all_missing_abstention", "checkpoint_reload_exact"))
    write(args.output / "acceptance-checks.json", checks)
    print(json.dumps(checks), flush=True)


if __name__ == "__main__": main()

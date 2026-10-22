"""Post-selection historical-clip ablation with frozen SF-14 parameters; no tuning."""
import argparse
import json
from pathlib import Path
import pickle
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.dataset import digest
from learning.temporal_tracker import TrackerParams
from learning.temporal_evaluation import group_sequences, evaluate_all, AVAILABILITY, CORRUPTIONS


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, nargs="+", required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists(): raise ValueError("Ablation already scored")
    bundle = json.loads(args.bundle.read_text())
    protocol = ROOT / "docs/evidence/sf14-temporal/protocol.json"
    frozen = json.loads(protocol.read_text())
    values = dict(frozen["parameters"]); scale = values.pop("noise_scale")
    params = TrackerParams(sensor_sigma_m=tuple(s*scale for s in frozen["fitted_sensor_sigma_m"]), **values)
    frames = []
    for path in args.cache:
        # These are our local generated numeric caches, not external pickle input.
        with path.open("rb") as stream: payload = pickle.load(stream)
        if payload["ensemble_sha256"] != bundle["checkpoint_sha256"]:
            raise ValueError("Temporal cache/model mismatch")
        frames.extend(f for f in payload["frames"] if f["split"] == "test")
    sequences = group_sequences(frames)
    cases = evaluate_all(params, sequences, ("clean", *AVAILABILITY, *CORRUPTIONS))
    for value in cases.values():
        import numpy as np
        timings = value.pop("step_ms")
        value["step_ms"] = {"p50": float(np.percentile(timings,50)), "p95": float(np.percentile(timings,95))}
    output = {"profile": "sf15-historical-temporal-ablation.v1", "ensemble_sha256": bundle["checkpoint_sha256"],
              "frames": len(frames), "sequences": len(sequences), "cases": cases,
              "sf14_protocol_sha256": digest(protocol), "cache_hashes": {str(p):digest(p) for p in args.cache},
              "scope": "Historical SF-13/SF-14 test clips; post-selection descriptive transfer, not a fresh temporal holdout. Old fitted measurement noise retained; no learned drift or temporal head."}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    print(json.dumps({k:v for k,v in output.items() if k!='cases'}),flush=True)


if __name__ == "__main__": main()

"""Run one checkpoint-backed inference with no annotation/truth access."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import torch
from learning.inference import infer_capture

parser = argparse.ArgumentParser()
parser.add_argument("--observations", type=Path, required=True)
parser.add_argument("--capture-id", required=True)
parser.add_argument("--checkpoint", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--device", default="cpu")
args = parser.parse_args()
torch.set_num_threads(2)
result = infer_capture(args.observations, {"capture_id": args.capture_id}, args.checkpoint, args.device)
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
print(f"{len(result['detections'])} predictions; observation preprocessing + inference {result['latency_ms']:.1f} ms")

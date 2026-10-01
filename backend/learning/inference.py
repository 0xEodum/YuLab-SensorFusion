"""Checkpoint inference reads only the observation bundle and referenced arrays."""
from __future__ import annotations

from pathlib import Path
import time
import numpy as np
import torch

from app.contracts import validate_payload
from app.dataset import digest
from .data import PROFILE, preprocess
from .model import Detector, predictions


def infer_capture(root: Path, request: dict, checkpoint: Path, device="cpu") -> dict:
    if not isinstance(request, dict) or set(request) != {"capture_id"}:
        raise ValueError("Inference accepts only capture_id")
    saved = torch.load(checkpoint, weights_only=True, map_location=device)
    if saved["profile"] != "baseline-v1" or saved["preprocessing"] != PROFILE:
        raise ValueError("Unsupported checkpoint/preprocessing profile")
    model = Detector(saved["modality"]).to(device)
    model.load_state_dict(saved["model"]); model.eval()
    if str(device).startswith("cuda"): torch.cuda.synchronize()
    started = time.perf_counter()
    features, origin = preprocess(root, request["capture_id"])
    with torch.no_grad():
        output = predictions(model({k: v.unsqueeze(0).to(device) for k, v in features.items()}))[0]
    if str(device).startswith("cuda"): torch.cuda.synchronize()
    latency = (time.perf_counter() - started) * 1000
    detections = []
    for i, (box, cls, score) in enumerate(zip(output["boxes"], output["classes"], output["scores"])):
        yaw = float(box[6])
        detections.append({"prediction_id": f"prediction-{i}", "class_id": int(cls) + 8,
                           "score": float(score), "box_3d": {"frame": "east-up-south",
                           "center_m": (box[:3] * 200 + origin).tolist(),
                           "extent_m": (box[3:6] * 200).tolist(),
                           "quaternion_xyzw": [0, float(np.sin(yaw/2)), 0, float(np.cos(yaw/2))]},
                           "observation_supported": True,
                           # Baselines do not estimate variance or evidential routing.
                           "position_variance_m2": None, "routing": None})
    result = {"schema_version": "lab.v1", "kind": "PredictionBundle", "capture_id": request["capture_id"],
              "checkpoint_id": f"baseline-{saved['modality']}", "checkpoint_sha256": digest(checkpoint),
              "latency_ms": latency, "detections": detections, "state": None}
    validate_payload("PredictionBundle", result)
    return result

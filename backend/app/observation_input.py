"""Observation-only read boundary for future inference and SF-11 loaders."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from .contracts import validate_payload
from .dataset import digest


def load_observation_only(root: Path, request: dict) -> tuple[dict, dict[str, np.ndarray]]:
    if not isinstance(request, dict) or set(request) != {"capture_id"}:
        raise ValueError("Observation request accepts only capture_id")
    capture_id = request["capture_id"]
    if not isinstance(capture_id, str) or not capture_id.isascii() or not capture_id or any(
        char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for char in capture_id
    ):
        raise ValueError("Invalid capture ID")
    directory = (root / capture_id).resolve()
    if directory.parent != root.resolve():
        raise ValueError("Observation path escaped the dataset root")
    payload = json.loads((directory / "observation.json").read_text(encoding="utf-8"))
    validate_payload("ObservationBundle", payload)
    if payload["capture_id"] != capture_id:
        raise ValueError("Observation capture ID mismatch")
    arrays: dict[str, np.ndarray] = {}
    for modality in ("rgb", "ir", "lidar"):
        sensor = payload[modality]
        if sensor["status"] != "available":
            continue
        for name, reference in sensor["data"].items():
            if not isinstance(reference, dict) or "artifact" not in reference:
                continue
            meta = reference["artifact"]
            path = directory / meta["id"]
            if path.resolve().parent != directory or digest(path) != meta["sha256"] or \
               path.stat().st_size != meta["byte_length"]:
                raise ValueError("Observation array hash mismatch")
            value = np.load(path, allow_pickle=False)
            if list(value.shape) != reference["shape"]:
                raise ValueError("Observation array shape mismatch")
            arrays[f"{modality}.{name}"] = value
    return payload, arrays

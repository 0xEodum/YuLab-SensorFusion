"""Exact, fixed preprocessing. Observation and supervision paths stay separate."""
from __future__ import annotations

import json
from pathlib import Path
import numpy as np
import torch
import torch.nn.functional as F

from app.observation_input import load_observation_only

PROFILE = {"version": "baseline-preprocess.v1", "image_hw": [96, 160],
           "points": 256, "coordinate_scale_m": 200.0,
           "rgb": "sRGB / 255, area resize", "ir": "radiance / 100, invalid=0, area resize",
           "lidar": "valid observed points, beam-order uniform subsample, world-relative XYZ / 200; intensity unchanged"}


def preprocess(root: Path, capture_id: str) -> tuple[dict[str, torch.Tensor], np.ndarray]:
    obs, arrays = load_observation_only(root, {"capture_id": capture_id})
    return preprocess_arrays(obs, arrays)


def preprocess_arrays(obs: dict, arrays: dict) -> tuple[dict[str, torch.Tensor], np.ndarray]:
    """The same fixed profile, usable after shared observation-level degradation."""
    transform = np.array(obs["rig"]["T_world_from_rig"]).reshape(4, 4)
    origin = transform[:3, 3].copy()
    sensors = {s["modality"]: s for s in obs["rig"]["sensors"]}
    features = {}
    calibration = []
    for modality in ("rgb", "ir"):
        sensor = sensors[modality]
        camera = sensor["camera"]
        extrinsic = transform @ np.array(sensor["T_rig_from_sensor"]).reshape(4, 4)
        calibration.extend(extrinsic[:3, :3].ravel())
        calibration.extend((extrinsic[:3, 3] - origin) / 200)
        # Camera keys are versioned by the canonical schema.
        calibration.extend([camera["fx_px"] / camera["width_px"], camera["fy_px"] / camera["height_px"],
                            camera["cx_px"] / camera["width_px"], camera["cy_px"] / camera["height_px"]])
        if modality == "rgb":
            image = torch.from_numpy(arrays["rgb.image"].copy()).permute(2, 0, 1).float() / 255
            valid = torch.from_numpy(arrays["rgb.validity_mask"].copy())
        else:
            image = torch.from_numpy(arrays["ir.radiance"].copy()).float().unsqueeze(0) / 100
            valid = torch.from_numpy(arrays["ir.validity_mask"].copy())
        image = image * valid.unsqueeze(0)
        features[modality] = F.interpolate(image.unsqueeze(0), size=PROFILE["image_hw"], mode="area")[0]
    sensor = sensors["lidar"]
    extrinsic = transform @ np.array(sensor["T_rig_from_sensor"]).reshape(4, 4)
    valid = arrays["lidar.validity"]
    xyz = arrays["lidar.xyz"][valid]
    intensity = arrays["lidar.intensity"][valid]
    xyz = (xyz @ extrinsic[:3, :3].T + extrinsic[:3, 3] - origin) / 200
    n = min(len(xyz), PROFILE["points"])
    indices = np.linspace(0, max(0, len(xyz) - 1), n, dtype=int)
    points = np.zeros((PROFILE["points"], 4), dtype=np.float32)
    points[:n, :3] = xyz[indices]
    points[:n, 3] = intensity[indices]
    features["lidar"] = torch.from_numpy(points)
    features["point_valid"] = torch.arange(PROFILE["points"]) < n
    features["calibration"] = torch.tensor(calibration, dtype=torch.float32)
    if not all(torch.isfinite(v).all() for v in features.values()):
        raise ValueError("Nonfinite observation features")
    return features, origin


def supervision(root: Path, entry: dict, origin: np.ndarray) -> dict:
    ann = json.loads((root / entry["capture_id"] / "annotations.json").read_text(encoding="utf-8"))
    boxes, classes, ignored = [], [], []
    for obj in ann["objects"]:
        box = obj["box_3d"]
        qx, qy, qz, qw = box["quaternion_xyzw"]
        if abs(qx) > 1e-6 or abs(qz) > 1e-6:
            raise ValueError("baseline-v1 requires upright yaw-only boxes")
        yaw = 2 * np.arctan2(qy, qw)
        value = [*((np.array(box["center_m"]) - origin) / 200), *(np.array(box["extent_m"]) / 200), yaw]
        if obj["eligible"]:
            boxes.append(value); classes.append(obj["class_id"] - 8)
        else:
            ignored.append(value)
    return {"boxes": torch.tensor(boxes, dtype=torch.float32).reshape(-1, 7),
            "classes": torch.tensor(classes, dtype=torch.long),
            "ignored": torch.tensor(ignored, dtype=torch.float32).reshape(-1, 7)}

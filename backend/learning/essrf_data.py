"""essrf-static-v1 preprocessing. Observation and supervision paths stay separate.

Geometry uses a gravity-aligned heading frame H built only from nominal rig
calibration: origin at the rig, x right, y world up, z backward (rig forward is
-z). Coordinates are divided by COORDINATE_SCALE_M, like baseline-v1 labels.
"""
from __future__ import annotations

import json
from pathlib import Path
import numpy as np
import torch
from scipy.ndimage import binary_dilation

from app.observation_input import load_observation_only

COORDINATE_SCALE_M = 200.0
MAX_POINTS = 8192
IMAGE_HW = (384, 640)
PROFILE = {"version": "essrf-preprocess.v1", "image_hw": list(IMAGE_HW), "max_points": MAX_POINTS,
           "coordinate_scale_m": COORDINATE_SCALE_M, "frame": "heading: x right, y up, z backward",
           "rgb": "uint8 sRGB, invalid pixels zero", "ir": "radiance / 100 fp16, invalid zero; flags valid|saturated<<1",
           "lidar": "all valid observed points in heading frame / 200, intensity unchanged"}
# Versioned supervision-only support criteria (reliability-targets.v1).
SUPPORT = {"version": "reliability-targets.v1", "min_visible_pixels": 32, "ring_px": 6,
           "rgb_min_contrast": .3, "ir_min_contrast": 1.0, "lidar_min_hits": 3}


def heading_frame(world_from_rig: np.ndarray) -> np.ndarray:
    """World-from-heading rotation: same horizontal forward as the rig, world up."""
    forward = world_from_rig[:3, :3] @ np.array([0.0, 0.0, -1.0])
    forward[1] = 0
    norm = np.linalg.norm(forward)
    if norm < 1e-6:
        raise ValueError("Rig looks vertically; heading frame undefined")
    forward /= norm
    up = np.array([0.0, 1.0, 0.0])
    right = np.cross(forward, up)
    return np.stack((right, up, -forward), 1)


def heading_yaw(world_from_heading: np.ndarray) -> float:
    """Rotation about world up taking heading axes to world axes."""
    return float(np.arctan2(world_from_heading[0, 2], world_from_heading[0, 0]))


def camera_from_heading(world_from_rig, world_from_heading, rig_from_sensor) -> np.ndarray:
    """4x4 transform from scaled heading coordinates to metric optical camera axes."""
    heading = np.eye(4)
    heading[:3, :3] = world_from_heading * COORDINATE_SCALE_M
    heading[:3, 3] = world_from_rig[:3, 3]
    return np.linalg.inv(world_from_rig @ rig_from_sensor) @ heading


def preprocess(root: Path, capture_id: str) -> dict[str, torch.Tensor]:
    obs, arrays = load_observation_only(root, {"capture_id": capture_id})
    return preprocess_arrays(obs, arrays)


def preprocess_arrays(obs: dict, arrays: dict) -> dict[str, torch.Tensor]:
    """The same fixed profile, usable after shared observation-level degradation."""
    world_from_rig = np.array(obs["rig"]["T_world_from_rig"]).reshape(4, 4)
    world_from_heading = heading_frame(world_from_rig)
    sensors = {s["modality"]: s for s in obs["rig"]["sensors"]}
    out: dict[str, torch.Tensor] = {}
    available = []
    for modality in ("rgb", "ir", "lidar"):
        status = obs[modality]["status"] == "available" and sensors[modality]["available"]
        available.append(bool(status))
    for modality in ("rgb", "ir"):
        sensor = sensors[modality]
        camera = sensor["camera"]
        if camera["distortion"] != "ideal-pinhole" or camera["frame"] != "optical-right-down-forward":
            raise ValueError("essrf-static-v1 supports ideal pinhole optical cameras only")
        if (camera["height_px"], camera["width_px"]) != IMAGE_HW:
            raise ValueError("Unexpected camera resolution")
        transform = camera_from_heading(world_from_rig, world_from_heading,
                                        np.array(sensor["T_rig_from_sensor"]).reshape(4, 4))
        out[f"{modality}_from_heading"] = torch.tensor(transform, dtype=torch.float32)
        out[f"{modality}_intrinsics"] = torch.tensor(
            [camera["fx_px"], camera["fy_px"], camera["cx_px"], camera["cy_px"]], dtype=torch.float32)
    if available[0]:
        valid = arrays["rgb.validity_mask"].astype(bool)
        out["rgb"] = torch.from_numpy((arrays["rgb.image"] * valid[..., None]).transpose(2, 0, 1).copy())
    else:
        out["rgb"] = torch.zeros((3, *IMAGE_HW), dtype=torch.uint8)
    if available[1]:
        valid = arrays["ir.validity_mask"].astype(bool)
        radiance = np.where(valid, arrays["ir.radiance"] / 100.0, 0).astype(np.float16)
        flags = valid.astype(np.uint8) | (arrays["ir.saturation_mask"].astype(np.uint8) << 1)
    else:
        radiance = np.zeros(IMAGE_HW, np.float16); flags = np.zeros(IMAGE_HW, np.uint8)
    out["ir"] = torch.from_numpy(radiance.copy()); out["ir_flags"] = torch.from_numpy(flags.copy())
    points = np.zeros((MAX_POINTS, 4), np.float32); count = 0
    if available[2]:
        sensor = sensors["lidar"]
        world_from_lidar = world_from_rig @ np.array(sensor["T_rig_from_sensor"]).reshape(4, 4)
        valid = arrays["lidar.validity"].astype(bool)
        xyz = arrays["lidar.xyz"][valid].astype(np.float64)
        if len(xyz) > MAX_POINTS:
            raise ValueError("LiDAR scan exceeds the bounded point budget")
        world = xyz @ world_from_lidar[:3, :3].T + world_from_lidar[:3, 3]
        local = (world - world_from_rig[:3, 3]) @ world_from_heading / COORDINATE_SCALE_M
        count = len(local)
        points[:count, :3] = local; points[:count, 3] = arrays["lidar.intensity"][valid]
    out["lidar"] = torch.from_numpy(points)
    out["point_valid"] = torch.arange(MAX_POINTS) < count
    out["available"] = torch.tensor(available)
    out["world_from_heading"] = torch.tensor(world_from_heading, dtype=torch.float32)
    out["heading_yaw"] = torch.tensor(heading_yaw(world_from_heading), dtype=torch.float32)
    for key, value in out.items():
        if value.is_floating_point() and not torch.isfinite(value).all():
            raise ValueError(f"Nonfinite observation feature {key}")
    return out


def _contrast(values: np.ndarray, mask: np.ndarray, valid: np.ndarray, ring_px: int) -> float:
    """|mean(object) - mean(ring)| / (std(ring) + floor), in the observed image."""
    inside = mask & valid
    ring = binary_dilation(mask, iterations=ring_px) & ~mask & valid
    if inside.sum() < 4 or ring.sum() < 4:
        return 0.0
    background = values[ring]
    return float(abs(values[inside].mean() - background.mean()) / (background.std() + .02))


def supervision(root: Path, capture_id: str, origin: np.ndarray) -> dict:
    """Truth path only: boxes plus per-object local support statistics."""
    directory = root / capture_id
    ann = json.loads((directory / "annotations.json").read_text(encoding="utf-8"))
    rgb = np.load(directory / "rgb_raw_npy").astype(np.float32).mean(-1) / 255
    rgb_valid = np.load(directory / "rgb_valid_npy").astype(bool)
    ir = np.load(directory / "ir_radiance_npy").astype(np.float32) / 100
    ir_valid = np.load(directory / "ir_validity_npy").astype(bool)
    boxes, classes, ignored, stats = [], [], [], []
    for obj in ann["objects"]:
        box = obj["box_3d"]
        qx, qy, qz, qw = box["quaternion_xyzw"]
        if abs(qx) > 1e-6 or abs(qz) > 1e-6:
            raise ValueError("essrf-static-v1 requires upright yaw-only boxes")
        value = [*((np.array(box["center_m"]) - origin) / COORDINATE_SCALE_M),
                 *(np.array(box["extent_m"]) / COORDINATE_SCALE_M), 2 * np.arctan2(qy, qw)]
        if not obj["eligible"]:
            ignored.append(value); continue
        boxes.append(value); classes.append(obj["class_id"] - 8)
        row = []
        for modality, image, valid in (("rgb", rgb, rgb_valid), ("ir", ir, ir_valid)):
            pixels = obj[modality]["visible_pixels"]
            mask = np.load(directory / obj[modality]["mask"]["artifact"]["id"]).astype(bool) if pixels else None
            row += [pixels, _contrast(image, mask, valid, SUPPORT["ring_px"]) if pixels else 0.0]
        row.append(obj["lidar_surface_hits"])
        stats.append(row)
    return {"boxes": torch.tensor(boxes, dtype=torch.float32).reshape(-1, 7),
            "classes": torch.tensor(classes, dtype=torch.long),
            "ignored": torch.tensor(ignored, dtype=torch.float32).reshape(-1, 7),
            # [rgb pixels, rgb contrast, ir pixels, ir contrast, lidar surface hits]
            "support_stats": torch.tensor(stats, dtype=torch.float32).reshape(-1, 5)}


def support_targets(stats: torch.Tensor, criteria: dict = SUPPORT) -> torch.Tensor:
    """Binary per-object, per-modality reliability targets [n, 3] from support stats."""
    if criteria["rgb_min_contrast"] is None or criteria["ir_min_contrast"] is None:
        raise ValueError("Contrast thresholds must be set from the published train distribution")
    pixels = criteria["min_visible_pixels"]
    rgb = (stats[:, 0] >= pixels) & (stats[:, 1] >= criteria["rgb_min_contrast"])
    ir = (stats[:, 2] >= pixels) & (stats[:, 3] >= criteria["ir_min_contrast"])
    lidar = stats[:, 4] >= criteria["lidar_min_hits"]
    return torch.stack((rgb, ir, lidar), 1)

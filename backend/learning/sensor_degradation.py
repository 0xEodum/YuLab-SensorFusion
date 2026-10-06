"""Fixed validation-only corruptions in native sensor coordinates, independent of truth.

Both model profiles preprocess exactly the same changed raw arrays. These six
local synthetic probes are not a claim of real sensor-failure coverage. Evaluation
OOD means the unlabelled exposure family from training, not a held-out corruption.
"""
from __future__ import annotations

import copy
import hashlib
import numpy as np

MODALITIES = ("rgb", "ir", "lidar")
CORRUPTIONS = tuple(f"{m}-{f}" for m in MODALITIES for f in ("known", "ood"))
SCENARIOS = tuple(f"availability-{bits}" for bits in range(8)) + CORRUPTIONS
PROFILE = {"version": "sf12-degradation.v1", "camera_rectangle_fraction": [.25, .25, .75, .75],
           "lidar_azimuth_wedge_rad": [-.2, .2], "lidar_ood_jitter_m": 10.,
           "seed": 1234, "ood": "training exposure family; not held-out corruption",
           "target_policy": "unchanged geometrically eligible objects in every scenario"}


def degrade(obs: dict, arrays: dict, scenario: str, capture_id: str, *, seed: int):
    """No annotations, environment, or IDs enter the model; ID only seeds noise."""
    if scenario not in SCENARIOS:
        raise ValueError("Unknown sensor degradation scenario")
    changed_obs = copy.deepcopy(obs)
    changed = {k: v.copy() for k, v in arrays.items()}
    if scenario.startswith("availability-"):
        bits = int(scenario.rsplit("-", 1)[1])
        for m, name in enumerate(MODALITIES):
            if bits & (1 << m):
                continue
            changed_obs[name]["status"] = "unavailable"
            for sensor in changed_obs["rig"]["sensors"]:
                if sensor["modality"] == name:
                    sensor["available"] = False
            for key in changed:
                if key.startswith(name + "."):
                    changed[key].fill(0)
        return changed_obs, changed
    name, family = scenario.split("-")
    token = hashlib.sha256(f"{seed}:{capture_id}:{scenario}".encode()).digest()
    rng = np.random.default_rng(int.from_bytes(token[:8], "little"))
    if name in ("rgb", "ir"):
        image = changed["rgb.image" if name == "rgb" else "ir.radiance"]
        height, width = image.shape[:2]
        region = (slice(height // 4, 3 * height // 4), slice(width // 4, 3 * width // 4))
        shape = image[region].shape[:2]
        if family == "known":
            noise = rng.random(shape)
        else:
            noise = np.broadcast_to(((np.arange(shape[0]) // 4) % 2)[:, None], shape)
        image[region] = (noise[..., None] * 254 + 1).astype(np.uint8) if name == "rgb" else noise * 200
    else:
        sensor = next(s for s in obs["rig"]["sensors"] if s["modality"] == "lidar")
        # Define wedge in nominal rig coordinates, independent of sensor convention.
        xyz = changed["lidar.xyz"]
        transform = np.asarray(sensor["T_rig_from_sensor"]).reshape(4, 4)
        rig = xyz @ transform[:3, :3].T + transform[:3, 3]
        angle = np.arctan2(rig[:, 0], -rig[:, 2])
        inside = (angle >= -.2) & (angle < .2) & changed["lidar.validity"].astype(bool)
        if family == "known":
            changed["lidar.validity"][inside] = False
            changed["lidar.xyz"][inside] = 0
            changed["lidar.intensity"][inside] = 0
        else:
            xyz[inside] += rng.uniform(-10, 10, (int(inside.sum()), 3)).astype(xyz.dtype)
    return changed_obs, changed

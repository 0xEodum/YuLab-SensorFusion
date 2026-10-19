"""Independent nominal/actual calibration validation at the dataset boundary."""
from __future__ import annotations

import copy
import math

import numpy as np

from .contracts import validate_payload


def actual_rig_at(request: dict, offset_s: float) -> dict:
    if not math.isfinite(offset_s) or request["plan"]["simulation_time_s"] + offset_s < 0:
        raise ValueError("Invalid sample time")
    actual = copy.deepcopy(request["rig"])
    state = request.get("temporal")
    if state is None:
        return actual
    validate_payload("TemporalCapture", state)
    validate_payload("RigSpec", actual)
    for values in [actual["T_world_from_rig"], *(s["T_rig_from_sensor"] for s in actual["sensors"])]:
        m = np.array(values, dtype=np.float64).reshape(4, 4)
        if not np.allclose(m[:3, :3].T @ m[:3, :3], np.eye(3), atol=1e-6, rtol=0) or \
           abs(np.linalg.det(m[:3, :3]) - 1) > 1e-6:
            raise ValueError("Nominal calibration must be rigid and right-handed")
    if len({d["modality"] for d in state["sensor_drift"]}) != len(state["sensor_drift"]):
        raise ValueError("Duplicate sensor drift modality")

    def advance(values, translation, yaw):
        m = np.array(values, dtype=np.float64).reshape(4, 4)
        c, s = math.cos(yaw), math.sin(yaw)
        m[:3, :3] = np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]]) @ m[:3, :3]
        m[:3, 3] += translation
        return m.ravel().tolist()

    actual["T_world_from_rig"] = advance(actual["T_world_from_rig"],
        np.array(state["velocity_world_m_per_s"]) * offset_s, state["yaw_rate_rad_per_s"] * offset_s)
    dt = request["plan"]["simulation_time_s"] + offset_s - state["reference_time_s"]
    for drift in state["sensor_drift"]:
        sensor = next(s for s in actual["sensors"] if s["modality"] == drift["modality"])
        sensor["T_rig_from_sensor"] = advance(sensor["T_rig_from_sensor"],
            np.array(drift["translation_rig_m"]) + np.array(drift["translation_rate_rig_m_per_s"]) * dt,
            drift["yaw_rad"] + drift["yaw_rate_rad_per_s"] * dt)
    validate_payload("RigSpec", actual)
    return actual


def capture_rigs(request: dict, result: dict) -> tuple[dict, dict]:
    """Observations receive only nominal calibration; geometry checks use actual."""
    if "temporal" not in request:
        if "temporal" in result or "actual_rig" in result:
            raise ValueError("Unexpected temporal calibration in static capture")
        return request["rig"], request["rig"]
    if result.get("temporal") != request["temporal"] or "actual_rig" not in result:
        raise ValueError("Missing or mismatched temporal capture provenance")
    expected = actual_rig_at(request, 0)
    actual = result["actual_rig"]
    validate_payload("RigSpec", actual)
    normalized = copy.deepcopy(actual)
    for key in ("T_world_from_rig",):
        if not np.allclose(actual[key], expected[key], atol=1e-9, rtol=0):
            raise ValueError("Capture actual calibration mismatch")
        normalized[key] = expected[key]
    for sensor, target in zip(normalized["sensors"], expected["sensors"], strict=True):
        if not np.allclose(sensor["T_rig_from_sensor"], target["T_rig_from_sensor"], atol=1e-9, rtol=0):
            raise ValueError("Capture actual calibration mismatch")
        sensor["T_rig_from_sensor"] = target["T_rig_from_sensor"]
    if normalized != expected:
        raise ValueError("Capture actual calibration metadata mismatch")
    return request["rig"], actual

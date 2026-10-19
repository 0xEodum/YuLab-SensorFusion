"""Nominal/actual calibration isolation and independent row-major drift oracle."""
import copy
import json
from pathlib import Path

import numpy as np
import pytest

from app.temporal_capture import actual_rig_at, capture_rigs

ROOT = Path(__file__).resolve().parents[2]


def fixture():
    request = json.loads((ROOT / "contracts/fixtures/CaptureRequest.json").read_text())
    request["temporal"] = {"schema_version": "lab.v1", "kind": "TemporalCapture",
        "profile": "rig-motion-drift.v1", "reference_time_s": 0,
        "velocity_world_m_per_s": [0, 0, -2], "yaw_rate_rad_per_s": 0,
        "sensor_drift": [{"modality": "lidar", "translation_rig_m": [1, 0, 0],
            "translation_rate_rig_m_per_s": [.5, 0, 0], "yaw_rad": 0, "yaw_rate_rad_per_s": .1}]}
    return request


def test_actual_calibration_matches_independent_translation_and_rotation_oracle():
    request = fixture()
    nominal = copy.deepcopy(request["rig"])
    actual = actual_rig_at(request, 1)
    tick = request["plan"]["simulation_time_s"]
    assert actual["T_world_from_rig"][11] == nominal["T_world_from_rig"][11] - 2
    a = .1 * (tick + 1)
    rotation = np.array([[np.cos(a), 0, np.sin(a)], [0, 1, 0], [-np.sin(a), 0, np.cos(a)]])
    original = np.array(nominal["sensors"][2]["T_rig_from_sensor"], dtype=np.float64).reshape(4, 4)
    expected = original.copy()
    expected[:3, :3] = rotation @ original[:3, :3]
    expected[0, 3] += 1 + .5 * (tick + 1)
    np.testing.assert_allclose(np.array(actual["sensors"][2]["T_rig_from_sensor"]).reshape(4, 4), expected)
    assert request["rig"] == nominal


def test_packaging_calibration_checks_actual_geometry_but_keeps_nominal_observations():
    request = fixture()
    result = {"actual_rig": actual_rig_at(request, 0), "temporal": request["temporal"]}
    nominal, actual = capture_rigs(request, result)
    assert nominal == request["rig"]
    assert nominal != actual
    bad = copy.deepcopy(result)
    bad["actual_rig"]["sensors"][2]["T_rig_from_sensor"][3] += 1
    with pytest.raises(ValueError, match="actual calibration"):
        capture_rigs(request, bad)
    with pytest.raises(ValueError):
        capture_rigs(request, {})
    with pytest.raises(ValueError):
        capture_rigs({k:v for k,v in request.items() if k != "temporal"}, result)


def test_static_packaging_and_invalid_motion_inputs():
    request = fixture()
    request.pop("temporal")
    assert capture_rigs(request, {}) == (request["rig"], request["rig"])
    assert actual_rig_at(request, 0) == request["rig"]
    request = fixture()
    request["temporal"]["sensor_drift"] *= 2
    with pytest.raises(ValueError):
        actual_rig_at(request, 0)
    request = fixture()
    with pytest.raises(ValueError):
        actual_rig_at(request, float("nan"))


def test_temporal_ir_cannot_silently_render_before_its_saved_thermal_anchor():
    request=fixture()
    request["plan"]["modalities"]=["rgb","ir","lidar"]
    request["plan"]["simulation_time_s"]=1
    request["environment"]["simulation_time_s"]=1
    next(s for s in request["rig"]["sensors"] if s["modality"]=="ir")["timestamp_offset_s"]=-.1
    with pytest.raises(ValueError,match="IR.*nonnegative"):
        actual_rig_at(request,0)

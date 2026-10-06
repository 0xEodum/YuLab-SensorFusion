"""Matched sensor failure/corruption acts on observations before profile preprocessing."""
import copy
import numpy as np
import pytest
torch = pytest.importorskip("torch")
from learning import data, essrf_data


def raw():
    optical = np.diag([1., -1, -1, 1]).ravel().tolist()
    sensor = lambda m: dict(modality=m, available=True, T_rig_from_sensor=optical,
        camera=dict(width_px=640, height_px=384, fx_px=463.5, fy_px=463.5,
                    cx_px=320, cy_px=192, distortion="ideal-pinhole", frame="optical-right-down-forward"))
    obs = dict(rig=dict(T_world_from_rig=np.eye(4).ravel().tolist(),
                       sensors=[sensor(m) for m in ("rgb", "ir", "lidar")]))
    obs.update({m: dict(status="available") for m in ("rgb", "ir", "lidar")})
    arrays = {"rgb.image": np.full((384, 640, 3), 120, np.uint8),
              "rgb.validity_mask": np.ones((384, 640), bool),
              "ir.radiance": np.full((384, 640), 80, np.float32),
              "ir.validity_mask": np.ones((384, 640), bool),
              "ir.saturation_mask": np.zeros((384, 640), bool),
              "lidar.xyz": np.array([[0., 0, 100], [40, 0, 100], [-40, 0, 100]], np.float32),
              "lidar.intensity": np.ones(3, np.float32), "lidar.validity": np.ones(3, bool)}
    return obs, arrays


def test_profile_preprocessors_accept_same_raw_observation_without_truth():
    obs, arrays = raw()
    baseline, _ = data.preprocess_arrays(obs, arrays)
    essrf = essrf_data.preprocess_arrays(obs, arrays)
    assert baseline["rgb"].shape == (3, 96, 160)
    assert essrf["rgb"].shape == (3, 384, 640)
    assert torch.allclose(baseline["ir"].mean(), essrf["ir"].float().mean(), atol=.001)


@pytest.mark.parametrize("scenario", [f"{m}-{family}" for m in ("rgb", "ir", "lidar") for family in ("known", "ood")])
def test_raw_corruptions_are_local_seeded_and_leave_other_sensors_unchanged(scenario):
    from learning.sensor_degradation import degrade
    obs, arrays = raw()
    original = {k: v.copy() for k, v in arrays.items()}
    out_obs, changed = degrade(obs, arrays, scenario, "capture-1", seed=1234)
    again_obs, again = degrade(obs, arrays, scenario, "capture-1", seed=1234)
    assert obs == out_obs == again_obs
    assert all(np.array_equal(arrays[k], original[k]) for k in arrays)
    assert all(np.array_equal(changed[k], again[k]) for k in arrays)
    modality = scenario.split("-")[0]
    assert all(np.array_equal(changed[k], original[k]) for k in arrays if not k.startswith(modality + "."))
    assert any(not np.array_equal(changed[k], original[k]) for k in arrays)
    assert all(np.isfinite(v).all() for v in changed.values())
    data.preprocess_arrays(out_obs, changed)
    essrf_data.preprocess_arrays(out_obs, changed)


def test_every_availability_pattern_and_empty_input_use_same_preprocessors():
    from learning.sensor_degradation import degrade
    obs, arrays = raw()
    for bits in range(8):
        changed_obs, changed = degrade(obs, arrays, f"availability-{bits}", "frame", seed=1234)
        baseline, _ = data.preprocess_arrays(changed_obs, changed)
        essrf = essrf_data.preprocess_arrays(changed_obs, changed)
        assert essrf["available"].tolist() == [bool(bits & (1 << m)) for m in range(3)]
        for m, name in enumerate(("rgb", "ir", "lidar")):
            if not bits & (1 << m):
                assert not baseline[name].any() and not essrf[name].any()
        if not bits:
            assert not baseline["point_valid"].any() and not essrf["point_valid"].any()
    assert obs == raw()[0]


def test_invalid_scenario_rejected_and_clean_is_exact_identity():
    from learning.sensor_degradation import degrade
    obs, arrays = raw()
    changed_obs, changed = degrade(obs, arrays, "availability-7", "frame", seed=1234)
    assert obs == changed_obs
    assert all(np.array_equal(arrays[k], changed[k]) for k in arrays)
    with pytest.raises(ValueError):
        degrade(obs, arrays, "made-up", "frame", seed=1234)


def test_ood_auroc_uses_half_credit_for_ties():
    from learning.essrf_evaluation import auroc
    assert auroc(np.ones(3), np.ones(4)) == .5
    assert auroc(np.array([1, 2]), np.array([0, 1])) == pytest.approx(.875)

"""Comparison runner: common observations, immutable supervision and provenance."""
from types import SimpleNamespace
from pathlib import Path
import numpy as np
import pytest
torch = pytest.importorskip("torch")
from learning import data, essrf_data
from learning.model import Detector
from test_sensor_degradation import raw


def test_availability_cases_preserve_calibration_and_do_not_add_baseline_abstention():
    from learning.sf12_comparison import failure_inputs, score_baseline
    obs, arrays = raw()
    features, _ = data.preprocess_arrays(obs, arrays)
    features = {k: v[None] for k, v in features.items()}
    failed = failure_inputs(features, 0, "baseline-v1")
    assert torch.equal(failed["calibration"], features["calibration"])
    assert features["rgb"].any() and not failed["rgb"].any()
    model = Detector("fusion", width=32).eval()
    with torch.no_grad():
        model.classifier.weight.zero_()
        model.classifier.bias.copy_(torch.tensor([10., 0, 0, -10.]))
    empty = dict(boxes=torch.empty(0, 7), classes=torch.empty(0, dtype=torch.long), ignored=torch.empty(0, 7))
    report = score_baseline(model, failed, [empty], [dict(condition=0)], 1)
    assert report["false_positives"] == 16  # score measured hallucinations, no oracle null gate


def test_essrf_failure_mask_never_reenables_hardware_missing_sensor():
    from learning.sf12_comparison import failure_inputs
    obs, arrays = raw()
    features = {k: v[None] for k, v in essrf_data.preprocess_arrays(obs, arrays).items()}
    features["available"][:, 1] = False
    failed = failure_inputs(features, 7, "essrf-static-v1")
    assert failed["available"].tolist() == [[True, False, True]]
    assert not failure_inputs(features, 0, "essrf-static-v1")["available"].any()


def test_comparison_cache_checks_scenario_seed_capture_order_and_profiles(tmp_path):
    from learning.sf12_comparison import load_case
    args = SimpleNamespace(comparison_root=tmp_path)
    path = tmp_path / "rgb-known.pt"
    value = dict(dataset_sha256="dataset", capture_ids=["frame"], scenario="rgb-known",
        degradation=dict(version="invalid"), preprocessing=dict(baseline=data.PROFILE, essrf=essrf_data.PROFILE),
        baseline={}, essrf={})
    torch.save(value, path)
    with pytest.raises(ValueError, match="provenance"):
        load_case(args, "rgb-known", "dataset", [dict(capture_id="frame")], "cpu")


def test_prepare_uses_validation_observation_only_and_both_fixed_profiles(tmp_path, monkeypatch):
    from learning import sf12_comparison as C
    args = SimpleNamespace(comparison_root=tmp_path, dataset=tmp_path, workers=0)
    rows = [dict(capture_id="frame", split="validation")]
    monkeypatch.setattr(C, "records", lambda args, split: ("dataset", rows) if split == "validation" else pytest.fail("sealed access"))
    calls = []
    def reader(root, request):
        calls.append(request)
        assert request == {"capture_id": "frame"}
        return raw()
    monkeypatch.setattr(C, "load_observation_only", reader)
    C.prepare_suite(args, scenarios=["rgb-known"])
    baseline, essrf = C.load_case(args, "rgb-known", "dataset", rows, "cpu")
    assert len(calls) == 1 and baseline["rgb"].shape == (1, 3, 96, 160)
    assert essrf["rgb"].shape == (1, 3, 384, 640)
    # Area-resize the very same corrupted sRGB array; exact, not two RNG calls.
    expected = torch.nn.functional.interpolate(essrf["rgb"].float() / 255, size=(96, 160), mode="area")
    assert torch.equal(expected, baseline["rgb"])
    C.prepare_suite(args, scenarios=["rgb-known"])
    assert len(calls) == 1  # validated cache resume
    rows[0]["split"] = "test"
    with pytest.raises(ValueError, match="validation"):
        C.prepare_suite(args, scenarios=["ir-known"])


def test_complete_comparison_uses_all_cases_and_frozen_checkpoints(tmp_path, monkeypatch):
    from learning import sf12_comparison as C, essrf_training as T
    from learning.essrf_model import ESSRF
    obs, arrays = raw()
    baseline, _ = data.preprocess_arrays(obs, arrays)
    baseline = {k: v[None] for k, v in baseline.items()}
    essrf = {k: v[None] for k, v in essrf_data.preprocess_arrays(obs, arrays).items()}
    rows = [dict(capture_id="frame", condition=0, split="validation")]
    targets = [dict(boxes=torch.empty(0, 7), classes=torch.empty(0, dtype=torch.long),
                    ignored=torch.empty(0, 7), support=torch.empty(0, 3, dtype=torch.bool))]
    monkeypatch.setattr(C, "records", lambda args, split: ("dataset", rows))
    monkeypatch.setattr(C, "load", lambda args, split, device: (essrf, targets, rows))
    monkeypatch.setattr(C, "load_observation_only", lambda *a: raw())
    cfg = SimpleNamespace(dataset=tmp_path, sf11=tmp_path, comparison_root=tmp_path / "cases", workers=0,
        seeds=[11], device="cpu", batch_size=1, report=tmp_path / "report.json", essrf_run_root=tmp_path / "essrf")
    torch.save(dict(dataset_sha256="dataset", preprocessing=data.PROFILE, features=baseline),
               tmp_path / "validation-observations.pt")
    for modality in ("rgb", "ir", "lidar", "fusion"):
        model = Detector(modality, width=32)
        with torch.no_grad():
            model.classifier.weight.zero_()
            model.classifier.bias.copy_(torch.tensor([10., 0, 0, -10.]))
        folder = tmp_path / "runs" / modality
        folder.mkdir(parents=True)
        torch.save(dict(profile="baseline-v1", preprocessing=data.PROFILE, dataset_sha256="dataset", seed=11,
            modality=modality, model=model.state_dict(), epoch=40, config=dict(queries=16, width=32, epochs=40),
            source_revision="frozen-baseline"), folder / "best.pt")
    model = ESSRF(queries=4, width=16, samples=2, layers=1, global_context=False)
    folder = cfg.essrf_run_root / "seed-11"
    folder.mkdir(parents=True)
    torch.save(dict(profile=ESSRF.profile, preprocessing=essrf_data.PROFILE, support=essrf_data.SUPPORT,
        dataset_sha256="dataset", seed=11, epoch=40, config=model.config, model=model.state_dict(),
        source_revision="frozen-essrf"), folder / "best.pt")
    C.prepare_suite(cfg)
    result = C.compare(cfg)
    assert result["split"] == "validation" and result["capture_ids"] == ["frame"]
    assert len(result["models"]) == 5 and cfg.report.exists()
    for name, values in result["models"].items():
        assert set(values["scenarios"]) == set(C.SCENARIOS)
        assert values["checkpoint_epoch"] == 40 and len(values["checkpoint_sha256"]) == 64
        assert len(values["scenarios"]["availability-7"]["conditions"]) == 10
    assert result["models"]["essrf-seed-11"]["scenarios"]["availability-0"]["detections"] == 0
    assert result["models"]["baseline-fusion-seed-11"]["scenarios"]["availability-0"]["false_positives"] == 16
    assert "reliability" in result["models"]["essrf-seed-11"]
    assert "expert_ungated_map_3d" in result["models"]["essrf-seed-11"]["scenarios"]["availability-1"]
    assert result["device"] == "cpu"
    assert not targets[0]["boxes"].numel()  # no corruption rewrites truth

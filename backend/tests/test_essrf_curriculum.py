"""SF-12 curriculum guarantees, including its effective sampling distribution."""
from types import SimpleNamespace
import importlib.util
from pathlib import Path

import pytest
torch = pytest.importorskip("torch")
from learning import essrf_training as T, essrf_loss as L
from learning.essrf_model import ESSRF


def args(**changes):
    return SimpleNamespace(**dict(dict(schedule="curriculum", clean=False, clean_epochs=8,
        ramp_epochs=16, full_sensor_probability=.7, subset_weight=1.,
        subset_warmup=6, reliability_warmup=4), **changes))


def test_query_defaults_follow_selected_32_and_cli_keeps_16_ablation():
    assert ESSRF().queries == 32
    spec = importlib.util.spec_from_file_location("essrf_cli", Path(__file__).parents[2] / "tools/essrf-pilot.py")
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    assert cli.build_parser().parse_args(["train"]).queries == 32
    assert cli.build_parser().parse_args(["train", "--queries", "16"]).queries == 16
    assert ESSRF(queries=16).queries == 16


def test_curriculum_trains_mixture_from_first_epoch_and_ramps_all_terms():
    plans = [T.training_plan(e, args()) for e in range(40)]
    for plan in plans[:8]:
        assert plan["weights"] == {"mix": 1., "sub": 0., "rel": 0.}
        assert plan["p_full"] == 1 and plan["p_known"] == plan["p_ood"] == 0
    assert plans[8]["weights"]["sub"] == pytest.approx(1 / 16)
    assert plans[8]["p_full"] == pytest.approx(1 - .3 / 16)
    assert plans[23]["weights"] == {"mix": 1., "sub": 1., "rel": 1.}
    assert plans[23]["p_full"] == pytest.approx(.7)
    assert plans[23]["p_known"] == .25 and plans[23]["p_ood"] == .1
    for key in ("p_known", "p_ood"):
        assert all(a[key] <= b[key] for a, b in zip(plans, plans[1:]))
    assert all(p["weights"]["mix"] == 1 for p in plans)
    assert plans[-1] == plans[23]


def test_controls_remain_reproducible_and_zero_ramp_is_explicit():
    assert T.training_plan(0, args(schedule="legacy"))["weights"] == {"mix": 0., "sub": 1., "rel": 0.}
    assert T.training_plan(6, args(schedule="legacy"))["weights"] == {"mix": 0., "sub": 1., "rel": 1.}
    assert not T.training_plan(10, args(schedule="legacy"))["exact_full"]
    assert T.training_plan(39, args(clean=True))["weights"] == {"mix": 1., "sub": 0., "rel": 0.}
    assert T.training_plan(8, args(ramp_epochs=0))["p_full"] == .7


@pytest.mark.parametrize("changes", [dict(clean_epochs=-1), dict(ramp_epochs=-1),
    dict(full_sensor_probability=1.1), dict(subset_weight=-.1)])
def test_invalid_curriculum_fails_before_training(changes):
    with pytest.raises(ValueError):
        T.training_plan(0, args(**changes))


def test_actual_all_sensor_fraction_is_70_percent_and_every_pattern_occurs():
    gen = torch.Generator().manual_seed(11)
    available = L.availability_patterns(100000, gen, "cpu", p_full=.7, exact_full=True)
    assert float(available.all(1).float().mean()) == pytest.approx(.7, abs=.005)
    bits = (available.long() * torch.tensor([1, 2, 4])).sum(1)
    assert set(bits.tolist()) == set(range(8))
    assert L.availability_patterns(50, gen, "cpu", p_full=1, exact_full=True).all()
    assert not L.availability_patterns(50, gen, "cpu", p_full=0, exact_full=True).all(1).any()


def test_curriculum_checkpoint_cannot_select_clean_warm_start():
    assert not T.selection_eligible(0, args())
    assert not T.selection_eligible(22, args())
    assert T.selection_eligible(23, args())
    assert T.selection_eligible(0, args(clean=True))
    assert not T.selection_eligible(9, args(schedule="legacy"))
    assert T.selection_eligible(10, args(schedule="legacy"))


def test_training_loop_records_plan_sampling_budget_and_reloadable_checkpoints(tmp_path, monkeypatch):
    from test_essrf import synthetic_inputs
    features = synthetic_inputs(batch=3)
    targets = [dict(boxes=torch.tensor([[.1, 0, -.3, .02, .02, .02, 0]]),
        classes=torch.tensor([i]), ignored=torch.empty(0, 7), support=torch.ones(1, 3, dtype=torch.bool)) for i in range(3)]
    rows = [dict(condition=i) for i in range(3)]
    monkeypatch.setattr(T, "load", lambda args, split, device: (features, targets, rows))
    (tmp_path / "manifest.json").write_text("{}")
    cfg = args(dataset=tmp_path, run_root=tmp_path, device="cpu", seed=11,
        queries=4, width=16, samples=2, layers=1, local_only=True,
        tiny=False, epochs=3, batch_size=3, lr=5e-4, clean_epochs=1, ramp_epochs=1)
    T.train(cfg)
    import json
    history = json.loads((tmp_path / "seed-11/history.json").read_text())
    assert len(history) == 3
    assert history[0]["sampling_counts"]["patterns"]["7"] == 3
    assert sum(history[0]["sampling_counts"]["corruptions"].values()) == 0
    assert history[0]["training_plan"]["weights"] == {"mix": 1., "sub": 0., "rel": 0.}
    runtime = json.loads((tmp_path / "seed-11/runtime.json").read_text())
    assert runtime["optimizer_updates"] == 3
    from learning.essrf_evaluation import load_checkpoint
    loaded, saved = load_checkpoint(tmp_path / "seed-11/best.pt", "cpu", T.digest(tmp_path / "manifest.json"))
    assert saved["epoch"] >= 2 and saved["config"]["schedule"] == "curriculum"
    assert saved["config"]["clean_epochs"] == 1 and not saved["config"]["global_context"]
    assert saved["config"]["image_sampler"] == "bilinear-v1"
    assert saved["numerics"]["deterministic_algorithms"] is True
    assert saved["source_revision"] == runtime["source_revision"]
    assert loaded.queries == 4 and (tmp_path / "seed-11/last.pt").exists()


def test_too_short_budget_rejected_before_loading_data(monkeypatch):
    monkeypatch.setattr(T, "load", lambda *a: pytest.fail("invalid configuration reached data"))
    with pytest.raises(ValueError, match="budget"):
        T.train(args(tiny=False, epochs=23))

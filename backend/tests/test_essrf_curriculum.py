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


def test_query_defaults_are_16_and_cli_keeps_32_ablation():
    assert ESSRF().queries == 16
    spec = importlib.util.spec_from_file_location("essrf_cli", Path(__file__).parents[2] / "tools/essrf-pilot.py")
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    assert cli.build_parser().parse_args(["train"]).queries == 16
    assert cli.build_parser().parse_args(["train", "--queries", "32"]).queries == 32


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

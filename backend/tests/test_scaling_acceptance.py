import copy

import pytest

from learning.scaling_acceptance import decide_volume, assert_frozen, make_freeze


def summary(clean, macro, sd=.01):
    return {"clean_mean": clean, "macro_mean": macro, "clean_sd": sd, "macro_sd": sd,
            "all_missing_detections": 0, "replicates": 3}


def test_scaling_requires_validation_gain_before_more_data():
    baseline = summary(.8, .75)
    assert decide_volume(baseline, summary(.79, .74), 3000)["expand"] is False
    assert decide_volume(baseline, summary(.82, .77), 3000)["expand"] is True
    assert decide_volume(baseline, summary(.82, .77), 30000)["expand"] is False


def test_scaling_does_not_promote_unstable_or_outage_inventing_candidate():
    baseline = summary(.8, .75)
    bad = summary(.85, .8, sd=.1)
    assert decide_volume(baseline, bad, 3000)["promote"] is False
    bad = summary(.85, .8); bad["all_missing_detections"] = 1
    assert decide_volume(baseline, bad, 3000)["promote"] is False
    bad = summary(.85, .8); bad["replicates"] = 1
    with pytest.raises(ValueError): decide_volume(baseline, bad, 3000)


def test_freeze_rejects_changed_sources_and_checkpoints(tmp_path):
    a = tmp_path / "source.py"; a.write_text("a")
    b = tmp_path / "weights.pt"; b.write_bytes(b"weights")
    frozen = make_freeze([a, b], {"volume": 3000})
    assert_frozen(frozen)
    a.write_text("changed")
    with pytest.raises(ValueError, match="changed"):
        assert_frozen(frozen)

"""Parallel dataset capture keeps dependent requests ordered on one session."""
import threading

import pytest

from app import capture_session
from app.capture_lanes import Unit, UnitScheduler, plan_units


def request(world, sequence, history="equilibrated"):
    return {"world": {"world_id": world}, "plan": {"sequence_id": sequence},
            "environment": {"thermal_history": history}}


def test_sequences_become_independent_ordered_units():
    requests = [request("a", "s1"), request("a", "s2"), request("b", "s3"),
                request("a", "s1"), request("b", "s3")]
    units = plan_units(requests)
    assert sorted(u.indices for u in units) == [(0, 3), (1,), (2, 4)]
    by_index = {u.indices[0]: u for u in units}
    assert by_index[0].world_key == by_index[1].world_key != by_index[2].world_key


def test_continued_thermal_history_keeps_whole_world_on_one_session():
    requests = [request("a", "s1"), request("a", "s2", "continued"), request("a", "s3"),
                request("b", "s4"), request("b", "s5")]
    units = plan_units(requests)
    assert sorted(u.indices for u in units) == [(0, 1, 2), (3,), (4,)]


def test_world_key_uses_complete_snapshot_not_world_id():
    changed = request("a", "s2")
    changed["world"]["seed"] = 1
    units = plan_units([request("a", "s1"), changed])
    assert len({u.world_key for u in units}) == 2


def test_scheduler_prefers_cached_world_then_least_shared_world():
    units = [Unit("a", (0,)), Unit("a", (1,)), Unit("b", (2,)), Unit("a", (3,))]
    scheduler = UnitScheduler(units)
    first = scheduler.take(None)
    second = scheduler.take(None)
    assert {first.world_key, second.world_key} == {"a", "b"}
    assert scheduler.take(second).world_key == "a"  # b is exhausted; a is next best.
    assert scheduler.take(first).world_key == "a"
    assert scheduler.take(None) is None


def test_scheduler_hands_out_every_unit_exactly_once_under_threads():
    units = [Unit(str(i % 3), (i,)) for i in range(60)]
    scheduler = UnitScheduler(units)
    taken, lock = [], threading.Lock()

    def worker():
        unit = None
        while (unit := scheduler.take(unit)) is not None:
            with lock:
                taken.append(unit.indices[0])

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(taken) == list(range(60))


def test_sharing_violation_is_retried_then_surfaced(monkeypatch):
    calls = []

    def flaky(path):
        calls.append(path)
        if len(calls) < 3:
            raise PermissionError(13, "sharing violation")
        return "ok"

    assert capture_session._retry_sharing(flaky, "x") == "ok"
    monkeypatch.setattr(capture_session, "SHARING_RETRY_S", 0.0)

    def denied(_path):
        raise PermissionError(13, "denied")

    with pytest.raises(PermissionError):
        capture_session._retry_sharing(denied, "x")

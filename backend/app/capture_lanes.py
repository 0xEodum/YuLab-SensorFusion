"""Order-preserving work units for parallel dataset capture sessions.

Each request result depends only on its own frozen snapshots, with one exception:
a continued thermal history resolves an earlier capture's published state. Units
therefore keep a sequence together, and keep a whole world together whenever any
of its requests continue thermal history. Requests inside a unit run in request
order on one session; distinct units are independent.
"""
from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass


@dataclass(frozen=True)
class Unit:
    world_key: str
    indices: tuple[int, ...]


def world_key(request: dict) -> str:
    """Complete-snapshot key, matching the worker's geometry-cache identity."""
    canonical = json.dumps(request["world"], sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def plan_units(requests: list[dict]) -> list[Unit]:
    keys = [world_key(request) for request in requests]
    continued = {key for key, request in zip(keys, requests)
                 if request["environment"]["thermal_history"] == "continued"}
    grouped: dict[tuple[str, str], list[int]] = {}
    for index, (key, request) in enumerate(zip(keys, requests)):
        scope = "" if key in continued else request["plan"]["sequence_id"]
        grouped.setdefault((key, scope), []).append(index)
    return [Unit(key, tuple(indices)) for (key, _scope), indices in grouped.items()]


class UnitScheduler:
    """Hands out units, preferring the world a session already has cached."""

    def __init__(self, units: list[Unit]):
        self._pending = list(units)
        self._active: dict[str, int] = {}
        self._lock = threading.Lock()

    def take(self, previous: Unit | None) -> Unit | None:
        with self._lock:
            if previous is not None:
                self._active[previous.world_key] -= 1
            if not self._pending:
                return None
            remaining: dict[str, int] = {}
            for unit in self._pending:
                remaining[unit.world_key] = remaining.get(unit.world_key, 0) + 1
            if previous is not None and previous.world_key in remaining:
                chosen_key = previous.world_key
            else:
                # Start the least-shared world, then the one with most work left.
                chosen_key = min(remaining, key=lambda key: (
                    self._active.get(key, 0), -remaining[key]))
            unit = next(u for u in self._pending if u.world_key == chosen_key)
            self._pending.remove(unit)
            self._active[chosen_key] = self._active.get(chosen_key, 0) + 1
            return unit

"""Matched static-versus-temporal scoring on cached sequence detections.

Observed detections are scored with the unchanged SF-Q evaluator. Prediction-only track outputs never count as
observed detections; their continuation (recall, centre error, recovery latency) is reported separately.
Truth is used only here, never by the tracker input builder.
"""
from __future__ import annotations

import time
from collections import defaultdict

import numpy as np

from .decision_fusion import fuse
from .evaluate import THRESHOLDS, box_iou, evaluate
from .temporal_tracker import FrameInput, SensorGeometry, Tracker, TrackerParams

EMPTY = {"boxes": np.empty((0, 7)), "classes": np.empty(0, dtype=np.int64), "scores": np.empty(0)}
AVAILABILITY = tuple(f"availability-{b}" for b in range(1, 7))
CORRUPTIONS = tuple(f"{m}-{f}" for m in ("rgb", "ir", "lidar") for f in ("known", "ood"))


def group_sequences(frames: list[dict]) -> dict[str, list[dict]]:
    grouped = defaultdict(list)
    for frame in frames:
        grouped[frame["sequence_id"]].append(frame)
    return {k: sorted(v, key=lambda f: f["frame_index"]) for k, v in sorted(grouped.items())}


def frame_input(frame: dict, scenario: str) -> FrameInput:
    """Observation-side view of a cached frame: no truth, no actual (drifted) calibration."""
    chosen, clean = frame["scenarios"][scenario], frame["scenarios"]["clean"]
    points = chosen["lidar_points"]
    if points is None:
        points = clean["lidar_points"] if chosen["available"][2] and clean["lidar_points"] is not None else np.empty((0, 3), np.float32)
    sensors = {name: SensorGeometry(g["T_world_from_sensor"], g.get("camera")) for name, g in frame["sensors"].items()}
    return FrameInput(frame["frame_index"], float(frame["time_s"]), tuple(bool(a) for a in chosen["available"]),
                      tuple(chosen["experts"]), sensors, np.asarray(points, dtype=np.float64))


def static_prediction(frame: dict, scenario: str) -> dict:
    chosen = frame["scenarios"][scenario]
    return fuse(chosen["experts"], chosen["available"])


def target(frame: dict) -> dict:
    eligible = [t for t in frame["truth"] if t["eligible"]]
    return {"boxes": np.array([t["box"] for t in eligible], dtype=np.float64).reshape(-1, 7),
            "classes": np.array([t["class"] for t in eligible], dtype=np.int64)}


def _as_prediction(outputs) -> dict:
    if not outputs:
        return {"boxes": np.empty((0, 7)), "classes": np.empty(0, dtype=np.int64), "scores": np.empty(0)}
    return {"boxes": np.stack([o.box for o in outputs]), "classes": np.array([o.cls for o in outputs], dtype=np.int64),
            "scores": np.array([o.score for o in outputs])}


def run_sequence(params: TrackerParams, frames: list[dict], scenario: str):
    """Fresh tracker per sequence (reset isolation). Returns per-frame outputs and per-step milliseconds."""
    tracker, outputs, latencies = Tracker(params), [], []
    for frame in frames:
        data = frame_input(frame, scenario)
        started = time.perf_counter()
        outputs.append(tracker.step(data))
        latencies.append((time.perf_counter() - started) * 1000)
    return outputs, latencies


def _matches(output_box, output_cls, truth: dict) -> list[tuple[int, float]]:
    """Indices of same-class truth boxes the output hits under the class overlap threshold."""
    hits = []
    for k, (box, cls) in enumerate(zip(truth["boxes"], truth["classes"])):
        if int(cls) == output_cls and box_iou(output_box, box) >= THRESHOLDS[int(cls)]:
            hits.append((k, float(np.linalg.norm(output_box[:3] - box[:3]))))
    return hits


def _runs(flags: list[bool]):
    start = None
    for i, flag in enumerate(flags + [False]):
        if flag and start is None:
            start = i
        elif not flag and start is not None:
            yield start, i
            start = None


def evaluate_scenario(params: TrackerParams, sequences: dict[str, list[dict]], scenario: str) -> dict:
    static, observed, everything, targets = [], [], [], []
    latencies, invented = [], 0
    outage = {"frames": 0, "positives": 0, "static_hits": 0, "tracker_hits": 0, "tracker_errors": []}
    partial = {"frames": 0, "positives": 0, "static_hits": 0, "tracker_hits": 0}
    recovery = {"static": [], "tracker": []}
    for frames in sequences.values():
        outputs, steps = run_sequence(params, frames, scenario)
        latencies += steps
        all_missing = [not any(f["scenarios"][scenario]["available"]) for f in frames]
        tracker_hit_by_frame, static_hit_by_frame, seen_ids = [], [], set()
        for k, (frame, out, missing) in enumerate(zip(frames, outputs, all_missing)):
            truth = target(frame); targets.append(truth)
            fused = static_prediction(frame, scenario); static.append(fused)
            observed.append(_as_prediction([o for o in out if o.observed])); everything.append(_as_prediction(out))
            if missing:
                invented += sum(o.observed for o in out) + sum(o.track_id not in seen_ids for o in out)
            seen_ids |= {o.track_id for o in out}
            t_hits, s_hits, errors = set(), set(), []
            for o in out:
                for index, error in _matches(o.box, o.cls, truth):
                    if index not in t_hits:
                        t_hits.add(index); errors.append(error)
            for box, cls in zip(fused["boxes"], fused["classes"]):
                s_hits |= {i for i, _ in _matches(box, int(cls), truth)}
            tracker_hit_by_frame.append(t_hits); static_hit_by_frame.append(s_hits)
            bucket = outage if missing else partial
            bucket["frames"] += 1; bucket["positives"] += len(truth["classes"])
            bucket["static_hits"] += len(s_hits); bucket["tracker_hits"] += len(t_hits)
            if missing:
                outage["tracker_errors"] += errors
        observed_hits = []
        for out, truth in zip(outputs, (target(f) for f in frames)):
            observed_hits.append({i for o in out if o.observed for i, _ in _matches(o.box, o.cls, truth)})
        for start, stop in _runs(all_missing):
            if stop >= len(frames):
                continue
            wanted = set(range(len(target(frames[stop - 1])["classes"])))
            for name, hits in (("tracker", observed_hits), ("static", static_hit_by_frame)):
                for index in wanted:
                    later = [n for n in range(stop, len(frames)) if index in hits[n]]
                    recovery[name].append(later[0] - stop + 1 if later else None)
    def summary(values):
        found = [v for v in values if v is not None]
        return {"events": len(values), "recovered": len(found), "mean_frames": float(np.mean(found)) if found else None}
    def rate(bucket, key):
        return bucket[key] / bucket["positives"] if bucket["positives"] else None
    errors = outage.pop("tracker_errors")
    return {"static": evaluate(static, targets), "tracker_observed": evaluate(observed, targets),
            "tracker_with_prediction_only": evaluate(everything, targets),
            "outage_frames": {"frames": outage["frames"], "positives": outage["positives"],
                              "static_recall": rate(outage, "static_hits"), "tracker_continued_recall": rate(outage, "tracker_hits"),
                              "tracker_centre_error_m": float(np.mean(errors)) if errors else None},
            "available_frames": {"frames": partial["frames"], "positives": partial["positives"],
                                 "static_recall": rate(partial, "static_hits"), "tracker_recall": rate(partial, "tracker_hits")},
            "recovery_latency": {"static": summary(recovery["static"]), "tracker": summary(recovery["tracker"])},
            "invented_observations": invented, "step_ms": latencies}


def macro(results: dict, key: str) -> dict:
    """Equal-weight macro over the six availability subsets and six raw corruption probes, as in SF-Q."""
    values = {name: [results[s][name]["map_3d"] for s in AVAILABILITY + CORRUPTIONS if s in results] for name in (key,)}
    return float(np.mean(values[key])) if values[key] and None not in values[key] else None


def evaluate_all(params: TrackerParams, sequences: dict, scenarios: tuple) -> dict:
    return {scenario: evaluate_scenario(params, sequences, scenario) for scenario in scenarios}

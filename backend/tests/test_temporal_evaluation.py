"""Static-versus-temporal scoring on synthetic cached sequences."""
import copy

import numpy as np
import pytest

pytest.importorskip("scipy")

from learning.temporal_evaluation import evaluate_scenario, frame_input, group_sequences, run_sequence
from learning.temporal_tracker import TrackerParams

CAMERA = {"fx_px": 463.5, "fy_px": 463.5, "cx_px": 320.0, "cy_px": 192.0, "width_px": 640, "height_px": 384}
SENSORS = {"rgb": {"T_world_from_sensor": np.eye(4), "camera": CAMERA}, "ir": {"T_world_from_sensor": np.eye(4), "camera": CAMERA},
           "lidar": {"T_world_from_sensor": np.eye(4)}}
OUTAGE = range(8, 14)


def truth_box(index):
    return np.array([2.0 + 0.2 * index, 0.0, 30.0, 8.0, 4.0, 14.0, 0.0])


def expert(index, present):
    if not present:
        return {"boxes": np.empty((0, 7)), "classes": np.empty(0, dtype=np.int64), "scores": np.empty(0)}
    return {"boxes": truth_box(index)[None], "classes": np.array([0]), "scores": np.array([0.9])}


def cached_frame(sequence, index, outage=False):
    present = not outage
    clean = {"available": [present] * 3, "experts": [expert(index, present)] * 3,
             "lidar_points": np.array([[2.0 + 0.2 * index, 0.0, 30.0]], dtype=np.float32) if present else None}
    return {"sequence_id": sequence, "frame_index": index, "time_s": index * 0.2, "sensors": SENSORS, "split": "train",
            "truth": [{"instance_id": "a", "class": 0, "eligible": True, "box": truth_box(index)}],
            "scenarios": {"clean": clean}}


def sequences(names=("s0",)):
    return group_sequences([cached_frame(n, i, i in OUTAGE) for n in names for i in range(20)])


def test_outage_is_continued_without_invented_observations_and_static_has_nothing():
    result = evaluate_scenario(TrackerParams(confirm_hits=1), sequences(), "clean")
    outage = result["outage_frames"]
    assert outage["frames"] == 6 and outage["static_recall"] == 0.0
    assert outage["tracker_continued_recall"] == 1.0
    assert result["invented_observations"] == 0
    assert result["recovery_latency"]["tracker"]["recovered"] == 1
    assert result["recovery_latency"]["tracker"]["mean_frames"] == 1.0


def test_prediction_only_outputs_are_excluded_from_observed_detection_scores():
    result = evaluate_scenario(TrackerParams(confirm_hits=1), sequences(), "clean")
    # 14 observed frames contain one correct detection each; outage predictions add recall only to the 'with prediction' view.
    assert result["tracker_observed"]["classes"]["aircraft"]["positives"] == 20
    assert result["tracker_observed"]["classes"]["aircraft"]["recall"] == 14 / 20
    assert result["tracker_with_prediction_only"]["classes"]["aircraft"]["recall"] == 1.0


def test_tracker_input_and_outputs_do_not_depend_on_truth():
    frames = sequences()["s0"]
    altered = copy.deepcopy(frames)
    for frame in altered:
        frame["truth"] = [{"instance_id": "x", "class": 2, "eligible": True, "box": np.array([500.0, 9, 9, 1, 1, 1, 1.0])}]
    first, _ = run_sequence(TrackerParams(), frames, "clean")
    second, _ = run_sequence(TrackerParams(), altered, "clean")
    for a, b in zip(first, second):
        assert [(o.track_id, o.observed) for o in a] == [(o.track_id, o.observed) for o in b]
        assert all(np.array_equal(x.box, y.box) for x, y in zip(a, b))
    assert not hasattr(frame_input(frames[0], "clean"), "truth")


def test_sequences_are_tracked_independently_with_no_state_bleed():
    both = evaluate_scenario(TrackerParams(), sequences(("s0", "s1")), "clean")
    single = evaluate_scenario(TrackerParams(), sequences(("s0",)), "clean")
    assert both["tracker_observed"]["classes"]["aircraft"]["recall"] == single["tracker_observed"]["classes"]["aircraft"]["recall"]
    assert both["invented_observations"] == 0

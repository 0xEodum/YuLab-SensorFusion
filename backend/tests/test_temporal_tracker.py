"""Temporal tracker contracts: motion prior, gated information update, outages, lifecycle, reset."""
import numpy as np
import pytest

from learning.temporal_tracker import (FrameInput, SensorGeometry, Tracker, TrackerParams, information_update)

DT = 0.2
CAMERA = {"fx_px": 463.5, "fy_px": 463.5, "cx_px": 320.0, "cy_px": 192.0, "width_px": 640, "height_px": 384}
SENSORS = {"rgb": SensorGeometry(np.eye(4), CAMERA), "ir": SensorGeometry(np.eye(4), CAMERA), "lidar": SensorGeometry(np.eye(4), None)}


def box(x, z, cls=0, y=0.0, size=(8.0, 4.0, 14.0), yaw=0.0):
    return np.array([x, y, z, *size, yaw])


def dets(*items):
    """items: (box, class, score) -> detection dict in the cache layout."""
    if not items:
        return {"boxes": np.empty((0, 7)), "classes": np.empty(0, dtype=np.int64), "scores": np.empty(0)}
    return {"boxes": np.stack([i[0] for i in items]), "classes": np.array([i[1] for i in items], dtype=np.int64),
            "scores": np.array([i[2] for i in items], dtype=float)}


def frame(index, per_sensor=None, available=(True, True, True), points=None):
    per_sensor = per_sensor or [dets(), dets(), dets()]
    if points is None:
        points = np.array([[2.0 + 0.1 * k, 0.0, 30.0] for k in range(5)])
    return FrameInput(frame_index=index, time_s=index * DT, available=tuple(available), detections=tuple(per_sensor),
                      sensors=SENSORS, lidar_points=points)


def moving_object(index, speed=1.0, x0=2.0, z=30.0):
    return box(x0 + speed * index * DT, z)


def seen(index, score=0.9, speed=1.0):
    detection = dets((moving_object(index, speed), 0, score))
    return frame(index, [detection, detection, detection],
                 points=np.array([[2.0 + speed * index * DT + 0.1 * k, 0.0, 30.0] for k in range(5)]))


def warm(tracker, frames=6, speed=1.0):
    outputs = []
    for i in range(frames):
        outputs = tracker.step(seen(i, speed=speed))
    return outputs


# --- information update -------------------------------------------------------------------------

def test_zero_observation_mass_returns_prior_bit_exactly():
    x = np.array([1.0, 2.0, 0.3, -0.1]); P = np.diag([1.0, 2.0, 0.5, 0.5])
    H = np.hstack((np.eye(2), np.zeros((2, 2)))); R = np.eye(2)
    new_x, new_P = information_update(x, P, H, np.array([9.0, 9.0]), R, 0.0)
    assert np.array_equal(new_x, x) and np.array_equal(new_P, P)


def test_positive_observation_mass_shrinks_covariance_monotonically_and_unit_mass_matches_kalman():
    x = np.zeros(4); P = np.diag([4.0, 4.0, 1.0, 1.0])
    H = np.hstack((np.eye(2), np.zeros((2, 2)))); R = 0.5 * np.eye(2); z = np.array([1.0, -1.0])
    traces = [np.trace(information_update(x, P, H, z, R, k)[1]) for k in (0.0, 0.25, 0.5, 1.0)]
    assert all(a > b for a, b in zip(traces, traces[1:]))
    gain = P @ H.T @ np.linalg.inv(H @ P @ H.T + R)
    kalman_x, kalman_P = x + gain @ (z - H @ x), (np.eye(4) - gain @ H) @ P
    full_x, full_P = information_update(x, P, H, z, R, 1.0)
    np.testing.assert_allclose(full_x, kalman_x, atol=1e-12); np.testing.assert_allclose(full_P, kalman_P, atol=1e-12)


# --- outages -------------------------------------------------------------------------------------

def test_full_outage_follows_motion_prior_without_correction_or_shrinking_uncertainty():
    tracker = Tracker(TrackerParams()); warm(tracker, 6)
    before = tracker.snapshot()[0]
    previous_trace = np.trace(before["P"]); expected = before["state"].copy()
    for k in range(1, 6):
        # Corrupted bundle: detections present but every sensor flagged absent must be ignored entirely.
        junk = dets((box(100.0, 5.0), 0, 0.99))
        outputs = tracker.step(frame(5 + k, [junk, junk, junk], available=(False, False, False)))
        track = tracker.snapshot()[0]
        expected = expected + np.array([expected[2] * DT, expected[3] * DT, 0, 0])
        np.testing.assert_allclose(track["state"], expected, atol=1e-9)
        assert np.trace(track["P"]) > previous_trace
        previous_trace = np.trace(track["P"])
        assert len(outputs) == 1 and not outputs[0].observed
        assert len(tracker.snapshot()) == 1  # nothing invented from the ignored detections


def test_outage_state_equals_pure_prediction_bit_exactly_regardless_of_detection_content():
    a, b = Tracker(TrackerParams()), Tracker(TrackerParams())
    warm(a, 6); warm(b, 6)
    a.step(frame(6, [dets(), dets(), dets()], available=(False,) * 3))
    junk = dets((box(7.0, 33.0), 0, 0.99))
    b.step(frame(6, [junk, junk, junk], available=(False,) * 3, points=np.array([[7.0, 0, 33.0]])))
    assert np.array_equal(a.snapshot()[0]["state"], b.snapshot()[0]["state"])
    assert np.array_equal(a.snapshot()[0]["P"], b.snapshot()[0]["P"])


def test_full_outage_never_births_tracks():
    tracker = Tracker(TrackerParams())
    junk = dets((box(7.0, 33.0), 0, 0.99))
    for i in range(5):
        assert tracker.step(frame(i, [junk, junk, junk], available=(False,) * 3)) == []
    assert tracker.snapshot() == []


@pytest.mark.parametrize("lost", [0, 1, 2])
def test_single_sensor_loss_and_recovery_keep_the_track_observed(lost):
    tracker = Tracker(TrackerParams()); warm(tracker, 5)
    available = [True, True, True]; available[lost] = False
    for i in range(5, 9):
        outputs = tracker.step(frame(i, [seen(i).detections[s] for s in range(3)], available=tuple(available),
                                     points=seen(i).lidar_points))
        assert len(outputs) == 1 and outputs[0].observed
    outputs = tracker.step(seen(9))
    assert len(outputs) == 1 and outputs[0].observed and outputs[0].track_id == 1


def test_track_survives_a_brief_outage_then_is_observed_again_with_the_same_identity():
    tracker = Tracker(TrackerParams()); first = warm(tracker, 6)[0].track_id
    for i in range(6, 12):
        tracker.step(frame(i, available=(False,) * 3))
    outputs = tracker.step(seen(12))
    assert [o.track_id for o in outputs] == [first] and outputs[0].observed
    assert abs(outputs[0].box[0] - moving_object(12)[0]) < 1.0


def test_prediction_only_track_expires_after_the_configured_number_of_missed_frames():
    params = TrackerParams(max_missed_frames=3)
    tracker = Tracker(params); warm(tracker, 6)
    alive = [len(tracker.step(frame(6 + k, available=(False,) * 3))) for k in range(6)]
    assert alive == [1, 1, 1, 0, 0, 0]
    assert tracker.snapshot() == []


def test_track_expires_when_position_uncertainty_exceeds_the_limit():
    params = TrackerParams(max_missed_frames=1000, max_position_sigma_m=2.0, accel_sigma_m_per_s2=2.0)
    tracker = Tracker(params); warm(tracker, 6)
    counts = [len(tracker.step(frame(6 + k, available=(False,) * 3))) for k in range(30)]
    assert counts[0] == 1 and counts[-1] == 0


# --- lifecycle -----------------------------------------------------------------------------------

def test_low_score_detection_does_not_birth_and_confirmation_requires_repeated_hits():
    tracker = Tracker(TrackerParams(birth_min_score=0.3, confirm_hits=2))
    weak = dets((box(2.0, 30.0), 0, 0.1))
    assert tracker.step(frame(0, [weak, weak, weak])) == [] and tracker.snapshot() == []
    strong = dets((box(2.0, 30.0), 0, 0.9))
    assert tracker.step(frame(1, [strong, strong, strong])) == []     # tentative, not yet emitted
    assert len(tracker.snapshot()) == 1
    assert len(tracker.step(frame(2, [strong, strong, strong]))) == 1  # confirmed on the second frame


def test_tentative_track_without_repeat_is_discarded():
    tracker = Tracker(TrackerParams(confirm_hits=2))
    strong = dets((box(2.0, 30.0), 0, 0.9))
    tracker.step(frame(0, [strong, dets(), dets()]))
    for i in range(1, 4):
        tracker.step(frame(i))
    assert tracker.snapshot() == []


def test_class_mismatch_does_not_associate_and_births_a_separate_track():
    tracker = Tracker(TrackerParams(confirm_hits=1)); warm(tracker, 3)
    other = dets((moving_object(3), 1, 0.9))
    tracker.step(frame(3, [other, other, other]))
    assert sorted({t["class"] for t in tracker.snapshot()}) == [0, 1]


def test_measurements_beyond_the_gate_birth_instead_of_dragging_the_track():
    tracker = Tracker(TrackerParams(confirm_hits=1)); warm(tracker, 4)
    before = tracker.snapshot()[0]["state"][:2].copy()
    far = dets((box(60.0, 30.0), 0, 0.9))
    tracker.step(frame(4, [far, far, far], points=np.array([[60.0, 0, 30.0]])))
    tracks = tracker.snapshot()
    assert len(tracks) == 2
    assert np.linalg.norm(tracks[0]["state"][:2] - (before + np.array([1.0 * DT, 0.0]))) < 0.5


def test_estimated_velocity_converges_to_object_velocity():
    tracker = Tracker(TrackerParams()); warm(tracker, 20, speed=2.0)
    assert tracker.snapshot()[0]["state"][2] == pytest.approx(2.0, abs=0.3)


# --- gating and calibration ---------------------------------------------------------------------

def test_camera_only_measurement_for_a_reference_outside_the_image_is_not_applied():
    tracker = Tracker(TrackerParams(confirm_hits=1, birth_min_score=0.3))
    far_left = dets((box(-40.0, 40.0), 0, 0.9))
    points = np.array([[-40.0, 0, 40.0]])
    tracker.step(frame(0, [far_left, far_left, far_left], points=points))     # birth from LiDAR/camera
    tracker.step(frame(1, [dets(), dets(), dets()], points=points))
    state_before = tracker.snapshot()[0]["state"].copy(); cov_before = tracker.snapshot()[0]["P"].copy()
    shifted = dets((box(-39.0, 40.0), 0, 0.9))
    # LiDAR absent; both cameras report a shifted box, but the reference projects far outside the image.
    tracker.step(frame(2, [shifted, shifted, dets()], available=(True, True, False), points=np.empty((0, 3))))
    predicted = state_before.copy(); predicted[:2] += predicted[2:] * DT
    np.testing.assert_allclose(tracker.snapshot()[0]["state"], predicted, atol=1e-9)
    assert np.trace(tracker.snapshot()[0]["P"]) > np.trace(cov_before)


def test_larger_calibration_uncertainty_reduces_the_pull_of_a_camera_measurement():
    def final_x(rotation_sigma):
        params = TrackerParams(confirm_hits=1, calibration_rotation_sigma_rad=rotation_sigma, gate_chi2=1e6)
        tracker = Tracker(params)
        for i in range(4):
            tracker.step(frame(i, [dets(), seen(i).detections[1], dets()], available=(False, True, False)))
        shifted = dets((box(moving_object(4)[0] + 1.5, 30.0), 0, 0.9))
        tracker.step(frame(4, [dets(), shifted, dets()], available=(False, True, False)))
        return tracker.snapshot()[0]["state"][0] - moving_object(4)[0]
    assert final_x(0.05) < final_x(0.0005)


# --- sequence semantics -------------------------------------------------------------------------

def test_reset_clears_all_state_so_a_new_sequence_matches_a_fresh_tracker():
    reused, fresh = Tracker(TrackerParams()), Tracker(TrackerParams())
    warm(reused, 8, speed=2.0)
    reused.reset()
    assert reused.snapshot() == []
    for i in range(6):
        a = reused.step(seen(i)); b = fresh.step(seen(i))
        assert [(o.track_id, o.observed) for o in a] == [(o.track_id, o.observed) for o in b]
        for x, y in zip(a, b):
            assert np.array_equal(x.box, y.box) and x.score == y.score


def test_non_increasing_time_is_an_explicit_error():
    tracker = Tracker(TrackerParams()); tracker.step(seen(3))
    with pytest.raises(ValueError, match="time"):
        tracker.step(seen(3))
    with pytest.raises(ValueError, match="time"):
        tracker.step(seen(2))


def test_gap_beyond_the_declared_limit_expires_every_track_before_processing():
    tracker = Tracker(TrackerParams(max_gap_s=1.0)); warm(tracker, 6)
    outputs = tracker.step(frame(6 + 20, available=(False,) * 3))   # 4 s later
    assert outputs == [] and tracker.snapshot() == []
    assert tracker.last_reset_reason == "time-gap"


def test_outputs_are_finite_and_prediction_only_scores_decay():
    tracker = Tracker(TrackerParams()); warm(tracker, 6)
    scores = []
    for i in range(6, 10):
        out = tracker.step(frame(i, available=(False,) * 3))[0]
        assert np.isfinite(out.box).all() and np.isfinite(out.position_covariance).all()
        scores.append(out.score)
    assert all(a > b for a, b in zip(scores, scores[1:]))

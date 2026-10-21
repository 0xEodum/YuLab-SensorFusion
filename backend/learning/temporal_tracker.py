"""Observation-only temporal tracker over per-sensor detections (SF-14 `ensemble-kalman-tracker.v1`).

World-frame constant-velocity tracks (x, z, vx, vz) with scalar random-walk attributes (y, w, h, l, yaw),
updated in information form with an observation mass kappa in [0, 1]:

    P+ = (P-^-1 + kappa H^T R^-1 H)^-1,   x+ = x- + P+ kappa H^T R^-1 (z - H x-)

kappa = 0 returns the prior bit-exactly through a separate path, so measurement processing can neither
move the state nor shrink the covariance. Without any available sensor no measurement code runs:
tracks follow the motion prior, covariance grows, nothing is born. Camera support requires the
predicted reference to reach the image (projected state + declared calibration covariance); LiDAR
support requires observed points near the reference. Measurement noise is inflated by the declared
extrinsic prior through the analytic pose Jacobian. Truth, drift and weather never enter.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Optional

import numpy as np
from scipy.optimize import linear_sum_assignment

from .temporal_geometry import camera_observable, lidar_support, world_calibration_covariance

SENSORS = ("rgb", "ir", "lidar")
UPDATE_ORDER = (2, 1, 0)   # LiDAR, IR, RGB: strongest positional evidence first (SF-Q ordering)
ATTRIBUTES = (1, 3, 4, 5, 6)   # y, w, h, l, yaw within a [x, y, z, w, h, l, yaw] box
YAW = 4                        # index inside ATTRIBUTES
INFEASIBLE = 1e9
H_POSITION = np.hstack((np.eye(2), np.zeros((2, 2))))


@dataclass(frozen=True)
class TrackerParams:
    accel_sigma_m_per_s2: float = 0.5
    attribute_drift_sigma: float = 0.1            # per sqrt(s), metres (yaw: radians)
    sensor_sigma_m: tuple = (2.0, 2.0, 2.0)       # rgb, ir, lidar world-position measurement std
    attribute_sigma_m: float = 1.5
    yaw_sigma_rad: float = 0.5
    initial_velocity_sigma_m_per_s: float = 3.0
    calibration_rotation_sigma_rad: float = 0.01  # declared nominal tolerance, not the simulated drift
    calibration_translation_sigma_m: float = 0.2
    pixel_sigma_px: float = 2.0
    observability_margin_sigma: float = 3.0
    lidar_radius_m: float = 6.0
    lidar_neighbours: int = 8
    lidar_min_points: int = 1
    gate_chi2: float = 9.21
    birth_min_score: float = 0.3
    confirm_hits: int = 2
    confirm_window: int = 3
    max_missed_frames: int = 12
    max_position_sigma_m: float = 25.0
    max_gap_s: float = 1.0
    score_smoothing: float = 0.5
    kappa_exponent: float = 1.0
    prediction_score_decay: float = 0.85


@dataclass(frozen=True)
class SensorGeometry:
    T_world_from_sensor: np.ndarray
    camera: Optional[dict]


@dataclass(frozen=True)
class FrameInput:
    frame_index: int
    time_s: float
    available: tuple
    detections: tuple     # rgb, ir, lidar: {"boxes": (N, 7) world metres, "classes": (N,), "scores": (N,)}
    sensors: dict         # SENSORS name -> SensorGeometry (nominal)
    lidar_points: np.ndarray


@dataclass(frozen=True)
class TrackOutput:
    track_id: int
    box: np.ndarray
    cls: int
    score: float
    observed: bool        # supported by a measurement in this frame; False = prediction-only
    position_covariance: np.ndarray


@dataclass(frozen=True)
class Track:
    track_id: int
    state: np.ndarray
    P: np.ndarray
    attributes: np.ndarray
    attribute_variance: np.ndarray
    class_mass: np.ndarray
    score: float
    history: tuple = ()
    missed: int = 0
    confirmed: bool = False
    matched: bool = False


def information_update(x, P, H, z, R, kappa):
    """Gated information-form measurement update; kappa = 0 is a separate exact-prior path."""
    if kappa == 0:
        return x.copy(), P.copy()
    R_inv = np.linalg.inv(R)
    posterior = np.linalg.inv(np.linalg.inv(P) + kappa * H.T @ R_inv @ H)
    posterior = 0.5 * (posterior + posterior.T)
    return x + posterior @ (kappa * H.T @ R_inv @ (z - H @ x)), posterior


def _scalar_update(value, variance, measurement, noise, kappa, periodic=False):
    if kappa == 0:
        return value, variance
    residual = measurement - value
    if periodic:
        residual = (residual + np.pi / 2) % np.pi - np.pi / 2
    posterior = 1.0 / (1.0 / variance + kappa / noise)
    return value + posterior * kappa * residual / noise, posterior


def _position_sigma(P):
    return float(np.sqrt(np.linalg.eigvalsh(P[:2, :2]).max()))


class Tracker:
    def __init__(self, params: TrackerParams):
        self.params = params
        self.reset()

    def reset(self):
        self._tracks: list[Track] = []
        self._last_time: Optional[float] = None
        self._next_id = 1
        self.last_reset_reason = "reset"

    def snapshot(self):
        return [{"track_id": t.track_id, "state": t.state.copy(), "P": t.P.copy(), "class": int(np.argmax(t.class_mass)),
                 "confirmed": t.confirmed, "missed": t.missed, "score": t.score} for t in self._tracks]

    # -- frame processing -----------------------------------------------------------------------

    def step(self, frame: FrameInput) -> list[TrackOutput]:
        if self._last_time is not None:
            if frame.time_s <= self._last_time:
                raise ValueError("Frame time must increase strictly")
            if frame.time_s - self._last_time > self.params.max_gap_s:
                self._tracks = []
                self.last_reset_reason = "time-gap"
        dt = 0.0 if self._last_time is None else frame.time_s - self._last_time
        self._last_time = frame.time_s
        tracks = [replace(self._predict(t, dt), matched=False) for t in self._tracks]
        evidence: dict[int, list[float]] = {}
        # Without delivered observations no measurement code runs: prior only, no births.
        if any(frame.available):
            tracks = self._measure(tracks, frame, evidence)
        tracks = [self._lifecycle(t, evidence.get(t.track_id, []), sum(map(bool, frame.available))) for t in tracks]
        self._tracks = [t for t in tracks if t is not None]
        return [self._output(t) for t in self._tracks if t.confirmed]

    def _predict(self, track: Track, dt: float) -> Track:
        if dt == 0:
            return track
        F = np.eye(4); F[0, 2] = F[1, 3] = dt
        q2 = self.params.accel_sigma_m_per_s2 ** 2
        Q = q2 * np.block([[dt ** 4 / 4 * np.eye(2), dt ** 3 / 2 * np.eye(2)], [dt ** 3 / 2 * np.eye(2), dt ** 2 * np.eye(2)]])
        drift = self.params.attribute_drift_sigma ** 2 * dt
        return replace(track, state=F @ track.state, P=F @ track.P @ F.T + Q, attribute_variance=track.attribute_variance + drift)

    # -- measurement ----------------------------------------------------------------------------

    def _calibration(self):
        p = self.params
        return np.diag([p.calibration_rotation_sigma_rad ** 2] * 3 + [p.calibration_translation_sigma_m ** 2] * 3)

    def _support_and_noise(self, track: Track, m: int, frame: FrameInput):
        """Whether track's predicted reference can be supported by sensor m, and its measurement covariance."""
        p = self.params
        geometry = frame.sensors[SENSORS[m]]
        pose = geometry.T_world_from_sensor
        reference = np.array([track.state[0], track.attributes[0], track.state[1]])
        offset_sensor = pose[:3, :3].T @ (reference - pose[:3, 3])
        calibration_world = pose[:3, :3] @ world_calibration_covariance(offset_sensor, self._calibration()) @ pose[:3, :3].T
        noise = p.sensor_sigma_m[m] ** 2 * np.eye(2) + calibration_world[np.ix_([0, 2], [0, 2])]
        if m == 2:
            radius = p.lidar_radius_m + 3 * _position_sigma(track.P)
            support = lidar_support(frame.lidar_points, reference, radius, p.lidar_neighbours, p.lidar_min_points).valid
        else:
            state_world = np.zeros((3, 3))
            state_world[np.ix_([0, 2], [0, 2])] = track.P[:2, :2]
            state_world[1, 1] = track.attribute_variance[0]
            state_camera = pose[:3, :3].T @ state_world @ pose[:3, :3]
            support = camera_observable(geometry.camera, offset_sensor, state_camera, self._calibration(), p.pixel_sigma_px,
                                        p.observability_margin_sigma)
        return support, noise

    def _measure(self, tracks: list[Track], frame: FrameInput, evidence: dict) -> list[Track]:
        p = self.params
        for m in UPDATE_ORDER:
            if not frame.available[m]:
                continue
            detections = frame.detections[m]
            count = len(detections["scores"])
            if count == 0:
                continue
            info = [self._support_and_noise(t, m, frame) for t in tracks]
            cost = np.full((len(tracks), count), INFEASIBLE)
            raw_chi2 = np.full((len(tracks), count), np.inf)
            for i, (track, (support, noise)) in enumerate(zip(tracks, info)):
                S_inv = np.linalg.inv(track.P[:2, :2] + noise)
                cls = int(np.argmax(track.class_mass))
                for j in range(count):
                    residual = detections["boxes"][j][[0, 2]] - track.state[:2]
                    raw_chi2[i, j] = residual @ S_inv @ residual
                    if support and raw_chi2[i, j] <= p.gate_chi2 and int(detections["classes"][j]) == cls:
                        cost[i, j] = raw_chi2[i, j]
            matched_detections = set()
            if len(tracks):
                for i, j in zip(*linear_sum_assignment(cost)):
                    if cost[i, j] >= INFEASIBLE:
                        continue
                    matched_detections.add(j)
                    tracks[i] = self._update(tracks[i], detections, int(j), info[i][1], evidence)
            for j in range(count):
                if j in matched_detections or detections["scores"][j] < p.birth_min_score:
                    continue
                # A detection explained by an existing track the sensor cannot support is not a new object.
                shadowed = any(not info[i][0] and raw_chi2[i, j] <= p.gate_chi2 and
                               int(detections["classes"][j]) == int(np.argmax(tracks[i].class_mass)) for i in range(len(info)))
                if not shadowed:
                    tracks.append(self._birth(detections, j, m, frame, evidence))
        return tracks

    def _update(self, track: Track, detections: dict, j: int, noise: np.ndarray, evidence: dict) -> Track:
        p = self.params
        score = float(detections["scores"][j])
        kappa = min(max(score, 0.0), 1.0) ** p.kappa_exponent
        if kappa == 0:
            return track
        box = detections["boxes"][j]
        state, P = information_update(track.state, track.P, H_POSITION, box[[0, 2]], noise, kappa)
        attributes, variance = track.attributes.copy(), track.attribute_variance.copy()
        for k, index in enumerate(ATTRIBUTES):
            sigma = p.yaw_sigma_rad if k == YAW else p.attribute_sigma_m
            attributes[k], variance[k] = _scalar_update(attributes[k], variance[k], box[index], sigma ** 2, kappa, periodic=k == YAW)
        mass = track.class_mass.copy(); mass[int(detections["classes"][j])] += kappa
        evidence.setdefault(track.track_id, []).append(score)
        return replace(track, state=state, P=P, attributes=attributes, attribute_variance=variance, class_mass=mass, matched=True)

    def _birth(self, detections: dict, j: int, m: int, frame: FrameInput, evidence: dict) -> Track:
        p = self.params
        box = detections["boxes"][j]; score = float(detections["scores"][j])
        P = np.diag([p.sensor_sigma_m[m] ** 2] * 2 + [p.initial_velocity_sigma_m_per_s ** 2] * 2)
        variance = np.array([p.attribute_sigma_m ** 2] * 4 + [p.yaw_sigma_rad ** 2])
        mass = np.zeros(3); mass[int(detections["classes"][j])] = score
        track = Track(self._next_id, np.array([box[0], box[2], 0.0, 0.0]), P, box[list(ATTRIBUTES)].astype(float), variance, mass,
                      score, matched=True)
        self._next_id += 1
        evidence[track.track_id] = [score]
        return track

    # -- lifecycle ------------------------------------------------------------------------------

    def _lifecycle(self, track: Track, scores: list[float], available_count: int) -> Optional[Track]:
        p = self.params
        history = (track.history + (track.matched,))[-p.confirm_window:]
        if track.matched:
            observed_score = min(1.0, sum(scores) / max(available_count, 1))
            first = len(track.history) == 0
            score = observed_score if first else p.score_smoothing * track.score + (1 - p.score_smoothing) * observed_score
            track = replace(track, score=score, history=history, missed=0)
            if not track.confirmed and sum(history) >= p.confirm_hits:
                track = replace(track, confirmed=True)
            return track
        missed = track.missed + 1
        track = replace(track, history=history, missed=missed, score=track.score * (p.prediction_score_decay if track.confirmed else 1.0))
        if not track.confirmed:
            return None if len(history) >= p.confirm_window and sum(history) < p.confirm_hits else track
        if missed > p.max_missed_frames or _position_sigma(track.P) > p.max_position_sigma_m:
            return None
        return track

    def _output(self, track: Track) -> TrackOutput:
        y, w, h, l, yaw = track.attributes
        return TrackOutput(track.track_id, np.array([track.state[0], y, track.state[1], w, h, l, yaw]),
                           int(np.argmax(track.class_mass)), float(track.score), track.matched, track.P[:2, :2].copy())

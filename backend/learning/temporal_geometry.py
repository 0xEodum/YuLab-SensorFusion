"""Sensor geometry for the temporal tracker: projection, calibration covariance, LiDAR support.

Optical cameras use +X right, +Y down, +Z forward and ideal pinhole intrinsics. Pose
perturbations are left SE(3) increments xi = [rotation vector, translation] applied to a
camera-frame point, x' = exp(xi) x. Every function returns finite values for degenerate
input (behind the camera, no points); validity is reported separately, never inferred
from NaN. Nothing here reads truth: poses are nominal and calibration covariances are
declared priors.
"""
from __future__ import annotations

from typing import NamedTuple

import numpy as np

NEAR_DEPTH_M = 0.5


class Projection(NamedTuple):
    pixel: np.ndarray      # (u, v) in pixels, finite even when invalid
    jacobian: np.ndarray   # d(u, v)/d(x, y, z), 2x3, zeros when depth is not usable
    depth: float
    valid: bool            # in front of the camera and inside the image


class LidarSupport(NamedTuple):
    count: int             # observed points inside the radius
    mean_offset: np.ndarray  # mean of the nearest `neighbours` offsets from the reference; zeros without points
    valid: bool            # at least `min_points` inside the radius


def project_pinhole(camera: dict, point: np.ndarray) -> Projection:
    x, y, z = (float(v) for v in point)
    if z <= NEAR_DEPTH_M:
        return Projection(np.array([camera["cx_px"], camera["cy_px"]]), np.zeros((2, 3)), z, False)
    fx, fy = camera["fx_px"], camera["fy_px"]
    pixel = np.array([fx * x / z + camera["cx_px"], fy * y / z + camera["cy_px"]])
    jacobian = np.array([[fx / z, 0.0, -fx * x / z ** 2], [0.0, fy / z, -fy * y / z ** 2]])
    inside = 0 <= pixel[0] < camera["width_px"] and 0 <= pixel[1] < camera["height_px"]
    return Projection(pixel, jacobian, z, bool(inside))


def pose_jacobian(point: np.ndarray) -> np.ndarray:
    """d(exp(xi) x)/d xi at xi = 0: [-[x]_x, I] (3x6)."""
    x, y, z = point
    skew = np.array([[0.0, -z, y], [z, 0.0, -x], [-y, x, 0.0]])
    return np.hstack((-skew, np.eye(3)))


def projection_pose_jacobian(camera: dict, point: np.ndarray) -> np.ndarray:
    return project_pinhole(camera, point).jacobian @ pose_jacobian(point)


def pixel_covariance(camera: dict, point: np.ndarray, state_covariance: np.ndarray,
                     calibration_covariance: np.ndarray, pixel_sigma: float) -> np.ndarray:
    """J_x S J_x^T + J_xi C J_xi^T + sigma_pix^2 I (state covariance in camera axes)."""
    j_x = project_pinhole(camera, point).jacobian
    j_xi = projection_pose_jacobian(camera, point)
    return j_x @ state_covariance @ j_x.T + j_xi @ calibration_covariance @ j_xi.T + pixel_sigma ** 2 * np.eye(2)


def camera_observable(camera: dict, point: np.ndarray, state_covariance: np.ndarray,
                      calibration_covariance: np.ndarray, pixel_sigma: float, margin_sigma: float) -> bool:
    """A predicted reference can receive camera support when it lies in front of the camera and its
    uncertainty ellipse's bounding box, scaled by `margin_sigma`, reaches the image."""
    if point[2] <= NEAR_DEPTH_M:
        return False
    pixel = project_pinhole(camera, point).pixel
    sigma = np.sqrt(np.diag(pixel_covariance(camera, point, state_covariance, calibration_covariance, pixel_sigma)))
    low, high = pixel - margin_sigma * sigma, pixel + margin_sigma * sigma
    return bool(high[0] >= 0 and low[0] <= camera["width_px"] - 1 and high[1] >= 0 and low[1] <= camera["height_px"] - 1)


def world_calibration_covariance(offset_from_sensor: np.ndarray, calibration_covariance: np.ndarray) -> np.ndarray:
    """Displacement covariance of a point at `offset_from_sensor` caused by extrinsic uncertainty.

    Axes are those of the offset (rotation error acts as a lateral displacement growing with range).
    """
    jacobian = pose_jacobian(np.asarray(offset_from_sensor, dtype=float))
    return jacobian @ calibration_covariance @ jacobian.T


def lidar_support(points: np.ndarray, reference: np.ndarray, radius_m: float, neighbours: int,
                  min_points: int = 1) -> LidarSupport:
    """Observed points near a predicted reference; validity masks empty or distant neighbourhoods."""
    if len(points) == 0:
        return LidarSupport(0, np.zeros(3), False)
    offsets = np.asarray(points, dtype=float) - reference
    distance = np.linalg.norm(offsets, axis=1)
    inside = np.flatnonzero(distance <= radius_m)
    if len(inside) == 0:
        return LidarSupport(0, np.zeros(3), False)
    nearest = inside[np.argsort(distance[inside], kind="stable")[:neighbours]]
    return LidarSupport(int(len(inside)), offsets[nearest].mean(axis=0), len(inside) >= min_points)

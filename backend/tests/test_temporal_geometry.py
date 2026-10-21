"""Camera projection Jacobians, calibration covariance and LiDAR support for the temporal tracker."""
import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from learning.temporal_geometry import (camera_observable, lidar_support, pixel_covariance, pose_jacobian,
                                        project_pinhole, projection_pose_jacobian, world_calibration_covariance)

CAMERA = {"fx_px": 463.5, "fy_px": 463.5, "cx_px": 320.0, "cy_px": 192.0, "width_px": 640, "height_px": 384}


def perturbed(point, xi):
    """Left SE(3) perturbation exp(xi) applied to a camera-frame point; xi = [rotvec, translation]."""
    return Rotation.from_rotvec(xi[:3]).apply(point) + xi[3:]


def test_projection_jacobian_matches_central_difference():
    point = np.array([3.0, -1.5, 40.0])
    result = project_pinhole(CAMERA, point)
    step = 1e-5
    numeric = np.stack([(project_pinhole(CAMERA, point + step * e).pixel - project_pinhole(CAMERA, point - step * e).pixel)
                        / (2 * step) for e in np.eye(3)], axis=1)
    assert result.valid
    np.testing.assert_allclose(result.jacobian, numeric, rtol=1e-6, atol=1e-8)


def test_pose_jacobian_matches_finite_difference_of_exponential_map():
    point = np.array([-4.0, 2.0, 25.0])
    step = 1e-6
    numeric = np.stack([(perturbed(point, step * e) - perturbed(point, -step * e)) / (2 * step) for e in np.eye(6)], axis=1)
    np.testing.assert_allclose(pose_jacobian(point), numeric, rtol=1e-6, atol=1e-8)


def test_projection_pose_jacobian_composes_projection_and_pose_derivatives():
    point = np.array([5.0, 1.0, 60.0])
    step = 1e-6
    numeric = np.stack([(project_pinhole(CAMERA, perturbed(point, step * e)).pixel
                         - project_pinhole(CAMERA, perturbed(point, -step * e)).pixel) / (2 * step) for e in np.eye(6)], axis=1)
    np.testing.assert_allclose(projection_pose_jacobian(CAMERA, point), numeric, rtol=1e-5, atol=1e-6)


@pytest.mark.parametrize("point", [[0, 0, 0], [0, 0, -5.0], [1, 2, 0.1], [0, 0, 0.5]])
def test_points_behind_or_at_the_camera_are_invalid_and_finite(point):
    result = project_pinhole(CAMERA, np.array(point, dtype=float))
    assert not result.valid
    assert np.isfinite(result.pixel).all() and np.isfinite(result.jacobian).all()
    assert not camera_observable(CAMERA, np.array(point, dtype=float), np.eye(3), np.zeros((6, 6)), 1.0, margin_sigma=3)


def test_off_image_reference_is_not_observable_unless_uncertainty_reaches_the_image():
    far_left = np.array([-40.0, 0.0, 40.0])  # u = 320 - 463.5 ~ -143
    assert project_pinhole(CAMERA, far_left).pixel[0] < 0
    assert not project_pinhole(CAMERA, far_left).valid
    assert not camera_observable(CAMERA, far_left, 1e-4 * np.eye(3), np.zeros((6, 6)), 1.0, margin_sigma=3)
    # A huge positional covariance projects to a pixel covariance whose margin reaches the image.
    assert camera_observable(CAMERA, far_left, 300.0 * np.eye(3), np.zeros((6, 6)), 1.0, margin_sigma=3)


def test_centre_reference_is_observable_with_zero_covariance():
    assert camera_observable(CAMERA, np.array([0.0, 0.0, 30.0]), np.zeros((3, 3)), np.zeros((6, 6)), 0.0, margin_sigma=3)


def test_pixel_covariance_adds_state_calibration_and_pixel_terms():
    point = np.array([2.0, 1.0, 30.0])
    state = np.diag([0.5, 0.2, 1.0]) ** 2
    calibration = np.diag([0.01, 0.01, 0.01, 0.1, 0.1, 0.1]) ** 2
    sigma_pix = 0.7
    result = pixel_covariance(CAMERA, point, state, calibration, sigma_pix)
    j_x = project_pinhole(CAMERA, point).jacobian
    j_xi = projection_pose_jacobian(CAMERA, point)
    np.testing.assert_allclose(result, j_x @ state @ j_x.T + j_xi @ calibration @ j_xi.T + sigma_pix ** 2 * np.eye(2))
    assert np.linalg.eigvalsh(result).min() > 0
    no_calibration = pixel_covariance(CAMERA, point, state, np.zeros((6, 6)), sigma_pix)
    assert np.trace(result) > np.trace(no_calibration)


def test_world_calibration_covariance_grows_with_range_and_is_psd():
    calibration = np.diag([0.01, 0.01, 0.01, 0.05, 0.05, 0.05]) ** 2
    near = world_calibration_covariance(np.array([0.0, 0.0, 10.0]), calibration)
    far = world_calibration_covariance(np.array([0.0, 0.0, 100.0]), calibration)
    assert near.shape == (3, 3) and np.linalg.eigvalsh(far).min() >= -1e-15
    assert np.trace(far) > 10 * np.trace(near) * 0.9  # rotation error scales with range; translation floor remains


def test_lidar_support_with_zero_points_is_invalid_and_finite():
    support = lidar_support(np.empty((0, 3)), np.array([0.0, 0.0, 10.0]), radius_m=5.0, neighbours=4)
    assert support.count == 0 and not support.valid
    assert np.isfinite(support.mean_offset).all() and support.mean_offset.shape == (3,)


def test_lidar_support_uses_only_points_inside_the_radius_nearest_first():
    reference = np.array([10.0, 0.0, 0.0])
    points = np.array([[10.5, 0, 0], [10.1, 0, 0], [40.0, 0, 0], [10.0, 3.0, 0], [10.0, 6.0, 0]])
    support = lidar_support(points, reference, radius_m=5.0, neighbours=2)
    assert support.count == 3  # radius count before the neighbour cap; (10, 6, 0) is 6 m away
    assert support.valid
    np.testing.assert_allclose(support.mean_offset, np.mean([[0.1, 0, 0], [0.5, 0, 0]], axis=0))


def test_lidar_support_requires_a_minimum_number_of_points():
    points = np.array([[10.0, 0.0, 0.0]])
    assert not lidar_support(points, np.array([10.0, 0, 0]), radius_m=5.0, neighbours=4, min_points=2).valid
    assert lidar_support(points, np.array([10.0, 0, 0]), radius_m=5.0, neighbours=4, min_points=1).valid

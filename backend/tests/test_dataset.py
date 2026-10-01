"""Independently specified raster and eligibility fixtures for SF-10."""
import json
from pathlib import Path

import numpy as np
import pytest

from app.dataset import camera_label, target_policy, validate_manifest
from app.observation_input import load_observation_only


# name, isolated silhouette, opaque occluder, visible pixels, tight half-open box,
# truncated, ideal LiDAR hits, eligible, ignore reason. Raster is 12 x 10.
FIXTURES = [
    ("complete_rgb", (2, 2, 6, 6), None, 16, [2, 2, 6, 6], False, 0, True, None),
    ("complete_ir", (3, 2, 7, 6), None, 16, [3, 2, 7, 6], False, 0, True, None),
    ("partial_left", (2, 2, 8, 6), (2, 2, 5, 6), 12, [5, 2, 8, 6], False, 0, False, "small_fragment"),
    ("partial_right", (2, 2, 8, 6), (5, 2, 8, 6), 12, [2, 2, 5, 6], False, 0, False, "small_fragment"),
    ("narrow_right", (1, 1, 9, 7), (1, 1, 8, 7), 6, [8, 1, 9, 7], False, 0, False, "small_fragment"),
    ("narrow_left", (1, 1, 9, 7), (2, 1, 9, 7), 6, [1, 1, 2, 7], False, 0, False, "small_fragment"),
    ("truncated_left", (0, 2, 5, 6), None, 20, [0, 2, 5, 6], True, 0, True, None),
    ("truncated_right", (7, 2, 12, 6), None, 20, [7, 2, 12, 6], True, 0, True, None),
    ("hidden_rgb", (2, 2, 6, 6), (2, 2, 6, 6), 0, None, False, 0, False, "fully_occluded"),
    ("hidden_ir", (3, 2, 7, 6), (3, 2, 7, 6), 0, None, False, 0, False, "fully_occluded"),
    ("out_rgb", None, None, 0, None, False, 0, False, "out_of_frustum"),
    ("out_ir", None, None, 0, None, False, 0, False, "out_of_frustum"),
    ("dark_visible", (2, 2, 6, 6), None, 16, [2, 2, 6, 6], False, 0, True, None),
    ("fog_visible", (3, 2, 7, 6), None, 16, [3, 2, 7, 6], False, 0, True, None),
    ("one_pixel", (2, 2, 3, 3), None, 1, [2, 2, 3, 3], False, 0, False, "small_fragment"),
    ("four_pixels", (8, 4, 10, 6), None, 4, [8, 4, 10, 6], False, 0, False, "small_fragment"),
    ("lidar_three", (2, 2, 6, 6), (2, 2, 6, 6), 0, None, False, 3, True, None),
    ("lidar_two", (2, 2, 6, 6), (2, 2, 6, 6), 0, None, False, 2, False, "small_fragment"),
    ("view_left", (1, 2, 5, 6), None, 16, [1, 2, 5, 6], False, 0, True, None),
    ("view_right", (7, 2, 11, 6), None, 16, [7, 2, 11, 6], False, 0, True, None),
    ("overlap_a", (2, 2, 7, 7), (4, 2, 7, 5), 16, [2, 2, 7, 7], False, 0, True, None),
    ("overlap_b", (2, 2, 7, 7), (2, 4, 5, 7), 16, [2, 2, 7, 7], False, 0, True, None),
    ("slit_ir", (2, 2, 8, 6), (2, 2, 7, 6), 4, [7, 2, 8, 6], False, 0, False, "small_fragment"),
    ("empty_scene", None, None, 0, None, False, 0, False, "out_of_frustum"),
]


@pytest.mark.parametrize("fixture", FIXTURES, ids=[row[0] for row in FIXTURES])
def test_visibility_fixture(fixture, tmp_path):
    _, bounds, occluder, expected_pixels, expected_box, truncated, hits, eligible, reason = fixture
    raster = np.zeros((10, 12), dtype=np.bool_)
    isolated = 0
    if bounds:
        x0, y0, x1, y1 = bounds
        raster[y0:y1, x0:x1] = True
        isolated = (x1 - x0) * (y1 - y0)
    if occluder:
        x0, y0, x1, y1 = occluder
        raster[y0:y1, x0:x1] = False
    label = camera_label(raster, isolated, truncated, tmp_path / "mask_npy")
    assert label["visible_pixels"] == expected_pixels
    assert label["visible_box_xyxy"] == expected_box
    assert label["isolated_projected_pixels"] == isolated
    assert label["visible_fraction"] == (expected_pixels / isolated if isolated else None)
    assert label["truncated"] is truncated
    assert np.array_equal(np.load(tmp_path / "mask_npy"), raster)
    other = {"visible_pixels": 0, "isolated_projected_pixels": 0}
    assert target_policy(label, other, hits) == (eligible, reason)


def test_observation_request_rejects_truth_fields_before_file_access(tmp_path):
    for request in ({"capture_id": "capture-1", "truth": "secret"},
                    {"capture_id": "capture-1", "annotation_dir": "secret"},
                    {"capture_id": "../secret"}):
        with pytest.raises(ValueError):
            load_observation_only(tmp_path, request)


def test_manifest_rejects_duplicate_and_interrupted_captures(tmp_path, monkeypatch):
    fixture = Path(__file__).resolve().parents[2] / "contracts/fixtures/DatasetManifest.json"
    manifest = json.loads(fixture.read_text(encoding="utf-8"))
    manifest["captures"][0]["files"] = [manifest["captures"][0]["observation"]]
    manifest["captures"].append(dict(manifest["captures"][0]))
    manifest["counts"]["train"] = 2
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate capture ID"):
        validate_manifest(tmp_path)
    manifest["captures"].pop()
    manifest["counts"]["train"] = 1
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(FileNotFoundError):
        validate_manifest(tmp_path)
    manifest["schema_version"] = "lab.v0"
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError):
        validate_manifest(tmp_path)


def test_manifest_rejects_group_split_leakage(tmp_path, monkeypatch):
    fixture = Path(__file__).resolve().parents[2] / "contracts/fixtures/DatasetManifest.json"
    manifest = json.loads(fixture.read_text(encoding="utf-8"))
    manifest["captures"][0]["files"] = [manifest["captures"][0]["observation"]]
    second = dict(manifest["captures"][0])
    second["capture_id"] = "capture-2"
    second["split"] = "test"
    manifest["captures"].append(second)
    manifest["counts"]["test"] = 1
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr("app.dataset.validate_capture_files", lambda *_: None)
    observation = {"rgb": {"data": {"image": {"artifact": {"sha256": "a"}}}},
                   "ir": {"data": {"radiance": {"artifact": {"sha256": "b"}}}},
                   "lidar": {"data": {"xyz": {"artifact": {"sha256": "c"}}}}}
    for name in ("capture-1", "capture-2"):
        directory = tmp_path / name
        directory.mkdir()
        (directory / "observation.json").write_text(json.dumps(observation), encoding="utf-8")
    with pytest.raises(ValueError, match="Group leaks"):
        validate_manifest(tmp_path)


def test_manifest_validation_on_executor_surfaces_capture_failures(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    fixture = Path(__file__).resolve().parents[2] / "contracts/fixtures/DatasetManifest.json"
    manifest = json.loads(fixture.read_text(encoding="utf-8"))
    manifest["captures"][0]["files"] = [manifest["captures"][0]["observation"]]
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with ThreadPoolExecutor(max_workers=2) as pool, pytest.raises(FileNotFoundError):
        validate_manifest(tmp_path, pool)

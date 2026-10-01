"""SF-10 immutable capture packaging and strict dataset readback."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from concurrent.futures import Executor
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from .contracts import validate_payload

VISIBILITY_POLICY = "visible-pixels-16-lidar-3.v1"
CLASS_IDS = {"aircraft": 8, "ground_vehicle": 9, "ship": 10}


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def artifact(path: Path) -> dict:
    media = "application/json" if path.suffix == ".json" or path.name.endswith("_json") else (
        "image/png" if path.suffix == ".png" or path.name.endswith("_png") else "application/x-npy")
    return {"id": path.stem, "sha256": digest(path), "byte_length": path.stat().st_size,
            "media_type": media}


def array_artifact(path: Path, units: str, frame: str) -> dict:
    value = np.load(path, mmap_mode="r", allow_pickle=False)
    types = {"u1": "uint8", "u2": "uint16", "u4": "uint32", "f4": "float32",
             "f8": "float64", "b1": "bool"}
    dtype = types.get(value.dtype.str[-2:])
    if dtype is None:
        raise ValueError(f"Unsupported NPY dtype: {path}")
    return {"artifact": artifact(path), "dtype": dtype, "shape": list(value.shape),
            "units": units, "frame": frame}


def tight_box(mask: np.ndarray):
    ys, xs = np.nonzero(mask)
    return None if len(xs) == 0 else [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1]


def camera_label(mask: np.ndarray, isolated: int, truncated: bool, path: Path) -> dict:
    visible = int(np.count_nonzero(mask))
    if visible > isolated:
        raise ValueError("Visible pixels exceed isolated silhouette")
    with path.open("wb") as stream:
        np.save(stream, mask)
    return {"mask": array_artifact(path, "1", "image-top-left"),
            "visible_box_xyxy": tight_box(mask), "visible_pixels": visible,
            "isolated_projected_pixels": isolated,
            "visible_fraction": visible / isolated if isolated else None,
            "truncated": truncated}


def target_policy(rgb: dict, ir: dict, ideal_hits: int) -> tuple[bool, str | None]:
    eligible = max(rgb["visible_pixels"], ir["visible_pixels"]) >= 16 or ideal_hits >= 3
    out_of_view = rgb["isolated_projected_pixels"] == 0 and ir["isolated_projected_pixels"] == 0
    reason = None if eligible else ("out_of_frustum" if out_of_view and ideal_hits == 0 else
        "fully_occluded" if rgb["visible_pixels"] == ir["visible_pixels"] == ideal_hits == 0 else
        "small_fragment")
    return eligible, reason


def json_file(path: Path, value: dict) -> dict:
    path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":"),
                               allow_nan=False) + "\n", encoding="utf-8")
    return artifact(path)


def package_capture(request: dict, result: dict, capture_dir: Path, output: Path,
                    records: dict[str, dict]) -> dict:
    """Read published files, validate their hashes/shapes, then atomically publish bundles."""
    capture_id = result["capture_id"]
    if capture_id != request["plan"]["capture_id"] or result["sequence_id"] != request["plan"]["sequence_id"]:
        raise ValueError("Capture identity mismatch")
    if set(request["plan"]["modalities"]) != {"rgb", "ir", "lidar"}:
        raise ValueError("Dataset capture must contain all three modalities")
    output.mkdir(parents=True, exist_ok=False)
    files = result["artifacts"]
    for entry in files.values():
        source = capture_dir / entry["id"]
        if not source.is_file() or source.stat().st_size != entry["byte_length"] or digest(source) != entry["sha256"]:
            raise ValueError(f"Capture artifact hash mismatch: {entry['id']}")
        os.link(source, output / entry["id"])
    rgb_sensor = next(s for s in request["rig"]["sensors"] if s["modality"] == "rgb")
    ir_sensor = next(s for s in request["rig"]["sensors"] if s["modality"] == "ir")
    lidar_sensor = next(s for s in request["rig"]["sensors"] if s["modality"] == "lidar")
    height, width = result["height"], result["width"]
    if any(s["camera"]["width_px"] != width or s["camera"]["height_px"] != height
           for s in (rgb_sensor, ir_sensor)):
        raise ValueError("Camera calibration and raw raster dimensions differ")
    lidar_shape = (lidar_sensor["lidar"]["rows"], lidar_sensor["lidar"]["columns"])
    if result["lidar_calibration"]["rows"] != lidar_shape[0] or \
       result["lidar_calibration"]["columns"] != lidar_shape[1] or \
       result["lidar_calibration"]["T_world_from_rig"] != request["rig"]["T_world_from_rig"] or \
       result["lidar_calibration"]["T_rig_from_sensor"] != lidar_sensor["T_rig_from_sensor"] or \
       result["ir_calibration"]["band_um"] != [8, 14]:
        raise ValueError("Sensor calibration metadata mismatch")
    n = result["lidar_point_count"]
    expected_arrays = {
        "rgb_raw_npy": ((height, width, 3), np.uint8),
        "depth_npy": ((height, width), np.float32),
        "instance_npy": ((height, width), np.uint32),
        "ir_instance_npy": ((height, width), np.uint32),
        "ir_radiance_npy": ((height, width), np.float32),
        "ir_validity_npy": ((height, width), np.bool_),
        "ir_saturation_npy": ((height, width), np.bool_),
        "lidar_xyz_npy": ((n, 3), np.float32),
        "lidar_intensity_npy": ((n,), np.float32),
        "lidar_beam_id_npy": ((n,), np.uint32),
        "lidar_time_offset_npy": ((n,), np.float32),
        "lidar_validity_npy": ((n,), np.bool_),
        "lidar_class_ref_npy": ((n,), np.uint8),
        "lidar_beam_status_npy": (lidar_shape, np.uint8),
        "lidar_ideal_range_npy": (lidar_shape, np.float32),
        "lidar_ideal_instance_npy": (lidar_shape, np.uint32),
        "lidar_ideal_class_npy": (lidar_shape, np.uint8),
    }
    for name, (shape, dtype) in expected_arrays.items():
        value = np.load(output / name, allow_pickle=False)
        if value.shape != shape or value.dtype != np.dtype(dtype):
            raise ValueError(f"Raw shape/dtype mismatch: {name}")
        if np.issubdtype(value.dtype, np.floating) and not np.isfinite(value).all():
            raise ValueError(f"Nonfinite raw values: {name}")
    rgb = np.load(output / "rgb_raw_npy", allow_pickle=False)
    rgb_ids = np.load(output / "instance_npy", allow_pickle=False)
    ir_ids = np.load(output / "ir_instance_npy", allow_pickle=False)
    ideal = np.load(output / "lidar_ideal_instance_npy", allow_pickle=False)
    beams = np.load(output / "lidar_beam_id_npy", allow_pickle=False)
    statuses = np.load(output / "lidar_beam_status_npy", allow_pickle=False)
    if rgb.shape != (height, width, 3) or rgb.dtype != np.uint8 or any(
        value.shape != (height, width) or value.dtype != np.uint32 for value in (rgb_ids, ir_ids)
    ):
        raise ValueError("Camera artifact shape/dtype mismatch")
    if ideal.shape != statuses.shape or len(beams) != result["lidar_point_count"]:
        raise ValueError("LiDAR artifact shape mismatch")
    with (output / "rgb_valid_npy").open("wb") as stream:
        np.save(stream, np.ones((height, width), dtype=np.bool_))
    with (output / "lidar_beam_flat_npy").open("wb") as stream:
        np.save(stream, statuses.ravel())
    available = lambda sensor, data: {"status": "available", "timestamp_s": result["tick_s"] +
        sensor["timestamp_offset_s"], "health": "ok", "sensor_id": sensor["sensor_id"],
        "sensor_model_version": sensor["sensor_model_version"], "data": data}
    sensors = {s["modality"]: s for s in request["rig"]["sensors"]}
    image = lambda key, unit="1": array_artifact(output / key, unit, "image-top-left")
    point = lambda key, unit="1": array_artifact(output / key, unit, "lidar-forward-left-up")
    obs = {"schema_version": "lab.v1", "kind": "ObservationBundle",
           "capture_id": capture_id, "sequence_id": result["sequence_id"], "rig": request["rig"],
           "rgb": available(sensors["rgb"], {"image": image("rgb_raw_npy"),
                "validity_mask": image("rgb_valid_npy"), "transfer_function": "srgb",
                "exposure_s": sensors["rgb"]["exposure_s"]}),
           "ir": available(sensors["ir"], {"radiance": image("ir_radiance_npy", "W/m2/sr"),
                "validity_mask": image("ir_validity_npy"), "saturation_mask": image("ir_saturation_npy"),
                "band_um": [8, 14], "response_version": "lwir-8-14um.v1"}),
           "lidar": available(sensors["lidar"], {"xyz": point("lidar_xyz_npy", "m"),
                "intensity": point("lidar_intensity_npy"), "beam_id": point("lidar_beam_id_npy"),
                "time_offset": point("lidar_time_offset_npy", "s"),
                "validity": point("lidar_validity_npy"), "beam_table": point("lidar_beam_flat_npy")})}
    validate_payload("ObservationBundle", obs)
    observation = json_file(output / "observation.json", obs)
    thermal = json.loads((output / "thermal_state_json").read_text(encoding="utf-8"))
    temperatures: dict[str, list] = {}
    for node in thermal["nodes"]:
        temperatures.setdefault(node["instance_id"], []).append({
            "part_id": node["region_id"], "temperature_k": node["temperature_k"]})
    annotations = []
    truth_objects = []
    for instance in request["world"]["instances"]:
        name = instance["instance_id"]
        numeric = result["instance_ids"][name]
        record = records[instance["asset_id"]]
        if record["content_sha256"] != instance["asset_sha256"]:
            raise ValueError("Asset hash mismatch")
        rgb_label = camera_label(rgb_ids == numeric,
            result["isolated_pixels"]["rgb"][name], result["truncated"]["rgb"][name],
            output / f"mask_rgb_{numeric}_npy")
        ir_label = camera_label(ir_ids == numeric,
            result["isolated_pixels"]["ir"][name], result["truncated"]["ir"][name],
            output / f"mask_ir_{numeric}_npy")
        ideal_hits = int(np.count_nonzero(ideal == numeric))
        surface_hits = int(np.count_nonzero((statuses.ravel()[beams] == 1) & (ideal.ravel()[beams] == numeric)))
        eligible, reason = target_policy(rgb_label, ir_label, ideal_hits)
        annotations.append({"instance_id": name, "class_id": CLASS_IDS[record["class_name"]],
            "box_3d": result["posed_boxes"][name], "rgb": rgb_label, "ir": ir_label,
            "lidar_ideal_hits": ideal_hits, "lidar_surface_hits": surface_hits,
            "eligible": eligible, "ignore_reason": reason})
        truth_objects.append({"instance": instance, "velocity_m_per_s": [0, 0, 0],
                              "surface_temperatures_k": temperatures.get(name, [])})
    ann = {"schema_version": "lab.v1", "kind": "AnnotationBundle", "capture_id": capture_id,
           "class_map_version": "lidar-semantic.v1", "visibility_policy_version": VISIBILITY_POLICY,
           "objects": annotations}
    validate_payload("AnnotationBundle", ann)
    annotation = json_file(output / "annotations.json", ann)
    truth = {"schema_version": "lab.v1", "kind": "TruthBundle", "capture_id": capture_id,
             "world": request["world"], "actual_rig": request["rig"], "environment": request["environment"],
             "objects": truth_objects, "clean_intermediates": [files[key] for key in
                 ("depth", "instance", "ir_instance", "lidar_ideal_range", "lidar_ideal_instance", "lidar_ideal_class")],
             "corruption_masks": [image("ir_validity_npy"), image("ir_saturation_npy")]}
    validate_payload("TruthBundle", truth)
    truth_artifact = json_file(output / "truth.json", truth)
    return {"capture_id": capture_id, "sequence_id": result["sequence_id"],
            "observation": observation, "annotations": annotation, "truth": truth_artifact}


def validate_capture_files(directory: Path, entry: dict) -> None:
    if "files" in entry:
        inventory = entry["files"]
        names = [item["id"] for item in inventory]
        if len(names) != len(set(names)) or set(names) != {p.stem if p.suffix == ".json" else p.name
            for p in directory.iterdir() if p.is_file()}:
            raise ValueError("Incomplete or duplicate capture file inventory")
        for item in inventory:
            name = item["id"] + (".json" if item["id"] in ("observation", "annotations", "truth") else "")
            path = directory / name
            if digest(path) != item["sha256"] or path.stat().st_size != item["byte_length"]:
                raise ValueError(f"Corrupt inventoried file: {name}")
    metadata = json.loads((directory / "metadata_json").read_text(encoding="utf-8"))
    if metadata["capture_id"] != entry["capture_id"]:
        raise ValueError("Capture metadata identity mismatch")
    for source in metadata["artifacts"].values():
        path = directory / source["id"]
        if not path.is_file() or digest(path) != source["sha256"] or path.stat().st_size != source["byte_length"]:
            raise ValueError(f"Corrupt capture artifact: {path}")
    for key in ("observation", "annotations", "truth"):
        meta = entry[key]
        path = directory / (meta["id"] + ".json")
        if not path.is_file() or digest(path) != meta["sha256"] or path.stat().st_size != meta["byte_length"]:
            raise ValueError(f"Corrupt or missing bundle: {path}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        validate_payload(payload["kind"], payload)
        if payload["capture_id"] != entry["capture_id"]:
            raise ValueError("Bundle capture ID mismatch")
        def walk(node):
            if isinstance(node, dict):
                if set(("artifact", "dtype", "shape", "units", "frame")) <= node.keys():
                    meta = node["artifact"]
                    source = directory / meta["id"]
                    if not source.is_file() or digest(source) != meta["sha256"]:
                        raise ValueError(f"Corrupt array: {source}")
                    array = np.load(source, mmap_mode="r", allow_pickle=False)
                    if list(array.shape) != node["shape"]:
                        raise ValueError(f"Wrong array shape: {source}")
                for value in node.values(): walk(value)
            elif isinstance(node, list):
                for value in node: walk(value)
        walk(payload)


def validate_manifest(root: Path, executor: Executor | None = None) -> dict:
    """Validate a published dataset; per-capture file checks may run on an executor."""
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    validate_payload("DatasetManifest", manifest)
    captures = manifest["captures"]
    if len({x["capture_id"] for x in captures}) != len(captures):
        raise ValueError("Duplicate capture ID")
    groups = {}
    for entry in captures:
        if not entry.get("files"):
            raise ValueError("Capture file inventory missing")
        previous = groups.setdefault(entry["group_id"], entry["split"])
        if previous != entry["split"]:
            raise ValueError("Group leaks across splits")
    directories = [root / entry["capture_id"] for entry in captures]
    # map() re-raises the first failing capture's error while iterating.
    for _ in (executor.map if executor else map)(validate_capture_files, directories, captures):
        pass
    fingerprints = set()
    for entry in captures:
        observation = json.loads((root / entry["capture_id"] / "observation.json").read_text(encoding="utf-8"))
        fingerprint = tuple(observation[name]["data"][field]["artifact"]["sha256"]
            for name, field in (("rgb", "image"), ("ir", "radiance"), ("lidar", "xyz")))
        if fingerprint in fingerprints:
            raise ValueError("Duplicate tri-modal observation")
        fingerprints.add(fingerprint)
    for split in ("train", "validation", "test"):
        if manifest["counts"][split] != sum(x["split"] == split for x in captures):
            raise ValueError("Manifest split count mismatch")
    return manifest


def publish_manifest(root: Path, dataset_id: str, entries: list[dict],
                     requests: list[dict], records: dict[str, dict],
                     executor: Executor | None = None) -> dict:
    if not entries or len(entries) != len(requests):
        raise ValueError("Manifest requires one completed entry per request")
    if len({x["capture_id"] for x in entries}) != len(entries):
        raise ValueError("Duplicate capture ID")
    world_hashes = sorted({r["plan"]["world_sha256"] for r in requests})
    config_hash = hashlib.sha256(json.dumps(requests, sort_keys=True,
        separators=(",", ":")).encode()).hexdigest()
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    splits = {"train": 0, "validation": 0, "test": 0}
    for entry in entries:
        splits[entry["split"]] += 1
    manifest = {"schema_version": "lab.v1", "kind": "DatasetManifest",
        "dataset_id": dataset_id, "created_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "provenance": {"source_revision": revision,
            "world_sha256": hashlib.sha256("".join(world_hashes).encode()).hexdigest(),
            "asset_hashes": sorted({v["content_sha256"] for v in records.values()}),
            "config_sha256": config_hash, "sensor_version": "sensor-capture.v1",
            "generator_version": "sf10-dataset-job.v1", "toolchain": "Node capture worker / Python numpy",
            "seed": requests[0]["world"]["seed"]},
        "class_map": [{"id": id_, "name": name} for name, id_ in CLASS_IDS.items()],
        "class_map_version": "lidar-semantic.v1", "captures": entries, "files": [],
        "counts": splits}
    validate_payload("DatasetManifest", manifest)
    staging = root / "manifest.json.partial"
    json_file(staging, manifest)
    os.replace(staging, root / "manifest.json")
    validate_manifest(root, executor)
    return manifest

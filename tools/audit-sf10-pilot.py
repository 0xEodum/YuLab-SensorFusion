"""Independent numerical readback of every SF-10 pilot label and calibration."""
from __future__ import annotations

import argparse
import collections
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.dataset import validate_manifest  # noqa: E402


def canonical_hash(value: dict) -> str:
    def encode(node):
        if isinstance(node, dict):
            return "{" + ",".join(json.dumps(k, ensure_ascii=False) + ":" + encode(node[k])
                                  for k in sorted(node)) + "}"
        if isinstance(node, list):
            return "[" + ",".join(encode(v) for v in node) + "]"
        if isinstance(node, float):
            if not np.isfinite(node):
                raise ValueError("Nonfinite request value")
            if node == 0:
                return "0"
            if node.is_integer() and abs(node) < 1e21:
                return str(int(node))
            number = repr(node)
            if "e" in number:
                mantissa, exponent = number.split("e")
                power = int(exponent)
                if 1e-6 <= abs(node) < 1e21:
                    sign = "-" if mantissa.startswith("-") else ""
                    mantissa = mantissa.lstrip("-")
                    position = len(mantissa.split(".")[0]) + power
                    digits = mantissa.replace(".", "")
                    number = sign + ("0." + "0" * -position + digits if position <= 0 else
                                     digits[:position] + "." + digits[position:] if position < len(digits) else
                                     digits + "0" * (position - len(digits)))
                else:
                    number = mantissa.removesuffix(".0") + "e" + ("+" if power >= 0 else "-") + str(abs(power))
            return number
        return json.dumps(node, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    return hashlib.sha256(encode(value).encode()).hexdigest()


def run(root: Path, requests: Path, workers: int = 1) -> dict:
    if workers < 1:
        raise ValueError("workers must be positive")
    if workers == 1:
        manifest = validate_manifest(root)
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            manifest = validate_manifest(root, pool)
    expected = json.loads(requests.read_text(encoding="utf-8"))["requests"]
    by_id = {item["request"]["plan"]["capture_id"]: item for item in expected}
    if len(by_id) != len(expected) or set(by_id) != {entry["capture_id"] for entry in manifest["captures"]}:
        raise ValueError("Pilot requests and manifest differ")
    counts = collections.Counter()
    classes = collections.Counter()
    reasons = collections.Counter()
    groups: dict[str, set[str]] = collections.defaultdict(set)
    sequences: dict[str, list[tuple[str, str, str]]] = collections.defaultdict(list)
    for entry in manifest["captures"]:
        directory = root / entry["capture_id"]
        request = by_id[entry["capture_id"]]["request"]
        result = json.loads((directory / "metadata_json").read_text(encoding="utf-8"))
        annotation = json.loads((directory / "annotations.json").read_text(encoding="utf-8"))
        observation = json.loads((directory / "observation.json").read_text(encoding="utf-8"))
        if entry["group_id"] != by_id[entry["capture_id"]]["group_id"] or \
           entry["split"] != by_id[entry["capture_id"]]["split"]:
            raise ValueError("Group/split mismatch")
        groups[entry["group_id"]].add(entry["split"])
        for field in ("world", "rig", "environment"):
            if canonical_hash(request[field]) != request["plan"][f"{field}_sha256"]:
                raise ValueError(f"Request {field} hash mismatch")
        lidar = next(s for s in request["rig"]["sensors"] if s["modality"] == "lidar")
        calibration = result["lidar_calibration"]
        for actual, wanted in ((calibration["rows"], lidar["lidar"]["rows"]),
                               (calibration["columns"], lidar["lidar"]["columns"]),
                               (calibration["horizontal_fov_rad"], lidar["lidar"]["horizontal_fov_rad"]),
                               (calibration["vertical_fov_rad"], lidar["lidar"]["vertical_fov_rad"]),
                               (calibration["min_range_m"], lidar["min_range_m"]),
                               (calibration["max_range_m"], lidar["max_range_m"]),
                               (calibration["scan_duration_s"], lidar["scan_duration_s"]),
                               (calibration["timestamp_offset_s"], lidar["timestamp_offset_s"]),
                               (calibration["T_rig_from_sensor"], lidar["T_rig_from_sensor"]),
                               (calibration["T_world_from_rig"], request["rig"]["T_world_from_rig"])):
            if actual != wanted:
                raise ValueError("LiDAR calibration mismatch")
        if result["ir_calibration"]["band_um"] != [8, 14] or \
           observation["rig"] != request["rig"]:
            raise ValueError("Optical calibration mismatch")
        rgb = np.load(directory / "instance_npy", allow_pickle=False)
        ir = np.load(directory / "ir_instance_npy", allow_pickle=False)
        ideal = np.load(directory / "lidar_ideal_instance_npy", allow_pickle=False).ravel()
        status = np.load(directory / "lidar_beam_status_npy", allow_pickle=False).ravel()
        beam = np.load(directory / "lidar_beam_id_npy", allow_pickle=False)
        for obj in annotation["objects"]:
            name = obj["instance_id"]
            numeric = result["instance_ids"][name]
            if obj["box_3d"] != result["posed_boxes"][name]:
                raise ValueError("Posed 3D box mismatch")
            for camera, raster in (("rgb", rgb), ("ir", ir)):
                visible = raster == numeric
                mask = np.load(directory / obj[camera]["mask"]["artifact"]["id"], allow_pickle=False)
                if not np.array_equal(mask, visible):
                    raise ValueError("Visibility mask differs from depth-tested IDs")
                ys, xs = np.nonzero(visible)
                box = None if not len(xs) else [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1]
                data = obj[camera]
                isolated = result["isolated_pixels"][camera][name]
                if data["visible_pixels"] != len(xs) or data["visible_box_xyxy"] != box or \
                   data["isolated_projected_pixels"] != isolated or \
                   data["truncated"] != result["truncated"][camera][name] or \
                   data["visible_fraction"] != (len(xs) / isolated if isolated else None):
                    raise ValueError("Camera label/count/box mismatch")
            ideal_hits = int(np.count_nonzero(ideal == numeric))
            surface_hits = int(np.count_nonzero((ideal[beam] == numeric) & (status[beam] == 1)))
            if obj["lidar_ideal_hits"] != ideal_hits or obj["lidar_surface_hits"] != surface_hits:
                raise ValueError("LiDAR hit count mismatch")
            eligible = max(obj["rgb"]["visible_pixels"], obj["ir"]["visible_pixels"]) >= 16 or ideal_hits >= 3
            if obj["eligible"] != eligible or (eligible and obj["ignore_reason"] is not None):
                raise ValueError("Target eligibility mismatch")
            classes[obj["class_id"]] += 1
            if not eligible: reasons[obj["ignore_reason"]] += 1
            if obj["rgb"]["visible_pixels"] and obj["rgb"]["visible_fraction"] < 1:
                counts["rgb_partial"] += 1
            if obj["ir"]["visible_pixels"] and obj["ir"]["visible_fraction"] < 1:
                counts["ir_partial"] += 1
            counts["eligible" if eligible else "ignored"] += 1
            counts["rgb_truncated"] += obj["rgb"]["truncated"]
            counts["ir_truncated"] += obj["ir"]["truncated"]
        counts["captures"] += 1
        sequences[entry["sequence_id"]].append(tuple(result["artifacts"][name]["sha256"]
            for name in ("instance", "ir_instance", "lidar_ideal_instance")))
    if any(len(splits) != 1 for splits in groups.values()):
        raise ValueError("Split leakage")
    if any(len(values) != 10 or len(set(values)) != 1 for values in sequences.values()):
        raise ValueError("Geometry labels changed across condition variants")
    return {"counts": dict(counts), "class_counts": dict(classes),
            "ignore_reasons": dict(reasons), "split_counts": manifest["counts"],
            "layout_groups": {key: next(iter(value)) for key, value in groups.items()},
            "condition_variant_sequences": len(sequences),
            "all_variant_geometry_hashes_equal": True}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", type=Path)
    parser.add_argument("requests", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()
    report = run(args.dataset.resolve(), args.requests.resolve(), args.workers)
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded)


if __name__ == "__main__":
    main()

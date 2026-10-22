"""Run the frozen SF-Q ensemble once per sequence frame and scenario; cache per-sensor detections.

The cache feeds temporal tracker tuning/scoring so GPU inference is paid once. Detections are
stored in world-axis metres (rig-relative output plus nominal rig origin); truth is stored
beside them for scoring only and never read by the tracker.
"""
import argparse
import hashlib
import json
from pathlib import Path
import pickle
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
import numpy as np
import torch
from app.observation_input import load_observation_only
from learning.decision_inference import DecisionFusionPredictor
from learning.sensor_degradation import CORRUPTIONS, degrade

LIDAR_POINT_SCENARIOS = ("clean", "lidar-known", "lidar-ood")  # other scenarios reuse the clean scan or have no scan
SCENARIOS = ("clean",) + tuple(f"availability-{b}" for b in range(1, 7)) + CORRUPTIONS
DEGRADATION_SEED = 1234


def truth_objects(root: Path, capture_id: str) -> list[dict]:
    ann = json.loads((root / capture_id / "annotations.json").read_text(encoding="utf-8"))
    result = []
    for obj in ann["objects"]:
        box = obj["box_3d"]
        qx, qy, qz, qw = box["quaternion_xyzw"]
        result.append({"instance_id": obj["instance_id"], "class": obj["class_id"] - 8, "eligible": bool(obj["eligible"]),
                       "box": np.array([*box["center_m"], *box["extent_m"], 2 * np.arctan2(qy, qw)], dtype=np.float64)})
    return result


def sensor_geometry(obs: dict, transform: np.ndarray) -> dict:
    """Nominal (not drifted) world-from-sensor poses and camera intrinsics, from the observation rig only."""
    result = {}
    for sensor in obs["rig"]["sensors"]:
        entry = {"T_world_from_sensor": transform @ np.array(sensor["T_rig_from_sensor"]).reshape(4, 4)}
        if sensor["modality"] != "lidar":
            camera = sensor["camera"]
            if camera["distortion"] != "ideal-pinhole" or camera["frame"] != "optical-right-down-forward":
                raise ValueError("Tracker geometry supports ideal pinhole optical cameras only")
            entry["camera"] = {k: float(camera[k]) for k in ("fx_px", "fy_px", "cx_px", "cy_px", "width_px", "height_px")}
        result[sensor["modality"]] = entry
    return result


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--dataset", type=Path, required=True)
    p.add_argument("--bundle", type=Path, default=ROOT / "docs/evidence/sf-quality/model-bundle.json")
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--device", default="cuda")
    p.add_argument("--limit", type=int, default=0, help="Only the first N captures (smoke runs)")
    p.add_argument("--split", choices=("train", "validation", "test"), help="Cache one split without reading other split observations")
    a = p.parse_args()
    torch.set_num_threads(2)
    bundle = json.loads(a.bundle.read_text())
    model = DecisionFusionPredictor([ROOT / x["path"] for x in bundle["experts"]], a.device, [x["sha256"] for x in bundle["experts"]])
    manifest = json.loads((a.dataset / "manifest.json").read_text())
    entries = [e for e in manifest["captures"] if a.split is None or e["split"] == a.split]
    entries = entries[:a.limit] if a.limit else entries
    frames, started = [], time.perf_counter()
    for n, entry in enumerate(entries):
        cid = entry["capture_id"]
        obs, arrays = load_observation_only(a.dataset, {"capture_id": cid})
        transform = np.array(obs["rig"]["T_world_from_rig"]).reshape(4, 4)
        record = {"capture_id": cid, "sequence_id": entry["sequence_id"], "group_id": entry["group_id"], "split": entry["split"],
                  "frame_index": obs["frame_index"], "time_s": obs["capture_time_s"], "T_world_from_rig": transform, "sensors": sensor_geometry(obs, transform),
                  "truth": truth_objects(a.dataset, cid), "scenarios": {}}
        for scenario in SCENARIOS:
            # Corrupting an already-delivered-nothing sensor changes nothing: reuse the clean frame.
            absent = scenario in CORRUPTIONS and f"{scenario.split('-')[0]}.{'image' if scenario.startswith('rgb') else 'radiance' if scenario.startswith('ir') else 'xyz'}" not in arrays
            d_obs, d_arrays = (obs, arrays) if scenario == "clean" or absent else degrade(obs, arrays, scenario, cid, seed=DEGRADATION_SEED)
            experts, available, origin = model.sensor_experts(d_obs, d_arrays)
            points = None
            if scenario in LIDAR_POINT_SCENARIOS and available[2]:
                valid = d_arrays["lidar.validity"].astype(bool)
                lidar = record["sensors"]["lidar"]["T_world_from_sensor"]
                points = (d_arrays["lidar.xyz"][valid].astype(np.float64) @ lidar[:3, :3].T + lidar[:3, 3]).astype(np.float32)
            record["scenarios"][scenario] = {"available": available, "lidar_points": points, "experts": [
                {"boxes": np.concatenate([e["boxes"][:, :3] + origin, e["boxes"][:, 3:]], 1).astype(np.float64),
                 "classes": e["classes"], "scores": e["scores"]} for e in experts]}
        frames.append(record)
        if n % 16 == 0:
            print(f"{n + 1}/{len(entries)} {time.perf_counter() - started:.0f}s", flush=True)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    payload = {"profile": "sf14-expert-cache.v1", "scenarios": SCENARIOS, "degradation_seed": DEGRADATION_SEED,
               "dataset_manifest_sha256": sha256(a.dataset / "manifest.json"), "ensemble_sha256": model.sha256,
               "elapsed_s": time.perf_counter() - started, "frames": frames}
    with a.output.open("wb") as f:
        pickle.dump(payload, f, protocol=4)
    print(f"wrote {a.output} frames={len(frames)} elapsed={payload['elapsed_s']:.0f}s")


if __name__ == "__main__":
    main()

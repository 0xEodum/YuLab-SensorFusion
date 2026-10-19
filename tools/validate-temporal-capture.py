"""Real-worker acceptance for scan-time rig motion and truth-only calibration.

Consumes one generated request, never modifies its source or frozen datasets.
Creates six captures under a fresh output directory and reports measured parity.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requests", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    os.environ["YULAB_CAPTURE_ROOT"] = str(output / "captures")
    from app.capture_worker import run_capture_worker
    from app.capture_session import CaptureWorkerSession
    from app.dataset import package_capture, validate_capture_files
    from app.dataset_pipeline import catalog_records
    from app.observation_input import load_observation_only
    from app.temporal_capture import actual_rig_at

    source = json.loads(args.requests.read_text(encoding="utf-8"))["requests"][0]["request"]
    base = copy.deepcopy(source)
    base["plan"]["modalities"] = ["rgb", "ir", "lidar"]
    for sensor in base["rig"]["sensors"]:
        sensor["available"] = True
        if sensor["modality"] == "lidar":
            sensor["scan_duration_s"] = .1
    base["rig"]["timing_profile"] = "timed-scan"
    zero = {"schema_version": "lab.v1", "kind": "TemporalCapture", "profile": "rig-motion-drift.v1",
        "reference_time_s": 0, "velocity_world_m_per_s": [0, 0, 0], "yaw_rate_rad_per_s": 0, "sensor_drift": []}
    requests, results, reports = {}, {}, {}
    with CaptureWorkerSession() as session:
        for name in ("static", "static-repeat", "zero", "motion", "motion-repeat", "drift"):
            request = copy.deepcopy(base)
            capture_id = f"rig-{name}"
            request["plan"].update(capture_id=capture_id, sequence_id="rig-acceptance")
            if name not in ("static", "static-repeat"):
                request["temporal"] = copy.deepcopy(zero)
            if name in ("motion", "motion-repeat", "drift"):
                request["temporal"]["velocity_world_m_per_s"] = [0, 0, -2]
                request["temporal"]["yaw_rate_rad_per_s"] = .1
            if name == "drift":
                request["temporal"]["sensor_drift"] = [
                    {"modality": m, "translation_rig_m": [.25, 0, 0], "translation_rate_rig_m_per_s": [.01, 0, 0],
                     "yaw_rad": .02, "yaw_rate_rad_per_s": .001} for m in ("rgb", "ir", "lidar")]
                for i, sensor in enumerate(request["rig"]["sensors"]):
                    sensor["timestamp_offset_s"] = .01 * (i + 1)
            # Bind the complete nominal snapshots exactly as API capture does.
            for key in ("world", "rig", "environment"):
                request["plan"][f"{key}_sha256"] = hashlib.sha256(json.dumps(request[key], sort_keys=True,
                    separators=(",", ":")).encode()).hexdigest()
            started = time.perf_counter()
            result = run_capture_worker({**request, "_job_id": capture_id}, threading.Event(), session=session)
            directory = output / "dataset" / capture_id
            metadata = package_capture(request, result, output / "captures" / capture_id, directory, catalog_records())
            validate_capture_files(directory, metadata)
            obs, arrays = load_observation_only(output / "dataset", {"capture_id": capture_id})
            truth = json.loads((directory / "truth.json").read_text())
            assert obs["rig"] == request["rig"]
            assert "temporal" not in obs and "actual_rig" not in obs
            assert truth["actual_rig"] == result.get("actual_rig", request["rig"])
            if "temporal" in request:
                assert truth["temporal"] == request["temporal"]
                # Compare TS worker actual calibration to an independent Python implementation.
                expected = actual_rig_at(request, 0)
                import numpy as np
                for a, b in zip(result["actual_rig"]["sensors"], expected["sensors"], strict=True):
                    np.testing.assert_allclose(a["T_rig_from_sensor"], b["T_rig_from_sensor"], atol=1e-9, rtol=0)
            if name == "drift":
                assert truth["actual_rig"] != obs["rig"]
                assert obs["lidar"]["data"]["sampling_profile"] == "timed-sensor.v1"
                import numpy as np
                sensor = next(s for s in request["rig"]["sensors"] if s["modality"] == "lidar")
                total = sensor["lidar"]["rows"] * sensor["lidar"]["columns"]
                np.testing.assert_allclose(arrays["lidar.time_offset"],
                    sensor["scan_duration_s"] * arrays["lidar.beam_id"] / (total - 1), atol=1e-8, rtol=0)
            worker_metadata = json.loads((directory / "metadata_json").read_text())
            reports[name] = {"wall_s": time.perf_counter() - started, "renderer": result["renderer"],
                "timings_ms": worker_metadata["timings_ms"], "point_count": result["lidar_point_count"],
                "observation_sha256": metadata["observation"]["sha256"], "array_count": len(arrays)}
            requests[name], results[name] = request, result
            print(json.dumps({"capture": name, **reports[name]}), flush=True)

    def data_hashes(name):
        return {k: v["sha256"] for k, v in results[name]["artifacts"].items() if k != "metadata"}
    assert data_hashes("static") == data_hashes("static-repeat") == data_hashes("zero")
    assert data_hashes("motion") == data_hashes("motion-repeat")
    assert results["motion"]["artifacts"]["lidar_xyz"]["sha256"] != results["static"]["artifacts"]["lidar_xyz"]["sha256"]
    assert results["drift"]["artifacts"]["rgb_raw"]["sha256"] != results["motion"]["artifacts"]["rgb_raw"]["sha256"]
    # Replay model input without any truth, annotations or worker metadata present.
    original = output / "dataset" / "rig-drift"
    isolated = output / "observation-only" / "rig-drift"
    isolated.mkdir(parents=True)
    observation = json.loads((original / "observation.json").read_text())
    os.link(original / "observation.json", isolated / "observation.json")
    for modality in ("rgb", "ir", "lidar"):
        for value in observation[modality]["data"].values():
            if isinstance(value, dict) and "artifact" in value:
                name = value["artifact"]["id"]
                os.link(original / name, isolated / name)
    _, arrays = load_observation_only(isolated.parent, {"capture_id": "rig-drift"})
    summary = {"profile": "rig-motion-drift.v1", "checks": {
        "static_repeat_exact": True, "zero_motion_exact": True, "motion_repeat_exact": True,
        "motion_changes_lidar": True, "drift_changes_rgb": True, "nominal_actual_isolation": True,
        "observation_only_arrays": len(arrays)}, "captures": reports,
        "limits": ["static objects; constant linear velocity and world/rig +Y yaw",
                   "global-shutter image sampled at timestamp; finite exposure integration not modeled",
                   "sequence coordinator, moving objects and temporal split policies remain SF-13 work"]}
    (output / "acceptance.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary["checks"]), flush=True)


if __name__ == "__main__":
    main()

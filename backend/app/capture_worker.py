"""Validated subprocess boundary for the Node/headless-Chromium capture worker."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import threading
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

from .jobs import WorkerContextLost, WorkerCrashed, WorkerTimedOut

ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_ROOT = Path(os.environ.get("YULAB_CAPTURE_ROOT", ROOT / "artifacts" / "capture-jobs")).resolve()
WORKER = ROOT / "workers" / "capture" / "index.mjs"
TIMEOUT_S = 120.0


def _command(*args: str):
    return ["node", str(WORKER), *args]


def _parse_stdout(text: str):
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        raise WorkerCrashed("Capture worker returned no protocol response.")
    try:
        return json.loads(lines[-1])
    except json.JSONDecodeError as exc:
        raise WorkerCrashed("Capture worker returned an invalid protocol response.") from exc


@lru_cache(maxsize=1)
def probe_capture_worker():
    completed = subprocess.run(
        _command("--capabilities"), cwd=ROOT, capture_output=True, text=True,
        timeout=30, check=False,
    )
    if completed.returncode != 0:
        raise WorkerCrashed("Capture renderer capability handshake failed.")
    result = _parse_stdout(completed.stdout)
    if (
        result.get("protocol") != "capture-worker.v1"
        or not result.get("webgl2")
        or not result.get("float_readback")
    ):
        raise WorkerContextLost("Required WebGL2 float reference passes are unavailable.")
    return result


def run_capture_worker(request: dict[str, Any], cancel: threading.Event):
    job_id = request.get("_job_id")
    if not isinstance(job_id, str):
        raise WorkerCrashed("Capture coordinator omitted the worker job identity.")
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    partial = (ARTIFACT_ROOT / f"{job_id}.partial").resolve()
    final = (ARTIFACT_ROOT / job_id).resolve()
    if partial.parent != ARTIFACT_ROOT or final.parent != ARTIFACT_ROOT:
        raise WorkerCrashed("Capture job path escaped the artifact root.")
    partial.mkdir(parents=False, exist_ok=False)
    wire_request = {key: value for key, value in request.items() if not key.startswith("_")}
    request_path = partial / "request.json"
    request_path.write_text(json.dumps(wire_request, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    # Files are drained by the OS while the worker runs. A large JSON result must
    # never fill a PIPE and block process exit before communicate() is reached.
    with tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as stdout_file, \
         tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as stderr_file:
        process = subprocess.Popen(
            _command("--request", str(request_path), "--output", str(partial)),
            cwd=ROOT, stdout=stdout_file, stderr=stderr_file, text=True,
        )
        started = time.monotonic()
        while process.poll() is None:
            if cancel.wait(0.05):
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
                raise WorkerCrashed("Capture worker was cancelled before publication.")
            if time.monotonic() - started > TIMEOUT_S:
                process.kill()
                process.wait(timeout=5)
                raise WorkerTimedOut(f"Capture exceeded the {TIMEOUT_S:g} second worker limit.")
        stdout_file.seek(0)
        stderr_file.seek(0)
        stdout, stderr = stdout_file.read(), stderr_file.read()
    if process.returncode != 0:
        if "worker_context_lost" in stderr:
            raise WorkerContextLost("Capture browser lost the required rendering context.")
        raise WorkerCrashed(f"Capture browser exited with code {process.returncode}.")
    result = _parse_stdout(stdout)
    if result.get("capture_id") != wire_request["plan"]["capture_id"]:
        raise WorkerCrashed("Capture worker returned the wrong capture identity.")
    required = {"rgb", "depth_preview", "instance_preview", "depth", "instance", "metadata"}
    if "ir" in wire_request["plan"]["modalities"]:
        required.update({
            "ir_preview", "ir_radiance", "ir_validity", "ir_saturation", "thermal_state",
        })
        if result.get("ir_calibration") is None:
            raise WorkerCrashed("Capture worker omitted IR calibration metadata.")
    if "lidar" in wire_request["plan"]["modalities"]:
        required.update({
            "lidar_xyz", "lidar_intensity", "lidar_beam_id", "lidar_time_offset",
            "lidar_validity", "lidar_beam_status", "lidar_ideal_range",
            "lidar_ideal_instance", "lidar_range_preview", "lidar_cloud_preview",
        })
        if result.get("lidar_calibration") is None:
            raise WorkerCrashed("Capture worker omitted LiDAR calibration metadata.")
    if set(result.get("artifacts", {})) != required:
        raise WorkerCrashed("Capture worker returned an incomplete artifact set.")
    for artifact in result["artifacts"].values():
        path = partial / artifact["id"]
        if not path.is_file() or path.stat().st_size != artifact["byte_length"]:
            raise WorkerCrashed("Capture artifact validation failed before publication.")
    os.replace(partial, final)
    return result

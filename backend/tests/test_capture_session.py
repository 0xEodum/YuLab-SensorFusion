"""Exercise a live subprocess protocol without requiring GPU fixtures."""
import json
import sys
import threading

import pytest

from app import capture_worker
from app.capture_session import CaptureWorkerSession
from app.jobs import WorkerCrashed, WorkerTimedOut, WorkerContextLost


FAKE_WORKER = """
import json, os, sys, time
from pathlib import Path
for line in sys.stdin:
    cmd = json.loads(line)
    output = Path(cmd['output'])
    req = json.loads(Path(cmd['request']).read_text())
    mode = req.get('mode')
    if mode == 'crash': sys.exit(19)
    if mode == 'hang': time.sleep(30)
    result = {'capture_id': req['id'], 'pid': os.getpid()}
    (output/'result.json').write_text(json.dumps(result))
    response = {'ok': mode != 'context', 'error': 'worker_context_lost'}
    stage = output/'response.partial'
    stage.write_text(json.dumps(response))
    stage.replace(output/'worker-response.json')
"""


def setup(monkeypatch, tmp_path, mode=None):
    monkeypatch.setattr(capture_worker, "_command", lambda *_: [sys.executable, "-u", "-c", FAKE_WORKER])
    def paths(id_):
        directory = tmp_path / id_
        directory.mkdir()
        request = directory / "request.json"
        request.write_text(json.dumps({"id": id_, "mode": mode}))
        return request, directory
    return paths


def test_session_reuses_process_and_closes_after_job(monkeypatch, tmp_path):
    paths = setup(monkeypatch, tmp_path)
    with CaptureWorkerSession() as session:
        first = json.loads(session.run(*paths("a"), threading.Event()))
        second = json.loads(session.run(*paths("b"), threading.Event()))
        process = session.process
        assert first['pid'] == second['pid']
        assert [first['capture_id'], second['capture_id']] == ['a', 'b']
    assert process.poll() == 0
    assert session.process is None


@pytest.mark.parametrize("mode,exception", [("crash", WorkerCrashed), ("hang", WorkerTimedOut),
                                           ("context", WorkerContextLost)])
def test_failed_session_stops_without_publishing(monkeypatch, tmp_path, mode, exception):
    paths = setup(monkeypatch, tmp_path, mode)
    monkeypatch.setattr(capture_worker, "TIMEOUT_S", 0.15 if mode == "hang" else 2)
    with CaptureWorkerSession() as session:
        with pytest.raises(exception):
            session.run(*paths("a"), threading.Event())
        assert session.process is None


def test_cancelled_session_stops(monkeypatch, tmp_path):
    paths = setup(monkeypatch, tmp_path, "hang")
    cancel = threading.Event()
    cancel.set()
    with CaptureWorkerSession() as session:
        with pytest.raises(WorkerCrashed, match="cancelled"):
            session.run(*paths("a"), cancel)
        assert session.process is None


@pytest.mark.parametrize("failure", [None, "identity", "missing", "cancel", "telemetry"])
def test_session_result_is_validated_before_atomic_publication(monkeypatch, tmp_path, failure):
    monkeypatch.setattr(capture_worker, "ARTIFACT_ROOT", tmp_path)
    cancel = threading.Event()
    required = {"rgb", "rgb_raw", "depth_preview", "instance_preview", "depth", "instance", "metadata"}
    class Session:
        def run(self, _request, output, _cancel):
            result = {"protocol": "capture-worker.v1",
                      "capture_id": "other" if failure == "identity" else "a", "sequence_id": "seq-a",
                      "tick_s": 0, "width": 1, "height": 1, "renderer": "fixture", "device": "fixture",
                      "browser_channel": "fixture", "elapsed_ms": 1, "render_elapsed_ms": 1,
                      "node_rss_bytes": 1, "browser_heap_bytes": None, "gpu_memory_bytes": None,
                      "resident_chunks": ["0,0@2"], "instance_ids": {}, "ir_calibration": None,
                      "lidar_calibration": None, "lidar_point_count": 0, "artifacts": {}}
            for name in required:
                if failure != "missing" or name != "depth":
                    (output / name).write_bytes(b"x")
                result["artifacts"][name] = {"id": name, "byte_length": 1,
                                             "sha256": "0" * 64, "media_type": "application/x-npy"}
            if failure == "telemetry":
                result["timings_ms"] = {"world_mesh_ms": 1}
            if failure == "cancel":
                cancel.set()
            return json.dumps(result)
    request = {"_job_id": "job-a", "plan": {"capture_id": "a", "modalities": ["rgb"]}}
    if failure:
        with pytest.raises(WorkerCrashed):
            capture_worker.run_capture_worker(request, cancel, session=Session())
        assert not (tmp_path / "job-a").exists()
    else:
        result = capture_worker.run_capture_worker(request, cancel, session=Session())
        assert result["capture_id"] == "a"
        assert (tmp_path / "job-a").is_dir()
        assert not (tmp_path / "job-a.partial").exists()

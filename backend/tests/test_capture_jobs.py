import threading
import time

from app.jobs import (
    CaptureCoordinator,
    CaptureJobStore,
    WorkerContextLost,
    WorkerCrashed,
    WorkerTimedOut,
)


def wait_terminal(store, job_id, timeout=2):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = store.get(job_id)
        if job["state"] in {"succeeded", "failed", "cancelled"}:
            return job
        time.sleep(0.01)
    raise AssertionError("capture job did not reach a terminal state")


def request(capture_id="capture-fixture"):
    return {"capture_id": capture_id, "payload": {"kind": "fixture"}}


def result(capture_id="capture-fixture"):
    return {"capture_id": capture_id, "artifacts": {}, "elapsed_ms": 1}


def test_success_is_persisted_and_publishes_only_a_complete_result(tmp_path):
    store = CaptureJobStore(tmp_path / "jobs.sqlite3")
    coordinator = CaptureCoordinator(store, lambda _request, _cancel: result())
    job = coordinator.submit(request())
    terminal = wait_terminal(store, job["job_id"])
    assert terminal["state"] == "succeeded"
    assert terminal["progress"] == 1
    assert terminal["result"]["capture_id"] == "capture-fixture"
    reopened = CaptureJobStore(tmp_path / "jobs.sqlite3")
    assert reopened.get(job["job_id"]) == terminal


def test_crash_and_timeout_are_explicit_failures_without_partial_frames(tmp_path):
    for failure, code in [
        (WorkerCrashed("browser exited 19"), "worker_crash"),
        (WorkerTimedOut("capture exceeded 5 s"), "worker_timeout"),
        (WorkerContextLost("WebGL context lost"), "worker_context_lost"),
    ]:
        store = CaptureJobStore(tmp_path / f"{code}.sqlite3")
        def run(_request, _cancel, failure=failure):
            raise failure
        job = CaptureCoordinator(store, run).submit(request(code))
        terminal = wait_terminal(store, job["job_id"])
        assert terminal["state"] == "failed"
        assert terminal["error"]["code"] == code
        assert terminal["result"] is None


def test_cancellation_is_terminal_and_cooperative(tmp_path):
    entered = threading.Event()
    def run(_request, cancel):
        entered.set()
        assert cancel.wait(1)
        return result()
    store = CaptureJobStore(tmp_path / "jobs.sqlite3")
    coordinator = CaptureCoordinator(store, run)
    job = coordinator.submit(request())
    assert entered.wait(1)
    cancelling = coordinator.cancel(job["job_id"])
    assert cancelling["state"] in {"cancelling", "cancelled"}
    terminal = wait_terminal(store, job["job_id"])
    assert terminal["state"] == "cancelled"
    assert terminal["result"] is None


def test_interrupted_running_jobs_fail_on_coordinator_restart(tmp_path):
    path = tmp_path / "jobs.sqlite3"
    store = CaptureJobStore(path)
    job = store.create(request())
    store.transition(job["job_id"], "running", progress=0.25)
    recovered = CaptureJobStore(path)
    recovered.fail_interrupted()
    terminal = recovered.get(job["job_id"])
    assert terminal["state"] == "failed"
    assert terminal["error"]["code"] == "worker_interrupted"
    assert terminal["result"] is None


def test_capture_queue_runs_one_worker_at_a_time(tmp_path):
    first_entered = threading.Event()
    release_first = threading.Event()
    active = 0
    peak = 0
    lock = threading.Lock()
    def run(request, _cancel):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        if request["capture_id"] == "first":
            first_entered.set()
            assert release_first.wait(1)
        with lock:
            active -= 1
        return result(request["capture_id"])
    store = CaptureJobStore(tmp_path / "jobs.sqlite3")
    coordinator = CaptureCoordinator(store, run)
    first = coordinator.submit(request("first"))
    assert first_entered.wait(1)
    second = coordinator.submit(request("second"))
    time.sleep(0.05)
    assert store.get(second["job_id"])["state"] == "queued"
    release_first.set()
    assert wait_terminal(store, first["job_id"])["state"] == "succeeded"
    assert wait_terminal(store, second["job_id"])["state"] == "succeeded"
    assert peak == 1

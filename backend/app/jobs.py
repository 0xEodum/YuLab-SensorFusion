"""Persistent single-host capture jobs with explicit terminal failure states."""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4


class WorkerCrashed(RuntimeError):
    code = "worker_crash"


class WorkerTimedOut(RuntimeError):
    code = "worker_timeout"


class WorkerContextLost(RuntimeError):
    code = "worker_context_lost"


class CaptureJobStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        with self._connect() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS capture_jobs (
                    job_id TEXT PRIMARY KEY,
                    capture_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    progress REAL NOT NULL,
                    request_json TEXT NOT NULL,
                    result_json TEXT,
                    error_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

    def _connect(self):
        return sqlite3.connect(self.path, timeout=10)

    @staticmethod
    def _now():
        return datetime.now(UTC).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _row(row):
        if row is None:
            raise KeyError("Unknown capture job")
        return {
            "schema_version": "lab.v1", "kind": "CaptureJob",
            "job_id": row[0], "capture_id": row[1], "state": row[2],
            "progress": row[3],
            "result": json.loads(row[4]) if row[4] else None,
            "error": json.loads(row[5]) if row[5] else None,
            "created_at": row[6], "updated_at": row[7],
        }

    def create(self, request: dict[str, Any]):
        capture_id = request.get("capture_id") or request.get("plan", {}).get("capture_id")
        if not isinstance(capture_id, str) or not capture_id:
            raise ValueError("Capture request requires capture_id")
        now = self._now()
        job_id = f"capture-job-{uuid4().hex}"
        with self._lock, self._connect() as db:
            db.execute(
                "INSERT INTO capture_jobs VALUES (?, ?, 'queued', 0, ?, NULL, NULL, ?, ?)",
                (job_id, capture_id, json.dumps(request, separators=(",", ":")), now, now),
            )
        return self.get(job_id)

    def request(self, job_id: str):
        with self._lock, self._connect() as db:
            row = db.execute(
                "SELECT request_json FROM capture_jobs WHERE job_id = ?", (job_id,),
            ).fetchone()
        if row is None:
            raise KeyError("Unknown capture job")
        return json.loads(row[0])

    def get(self, job_id: str):
        with self._lock, self._connect() as db:
            row = db.execute(
                "SELECT job_id,capture_id,state,progress,result_json,error_json,created_at,updated_at "
                "FROM capture_jobs WHERE job_id = ?", (job_id,),
            ).fetchone()
        return self._row(row)

    def transition(
        self, job_id: str, state: str, *, progress: float | None = None,
        result: dict[str, Any] | None = None, error: dict[str, Any] | None = None,
    ):
        allowed = {"queued", "running", "cancelling", "cancelled", "succeeded", "failed"}
        if state not in allowed:
            raise ValueError("Invalid capture job state")
        current = self.get(job_id)
        if current["state"] in {"cancelled", "succeeded", "failed"}:
            return current
        next_progress = current["progress"] if progress is None else progress
        if not 0 <= next_progress <= 1:
            raise ValueError("Invalid capture progress")
        if state == "succeeded" and result is None:
            raise ValueError("Succeeded capture requires a complete result")
        if state != "succeeded":
            result = None
        with self._lock, self._connect() as db:
            db.execute(
                "UPDATE capture_jobs SET state=?,progress=?,result_json=?,error_json=?,updated_at=? WHERE job_id=?",
                (
                    state, 1 if state == "succeeded" else next_progress,
                    json.dumps(result, separators=(",", ":")) if result is not None else None,
                    json.dumps(error, separators=(",", ":")) if error is not None else None,
                    self._now(), job_id,
                ),
            )
        return self.get(job_id)

    def fail_interrupted(self):
        with self._lock, self._connect() as db:
            rows = db.execute(
                "SELECT job_id FROM capture_jobs WHERE state IN ('running','cancelling')"
            ).fetchall()
        for (job_id,) in rows:
            self.transition(job_id, "failed", error={
                "code": "worker_interrupted",
                "message": "Capture worker was interrupted before publication.",
            })


Runner = Callable[[dict[str, Any], threading.Event], dict[str, Any]]


class CaptureCoordinator:
    def __init__(self, store: CaptureJobStore, runner: Runner):
        self.store = store
        self.runner = runner
        self._cancels: dict[str, threading.Event] = {}
        self._lock = threading.RLock()
        self._worker_slot = threading.Semaphore(1)

    def submit(self, request: dict[str, Any]):
        job = self.store.create(request)
        cancel = threading.Event()
        with self._lock:
            self._cancels[job["job_id"]] = cancel
        threading.Thread(
            target=self._run,
            args=(job["job_id"], {**request, "_job_id": job["job_id"]}, cancel),
            daemon=True,
            name=f"capture-{job['job_id']}",
        ).start()
        return job

    def _run(self, job_id: str, request: dict[str, Any], cancel: threading.Event):
        acquired = False
        try:
            while not acquired:
                if cancel.is_set():
                    self.store.transition(job_id, "cancelled")
                    return
                acquired = self._worker_slot.acquire(timeout=0.05)
            self.store.transition(job_id, "running", progress=0.05)
            result = self.runner(request, cancel)
            if cancel.is_set():
                self.store.transition(job_id, "cancelled")
            else:
                self.store.transition(job_id, "succeeded", result=result)
        except (WorkerCrashed, WorkerTimedOut, WorkerContextLost) as exc:
            if cancel.is_set():
                self.store.transition(job_id, "cancelled")
            else:
                self.store.transition(job_id, "failed", error={
                    "code": exc.code, "message": str(exc),
                })
        except Exception:
            self.store.transition(job_id, "failed", error={
                "code": "worker_error",
                "message": "Capture worker could not complete the job.",
            })
        finally:
            if acquired:
                self._worker_slot.release()
            with self._lock:
                self._cancels.pop(job_id, None)

    def cancel(self, job_id: str):
        job = self.store.get(job_id)
        if job["state"] in {"cancelled", "succeeded", "failed"}:
            return job
        job = self.store.transition(job_id, "cancelling")
        with self._lock:
            cancel = self._cancels.get(job_id)
            if cancel:
                cancel.set()
        return job

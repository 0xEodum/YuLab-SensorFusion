"""One sequential Node/browser session per dataset job; no reused sensor state."""
from __future__ import annotations

import json
import subprocess
import tempfile
import time

from .jobs import WorkerContextLost, WorkerCrashed, WorkerTimedOut

SHARING_RETRY_S = 2.0


def _retry_sharing(operation, path):
    """Windows briefly denies access to a just-renamed file (scanners, handle release)."""
    deadline = time.monotonic() + SHARING_RETRY_S
    while True:
        try:
            return operation(path)
        except PermissionError:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.01)


class CaptureWorkerSession:
    def __init__(self):
        self.process = None
        self.logs = None

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()

    def close(self, force=False):
        if self.process is not None:
            if force and self.process.poll() is None:
                self.process.terminate()
            if self.process.stdin:
                try:
                    self.process.stdin.close()
                except BrokenPipeError:
                    pass
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
            self.process = None
        if self.logs is not None:
            self.logs.close()
            self.logs = None

    def run(self, request_path, output, cancel):
        from .capture_worker import ROOT, TIMEOUT_S, _command
        if self.process is None:
            self.logs = tempfile.TemporaryFile(mode="w+t", encoding="utf-8")
            self.process = subprocess.Popen(_command("--session"), cwd=ROOT,
                stdin=subprocess.PIPE, stdout=self.logs, stderr=self.logs,
                text=True, encoding="utf-8")
        response = output / "worker-response.json"
        command = {"request": str(request_path), "output": str(output)}
        try:
            self.process.stdin.write(json.dumps(command) + "\n")
            self.process.stdin.flush()
            started = time.monotonic()
            while not response.exists():
                if cancel.wait(0.02):
                    raise WorkerCrashed("Capture worker was cancelled before publication.")
                if self.process.poll() is not None:
                    raise WorkerCrashed("Persistent capture worker exited before responding.")
                if time.monotonic() - started > TIMEOUT_S:
                    raise WorkerTimedOut(f"Capture exceeded the {TIMEOUT_S:g} second worker limit.")
            acknowledgement = json.loads(
                _retry_sharing(lambda path: path.read_text(encoding="utf-8"), response))
            if not acknowledgement.get("ok"):
                error = acknowledgement.get("error", "Capture session failed")
                if "worker_context_lost" in error:
                    raise WorkerContextLost("Capture browser lost the required rendering context.")
                raise WorkerCrashed(error)
            _retry_sharing(lambda path: path.unlink(), response)
            if cancel.is_set():
                raise WorkerCrashed("Capture worker was cancelled before publication.")
            return json.dumps(json.loads((output / "result.json").read_text(encoding="utf-8")))
        except BaseException:
            self.close(force=True)
            raise

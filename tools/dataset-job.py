"""Run or resume a grouped, immutable SF-10 dataset job."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import sys
import threading
import time
from concurrent.futures import Future, ProcessPoolExecutor, wait
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.capture_worker import ARTIFACT_ROOT, run_capture_worker  # noqa: E402
from app.capture_lanes import UnitScheduler, plan_units  # noqa: E402
from app.capture_session import CaptureWorkerSession  # noqa: E402
from app.contracts import validate_payload  # noqa: E402
from app.dataset import digest, publish_manifest, validate_manifest  # noqa: E402
from app.dataset_pipeline import (capture_job_id, catalog_records, discard_partial,  # noqa: E402
                                  finalize_capture, resume_published)


def write_state(path: Path, state: dict) -> None:
    partial = path.with_suffix(".json.partial")
    partial.write_text(json.dumps(state, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    os.replace(partial, path)


def default_workers() -> int:
    # Each session is one mostly single-threaded browser plus packaging work.
    return max(1, min(6, (os.cpu_count() or 2) // 2))


def capture_item(item: dict, root: Path, cancel: threading.Event,
                 session: CaptureWorkerSession | None) -> tuple[dict | None, bool]:
    """Capture one request unless resumable. Returns (published metadata or None, reused)."""
    if (root / item["request"]["plan"]["capture_id"]).exists():
        return resume_published(item, root), True
    job_id = capture_job_id(item)
    if (ARTIFACT_ROOT / job_id).exists():
        return None, True
    discard_partial(ARTIFACT_ROOT / f"{job_id}.partial", ARTIFACT_ROOT)
    run_capture_worker({**item["request"], "_job_id": job_id}, cancel, session=session)
    return None, False


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--requests", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--dataset-id", default="sf10-pilot-v1")
    parser.add_argument("--count", type=int)
    parser.add_argument("--single-use", action="store_true", help="Launch a fresh browser for every capture (reference mode)")
    parser.add_argument("--workers", type=int, default=default_workers(),
                        help="Parallel capture sessions (default: %(default)s)")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--cancel", action="store_true")
    parser.add_argument("--validate", action="store_true")
    args = parser.parse_args()
    if args.workers < 1:
        raise ValueError("--workers must be at least 1")
    root = args.output.resolve()
    if args.validate:
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            manifest = validate_manifest(root, pool)
        print(json.dumps({"validated": len(manifest["captures"]), "counts": manifest["counts"]}))
        return
    if args.cancel:
        (root / "cancel.requested").touch()
        print("Cancellation requested")
        return
    payload = json.loads(args.requests.read_text(encoding="utf-8"))
    if payload.get("version") != "sf10-requests.v1":
        raise ValueError("Unsupported request manifest version")
    jobs = payload["requests"][:args.count]
    if not jobs or (args.count is not None and args.count <= 0):
        raise ValueError("No requested samples")
    for item in jobs:
        validate_payload("CaptureRequest", item["request"])
        if item["split"] not in ("train", "validation", "test"):
            raise ValueError("Invalid split")
    groups = {}
    for item in jobs:
        previous = groups.setdefault(item["group_id"], item["split"])
        if previous != item["split"]:
            raise ValueError("Split group collision")
    if len({j["request"]["plan"]["capture_id"] for j in jobs}) != len(jobs):
        raise ValueError("Duplicate requested capture IDs")
    root.mkdir(parents=True, exist_ok=True)
    state_path = root / "job-state.json"
    input_hash = digest(args.requests)
    if state_path.exists():
        if not args.resume:
            raise ValueError("Existing dataset job requires --resume")
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if state["request_sha256"] != input_hash or state["requested_count"] != len(jobs):
            raise ValueError("Resume request/count mismatch")
        if state["state"] == "succeeded":
            validate_manifest(root)
            print("Dataset already validated")
            return
    else:
        state = {"version": "sf10-dataset-job.v1", "state": "queued",
                 "request_sha256": input_hash, "requested_count": len(jobs),
                 "completed": [], "error": None}
        write_state(state_path, state)
    records = catalog_records()
    cancel = threading.Event()
    def interrupt(_signum, _frame):
        cancel.set()
    signal.signal(signal.SIGINT, interrupt)
    state["state"] = "running"
    state["error"] = None
    write_state(state_path, state)
    started = time.monotonic()
    entries: dict[int, dict] = {}
    reused = 0
    progress = threading.Lock()
    stopped = threading.Event()
    errors: list[BaseException] = []
    finalizing: list[Future] = []

    def cancelled() -> bool:
        return cancel.is_set() or (root / "cancel.requested").exists()

    def record(index: int, metadata: dict, was_reused: bool) -> None:
        nonlocal reused
        with progress:
            entries[index] = metadata
            reused += was_reused
            state["completed"] = [entries[i]["capture_id"] for i in sorted(entries)]
            write_state(state_path, state)
            print(f"{len(entries)}/{len(jobs)} {metadata['capture_id']} "
                  f"{time.monotonic() - started:.1f}s", flush=True)

    def fail(error: BaseException) -> None:
        with progress:
            errors.append(error)
        stopped.set()

    def finalize(pool: ProcessPoolExecutor, index: int, was_reused: bool) -> None:
        # Publication runs in a worker process; this session moves on to the next capture.
        future = pool.submit(finalize_capture, jobs[index], str(root))

        def done(result: Future) -> None:
            if result.cancelled():
                return
            if result.exception() is not None:
                fail(result.exception())
            else:
                record(index, result.result(), was_reused)

        future.add_done_callback(done)
        with progress:
            finalizing.append(future)

    def lane(scheduler: UnitScheduler, pool: ProcessPoolExecutor) -> None:
        session = None if args.single_use else CaptureWorkerSession()
        unit = None
        try:
            while not stopped.is_set():
                unit = scheduler.take(unit)
                if unit is None:
                    return
                for index in unit.indices:
                    if stopped.is_set() or cancelled():
                        stopped.set()
                        return
                    metadata, was_reused = capture_item(jobs[index], root, cancel, session)
                    if metadata is not None:
                        record(index, metadata, was_reused)
                    else:
                        finalize(pool, index, was_reused)
        except BaseException as error:
            fail(error)
        finally:
            if session is not None:
                session.close(force=stopped.is_set())

    pool = None
    try:
        # Create the shared capture root before lanes start: on Windows, resolving a
        # path while another thread creates its parent can briefly disagree.
        ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
        units = plan_units([item["request"] for item in jobs])
        workers = max(1, min(args.workers, len(units)))
        scheduler = UnitScheduler(units)
        pool = ProcessPoolExecutor(max_workers=workers)
        threads = [threading.Thread(target=lane, args=(scheduler, pool), daemon=True)
                   for _ in range(workers)]
        for thread in threads:
            thread.start()
        for thread in threads:
            # Short joins keep the main thread responsive to SIGINT.
            while thread.is_alive():
                thread.join(0.2)
        while True:
            with progress:
                waiting = [f for f in finalizing if not f.done()]
            if not waiting:
                break
            if stopped.is_set():
                for future in waiting:
                    future.cancel()
            wait(waiting, timeout=0.2)
        if errors:
            raise errors[0]
        if len(entries) < len(jobs):
            state["state"] = "cancelled"
            write_state(state_path, state)
            print(f"Cancelled after {len(entries)} captures", flush=True)
            return
        ordered = [entries[i] for i in range(len(jobs))]
        manifest = publish_manifest(root, args.dataset_id, ordered,
                                    [j["request"] for j in jobs], records, executor=pool)
        total_bytes = sum(path.stat().st_size for path in root.rglob("*") if path.is_file())
        seconds = time.monotonic() - started
        metrics = {"count": len(ordered), "reused_captures": reused,
                   "worker_mode": "single-use" if args.single_use else "persistent",
                   "workers": workers, "elapsed_s": seconds,
                   "captures_per_s": len(ordered) / seconds,
                   "new_captures_per_s": (len(ordered) - reused) / seconds,
                   "bytes_total": total_bytes, "bytes_per_capture": total_bytes / len(ordered),
                   "estimate_3000_bytes": total_bytes / len(ordered) * 3000,
                   "splits": manifest["counts"]}
        (root / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
        state["state"] = "succeeded"
        write_state(state_path, state)
        print(json.dumps(metrics), flush=True)
    except Exception as error:
        stopped.set()
        state["state"] = "cancelled" if cancel.is_set() else "failed"
        state["error"] = str(error)
        write_state(state_path, state)
        raise
    finally:
        if pool is not None:
            pool.shutdown(wait=True, cancel_futures=True)


if __name__ == "__main__":
    main()

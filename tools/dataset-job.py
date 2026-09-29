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
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.capture_worker import ARTIFACT_ROOT, run_capture_worker  # noqa: E402
from app.contracts import validate_payload  # noqa: E402
from app.dataset import (artifact, digest, package_capture, publish_manifest,
                         validate_capture_files, validate_manifest)  # noqa: E402


def write_state(path: Path, state: dict) -> None:
    partial = path.with_suffix(".json.partial")
    partial.write_text(json.dumps(state, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    os.replace(partial, path)


def discard_partial(path: Path, root: Path) -> None:
    if path.resolve().parent != root.resolve() or not path.name.endswith(".partial"):
        raise ValueError("Unsafe partial path")
    if path.exists():
        shutil.rmtree(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--requests", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--dataset-id", default="sf10-pilot-v1")
    parser.add_argument("--count", type=int)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--cancel", action="store_true")
    parser.add_argument("--validate", action="store_true")
    args = parser.parse_args()
    root = args.output.resolve()
    if args.validate:
        manifest = validate_manifest(root)
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
    records = {v["asset_id"]: v for v in json.loads(
        (ROOT / "frontend/public/catalog/catalog.json").read_text(encoding="utf-8"))["assets"]}
    cancel = threading.Event()
    def interrupt(_signum, _frame):
        cancel.set()
    signal.signal(signal.SIGINT, interrupt)
    state["state"] = "running"
    state["error"] = None
    write_state(state_path, state)
    started = time.monotonic()
    entries = []
    reused = 0
    try:
        for index, item in enumerate(jobs):
            if cancel.is_set() or (root / "cancel.requested").exists():
                state["state"] = "cancelled"
                write_state(state_path, state)
                print(f"Cancelled after {len(entries)} captures", flush=True)
                return
            request = item["request"]
            capture_id = request["plan"]["capture_id"]
            directory = root / capture_id
            job_id = f"capture-job-{capture_id}"
            capture_dir = ARTIFACT_ROOT / job_id
            if directory.exists():
                reused += 1
                metadata = {"capture_id": capture_id}
                for name in ("observation", "annotations", "truth"):
                    path = directory / f"{name}.json"
                    metadata[name] = {"id": name, "sha256": digest(path),
                                      "byte_length": path.stat().st_size, "media_type": "application/json"}
            else:
                if capture_dir.exists():
                    reused += 1
                    result = json.loads((capture_dir / "result.json").read_text(encoding="utf-8"))
                    if result["capture_id"] != capture_id:
                        raise ValueError("Existing capture has a different identity")
                else:
                    discard_partial(ARTIFACT_ROOT / f"{job_id}.partial", ARTIFACT_ROOT)
                    result = run_capture_worker({**request, "_job_id": job_id}, cancel)
                stage = root / f"{capture_id}.partial"
                discard_partial(stage, root)
                metadata = package_capture(request, result, capture_dir, stage, records)
                validate_capture_files(stage, metadata)
                os.replace(stage, directory)
            metadata.update(group_id=item["group_id"], split=item["split"])
            metadata["files"] = [artifact(path) for path in sorted(directory.iterdir()) if path.is_file()]
            validate_capture_files(directory, metadata)
            entries.append(metadata)
            state["completed"] = [x["capture_id"] for x in entries]
            write_state(state_path, state)
            print(f"{index + 1}/{len(jobs)} {capture_id} {time.monotonic() - started:.1f}s", flush=True)
        manifest = publish_manifest(root, args.dataset_id, entries,
                                    [j["request"] for j in jobs], records)
        total_bytes = sum(path.stat().st_size for path in root.rglob("*") if path.is_file())
        seconds = time.monotonic() - started
        metrics = {"count": len(entries), "reused_captures": reused, "elapsed_s": seconds,
                   "captures_per_s": len(entries) / seconds,
                   "new_captures_per_s": (len(entries) - reused) / seconds,
                   "bytes_total": total_bytes, "bytes_per_capture": total_bytes / len(entries),
                   "estimate_3000_bytes": total_bytes / len(entries) * 3000,
                   "splits": manifest["counts"]}
        (root / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
        state["state"] = "succeeded"
        write_state(state_path, state)
        print(json.dumps(metrics), flush=True)
    except Exception as error:
        state["state"] = "cancelled" if cancel.is_set() else "failed"
        state["error"] = str(error)
        write_state(state_path, state)
        raise


if __name__ == "__main__":
    main()

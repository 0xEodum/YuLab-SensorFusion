"""Audit/prune proven worker mirrors; deduplicate immutable manifest-owned arrays."""
import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.dataset import digest
from app.scaling import prune_worker_mirror, read


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--worker-root", type=Path)
    parser.add_argument("--deduplicate", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    dataset = args.dataset.resolve()
    workspace = (ROOT / "artifacts").resolve()
    if not dataset.is_relative_to(workspace):
        raise ValueError("Maintenance is restricted to workspace artifacts")
    workers = args.worker_root.resolve() if args.worker_root else None
    if workers and not workers.is_relative_to(workspace):
        raise ValueError("Worker root is outside workspace artifacts")
    if args.report.exists():
        raise ValueError("Report already exists")
    before = shutil.disk_usage(dataset).free
    manifest = read(dataset / "manifest.json")
    report = {"dataset": str(dataset), "manifest_sha256": digest(dataset / "manifest.json"),
              "applied": args.apply, "mirror_files": 0, "mirror_logical_bytes": 0,
              "mirror_unshared_bytes": 0, "deduplicated_files": 0, "deduplicated_logical_bytes": 0}
    known = {}
    started = time.monotonic()
    for i, entry in enumerate(manifest["captures"]):
        directory = dataset / entry["capture_id"]
        if directory.resolve().parent != dataset:
            raise ValueError("Unsafe capture path")
        worker = workers / ("capture-job-" + entry["capture_id"]) if workers else None
        if worker and (worker / "result.json").is_file():
            if worker.resolve().parent != workers:
                raise ValueError("Unsafe worker path")
            request = read(worker / "request.json")
            if request["environment"]["thermal_history"] == "continued":
                raise ValueError("Continued thermal worker state must be retained")
            result = prune_worker_mirror(worker, directory, apply=args.apply)
            report["mirror_files"] += result["files"]
            report["mirror_logical_bytes"] += result["bytes"]
            report["mirror_unshared_bytes"] += result["unshared_bytes"]
        if args.deduplicate:
            for item in entry["files"]:
                if not item["id"].endswith("_npy") or item["byte_length"] < 65536:
                    continue
                path = directory / item["id"]
                if path.resolve().parent != directory.resolve() or path.is_symlink():
                    raise ValueError("Unsafe array path")
                key = (item["sha256"], item["byte_length"])
                if key not in known:
                    if digest(path) != key[0] or path.stat().st_size != key[1]:
                        raise ValueError("Corrupt canonical array")
                    known[key] = path
                    continue
                canonical = known[key]
                if os.path.samefile(path, canonical):
                    continue
                if digest(path) != key[0] or path.stat().st_size != key[1]:
                    raise ValueError("Corrupt duplicate array")
                # NTFS has a 1024-link ceiling. Leave ample room for later
                # immutable dataset compositions; start another canonical copy.
                if canonical.stat().st_nlink >= 128:
                    known[key] = path
                    continue
                report["deduplicated_files"] += 1
                report["deduplicated_logical_bytes"] += key[1]
                if args.apply:
                    stage = path.with_name(path.name + ".dedup-partial")
                    if stage.exists():
                        raise ValueError("Dedup staging file already exists")
                    os.link(canonical, stage)
                    try:
                        os.replace(stage, path)
                    finally:
                        if stage.exists(): stage.unlink()
        if i % 100 == 0:
            print(f"storage {i}/{len(manifest['captures'])}", flush=True)
    report.update(elapsed_s=time.monotonic()-started, disk_free_delta_bytes=shutil.disk_usage(dataset).free-before,
                  measurement="Volume free-space delta includes unrelated concurrent writes; logical bytes are not physical savings")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report), flush=True)


if __name__ == "__main__": main()

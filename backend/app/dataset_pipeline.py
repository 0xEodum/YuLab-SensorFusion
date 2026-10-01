"""Per-capture dataset publication, runnable in a worker process.

Packaging and validation are CPU-bound Python (hashing, NPY checks, JSON Schema).
Running them in separate processes keeps them off the coordinator's GIL, so
capture sessions are not serialized behind publication work.
"""
from __future__ import annotations

import json
import os
import shutil
from functools import lru_cache
from pathlib import Path

from .capture_worker import ARTIFACT_ROOT
from .dataset import artifact, digest, package_capture, validate_capture_files

CATALOG = Path(__file__).resolve().parents[2] / "frontend/public/catalog/catalog.json"


@lru_cache(maxsize=1)
def catalog_records() -> dict[str, dict]:
    assets = json.loads(CATALOG.read_text(encoding="utf-8"))["assets"]
    return {record["asset_id"]: record for record in assets}


def discard_partial(path: Path, root: Path) -> None:
    if path.resolve().parent != root.resolve() or not path.name.endswith(".partial"):
        raise ValueError("Unsafe partial path")
    if path.exists():
        shutil.rmtree(path)


def capture_job_id(item: dict) -> str:
    return f"capture-job-{item['request']['plan']['capture_id']}"


def _inventory(item: dict, directory: Path, metadata: dict) -> dict:
    metadata.update(group_id=item["group_id"], split=item["split"])
    metadata["files"] = [artifact(path) for path in sorted(directory.iterdir()) if path.is_file()]
    validate_capture_files(directory, metadata)
    return metadata


def resume_published(item: dict, root: Path) -> dict:
    """Metadata for a capture already published into the dataset directory."""
    capture_id = item["request"]["plan"]["capture_id"]
    directory = root / capture_id
    result = json.loads((directory / "metadata_json").read_text(encoding="utf-8"))
    sequence_id = item["request"]["plan"]["sequence_id"]
    if result["capture_id"] != capture_id or result["sequence_id"] != sequence_id:
        raise ValueError("Resume capture/sequence identity mismatch")
    metadata = {"capture_id": capture_id, "sequence_id": sequence_id}
    for name in ("observation", "annotations", "truth"):
        path = directory / f"{name}.json"
        metadata[name] = {"id": name, "sha256": digest(path),
                          "byte_length": path.stat().st_size, "media_type": "application/json"}
    return _inventory(item, directory, metadata)


def finalize_capture(item: dict, root: str) -> dict:
    """Package a published worker capture, validate it and atomically publish it."""
    dataset_root = Path(root)
    request = item["request"]
    capture_id = request["plan"]["capture_id"]
    capture_dir = ARTIFACT_ROOT / capture_job_id(item)
    result = json.loads((capture_dir / "result.json").read_text(encoding="utf-8"))
    if result["capture_id"] != capture_id:
        raise ValueError("Existing capture has a different identity")
    directory = dataset_root / capture_id
    stage = dataset_root / f"{capture_id}.partial"
    discard_partial(stage, dataset_root)
    metadata = package_capture(request, result, capture_dir, stage, catalog_records())
    validate_capture_files(stage, metadata)
    from .capture_session import _retry_sharing
    _retry_sharing(lambda source: os.replace(source, directory), stage)
    return _inventory(item, directory, metadata)

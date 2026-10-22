"""Immutable static dataset composition and hash-verified storage maintenance."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil

from .dataset import digest, publish_manifest, validate_capture_files
from .dataset_pipeline import catalog_records


def link_or_copy(source, destination):
    try:
        os.link(source, destination)
    except OSError as error:
        if getattr(error, "winerror", None) != 1142:
            raise
        shutil.copyfile(source, destination)


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def physical_world(world):
    value = {k: v for k, v in world.items() if k != "world_id"}
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def select_sources(sources):
    selected, provenance = [], []
    ids, groups, worlds, sequences = set(), {}, {}, {}
    for source in sources:
        root = Path(source["dataset"]).resolve()
        requests = Path(source["requests"]).resolve()
        manifest = read(root / "manifest.json")
        by_id = {r["request"]["plan"]["capture_id"]: r for r in read(requests)["requests"]}
        used = 0
        for entry in manifest["captures"]:
            if entry["split"] not in source["splits"]:
                continue
            capture_id = entry["capture_id"]
            item = by_id[capture_id]
            if (item["split"], item["group_id"]) != (entry["split"], entry["group_id"]):
                raise ValueError("Source split/group mismatch; relabelling is forbidden")
            if capture_id in ids:
                raise ValueError("Duplicate source capture")
            ids.add(capture_id)
            for table, key, label in (
                (groups, entry["group_id"], "group"),
                (worlds, physical_world(item["request"]["world"]), "world"),
                (sequences, entry["sequence_id"], "sequence"),
            ):
                if table.setdefault(key, entry["split"]) != entry["split"]:
                    raise ValueError(f"Source {label} leaks across splits")
            selected.append((root, entry, item))
            used += 1
        if not used:
            raise ValueError("Source selection is empty")
        provenance.append({"dataset": str(root), "manifest_sha256": digest(root / "manifest.json"),
                           "requests_sha256": digest(requests), "splits": source["splits"], "selected": used})
    if not selected:
        raise ValueError("Dataset selection is empty")
    return selected, provenance


def _compose_capture(job):
    root, entry, output = job
    capture_id = entry["capture_id"]
    destination = output / capture_id
    if destination.resolve().parent != output:
        raise ValueError("Unsafe capture identity")
    if destination.exists():
        return
    stage = output / (capture_id + ".partial")
    if stage.exists():
        shutil.rmtree(stage)
    shutil.copytree(root / capture_id, stage, copy_function=link_or_copy)
    validate_capture_files(stage, entry)
    os.replace(stage, destination)


def compose(sources, output, dataset_id, executor=None):
    """Use hardlinks to sealed files. Never rewrite source captures or their splits."""
    output = Path(output).resolve()
    selected, provenance = select_sources(sources)
    output.mkdir(parents=True, exist_ok=True)
    origin = output / "sources.json"
    if origin.exists() and read(origin) != provenance:
        raise ValueError("Composition provenance changed")
    origin.write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
    jobs = [(root, entry, output) for root, entry, item in selected]
    for i, _ in enumerate((executor.map if executor else map)(_compose_capture, jobs)):
        if i % 250 == 0:
            print(f"compose {i}/{len(jobs)}", flush=True)
    entries = [entry for root, entry, item in selected]
    requests = [item["request"] for root, entry, item in selected]
    manifest = publish_manifest(output, dataset_id, entries, requests, catalog_records(), executor)
    (output / "requests.json").write_text(json.dumps({"version": "sf10-requests.v1", "requests": [s[2] for s in selected]}, indent=2) + "\n", encoding="utf-8")
    return manifest


def prune_worker_mirror(worker, survivor, *, apply=False):
    """Remove only declared raw files that survive with verified identical bytes.

    request/result/metadata remain as provenance. Caller must not use this on an
    active worker or on a continued-thermal job whose worker state is required.
    """
    worker, survivor = Path(worker).resolve(), Path(survivor).resolve()
    result, metadata = read(worker / "result.json"), read(survivor / "metadata_json")
    if result["capture_id"] != metadata["capture_id"]:
        raise ValueError("Worker mirror capture mismatch")
    victims = []
    for record in result["artifacts"].values():
        name = record["id"]
        # The result inventories metadata_json, which cannot inventory itself.
        # Keep this small provenance file in the worker as well as result/request.
        if name == "metadata_json":
            continue
        a, b = worker / name, survivor / name
        if a.resolve().parent != worker or b.resolve().parent != survivor or a.is_symlink() or b.is_symlink():
            raise ValueError("Unsafe mirror artifact path")
        if record not in metadata["artifacts"].values():
            raise ValueError("Unmatched mirror artifact metadata")
        if not b.is_file() or b.stat().st_size != record["byte_length"] or digest(b) != record["sha256"]:
            raise ValueError("Surviving mirror hash mismatch")
        if not a.exists():
            continue
        if a.stat().st_size != record["byte_length"] or digest(a) != record["sha256"]:
            raise ValueError("Worker mirror hash mismatch")
        victims.append(a)
    report = {"files": len(victims), "bytes": sum(p.stat().st_size for p in victims),
              "unshared_bytes": sum(p.stat().st_size for p in victims if p.stat().st_nlink == 1), "applied": apply}
    if apply:
        for path in victims:
            path.unlink()
    return report

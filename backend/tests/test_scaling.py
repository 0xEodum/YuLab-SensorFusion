"""Scale-up must retain split provenance and only prune proven worker mirrors."""
import json
from pathlib import Path
import subprocess
import importlib.util
import sys

import pytest

from app.scaling import prune_worker_mirror, select_sources
from app.dataset import digest


def source(tmp_path, name, split, group="scene-1"):
    root = tmp_path / name
    root.mkdir()
    entry = {"capture_id": name, "split": split, "group_id": group, "sequence_id": name}
    (root / "manifest.json").write_text(json.dumps({"captures": [entry]}))
    request = {"group_id": group, "split": split, "request": {
        "world": {"seed": 1}, "plan": {"capture_id": name, "world_sha256": group}}}
    path = tmp_path / (name + "-requests.json")
    path.write_text(json.dumps({"requests": [request]}))
    return {"dataset": str(root), "requests": str(path), "splits": [split]}


def test_select_train_does_not_relabel_historical_holdouts(tmp_path):
    old = source(tmp_path, "old", "test")
    old["splits"] = ["train"]
    with pytest.raises(ValueError, match="empty"):
        select_sources([old])


def test_select_rejects_world_alias_across_splits(tmp_path):
    a = source(tmp_path, "a", "train", "name-a")
    b = source(tmp_path, "b", "test", "name-b")
    # Physical world snapshots, even if their group labels differ.
    with pytest.raises(ValueError, match="world|World"):
        select_sources([a, b])


def test_select_preserves_order_and_source_hashes(tmp_path):
    a = source(tmp_path, "a", "train")
    selected, provenance = select_sources([a])
    assert selected[0][1]["split"] == "train"
    assert provenance[0]["manifest_sha256"] == digest(Path(a["dataset"]) / "manifest.json")


def mirror(tmp_path):
    worker, dataset = tmp_path / "worker", tmp_path / "dataset"
    worker.mkdir(); dataset.mkdir()
    (worker / "rgb_raw_npy").write_bytes(b"immutable pixels")
    (dataset / "rgb_raw_npy").write_bytes(b"immutable pixels")
    meta = {"id": "rgb_raw_npy", "sha256": digest(worker / "rgb_raw_npy"), "byte_length": 16}
    (worker / "result.json").write_text(json.dumps({"capture_id": "x", "artifacts": {"rgb_raw": meta}}))
    (dataset / "metadata_json").write_text(json.dumps({"capture_id": "x", "artifacts": {"rgb_raw": meta}}))
    return worker, dataset


def test_prune_preserves_result_and_requires_verified_survivor(tmp_path):
    worker, dataset = mirror(tmp_path)
    assert prune_worker_mirror(worker, dataset, apply=False)["bytes"] == 16
    assert (worker / "rgb_raw_npy").exists()
    assert prune_worker_mirror(worker, dataset, apply=True)["bytes"] == 16
    assert not (worker / "rgb_raw_npy").exists()
    assert (worker / "result.json").exists()
    assert (dataset / "rgb_raw_npy").read_bytes() == b"immutable pixels"
    assert prune_worker_mirror(worker, dataset, apply=True)["bytes"] == 0


def test_prune_checks_every_file_before_deleting_any(tmp_path):
    worker, dataset = mirror(tmp_path)
    (dataset / "rgb_raw_npy").write_bytes(b"corruption")
    with pytest.raises(ValueError, match="mirror|hash|Hash"):
        prune_worker_mirror(worker, dataset, apply=True)
    assert (worker / "rgb_raw_npy").exists()


def test_prune_rejects_escaped_artifact(tmp_path):
    worker, dataset = mirror(tmp_path)
    value = json.loads((worker / "result.json").read_text())
    value["artifacts"]["rgb_raw"]["id"] = "../outside"
    (worker / "result.json").write_text(json.dumps(value))
    with pytest.raises(ValueError):
        prune_worker_mirror(worker, dataset, apply=True)


def test_prune_keeps_self_referenced_metadata(tmp_path):
    worker, dataset = mirror(tmp_path)
    (worker / "metadata_json").write_bytes(b"provenance")
    result = json.loads((worker / "result.json").read_text())
    result["artifacts"]["metadata"] = {"id": "metadata_json", "sha256": digest(worker / "metadata_json"), "byte_length": 10}
    (worker / "result.json").write_text(json.dumps(result))
    prune_worker_mirror(worker, dataset, apply=True)
    assert (worker / "metadata_json").read_bytes() == b"provenance"


def test_request_generator_explicit_layout_splits(tmp_path):
    root = Path(__file__).resolve().parents[2]
    output = tmp_path / "requests.json"
    result = subprocess.run(["node", "--experimental-strip-types", "tools/generate-sf10-requests.ts",
        "--learning", "--layouts", "3", "--count", "150", "--split-layouts", "1,1,1",
        "--seed-offset", "3700000", "--id-prefix", "sf15", "--output", str(output)],
        cwd=root, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    rows = json.loads(output.read_text())["requests"]
    assert [rows[i]["split"] for i in (0, 50, 100)] == ["train", "validation", "test"]


def test_request_generator_rejects_partial_layout_declaration(tmp_path):
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(["node", "--experimental-strip-types", "tools/generate-sf10-requests.ts",
        "--learning", "--layouts", "3", "--count", "150", "--split-layouts", "1,1,0",
        "--output", str(tmp_path / "invalid.json")], cwd=root, capture_output=True, text=True)
    assert result.returncode != 0


def test_heldout_conditions_change_environment_not_geometry(tmp_path):
    root = Path(__file__).resolve().parents[2]
    captures = []
    for profile in ("standard", "sf15-heldout"):
        output = tmp_path / (profile + ".json")
        result = subprocess.run(["node", "--experimental-strip-types", "tools/generate-sf10-requests.ts",
            "--learning", "--layouts", "1", "--count", "50", "--split-layouts", "0,0,1",
            "--condition-profile", profile, "--output", str(output)], cwd=root, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        captures.append(json.loads(output.read_text())["requests"][0]["request"])
    assert captures[0]["world"] == captures[1]["world"]
    assert captures[0]["rig"] == captures[1]["rig"]
    assert captures[0]["environment"] != captures[1]["environment"]


def test_array_dedup_preserves_bytes_and_leaves_ntfs_link_headroom(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("storage_test", root / "tools/storage-maintenance.py")
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    dataset = tmp_path / "artifacts/data"; dataset.mkdir(parents=True)
    entries = []
    data = b"x" * 65536
    for i in range(140):
        capture = dataset / f"c{i}"; capture.mkdir()
        path = capture / "mask_npy"; path.write_bytes(data)
        entries.append({"capture_id": capture.name, "files": [{"id": path.name, "byte_length": len(data), "sha256": digest(path)}]})
    manifest = dataset / "manifest.json"
    manifest.write_text(json.dumps({"captures": entries}))
    before = digest(manifest)
    report = tmp_path / "report.json"
    monkeypatch.setattr(sys, "argv", ["storage", "--dataset", str(dataset), "--deduplicate", "--apply", "--report", str(report)])
    module.main()
    assert digest(manifest) == before
    assert json.loads(report.read_text())["deduplicated_files"] == 138
    assert all((dataset / e["capture_id"] / "mask_npy").read_bytes() == data for e in entries)
    assert max((dataset / e["capture_id"] / "mask_npy").stat().st_nlink for e in entries) <= 128


def test_composition_dispatches_independent_captures_to_validation_pool(tmp_path, monkeypatch):
    from app import scaling
    a = source(tmp_path, "a", "train")
    capture = Path(a["dataset"]) / "a"; capture.mkdir()
    (capture / "observation.json").write_bytes(b"sealed source")
    monkeypatch.setattr(scaling, "validate_capture_files", lambda *_: None)
    monkeypatch.setattr(scaling, "catalog_records", lambda: {})
    monkeypatch.setattr(scaling, "publish_manifest", lambda *args: {"counts": {"train": 1}})
    calls = []
    class Pool:
        def map(self, function, jobs):
            jobs = list(jobs); calls.append(len(jobs))
            return map(function, jobs)
    out = tmp_path / "composed"
    result = scaling.compose([a], out, "test", Pool())
    assert calls == [1]
    assert result["counts"]["train"] == 1
    assert (out / "a/observation.json").read_bytes() == b"sealed source"
    assert (capture / "observation.json").read_bytes() == b"sealed source"

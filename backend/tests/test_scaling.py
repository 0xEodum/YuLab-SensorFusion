"""Scale-up must retain split provenance and only prune proven worker mirrors."""
import json
from pathlib import Path
import subprocess

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

"""Readback, corruption, and observation-only acceptance for a small SF-10 dataset."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.dataset import validate_manifest  # noqa: E402
from app.observation_input import load_observation_only  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", type=Path)
    args = parser.parse_args()
    source = args.dataset.resolve()
    manifest = validate_manifest(source)
    first = manifest["captures"][0]["capture_id"]
    with tempfile.TemporaryDirectory(prefix="sf10-qa-") as temporary:
        root = Path(temporary)
        clean = root / "observation-only" / first
        clean.mkdir(parents=True)
        original = source / first
        observation = json.loads((original / "observation.json").read_text(encoding="utf-8"))
        shutil.copy2(original / "observation.json", clean / "observation.json")
        for modality in ("rgb", "ir", "lidar"):
            for value in observation[modality]["data"].values():
                if isinstance(value, dict) and "artifact" in value:
                    name = value["artifact"]["id"]
                    shutil.copy2(original / name, clean / name)
        loaded, arrays = load_observation_only(clean.parent, {"capture_id": first})
        assert loaded["capture_id"] == first and len(arrays) == 11
        assert not (clean / "truth.json").exists() and not (clean / "annotations.json").exists()
        duplicate = root / "corrupt"
        shutil.copytree(source, duplicate)
        bad = duplicate / first / "rgb_raw_npy"
        contents = bytearray(bad.read_bytes())
        contents[-1] ^= 1
        bad.write_bytes(contents)
        try:
            validate_manifest(duplicate)
        except ValueError:
            pass
        else:
            raise AssertionError("Corrupt RGB array passed validation")
    print(json.dumps({"validated_captures": len(manifest["captures"]),
        "observation_arrays_without_truth": len(arrays), "corruption_rejected": True}))


if __name__ == "__main__":
    main()

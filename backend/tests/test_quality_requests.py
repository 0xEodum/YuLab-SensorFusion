"""Fresh holdout requests retain capture semantics and independent split groups."""
import json
from pathlib import Path
import subprocess
import pytest

ROOT=Path(__file__).resolve().parents[2]


def test_fresh_holdout_groups_conditions_and_default_request_parity(tmp_path):
    if not (ROOT / "node_modules/three").exists(): pytest.skip("Node dependencies unavailable")
    path=tmp_path/"fresh.json"
    subprocess.run(["node","--experimental-strip-types","tools/generate-sf10-requests.ts","--learning",
                    "--holdout-only","--seed-offset","1000000","--layouts","2","--count","100",
                    "--id-prefix","requesttest","--output",str(path)],cwd=ROOT,check=True,capture_output=True)
    requests=json.loads(path.read_text())["requests"]
    assert len(requests) == 100
    assert {r["split"] for r in requests} == {"test"}
    assert len({r["group_id"] for r in requests}) == 2
    assert {r["request"]["plan"]["seed_channels"]["world"] for r in requests} == {1110000,1117919}
    assert all({s["camera"]["width_px"] for s in r["request"]["rig"]["sensors"] if s["camera"] is not None} == {640} for r in requests)
    legacy=ROOT / "artifacts/sf11/requests.json"
    if legacy.exists():
        subprocess.run(["node","--experimental-strip-types","tools/generate-sf10-requests.ts","--learning",
                        "--output",str(tmp_path/"legacy.json")],cwd=ROOT,check=True,capture_output=True)
        assert (tmp_path/"legacy.json").read_bytes() == legacy.read_bytes()

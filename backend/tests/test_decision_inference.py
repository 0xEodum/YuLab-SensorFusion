import json
from pathlib import Path
import shutil
import pytest
torch=pytest.importorskip("torch")
from learning.decision_inference import DecisionFusionPredictor, observation_features
from app.observation_input import load_observation_only


def fixtures():
    root=Path(__file__).resolve().parents[2]
    source=root / "artifacts/sf11/pilot-3000/sf11-2100"
    checkpoints=[root / f"artifacts/sf-quality/baseline-120/runs/{m}/best.pt" for m in ("rgb","ir","lidar")]
    if not source.exists() or not all(p.exists() for p in checkpoints): pytest.skip("Local quality acceptance fixtures absent")
    return source,checkpoints


def test_live_inference_never_reads_annotations_truth_or_missing_sensor_arrays(tmp_path):
    source,checkpoints=fixtures()
    obs=json.loads((source/"observation.json").read_text()); directory=tmp_path/obs["capture_id"]; directory.mkdir()
    shutil.copy2(source/"observation.json",directory)
    for m in ("rgb","ir","lidar"):
        for ref in obs[m]["data"].values():
            if isinstance(ref,dict) and "artifact" in ref:
                name=ref["artifact"]["id"]; shutil.copy2(source/name,directory/name)
    model=DecisionFusionPredictor(checkpoints)
    first=model.infer_capture(tmp_path,{"capture_id":obs["capture_id"]})
    (directory/"annotations.json").write_text("poison")
    (directory/"truth.json").write_text("poison")
    second=model.infer_capture(tmp_path,{"capture_id":obs["capture_id"]})
    assert first["detections"] == second["detections"]
    with pytest.raises(ValueError): model.infer_capture(tmp_path,{"capture_id":obs["capture_id"],"annotations":[]})
    with pytest.raises(ValueError): DecisionFusionPredictor(checkpoints,expected_hashes=["0"*64]*3)
    _,arrays=load_observation_only(source.parent,{"capture_id":obs["capture_id"]})
    for m in ("rgb","ir","lidar"):
        obs[m]["status"]="unavailable"
        next(s for s in obs["rig"]["sensors"] if s["modality"] == m)["available"]=False
    features,_,available=observation_features(obs,{})
    assert available == [False]*3
    assert not features["point_valid"].any()
    assert not features["rgb"].any() and not features["ir"].any()

import json
import pytest
from learning.quality_acceptance import freeze, sha256, summarize, validate_freeze


def test_holdout_freeze_rejects_changed_checkpoint_protocol_data_and_source(tmp_path):
    paths={name:tmp_path/name for name in ("protocol.json","manifest.json","best.pt","model.py")}
    for name,path in paths.items(): path.write_text(name)
    paths["protocol.json"].write_text(json.dumps({"dataset_sha256":sha256(paths["manifest.json"])}))
    frozen=freeze(tmp_path,paths["protocol.json"],[paths["best.pt"]],["model.py"])
    assert validate_freeze(tmp_path,frozen,paths["protocol.json"],paths["manifest.json"])
    for path in paths.values():
        original=path.read_bytes(); path.write_bytes(b"changed")
        with pytest.raises(ValueError): validate_freeze(tmp_path,frozen,paths["protocol.json"],paths["manifest.json"])
        path.write_bytes(original)


def test_acceptance_uses_sample_sd_and_strongest_control():
    candidate=[{"seed":s,"clean_map":x,"degradation_macro":.4} for s,x in zip((11,12,13),(.52,.53,.54))]
    weak=[{"seed":s,"clean_map":.3,"degradation_macro":.2} for s in (11,12,13)]
    result=summarize({"candidate":candidate,"weak":weak})
    assert result["accepted"]
    assert result["methods"]["candidate"]["clean_map"]["sample_sd"] == pytest.approx(.01)
    strong=[{"seed":s,"clean_map":.6,"degradation_macro":.5} for s in (11,12,13)]
    assert not summarize({"candidate":candidate,"weak":weak,"strong":strong})["accepted"]
    with pytest.raises(ValueError): summarize({"candidate":candidate[:2],"weak":weak[:2]})


def test_fresh_holdout_identity_is_separate_from_training_dataset(tmp_path):
    manifest=tmp_path/"manifest.json"; manifest.write_text("new data")
    protocol=tmp_path/"protocol.json"; protocol.write_text(json.dumps({"dataset_sha256":"f"*64,"evaluation_dataset_sha256":sha256(manifest)}))
    checkpoint=tmp_path/"best.pt"; checkpoint.write_text("weights")
    frozen=freeze(tmp_path,protocol,[checkpoint],[])
    assert frozen["dataset_sha256"] == sha256(manifest)
    assert frozen["protocol"]["dataset_sha256"] == "f"*64
    assert validate_freeze(tmp_path,frozen,protocol,manifest)


def test_seed_cohort_cannot_drop_failed_or_mismatched_replicates():
    values=[{"seed":s,"clean_map":m,"degradation_macro":.5} for s,m in zip((11,12,13,14,15),(.55,.60,.61,.56,.58))]
    control=[{"seed":s,"clean_map":.45,"degradation_macro":.3} for s in (11,12,13,14,15)]
    assert summarize({"candidate":values,"control":control})["seeds"] == [11,12,13,14,15]
    with pytest.raises(ValueError): summarize({"candidate":values[1:],"control":control})

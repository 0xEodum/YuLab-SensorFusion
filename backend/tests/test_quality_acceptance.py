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

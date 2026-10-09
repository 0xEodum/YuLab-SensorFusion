"""Immutable experiment gates and three-seed quality acceptance."""
import hashlib
import json
from pathlib import Path
import numpy as np


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_sha256(path):
    # Text identity is portable across Git's Windows CRLF checkout policy.
    return hashlib.sha256(Path(path).read_bytes().replace(b"\r\n",b"\n")).hexdigest()


def freeze(root, protocol_path, checkpoint_paths, source_paths):
    root=Path(root)
    protocol=json.loads(Path(protocol_path).read_text())
    entries=[]
    for path in checkpoint_paths:
        path=Path(path)
        if not path.is_file(): raise ValueError(f"Checkpoint missing: {path}")
        entries.append({"path":path.resolve().relative_to(root.resolve()).as_posix(),"sha256":sha256(path)})
    return {"version":"quality-freeze.v1","protocol":protocol,
            "protocol_sha256":sha256(protocol_path),"dataset_sha256":protocol.get("evaluation_dataset_sha256",protocol["dataset_sha256"]),
            "checkpoints":entries,"source_hash_normalization":"CRLF to LF",
            "sources":{str(p):source_sha256(root/p) for p in source_paths}}


def validate_freeze(root, frozen, protocol_path, manifest_path):
    root=Path(root).resolve()
    if frozen.get("version") != "quality-freeze.v1" or frozen["protocol_sha256"] != sha256(protocol_path):
        raise ValueError("Selection protocol changed after freeze")
    if frozen["dataset_sha256"] != sha256(manifest_path): raise ValueError("Dataset changed after freeze")
    for item in frozen["checkpoints"]:
        path=(root/item["path"]).resolve()
        if not path.is_relative_to(root) or sha256(path) != item["sha256"]:
            raise ValueError("Checkpoint changed after freeze")
    for path,expected in frozen["sources"].items():
        if source_sha256(root/path) != expected: raise ValueError("Inference source changed after freeze")
    return True


def summarize(reports):
    """Paired seed reports: mapping method -> list of clean/macro results."""
    seeds={tuple(r["seed"] for r in values) for values in reports.values()}
    if len(seeds) != 1 or len(next(iter(seeds))) < 3 or len(set(next(iter(seeds)))) != len(next(iter(seeds))):
        raise ValueError("Require at least three identical independent seed IDs across methods")
    summary={}
    for name,values in reports.items():
        summary[name]={metric:{"mean":float(np.mean([v[metric] for v in values])),
                              "sample_sd":float(np.std([v[metric] for v in values],ddof=1)),
                              "by_seed":[v[metric] for v in values]} for metric in ("clean_map","degradation_macro")}
    candidate=summary["candidate"]
    strongest={metric:max((v[metric]["mean"],name) for name,v in summary.items() if name != "candidate") for metric in ("clean_map","degradation_macro")}
    checks={"clean_above_050":candidate["clean_map"]["mean"] > .50,
            "macro_above_035":candidate["degradation_macro"]["mean"] > .35,
            "clean_sd_below_003":candidate["clean_map"]["sample_sd"] < .03,
            "macro_sd_below_003":candidate["degradation_macro"]["sample_sd"] < .03,
            "clean_beats_strongest_control":candidate["clean_map"]["mean"] > strongest["clean_map"][0],
            "macro_beats_strongest_control":candidate["degradation_macro"]["mean"] > strongest["degradation_macro"][0]}
    paired={}
    for name,values in reports.items():
        if name == "candidate": continue
        paired[name]={metric:{"mean":float(np.mean(d := np.asarray(summary["candidate"][metric]["by_seed"])-np.asarray(summary[name][metric]["by_seed"]))),
                             "sample_sd":float(np.std(d,ddof=1)),"by_seed":d.tolist()} for metric in ("clean_map","degradation_macro")}
    return {"seeds":list(next(iter(seeds))),"methods":summary,"strongest_controls":{k:{"method":v[1],"mean":v[0]} for k,v in strongest.items()},
            "paired_candidate_minus_control":paired,"checks":checks,"accepted":all(checks.values())}

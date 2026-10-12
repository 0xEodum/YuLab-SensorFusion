"""Frozen-checkpoint paired validation/holdout acceptance for decision fusion."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT / "backend"))
spec=importlib.util.spec_from_file_location("quality",ROOT / "tools/quality-pilot.py")
q=importlib.util.module_from_spec(spec); spec.loader.exec_module(q)
import numpy as np
import torch
from app.observation_input import load_observation_only
from learning.data import PROFILE, preprocess_arrays, supervision
from learning.decision_fusion import fuse
from learning.model import Detector
from learning.runtime import GraphInference
from learning.sensor_degradation import CORRUPTIONS, PROFILE as DEGRADATION, degrade
from learning.quality_acceptance import freeze, validate_freeze, summarize

PROTOCOL=ROOT / "docs/evidence/sf-quality/selection-protocol.json"
DATASET=q.config().dataset
VARIANT="initial"
SEEDS=(11,12,13)
SOURCES=["backend/learning/model.py","backend/learning/data.py","backend/learning/evaluate.py",
         "backend/learning/decision_fusion.py","backend/learning/runtime.py","backend/learning/matching.py",
         "backend/learning/decision_inference.py",
         "backend/learning/sensor_degradation.py","backend/learning/quality_acceptance.py",
         "tools/quality-holdout.py","tools/quality-pilot.py"]


def seed_root(seed):
    return ROOT / ("artifacts/sf-quality/baseline-120" if seed == 11 else f"artifacts/sf-quality/baseline-120-seed-{seed}")


def paths():
    result={}
    for seed in SEEDS:
        for m in ("rgb","ir","lidar","fusion"):
            result[(seed,m)]=(ROOT / f"artifacts/sf-quality/swa-seed-{seed}/{m}/best.pt") if VARIANT in ("swa","snapshots") and m != "fusion" else (ROOT / f"artifacts/sf-quality/swa-seed-{seed}/{m}/raw-best.pt" if seed >= 14 else seed_root(seed)/"runs"/m/"best.pt")
        if VARIANT in ("swa","snapshots"):
            for m in ("rgb","ir","lidar"): result[(seed,f"{m}-raw")]=(ROOT / f"artifacts/sf-quality/swa-seed-{seed}/{m}/raw-best.pt") if seed >= 14 else seed_root(seed)/"runs"/m/"best.pt"
            result[(seed,"fusion-swa")]=ROOT / f"artifacts/sf-quality/swa-seed-{seed}/fusion/best.pt"
        result[(seed,"fusion-360")]=ROOT / f"artifacts/sf-quality/fusion-360-seed-{seed}/best.pt"
    return result


def rows(split):
    if split == "test" and DATASET != q.config().dataset:
        entries=json.loads((DATASET / "manifest.json").read_text())["captures"]
        result=[]
        for entry in entries:
            if entry["split"] != "test": raise ValueError("Fresh holdout contains non-test captures")
            obs=json.loads((DATASET / entry["capture_id"] / "observation.json").read_text())
            origin=np.array(obs["rig"]["T_world_from_rig"]).reshape(4,4)[:3,3]
            result.append({"capture_id":entry["capture_id"],"split":"test","group_id":entry["group_id"],"condition":int(entry["capture_id"].rsplit("-",1)[1]) % 10,"origin":origin.tolist()})
        return result
    return [r for r in json.loads((q.config().output / "index.json").read_text())["records"] if r["split"] == split]


def prepare_test(output, frozen):
    validate_freeze(ROOT,frozen,PROTOCOL,DATASET / "manifest.json")
    records=rows("test"); names=["availability-7"]+list(CORRUPTIONS)
    destination=output / "test-cases"
    if all((destination/f"{n}.pt").exists() for n in names): return
    features={n:[] for n in names}
    for i,r in enumerate(records):
        obs,arrays=load_observation_only(DATASET,{"capture_id":r["capture_id"]})
        features["availability-7"].append(preprocess_arrays(obs,arrays)[0])
        for name in CORRUPTIONS:
            changed,values=degrade(obs,arrays,name,r["capture_id"],seed=DEGRADATION["seed"])
            features[name].append(preprocess_arrays(changed,values)[0])
        if i % 100 == 0: print("holdout observation preparation",i,flush=True)
    destination.mkdir(parents=True,exist_ok=True)
    for name,items in features.items():
        torch.save({"dataset_sha256":frozen["dataset_sha256"],"split":"test","capture_ids":[r["capture_id"] for r in records],
                    "preprocessing":PROFILE,"degradation":DEGRADATION,"features":{k:torch.stack([x[k] for x in items]) for k in items[0]}},destination/f"{name}.pt")


def load_test(output, name, frozen, device):
    state=torch.load(output/"test-cases"/f"{name}.pt",weights_only=True,map_location="cpu")
    if state["dataset_sha256"] != frozen["dataset_sha256"] or state["capture_ids"] != [r["capture_id"] for r in rows("test")] or state["preprocessing"] != PROFILE or state["degradation"] != DEGRADATION or state["split"] != "test":
        raise ValueError("Holdout cache provenance mismatch")
    features={k:v.to(device) for k,v in state["features"].items()}
    features["available"]=torch.ones(len(features["rgb"]),3,dtype=torch.bool,device=device)
    return features


def report(predicted, targets, records, device):
    actual=q.pilot.meters(targets)
    matches=q.match_frames(predicted,actual,q.frame_overlaps(predicted,actual,device))
    result=q.evaluate(predicted,actual,matches)
    result["detections"]=sum(len(p["boxes"]) for p in predicted)
    result["conditions"]={}
    for condition in range(10):
        ids=[i for i,r in enumerate(records) if r["condition"] == condition]
        result["conditions"][str(condition)]=q.evaluate([predicted[i] for i in ids],[actual[i] for i in ids],[matches[i] for i in ids])
    return result


def evaluate_split(output, split, frozen):
    validate_freeze(ROOT,frozen,PROTOCOL,DATASET / "manifest.json")
    q.pilot.seed_all(11,fill=False); device=torch.device("cuda"); records=rows(split)
    if split == "test":
        features=load_test(output,"availability-7",frozen,device)
        targets=[supervision(DATASET,r,np.array(r["origin"])) for r in records]
    else: features,targets,_=q.load("validation",device)
    models={}; expected={x["path"]:x["sha256"] for x in frozen["checkpoints"]}
    for key,path in paths().items():
        if path.relative_to(ROOT).as_posix() not in expected: raise ValueError("Unfrozen checkpoint")
        state=torch.load(path,weights_only=True,map_location="cpu"); seed,name=key
        if state["seed"] != seed or state["dataset_sha256"] != frozen["protocol"]["dataset_sha256"] or state["preprocessing"] != PROFILE:
            raise ValueError("Model provenance mismatch")
        budget=360 if name == "fusion-360" else 120
        if state["config"]["epochs"] != budget or state["config"]["lr"] != .001 or state["config"]["batch_size"] != 32:
            raise ValueError("Training budget mismatch")
        modality=name.split("-")[0]
        if VARIANT in ("swa","snapshots") and name in ("rgb","ir","lidar","fusion-swa") and (state.get("averaged_epochs") != 60 or state["config"].get("swa_start") != 61 or not state["config"].get("swa_final")):
            raise ValueError("Averaging policy mismatch")
        if state.get("modality",state["config"].get("modality")) != modality: raise ValueError("Model sensor mismatch")
        model=Detector(modality).to(device).eval(); model.load_state_dict(state["model"]); model.graph_inference=GraphInference(model)
        models[key]=model
    reports={key:{} for key in models}
    for seed in SEEDS: reports[(seed,"candidate")]={}
    def one_case(name, changed, bits=7):
        available=[bool(bits & 1<<m) for m in range(3)]
        for seed in SEEDS:
            predicted={m:q.pilot.infer(model,changed,32) for (s,m),model in models.items() if s == seed}
            for m,values in predicted.items(): reports[(seed,m)][name]=report(values,targets,records,device)
            if VARIANT == "snapshots":
                from learning.decision_fusion import fuse_snapshots
                fused=[fuse_snapshots([[predicted[m+"-raw"][i],predicted[m][i]] for m in ("rgb","ir","lidar")],available) for i in range(len(records))]
                null={"boxes":np.empty((0,7),dtype=np.float32),"classes":np.empty(0,dtype=np.int64),"scores":np.empty(0,dtype=np.float32)}
                joint=[fuse([predicted["fusion"][i],predicted["fusion-swa"][i],null],[True,True,False]) if bits else null for i in range(len(records))]
                reports.setdefault((seed,"fusion-snapshots"),{})[name]=report(joint,targets,records,device)
            else: fused=[fuse([predicted[m][i] for m in ("rgb","ir","lidar")],available) for i in range(len(records))]
            reports[(seed,"candidate")][name]=report(fused,targets,records,device)
            if name == "availability-7":
                q.pilot.write(output / split / f"seed-{seed}-predictions.json",[{"capture_id":r["capture_id"],**{k:v.tolist() for k,v in p.items()}} for r,p in zip(records,fused)])
        print(split,name,"candidate",[round(reports[(s,"candidate")][name]["map_3d"],4) for s in SEEDS],flush=True)
    for bits in range(8): one_case(f"availability-{bits}",q.availability(features,bits),bits)
    if split == "validation":
        for name,changed in q.suite(device): one_case(name,changed)
    else:
        for name in CORRUPTIONS: one_case(name,load_test(output,name,frozen,device))
    cases=[f"availability-{b}" for b in range(1,7)]+list(CORRUPTIONS)
    values={name:[] for _,name in reports}
    for (seed,name),items in reports.items():
        value={"seed":seed,"clean_map":items["availability-7"]["map_3d"],"degradation_macro":float(np.mean([items[c]["map_3d"] for c in cases])),"cases":items,"split":split,"dataset_sha256":q.digest(q.config().dataset / "manifest.json") if split == "validation" else frozen["dataset_sha256"]}
        values[name].append(value); q.pilot.write(output / split / f"{name}-seed-{seed}.json",value)
    for name in values: values[name].sort(key=lambda r:r["seed"])
    result=summarize(values); result.update(split=split,dataset_sha256=frozen["dataset_sha256"],macro_cases=cases)
    q.pilot.write(output / split / "summary.json",result)
    print(json.dumps(result),flush=True)


def main():
    global PROTOCOL,DATASET,VARIANT,SEEDS
    p=argparse.ArgumentParser(); p.add_argument("stage",choices=("freeze","prepare","evaluate")); p.add_argument("--split",choices=("validation","test"),default="test")
    p.add_argument("--output",type=Path,default=ROOT / "artifacts/sf-quality/acceptance")
    p.add_argument("--protocol",type=Path,default=PROTOCOL)
    p.add_argument("--dataset",type=Path,default=DATASET)
    p.add_argument("--variant",choices=("initial","swa","snapshots"),default="initial")
    p.add_argument("--seeds",nargs="+",type=int,default=[11,12,13])
    a=p.parse_args(); a.output.mkdir(parents=True,exist_ok=True)
    PROTOCOL=a.protocol.resolve(); DATASET=a.dataset.resolve(); VARIANT=a.variant
    SEEDS=tuple(a.seeds)
    declared=json.loads(PROTOCOL.read_text()).get("all_seeds",[11,12,13])
    if list(SEEDS) != declared: raise ValueError("Seed cohort does not match frozen protocol")
    path=a.output / "freeze.json"
    if a.stage == "freeze":
        if path.exists(): raise ValueError("Freeze exists; use a separate acceptance directory")
        q.pilot.write(path,freeze(ROOT,PROTOCOL,list(paths().values()),SOURCES)); print("checkpoint and source hashes frozen",flush=True)
    else:
        frozen=json.loads(path.read_text())
        if a.stage == "prepare": prepare_test(a.output,frozen)
        else: evaluate_split(a.output,a.split,frozen)


if __name__ == "__main__": main()

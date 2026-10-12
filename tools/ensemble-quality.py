"""Three disjoint initialization ensembles, frozen before fresh holdout access."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"backend"))
spec=importlib.util.spec_from_file_location("holdout",ROOT/"tools/quality-holdout.py")
h=importlib.util.module_from_spec(spec); spec.loader.exec_module(h)
q=h.q
import numpy as np
import torch
from learning.decision_fusion import fuse, initialization_experts
from learning.model import Detector
from learning.runtime import GraphInference
from learning.quality_acceptance import freeze, validate_freeze, summarize
from learning.sensor_degradation import CORRUPTIONS

GROUPS=((11,12,13),(14,15,16),(17,18,19))
METHODS=("candidate","rgb","ir","lidar","rgb-raw","ir-raw","lidar-raw","rgb-swa","ir-swa","lidar-swa","fusion","fusion-360","fusion-swa","fusion-snapshots")


def evaluate(output,split,frozen):
    validate_freeze(ROOT,frozen,h.PROTOCOL,h.DATASET/"manifest.json")
    q.pilot.seed_all(11,fill=False); device=torch.device("cuda"); records=h.rows(split)
    if split == "test":
        features=h.load_test(output,"availability-7",frozen,device)
        targets=[h.supervision(h.DATASET,r,np.array(r["origin"])) for r in records]
    else: features,targets,_=q.load("validation",device)
    models={}
    for (seed,name),path in h.paths().items():
        saved=torch.load(path,weights_only=True,map_location="cpu"); cfg=saved["config"]
        if saved["seed"] != seed or saved["dataset_sha256"] != frozen["protocol"]["dataset_sha256"] or saved["preprocessing"] != q.PROFILE:
            raise ValueError("Model provenance mismatch")
        if cfg["epochs"] != (360 if name == "fusion-360" else 120) or cfg["lr"] != .001 or cfg["batch_size"] != 32:
            raise ValueError("Training budget mismatch")
        if name in ("rgb","ir","lidar","fusion-swa") and (saved.get("averaged_epochs") != 60 or cfg.get("swa_start") != 61 or not cfg.get("swa_final")):
            raise ValueError("Averaging policy mismatch")
        modality=name.split("-")[0]
        if saved.get("modality",cfg.get("modality")) != modality: raise ValueError("Sensor mismatch")
        model=Detector(modality).to(device).eval(); model.load_state_dict(saved["model"]); model.graph_inference=GraphInference(model)
        models[(seed,name)]=model
    reports={(group[0],method):{} for group in GROUPS for method in METHODS}
    null={"boxes":np.empty((0,7),dtype=np.float32),"classes":np.empty(0,dtype=np.int64),"scores":np.empty(0,dtype=np.float32)}
    def case(name,changed,bits=7):
        available=[bool(bits & 1<<m) for m in range(3)]
        predicted={key:q.pilot.infer(model,changed,32) for key,model in models.items()}
        for group in GROUPS:
            assembled={method:[] for method in METHODS}
            for i in range(len(records)):
                runs=[[[predicted[(s,m+"-raw")][i],predicted[(s,m)][i]] for m in ("rgb","ir","lidar")] for s in group]
                experts=initialization_experts(runs,[True]*3)
                assembled["candidate"].append(fuse(experts,available))
                for m,expert in zip(("rgb","ir","lidar"),experts):
                    assembled[m].append(expert)
                    assembled[m+"-raw"].append(fuse([predicted[(s,m+"-raw")][i] for s in group],[True]*3))
                    assembled[m+"-swa"].append(fuse([predicted[(s,m)][i] for s in group],[True]*3))
                for m in ("fusion","fusion-360","fusion-swa"):
                    assembled[m].append(fuse([predicted[(s,m)][i] for s in group],[True]*3))
                joint=[fuse([predicted[(s,"fusion")][i],predicted[(s,"fusion-swa")][i],null],[True,True,False]) for s in group]
                assembled["fusion-snapshots"].append(fuse(joint,[True]*3) if bits else null)
            for method,values in assembled.items(): reports[(group[0],method)][name]=h.report(values,targets,records,device)
            if name == "availability-7":
                q.pilot.write(output/split/f"seed-{group[0]}-predictions.json",[{"capture_id":r["capture_id"],**{k:v.tolist() for k,v in p.items()}} for r,p in zip(records,assembled["candidate"])])
        print(split,name,[round(reports[(g[0],"candidate")][name]["map_3d"],4) for g in GROUPS],flush=True)
    for bits in range(8): case(f"availability-{bits}",q.availability(features,bits),bits)
    if split == "validation":
        for name,changed in q.suite(device): case(name,changed)
    else:
        for name in CORRUPTIONS: case(name,h.load_test(output,name,frozen,device))
    included=[f"availability-{b}" for b in range(1,7)]+list(CORRUPTIONS); values={m:[] for m in METHODS}
    for group in GROUPS:
        for method in METHODS:
            cases=reports[(group[0],method)]
            value={"seed":group[0],"member_seeds":list(group),"clean_map":cases["availability-7"]["map_3d"],
                   "degradation_macro":float(np.mean([cases[n]["map_3d"] for n in included])),"cases":cases,
                   "split":split,"dataset_sha256":q.digest(q.config().dataset/"manifest.json") if split == "validation" else frozen["dataset_sha256"]}
            values[method].append(value); q.pilot.write(output/split/f"{method}-seed-{group[0]}.json",value)
    result=summarize(values); result.update(split=split,initialization_groups=[list(g) for g in GROUPS],macro_cases=included,
                                          dataset_sha256=q.digest(q.config().dataset/"manifest.json") if split == "validation" else frozen["dataset_sha256"])
    q.pilot.write(output/split/"summary.json",result); print(json.dumps(result),flush=True)


def main():
    p=argparse.ArgumentParser(); p.add_argument("stage",choices=("freeze","prepare","evaluate")); p.add_argument("--split",choices=("validation","test"),default="validation")
    p.add_argument("--output",type=Path,default=ROOT/"artifacts/sf-quality/acceptance-ensemble")
    p.add_argument("--protocol",type=Path,default=ROOT/"docs/evidence/sf-quality/ensemble-selection-protocol.json")
    a=p.parse_args(); a.output.mkdir(parents=True,exist_ok=True)
    h.PROTOCOL=a.protocol.resolve(); h.DATASET=ROOT/"artifacts/sf-quality/fresh-holdout/dataset"; h.VARIANT="snapshots"; h.SEEDS=tuple(range(11,20))
    protocol=json.loads(h.PROTOCOL.read_text())
    if protocol["initialization_groups"] != [list(g) for g in GROUPS]: raise ValueError("Initialization groups changed")
    path=a.output/"freeze.json"
    if a.stage == "freeze":
        if path.exists(): raise ValueError("Freeze already exists")
        q.pilot.write(path,freeze(ROOT,h.PROTOCOL,list(h.paths().values()),h.SOURCES+["tools/ensemble-quality.py"]))
    else:
        frozen=json.loads(path.read_text())
        if a.stage == "prepare": h.prepare_test(a.output,frozen)
        else: evaluate(a.output,a.split,frozen)


if __name__ == "__main__": main()

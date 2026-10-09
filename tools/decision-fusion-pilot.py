"""Evaluate static late fusion; prediction caches and validation-only selection."""
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
from learning.decision_fusion import fuse
from learning.runtime import GraphInference
from learning.model import Detector
from learning.robust_query import RobustQuery
from learning.sensor_degradation import CORRUPTIONS
from app.dataset import digest
from learning.data import PROFILE


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--roots",nargs=3,type=Path,required=True,help="RGB, IR and LiDAR checkpoint directories")
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--iou",type=float,default=.1)
    p.add_argument("--weights",nargs=9,type=float,default=[1]*9)
    a=p.parse_args(); a.output.mkdir(parents=True,exist_ok=True)
    q.pilot.seed_all(11,fill=False); device=torch.device("cuda")
    features,targets,rows=q.load("validation",device)
    sha=digest(q.config().dataset / "manifest.json"); models=[]; checkpoints=[]
    for modality,folder in zip(("rgb","ir","lidar"),a.roots):
        path=folder / "best.pt"; saved=torch.load(path,weights_only=True,map_location="cpu")
        if saved["dataset_sha256"] != sha or saved["preprocessing"] != PROFILE: raise ValueError("Checkpoint provenance mismatch")
        cfg=saved["config"]
        if saved.get("profile") == "baseline-v1" or cfg.get("model") == "baseline":
            if saved.get("modality",cfg.get("modality")) != modality: raise ValueError("Checkpoint modality mismatch")
            model=Detector(modality,queries=cfg.get("queries",16),width=cfg["width"])
        else:
            if cfg["modality"] != modality: raise ValueError("Checkpoint modality mismatch")
            model=RobustQuery(modality,width=cfg["width"])
        model=model.to(device).eval(); model.load_state_dict(saved["model"]); model.graph_inference=GraphInference(model)
        models.append(model); checkpoints.append({"path":str(path),"sha256":digest(path),"epoch":saved["epoch"],"seed":saved["seed"]})
    reports={}; timings={}; actual=q.pilot.meters(targets)
    all_cases=[("availability-7",features)]+list(q.suite(device))
    clean_predictions=None
    for name,changed in all_cases:
        before=time.perf_counter()
        predictions=[q.pilot.infer(m,changed,32) for m in models]
        if name == "availability-7": clean_predictions=predictions
        selected=[(name,[True]*3,predictions)]
        if name == "availability-7":
            selected=[(f"availability-{bits}",[bool(bits & 1<<m) for m in range(3)],predictions) for bits in range(8)]
        for case,available,items in selected:
            merged=[fuse([items[m][i] for m in range(3)],available,a.iou,np.array(a.weights).reshape(3,3)) for i in range(len(rows))]
            overlaps=q.frame_overlaps(merged,actual,device)
            reports[case]=q.evaluate(merged,actual,q.match_frames(merged,actual,overlaps))
            reports[case]["detections"]=sum(len(x["boxes"]) for x in merged)
        timings[name]=time.perf_counter()-before
        print(name,reports[name]["map_3d"],flush=True)
    cases=[f"availability-{b}" for b in range(1,7)]+list(CORRUPTIONS)
    result={"clean_map":reports["availability-7"]["map_3d"],"degradation_macro":float(np.mean([reports[n]["map_3d"] for n in cases])),"cases":reports,"macro_cases":cases,"checkpoints":checkpoints,"dataset_sha256":sha,"preprocessing":PROFILE,"split":"validation","fusion":{"iou":a.iou,"weights":a.weights},"timings_s":timings}
    q.pilot.write(a.output / "comparison.json",result)
    print(json.dumps({k:v for k,v in result.items() if k not in ("cases","preprocessing")}),flush=True)


if __name__ == "__main__": main()

"""Run the frozen sensor-expert ensemble without annotations or simulator truth."""
import argparse
import json
from pathlib import Path
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT / "backend"))
import numpy as np
import torch
from learning.decision_inference import DecisionFusionPredictor

p=argparse.ArgumentParser()
p.add_argument("--observations",type=Path,required=True)
p.add_argument("--capture-id",required=True)
selection=p.add_mutually_exclusive_group(required=True)
selection.add_argument("--checkpoints",nargs="+",type=Path,help="Three experts, six raw/averaged snapshots, or three six-snapshot initialization groups")
selection.add_argument("--bundle",type=Path,help="Published model-bundle.json with ordered checkpoint paths and hashes")
p.add_argument("--output",type=Path,required=True)
p.add_argument("--device",default="cpu")
p.add_argument("--repeat",type=int,default=1,help="Include 10 warmup calls when benchmarking more than one repetition")
a=p.parse_args()
if a.repeat < 1: p.error("Repeat must be positive")
torch.set_num_threads(2)
expected=None
if a.bundle:
    bundle=json.loads(a.bundle.read_text())
    a.checkpoints=[ROOT / x["path"] for x in bundle["experts"]]
    expected=[x["sha256"] for x in bundle["experts"]]
started=time.perf_counter(); model=DecisionFusionPredictor(a.checkpoints,a.device,expected); load_s=time.perf_counter()-started
if a.bundle and model.identity["profile"] != bundle["profile"]: raise ValueError("Bundle profile mismatch")
if a.bundle and bundle.get("checkpoint_sha256",model.sha256) != model.sha256: raise ValueError("Bundle identity mismatch")
latencies=[]
for i in range(a.repeat + (10 if a.repeat > 1 else 0)):
    result=model.infer_capture(a.observations,{"capture_id":a.capture_id})
    if a.repeat == 1 or i >= 10: latencies.append(result["latency_ms"])
a.output.parent.mkdir(parents=True,exist_ok=True)
a.output.write_text(json.dumps(result,indent=2,allow_nan=False)+"\n")
runtime={"model_load_s":load_s,"preprocessing_inference_fusion_ms":{"p50":float(np.percentile(latencies,50)),"p95":float(np.percentile(latencies,95))},
         "repetitions":a.repeat,"device":a.device,"identity":model.identity,"checkpoint_sha256":model.sha256}
a.output.with_suffix(".runtime.json").write_text(json.dumps(runtime,indent=2)+"\n")
print(json.dumps(runtime),flush=True)

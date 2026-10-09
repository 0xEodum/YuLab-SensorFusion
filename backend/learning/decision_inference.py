"""Persistent independent-expert inference through the observation-only boundary."""
import hashlib
import json
from pathlib import Path
import time
import numpy as np
import torch
from app.contracts import validate_payload
from app.dataset import digest
from app.observation_input import load_observation_only
from .data import PROFILE, preprocess_arrays
from .decision_fusion import fuse
from .model import Detector, predictions


def observation_features(obs, arrays):
    """Materialize zero-sized missing observations without reading their files."""
    arrays=dict(arrays)
    sensors={s["modality"]:s for s in obs["rig"]["sensors"]}
    available=[obs[m]["status"] == "available" and sensors[m]["available"] for m in ("rgb","ir","lidar")]
    for i,m in enumerate(("rgb","ir")):
        if available[i]: continue
        camera=sensors[m]["camera"]; shape=(camera["height_px"],camera["width_px"])
        arrays[f"{m}.validity_mask"]=np.zeros(shape,dtype=bool)
        arrays["rgb.image" if m == "rgb" else "ir.radiance"]=np.zeros((*shape,3) if m == "rgb" else shape,dtype=np.uint8 if m == "rgb" else np.float32)
    if not available[2]:
        arrays.update({"lidar.xyz":np.empty((0,3),dtype=np.float32),"lidar.validity":np.empty(0,dtype=bool),"lidar.intensity":np.empty(0,dtype=np.float32)})
    features,origin=preprocess_arrays(obs,arrays)
    return features,origin,available


class DecisionFusionPredictor:
    def __init__(self, checkpoints, device="cpu", expected_hashes=None):
        if len(checkpoints) != 3: raise ValueError("Need RGB, IR and LiDAR checkpoints")
        self.device=torch.device(device); self.models=[]; identities=[]; seeds=set(); datasets=set()
        for i,(m,path) in enumerate(zip(("rgb","ir","lidar"),checkpoints)):
            sha=digest(Path(path))
            if expected_hashes is not None and sha != expected_hashes[i]: raise ValueError("Checkpoint hash mismatch")
            saved=torch.load(path,weights_only=True,map_location="cpu")
            if saved["profile"] != "baseline-v1" or saved["modality"] != m or saved["preprocessing"] != PROFILE:
                raise ValueError("Unsupported expert checkpoint")
            cfg=saved["config"]
            if cfg["width"] != 64 or cfg["queries"] != 16: raise ValueError("Unsupported expert architecture")
            model=Detector(m).to(self.device).eval(); model.load_state_dict(saved["model"])
            self.models.append(model); identities.append({"modality":m,"sha256":sha}); seeds.add(saved["seed"]); datasets.add(saved["dataset_sha256"])
        if len(seeds) != 1 or len(datasets) != 1: raise ValueError("Experts must have matched seed and dataset")
        self.seed=next(iter(seeds)); self.identity={"profile":"independent-experts-consensus.v1","experts":identities,"iou":.1,"weights":[1]*9,"preprocessing":PROFILE}
        self.sha256=hashlib.sha256(json.dumps(self.identity,sort_keys=True,separators=(",",":")).encode()).hexdigest()

    @torch.no_grad()
    def infer_capture(self, root, request):
        if not isinstance(request,dict) or set(request) != {"capture_id"}: raise ValueError("Inference accepts only capture_id")
        if self.device.type == "cuda": torch.cuda.synchronize(self.device)
        started=time.perf_counter(); obs,arrays=load_observation_only(Path(root),request)
        features,origin,available=observation_features(obs,arrays)
        inputs={k:v[None].to(self.device) for k,v in features.items()}; experts=[]
        for i,model in enumerate(self.models):
            if available[i]:
                predicted=predictions(model(inputs))[0]; predicted["boxes"][:,:6] *= 200
            else: predicted={"boxes":np.empty((0,7),dtype=np.float32),"classes":np.empty(0,dtype=np.int64),"scores":np.empty(0,dtype=np.float32)}
            experts.append(predicted)
        output=fuse(experts,available)
        if self.device.type == "cuda": torch.cuda.synchronize(self.device)
        latency=(time.perf_counter()-started)*1000; detections=[]
        for i,(box,cls,score) in enumerate(zip(output["boxes"],output["classes"],output["scores"])):
            yaw=float(box[6])
            detections.append({"prediction_id":f"prediction-{i}","class_id":int(cls)+8,"score":float(score),
                               "box_3d":{"frame":"east-up-south","center_m":(box[:3]+origin).tolist(),"extent_m":box[3:6].tolist(),
                                         "quaternion_xyzw":[0,float(np.sin(yaw/2)),0,float(np.cos(yaw/2))]},
                               "observation_supported":True,"position_variance_m2":None,"routing":None})
        result={"schema_version":"lab.v1","kind":"PredictionBundle","capture_id":request["capture_id"],
                "checkpoint_id":f"decision-fusion-seed-{self.seed}","checkpoint_sha256":self.sha256,"latency_ms":latency,
                "detections":detections,"state":None}
        validate_payload("PredictionBundle",result)
        return result

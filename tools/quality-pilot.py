"""Controlled train/validation experiments for the quality goal; no test access."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time

os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
import numpy as np
import torch
from app.dataset import digest
from learning.data import PROFILE
from learning.model import Detector, detection_loss, pack_targets, target_batch, predictions
from learning.robust_query import RobustQuery, scale_balanced_loss
from learning.runtime import GraphTrainer, GraphInference
from learning.matching import frame_overlaps
from learning.evaluate import evaluate, match_frames
from learning.sensor_degradation import CORRUPTIONS, PROFILE as DEGRADATION

spec = importlib.util.spec_from_file_location("pilot", ROOT / "tools/learning-pilot.py")
pilot = importlib.util.module_from_spec(spec); spec.loader.exec_module(pilot)


def config():
    return argparse.Namespace(dataset=ROOT / "artifacts/sf11/pilot-3000", output=ROOT / "artifacts/sf11/learning")


def load(split, device):
    if split not in ("train", "validation"):
        raise ValueError("Exploration never reads test")
    features, targets, rows = pilot.load_split(config(), split, device)
    features["available"] = torch.ones(len(rows), 3, dtype=torch.bool, device=device)
    return features, targets, rows


def suite(device):
    cfg = config()
    sha = digest(cfg.dataset / "manifest.json")
    rows = [r for r in json.loads((cfg.output / "index.json").read_text())["records"] if r["split"] == "validation"]
    for name in CORRUPTIONS:
        compact = ROOT / f"artifacts/sf-quality/cases/{name}.pt"
        if not compact.exists():
            state = torch.load(ROOT / f"artifacts/sf12/comparison-cache/{name}.pt", weights_only=True, map_location="cpu")
            if state["dataset_sha256"] != sha or state["capture_ids"] != [r["capture_id"] for r in rows] or state["preprocessing"]["baseline"] != PROFILE or state["degradation"] != DEGRADATION:
                raise ValueError("Degradation cache mismatch")
            compact.parent.mkdir(parents=True, exist_ok=True)
            torch.save({"sha": sha, "capture_ids": state["capture_ids"], "preprocessing": PROFILE, "degradation": DEGRADATION, "features": state["baseline"]}, compact)
        state = torch.load(compact, weights_only=True, map_location="cpu")
        if state["sha"] != sha or state["capture_ids"] != [r["capture_id"] for r in rows] or state["preprocessing"] != PROFILE or state["degradation"] != DEGRADATION:
            raise ValueError("Compact degradation cache mismatch")
        features = {k: v.to(device) for k, v in state["features"].items()}
        features["available"] = torch.ones(len(rows), 3, dtype=torch.bool, device=device)
        yield name, features


def availability(features, bits):
    result = dict(features)
    result["available"] = features["available"] & torch.tensor([bool(bits & 1 << m) for m in range(3)], device=features["available"].device)
    for m, name in enumerate(("rgb", "ir", "lidar")):
        if not bits & (1 << m):
            result[name] = torch.zeros_like(features[name])
            if name == "lidar": result["point_valid"] = torch.zeros_like(features["point_valid"])
    return result


def score(model, features, targets, size):
    predicted = pilot.infer(model, features, size)
    actual = pilot.meters(targets)
    overlaps = frame_overlaps(predicted, actual, device=features["calibration"].device)
    report = evaluate(predicted, actual, match_frames(predicted, actual, overlaps))
    report["detections"] = sum(len(p["boxes"]) for p in predicted)
    return report


def compare(model, features, targets, size):
    # The graph inference object caches inputs; it copies availability each call.
    reports = {f"availability-{bits}": score(model, availability(features, bits), targets, size) for bits in range(8)}
    for name, changed in suite(features["calibration"].device):
        reports[name] = score(model, changed, targets, size)
    cases = [f"availability-{b}" for b in range(1, 7)] + list(CORRUPTIONS)
    return {"clean_map": reports["availability-7"]["map_3d"], "degradation_macro": float(np.mean([reports[n]["map_3d"] for n in cases])), "macro_cases": cases, "cases": reports}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("stage", choices=("train", "evaluate", "profile"))
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--model", choices=("baseline", "robust"), default="robust")
    p.add_argument("--loss", choices=("baseline", "balanced"), default="balanced")
    p.add_argument("--modality", default="fusion", choices=("fusion", "rgb", "ir", "lidar"))
    p.add_argument("--augment", action="store_true")
    p.add_argument("--full-probability", type=float, default=.5)
    p.add_argument("--corruption-probability", type=float, default=.15)
    p.add_argument("--seed", type=int, default=11)
    p.add_argument("--epochs", type=int, default=120)
    p.add_argument("--lr", type=float, default=.001)
    p.add_argument("--width", type=int, default=64)
    p.add_argument("--batch-size", type=int, default=32)
    p.add_argument("--execution", choices=("eager", "graph"), default="graph")
    p.add_argument("--constant-lr", action="store_true")
    p.add_argument("--eval-every", type=int, default=5)
    p.add_argument("--tiny", action="store_true")
    a = p.parse_args()
    if a.epochs < 1 or a.batch_size < 1 or a.eval_every < 1 or a.lr <= 0: p.error("Positive training budget required")
    if a.stage == "profile": a.epochs = 5
    a.output.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter(); pilot.seed_all(a.seed, fill=False)
    device = torch.device("cuda")
    vf, vt, vr = load("validation", device)
    model = (Detector(a.modality, width=a.width) if a.model == "baseline" else RobustQuery(a.modality, width=a.width, augment=a.augment, full_probability=a.full_probability, corruption_probability=a.corruption_probability)).to(device)
    loss_fn = detection_loss if a.loss == "baseline" else scale_balanced_loss
    if a.stage == "evaluate":
        saved = torch.load(a.output / "best.pt", weights_only=True, map_location="cpu")
        if saved["dataset_sha256"] != digest(config().dataset / "manifest.json") or saved["preprocessing"] != PROFILE:
            raise ValueError("Checkpoint provenance mismatch")
        if any(saved["config"][k] != getattr(a,k) for k in ("model", "width", "modality")):
            raise ValueError("Checkpoint architecture mismatch")
        model.load_state_dict(saved["model"]); model.eval(); model.graph_inference = GraphInference(model)
        report = compare(model, vf, vt, a.batch_size)
        report.update(checkpoint_sha256=digest(a.output / "best.pt"), epoch=saved["epoch"], seed=saved["seed"], dataset_sha256=saved["dataset_sha256"], split="validation")
        pilot.write(a.output / "comparison.json", report)
        print(json.dumps({k:v for k,v in report.items() if k != "cases"}), flush=True); return
    features, targets, rows = load("train", device)
    if a.tiny:
        ids = sorted(set([next(i for i,t in enumerate(targets) if c in t["classes"]) for c in range(3)] + [next(i for i,t in enumerate(targets) if not len(t["boxes"]))]))
        features = pilot.batch(features, ids); targets = [targets[i] for i in ids]
        vf, vt = features, targets
    packed = pack_targets(targets, device)
    opt = torch.optim.AdamW(model.parameters(), lr=a.lr, weight_decay=.0001)
    torch.cuda.synchronize(); load_s = time.perf_counter()-started
    setup = time.perf_counter()
    trainer = None
    if a.execution == "graph":
        model.train(); trainer = GraphTrainer(model, features, packed, loss_function=loss_fn)
        for shape in {min(len(targets), a.batch_size), len(targets) % a.batch_size} - {0}: trainer.prepare(shape)
    model.graph_inference = GraphInference(model)
    torch.cuda.synchronize(); setup_s = time.perf_counter()-setup
    torch.cuda.reset_peak_memory_stats()
    best=-1; history=[]; phases={"train_s":0., "validation_s":0., "writes_s":0.}
    training = time.perf_counter()
    for epoch in range(a.epochs):
        lr = a.lr if a.constant_lr else a.lr * (.05 + .95 * (1 + np.cos(np.pi * epoch/a.epochs))/2)
        opt.param_groups[0]["lr"] = float(lr)
        model.train(); order = torch.randperm(len(targets)).tolist(); ids_device=torch.tensor(order,device=device)
        before=time.perf_counter(); losses=[]
        if trainer: trainer.begin_epoch()
        for start in range(0,len(targets),a.batch_size):
            ids=order[start:start+a.batch_size]
            if trainer: loss=trainer.step(ids_device[start:start+a.batch_size],opt)
            else:
                opt.zero_grad(set_to_none=True); loss=loss_fn(model(pilot.batch(features,ids)),target_batch(packed,ids),native=True)
                loss.backward(); torch.nn.utils.clip_grad_norm_(model.parameters(),1.); opt.step()
            losses.append(loss.detach().clone())
        loss=float(torch.stack(losses).mean()); phases["train_s"] += time.perf_counter()-before
        if not np.isfinite(loss): raise ValueError("Nonfinite loss")
        if trainer: trainer.check_finite()
        if (epoch+1)%a.eval_every and epoch != a.epochs-1: continue
        before=time.perf_counter(); report=score(model,vf,vt,a.batch_size); phases["validation_s"] += time.perf_counter()-before
        quality=report["map_3d"] or 0
        row={"epoch":epoch+1,"lr":float(lr),"loss":loss,"validation":report}; history.append(row)
        print(f"epoch {epoch+1} loss {loss:.4f} AP {quality:.4f}",flush=True)
        before=time.perf_counter()
        if quality >= best:
            best=quality
            torch.save({"model":model.state_dict(),"config":vars(a) | {"output":str(a.output)},"epoch":epoch+1,"seed":a.seed,"dataset_sha256":digest(config().dataset / "manifest.json"),"preprocessing":PROFILE,"source_revision":subprocess.check_output(["git","rev-parse","HEAD"],text=True).strip()},a.output / "best.pt")
        pilot.write(a.output / "history.json",history); phases["writes_s"] += time.perf_counter()-before
    torch.cuda.synchronize()
    pilot.write(a.output / "runtime.json",{"load_s":load_s,"graph_setup_s":setup_s,"training_wall_s":time.perf_counter()-training,"cli_wall_s":time.perf_counter()-started,"phases":phases,"peak_allocated_bytes":torch.cuda.max_memory_allocated(),"best_map":best,"device":torch.cuda.get_device_name(),"torch":torch.__version__,"config":vars(a)|{"output":str(a.output)},"checkpoint_sha256":digest(a.output / "best.pt")})


if __name__ == "__main__": main()

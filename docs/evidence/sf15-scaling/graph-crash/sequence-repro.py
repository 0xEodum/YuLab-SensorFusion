"""Label-free replay of the sealed-test sequence: clean graphs + reload replay, then rgb-known."""
import sys, gc, importlib.util
from pathlib import Path
import torch
ROOT = Path(sys.argv[1]); sys.path.insert(0, str(ROOT / "backend"))
spec = importlib.util.spec_from_file_location("se", ROOT / "tools/scale-ensemble.py")
ARGS = list(sys.argv); se = importlib.util.module_from_spec(spec); sys.argv = [sys.argv[0]]; spec.loader.exec_module(se)
from learning.model import Detector
from learning.runtime import GraphInference
dev = torch.device("cuda"); se.pilot.seed_all(11, fill=False)
run = ROOT / "artifacts/sf15/runs-10000"
paths = {**{("baseline", *k): p for k, p in se.paths(run, True).items()}, **{("candidate", *k): p for k, p in se.paths(run).items()}}
def model(key):
    saved = torch.load(paths[key], weights_only=True, map_location="cpu")
    m = Detector(key[2]).to(dev).eval(); m.load_state_dict(saved["model"]); m.graph_inference = GraphInference(m); return m
models = {k: model(k) for k in paths}
for case in ("clean", "rgb-known", "rgb-ood", "ir-known"):
    path = ROOT / f"artifacts/sf15/train-10000-eval-cache-test/{case}.pt"
    if not path.exists(): break
    feat = {k: v.to(dev) for k, v in torch.load(path, weights_only=True, map_location="cpu")["features"].items()}
    pred = {}
    for k, m in models.items():
        if case != "clean": print("try", k, flush=True)
        pred[k] = se.pilot.infer(m, feat, 32); torch.cuda.synchronize()
    torch.cuda.synchronize(); print("infer ok", case, flush=True)
    if case == "clean" and "--reload" in ARGS:
        for k in models:
            r = model(k); se.pilot.infer(r, feat, 32); del r; gc.collect()
        torch.cuda.synchronize(); print("reload ok", flush=True)
        if "--recapture" in ARGS:
            for m in models.values(): m.graph_inference = GraphInference(m)
            gc.collect()
    del feat, pred

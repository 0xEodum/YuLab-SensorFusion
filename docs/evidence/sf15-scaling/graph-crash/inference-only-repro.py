"""Inference-only crash reproduction on the cached sealed-test features (no labels, no metrics)."""
import sys, importlib.util
from pathlib import Path
import torch
ROOT = Path(sys.argv[1]); case = sys.argv[2]; mode = sys.argv[3]
sys.path.insert(0, str(ROOT / "backend"))
spec = importlib.util.spec_from_file_location("se", ROOT / "tools/scale-ensemble.py")
se = importlib.util.module_from_spec(spec); sys.argv = [sys.argv[0]]; spec.loader.exec_module(se)
from learning.model import Detector
from learning.runtime import GraphInference
dev = torch.device("cuda")
feat = torch.load(ROOT / f"artifacts/sf15/train-10000-eval-cache-test/{case}.pt", weights_only=True, map_location="cpu")["features"]
print({k: (tuple(v.shape), str(v.dtype)) for k, v in feat.items()}, flush=True)
for k, v in feat.items():
    if v.is_floating_point() and not torch.isfinite(v).all(): print("NONFINITE", k, int((~torch.isfinite(v)).sum()), flush=True)
feat = {k: v.to(dev) for k, v in feat.items()}
run = ROOT / "artifacts/sf15/runs-10000"
for method, mapping in {"baseline": se.paths(run, True), "candidate": se.paths(run)}.items():
    for key, path in mapping.items():
        saved = torch.load(path, weights_only=True, map_location="cpu")
        m = Detector(key[1]).to(dev).eval(); m.load_state_dict(saved["model"])
        if mode == "graph":
            m.graph_inference = GraphInference(m); out = se.pilot.infer(m, feat, 32)
        else:
            with torch.no_grad():
                out = [m({k: v[s:s+32] for k, v in feat.items()}) for s in range(0, len(feat["calibration"]), 32)]
        torch.cuda.synchronize(); print("ok", method, key, flush=True)

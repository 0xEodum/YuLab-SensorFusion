"""Matched SF-11 complete-step/evaluation profiling on frozen train/validation."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys
import subprocess
import time
import copy

os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
import numpy as np
import torch
from learning.model import Detector, detection_loss, pack_targets, target_batch
from learning.runtime import GraphTrainer, GraphInference

spec = importlib.util.spec_from_file_location("pilot", ROOT / "tools/learning-pilot.py")
pilot = importlib.util.module_from_spec(spec); spec.loader.exec_module(pilot)


def sync():
    torch.cuda.synchronize()


def module_from(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--steps", type=int, default=70)
    parser.add_argument("--profile", action="store_true")
    parser.add_argument("--nsight", action="store_true", help="Capture the complete epoch with cudaProfilerStart/Stop")
    parser.add_argument("--variant", choices=["reference", "batched", "selected", "native", "graph"], default="selected")
    parser.add_argument("--reference-revision", default="0c015d76525ed492d6eabbf1f1a1370bd312044d")
    args = parser.parse_args()
    pilot.seed_all(11)
    config = argparse.Namespace(dataset=ROOT / "artifacts/sf11/pilot-3000", output=ROOT / "artifacts/sf11/learning")
    device = torch.device("cuda")
    startup = time.perf_counter()
    features, targets, records = pilot.load_split(config, "train", device)
    sync(); train_load_s = time.perf_counter() - startup
    startup = time.perf_counter()
    vf, vt, vr = pilot.load_split(config, "validation", device)
    sync(); validation_load_s = time.perf_counter() - startup
    reference = ROOT / "artifacts/sf11/reference-source"
    reference.mkdir(parents=True, exist_ok=True)
    for source, name in (("backend/learning/model.py", "model.py"), ("backend/learning/evaluate.py", "evaluate.py"),
                         ("tools/learning-pilot.py", "learning-pilot.py")):
        (reference / name).write_bytes(subprocess.check_output(["git", "show", f"{args.reference_revision}:{source}"]))
    old_model = module_from(reference / "model.py", "reference_model")
    old_eval = module_from(reference / "evaluate.py", "reference_eval")
    old_pilot = module_from(reference / "learning-pilot.py", "reference_pilot")
    old_pilot.Detector = old_model.Detector; old_pilot.predictions = old_model.predictions; old_pilot.evaluate = old_eval.evaluate
    packed_targets = pack_targets(targets, device)
    native = args.variant in ("native", "graph")
    def loss_function(output, target):
        return old_model.detection_loss(output, target) if args.variant == "reference" else detection_loss(output, target, native=native)
    cycle = old_pilot if args.variant in ("reference", "batched") else pilot
    model = Detector("fusion").to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=.001, weight_decay=.0001)
    # AdamW non-capturable step counters belong on CPU. Mapping the entire
    # checkpoint to CUDA introduces one scalar D2H sync per parameter/update.
    checkpoint = torch.load(config.output / "runs/fusion/best.pt", weights_only=True, map_location="cpu")
    model.load_state_dict(checkpoint["model"]); optimizer.load_state_dict(copy.deepcopy(checkpoint["optimizer"]))
    order = torch.randperm(len(targets)).tolist()
    # Isolated value/gradient gate on the same learned predictions and supervision.
    probe_ids = order[:32]
    original = model(pilot.batch(features, probe_ids))
    left = {k: v.detach().clone().requires_grad_() for k,v in original.items()}
    right = {k: v.detach().clone().requires_grad_() for k,v in original.items()}
    old_loss = old_model.detection_loss(left, [targets[i] for i in probe_ids])
    new_loss = detection_loss(right, target_batch(packed_targets, probe_ids), native=native)
    torch.testing.assert_close(new_loss, old_loss, rtol=2e-6, atol=1e-6)
    old_loss.backward(); new_loss.backward()
    gradient_error = max(float((left[k].grad-right[k].grad).abs().max()) for k in left)
    for k in left: torch.testing.assert_close(right[k].grad, left[k].grad, rtol=3e-6, atol=1e-6)
    del original
    # Validation parity is checked before optimizer updates; test remains untouched.
    reference_report, reference_predictions = old_pilot.score(model, vf, vt, vr, 32)
    selected_report, selected_predictions = pilot.score(model, vf, vt, vr, 32)
    if reference_report != selected_report:
        raise ValueError("Evaluation metrics changed")
    if any(not np.array_equal(p[k], q[k]) for p,q in zip(reference_predictions,selected_predictions) for k in p):
        raise ValueError("Observation predictions changed")
    graph_setup_s = 0
    trainer = None
    if args.variant == "graph":
        setup = time.perf_counter()
        model.train()
        trainer = GraphTrainer(model, features, packed_targets)
        trainer.prepare(32); trainer.prepare(len(targets) % 32)
        model.graph_inference = GraphInference(model)
        graph_report, graph_predictions = pilot.score(model, vf, vt, vr, 32)
        if graph_report != reference_report or any(not np.array_equal(p[k], q[k])
            for p,q in zip(reference_predictions, graph_predictions) for k in p):
            raise ValueError("Graph inference changed validation predictions or metrics")
        sync(); graph_setup_s = time.perf_counter() - setup
    device_order = torch.tensor(order, device=device)
    timings = {k: [] for k in ("forward_ms", "loss_matching_ms", "backward_ms", "optimizer_ms", "complete_step_ms")}
    for step in range(args.steps + 10):
        ids = order[(step % 65)*32:(step % 65)*32 + 32]
        if not ids: ids = order[:32]
        sync(); started = time.perf_counter()
        optimizer.zero_grad(set_to_none=True)
        if trainer:
            loss = trainer.step(device_order[(step % 65)*32:(step % 65)*32 + 32], optimizer)
            sync(); finished = time.perf_counter()
            if step >= 10: timings["complete_step_ms"].append((finished-started)*1000)
            continue
        output = model(cycle.batch(features, ids)); sync(); forwarded = time.perf_counter()
        target = [targets[i] for i in ids] if args.variant == "reference" else target_batch(packed_targets, ids)
        loss = loss_function(output, target); sync(); matched = time.perf_counter()
        loss.backward(); sync(); backed = time.perf_counter()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0); optimizer.step(); sync(); finished = time.perf_counter()
        if step >= 10:
            for key, seconds in zip(timings, (forwarded-started, matched-forwarded, backed-matched, finished-backed, finished-started)):
                timings[key].append(seconds * 1000)
    sync(); started = time.perf_counter()
    evaluation_phases = {}
    if cycle is pilot:
        report, predicted = cycle.score(model, vf, vt, vr, 32, timings=evaluation_phases)
    else:
        report, predicted = cycle.score(model, vf, vt, vr, 32)
    sync()
    evaluation_s = time.perf_counter() - started
    if args.profile:
        with torch.profiler.profile(activities=[torch.profiler.ProfilerActivity.CPU, torch.profiler.ProfilerActivity.CUDA]) as prof:
            for start in range(0, 128, 32):
                ids = order[start:start+32]
                optimizer.zero_grad(set_to_none=True)
                if trainer:
                    trainer.step(device_order[start:start+32], optimizer)
                    continue
                target = [targets[i] for i in ids] if args.variant == "reference" else target_batch(packed_targets, ids)
                loss = loss_function(model(cycle.batch(features, ids)), target)
                loss.backward(); torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0); optimizer.step()
        args.output.with_suffix(".profile.txt").write_text(prof.key_averages().table(sort_by="self_cpu_time_total", row_limit=30))
    # Complete epoch timing keeps asynchronous execution and includes validation.
    pilot.seed_all(11); model.load_state_dict(checkpoint["model"]); optimizer.load_state_dict(copy.deepcopy(checkpoint["optimizer"]))
    epoch_order = torch.randperm(len(targets)).tolist()
    epoch_device_order = torch.tensor(epoch_order, device=device)
    model.train(); sync(); epoch_started = time.perf_counter()
    if args.nsight: torch.cuda.profiler.start()
    torch.cuda.nvtx.range_push("complete_train_epoch")
    epoch_losses = []
    if trainer: trainer.begin_epoch()
    for start in range(0, len(epoch_order), 32):
        if trainer:
            loss = trainer.step(epoch_device_order[start:start+32], optimizer)
            epoch_losses.append(loss)
            continue
        ids = epoch_order[start:start+32]; optimizer.zero_grad(set_to_none=True)
        target = [targets[i] for i in ids] if args.variant == "reference" else target_batch(packed_targets, ids)
        loss = loss_function(model(cycle.batch(features, ids)), target)
        if args.variant == "reference" and not torch.isfinite(loss): raise ValueError("Nonfinite loss")
        loss.backward(); torch.nn.utils.clip_grad_norm_(model.parameters(),1.0); optimizer.step()
        epoch_losses.append(float(loss.detach()) if args.variant == "reference" else loss.detach())
    if args.variant != "reference": epoch_losses = torch.stack(epoch_losses).cpu().numpy()
    if not np.isfinite(epoch_losses).all(): raise ValueError("Nonfinite epoch loss")
    if trainer: trainer.check_finite()
    epoch_train_s = time.perf_counter()-epoch_started
    torch.cuda.nvtx.range_pop()
    torch.cuda.nvtx.range_push("validation")
    epoch_report, _ = cycle.score(model, vf, vt, vr, 32); sync()
    torch.cuda.nvtx.range_pop()
    if args.nsight: torch.cuda.profiler.stop()
    epoch_total_s = time.perf_counter()-epoch_started
    value = {"variant": args.variant, "dataset_sha256": pilot.digest(config.dataset / "manifest.json"), "batch_size": 32,
             "reference_revision": args.reference_revision, "checkpoint_sha256": pilot.digest(config.output / "runs/fusion/best.pt"),
             "correctness": {"loss_absolute_error": float(abs(old_loss-new_loss).detach()), "gradient_max_absolute_error": gradient_error,
                             "validation_predictions_exact": True, "validation_metrics_exact": True},
             "startup": {"train_load_s": train_load_s, "validation_load_s": validation_load_s, "graph_setup_s": graph_setup_s},
             "resident_feature_bytes": sum(v.numel()*v.element_size() for v in features.values()) + sum(v.numel()*v.element_size() for v in vf.values()),
             "complete_epoch_train_s": epoch_train_s, "complete_epoch_total_s": epoch_total_s,
             "complete_epoch_loss": float(np.mean(epoch_losses)), "complete_epoch_validation": epoch_report,
             "steps": args.steps, "phase_ms": {k: {"mean": float(np.mean(v)), "p50": float(np.percentile(v,50)),
                                               "p95": float(np.percentile(v,95))} for k,v in timings.items() if v},
             "complete_epoch_estimate_s": np.mean(timings["complete_step_ms"])*66/1000 + evaluation_s,
             "validation_complete_s": evaluation_s, "validation_map": report["map_3d"],
             "evaluation_phases_s": evaluation_phases,
             "peak_allocated_bytes": torch.cuda.max_memory_allocated(), "peak_reserved_bytes": torch.cuda.max_memory_reserved()}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(value, indent=2)+"\n")
    print(json.dumps(value), flush=True)


if __name__ == "__main__": main()

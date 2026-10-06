"""essrf-static-v1 training/validation loop. Train and validation splits only."""
from __future__ import annotations

import json
import os
from pathlib import Path
import random
import subprocess
import time

import numpy as np
import psutil
import torch

from app.dataset import digest
from . import essrf_data, essrf_loss as L
from .essrf_model import ESSRF, SUBSETS
from .evaluate import evaluate, match_frames
from .model import predictions_from_arrays

SPLITS = ("train", "validation")


def write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(partial, path)


def seed_all(seed: int) -> None:
    random.seed(seed); np.random.seed(seed); torch.manual_seed(seed); torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.benchmark = False


def records(args, split: str):
    if split not in SPLITS:
        raise ValueError("SF-12 tooling never reads the sealed test split")
    index = json.loads((args.sf11 / "index.json").read_text(encoding="utf-8"))
    if index["dataset_sha256"] != digest(args.dataset / "manifest.json"):
        raise ValueError("Dataset changed after SF-11 publication")
    return index["dataset_sha256"], [r for r in index["records"] if r["split"] == split]


def load(args, split: str, device):
    dataset_sha, rows = records(args, split)
    cache = torch.load(args.output / f"{split}-observations.pt", weights_only=True, map_location="cpu")
    if cache["dataset_sha256"] != dataset_sha or cache["preprocessing"] != essrf_data.PROFILE:
        raise ValueError("Observation cache provenance mismatch")
    supervision = torch.load(args.output / f"{split}-supervision.pt", weights_only=False)
    if supervision["capture_ids"] != cache["capture_ids"] or cache["capture_ids"] != [r["capture_id"] for r in rows]:
        raise ValueError("Cache order mismatch")
    targets = [{"boxes": t["boxes"], "classes": t["classes"], "ignored": t["ignored"],
                "support": essrf_data.support_targets(t["support_stats"])} for t in supervision["targets"]]
    return {k: v.to(device) for k, v in cache["features"].items()}, targets, rows


def batch(features: dict, ids) -> dict:
    if isinstance(ids, list):
        ids = torch.as_tensor(ids, device=features["rgb"].device, dtype=torch.long)
    return {k: v[ids] for k, v in features.items()}


def meters(targets: list[dict]) -> list[dict]:
    result = []
    for t in targets:
        value = {k: t[k].numpy().copy() for k in ("boxes", "classes", "ignored")}
        value["boxes"][:, :6] *= 200; value["ignored"][:, :6] *= 200
        result.append(value)
    return result


@torch.no_grad()
def infer(model, features, size, available=None, threshold=.05, expert=None):
    """Mixture predictions, or one subset expert's ungated output when expert is set."""
    model.eval(); output, routing = [], []
    total = len(features["rgb"])
    for start in range(0, total, size):
        part = batch(features, torch.arange(start, min(start + size, total), device=features["rgb"].device))
        mask = None if available is None else available.to(part["rgb"].device).expand(len(part["rgb"]), 3)
        choice = None if expert is None else torch.full((len(part["rgb"]),), expert, device=part["rgb"].device)
        out = model(part, available=mask, expert_subsets=choice)
        head = out if expert is None else out["expert"]
        items = predictions_from_arrays(torch.cat((head["boxes"], head["probability"]), -1).cpu().numpy(), threshold)
        for item in items:
            item["boxes"][:, :6] *= 200
        output.extend(items)
        routing.append(torch.cat((out["pi"].mean(1), out["reliability"].mean(1)), -1).cpu())
    routing = torch.cat(routing)
    return output, {"pi_mean": routing[:, :8].mean(0).tolist(), "reliability_mean": routing[:, 8:].mean(0).tolist()}


def score(model, features, targets, rows, size, available=None, expert=None):
    predicted, routing = infer(model, features, size, available, expert=expert)
    actual = meters(targets)
    report = evaluate(predicted, actual, match_frames(predicted, actual))
    report["conditions"] = {}
    for condition in range(10):
        ids = [i for i, r in enumerate(rows) if r["condition"] == condition]
        report["conditions"][str(condition)] = evaluate([predicted[i] for i in ids], [actual[i] for i in ids])
    report["routing"] = routing
    return report, predicted


def _expert_pair(model, features, targets, size):
    predicted, _ = infer(model, features, size, expert=7)
    return predicted, meters(targets)


def phase_weights(epoch: int, args) -> dict:
    """Section 0.3 sequence: subset warm-up, reliability warm-up, then joint optimization."""
    if epoch < args.subset_warmup:
        return {"mix": 0., "sub": 1., "rel": 0.}
    if epoch < args.subset_warmup + args.reliability_warmup:
        return {"mix": 0., "sub": 1., "rel": 1.}
    return {"mix": 1., "sub": args.subset_weight, "rel": 1.}


def tiny_ids(targets) -> list[int]:
    chosen = []
    for cls in range(3):
        first = next(i for i, t in enumerate(targets) if cls in t["classes"].tolist())
        chosen += [first, first + 2]
    chosen.append(next(i for i, t in enumerate(targets) if len(t["boxes"]) == 0))
    return sorted(set(chosen))


def step(model, optimizer, inputs, truth, generator, weights, tiny, counters):
    device = inputs["rgb"].device
    size = len(inputs["rgb"])
    if tiny:
        augmented, regions = L.augment(inputs, generator, p_known=0, p_ood=0)
        available = torch.ones(size, 3, dtype=torch.bool, device=device)
    else:
        augmented, regions = L.augment(inputs, generator)
        available = L.availability_patterns(size, generator, device)
    available = available & inputs["available"]
    subsets = L.sample_expert_subsets(available, generator)
    bits = (available.long() * torch.tensor([1, 2, 4], device=device)).sum(1)
    for name, values in (("subsets", subsets), ("patterns", bits)):
        for value in values.tolist():
            counters[name][str(value)] += 1
    out = model(augmented, available=available, expert_subsets=subsets)
    # All-unavailable frames are supervised as abstention: no matched targets, no boxes.
    counts = truth["counts"] * available.any(1).cpu().numpy()
    mix_loss, matched, parts = L.detection(out, truth, counts, augmented)
    sub_loss, _, sub_parts = L.detection(out["expert"], truth, truth["counts"], augmented,
                                         frame_weight=(subsets > 0).float())
    y, labelled, ood = L.reliability_targets(matched, truth, L.query_regions(out, augmented, regions), available)
    rel_loss, rel_parts = L.evidential(out, y, labelled, ood)
    loss = weights["mix"] * mix_loss + weights["sub"] * sub_loss + weights["rel"] * rel_loss
    optimizer.zero_grad(set_to_none=True)
    loss.backward()
    torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
    optimizer.step()
    return loss.detach(), {**{f"mix_{k}": v for k, v in parts.items()}, **{f"sub_{k}": v for k, v in sub_parts.items()},
                           **rel_parts, "mix": float(mix_loss.detach()), "sub": float(sub_loss.detach()), "evidential": float(rel_loss.detach())}


def save(path, model, optimizer, epoch, args):
    torch.save({"profile": ESSRF.profile, "model": model.state_dict(), "optimizer": optimizer.state_dict(),
                "epoch": epoch, "seed": args.seed,
                "config": {**model.config, **{k: getattr(args, k) for k in
                           ("epochs", "batch_size", "lr", "subset_warmup", "reliability_warmup", "subset_weight")}},
                "weights": L.WEIGHTS, "support": essrf_data.SUPPORT, "preprocessing": essrf_data.PROFILE,
                "dataset_sha256": digest(args.dataset / "manifest.json"),
                "source_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()}, path)


def train(args) -> None:
    seed_all(args.seed)
    device = torch.device(args.device)
    features, targets, rows = load(args, "train", device)
    val_features, val_targets, val_rows = load(args, "validation", device)
    packed = L.pack(targets, device)
    generator = torch.Generator(device=device).manual_seed(args.seed)
    order_ids = tiny_ids(targets) if args.tiny else list(range(len(targets)))
    model = ESSRF(queries=args.queries, width=args.width, samples=args.samples, layers=args.layers,
                  global_context=not args.local_only).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-4)
    folder = args.run_root / ("tiny" if args.tiny else f"seed-{args.seed}")
    folder.mkdir(parents=True, exist_ok=True)
    if device.type == "cuda":
        torch.cuda.reset_peak_memory_stats()
    started = time.perf_counter(); history = []; best = -1.0
    counters = {"subsets": {str(s): 0 for s in SUBSETS}, "patterns": {str(s): 0 for s in SUBSETS}}
    epochs = args.tiny_steps if args.tiny else args.epochs
    for epoch in range(epochs):
        if args.tiny:
            weights = {"mix": 1., "sub": 1., "rel": 1.}
        elif args.clean:
            weights = {"mix": 1., "sub": 0., "rel": 0.}  # control: mixture only, clean full-sensor input
        else:
            weights = phase_weights(epoch, args)
        model.train(); losses = []; sums: dict[str, float] = {}
        order = order_ids if args.tiny else torch.randperm(len(order_ids)).tolist()
        for start in range(0, len(order), args.batch_size):
            ids = order[start:start + args.batch_size]
            loss, parts = step(model, optimizer, batch(features, ids), L.select(packed, ids), generator,
                               weights, args.tiny or args.clean, counters)
            losses.append(loss)
            for key, value in parts.items():
                sums[key] = sums.get(key, 0.0) + value
        epoch_loss = float(torch.stack(losses).mean())
        if not np.isfinite(epoch_loss):
            raise ValueError("Nonfinite loss")
        if args.tiny and epoch % 50 and epoch != epochs - 1:
            continue
        if args.tiny:
            report, _ = score(model, batch(features, order_ids), [targets[i] for i in order_ids],
                              [rows[i] for i in order_ids], args.batch_size)
        else:
            report, _ = score(model, val_features, val_targets, val_rows, args.batch_size)
            # Diagnostic only (not used for selection): the all-modality expert alone.
            report["expert_all_map_3d"] = evaluate(*_expert_pair(model, val_features, val_targets, args.batch_size))["map_3d"]
        steps = len(losses)
        history.append({"epoch": epoch + 1, "loss": epoch_loss, "weights": weights,
                        "parts": {k: v / steps for k, v in sums.items()}, "validation": report})
        write(folder / "history.json", history)
        quality = report["map_3d"] or 0
        print(f"epoch {epoch + 1} loss {epoch_loss:.4f} AP {quality:.4f} expert7 {report.get('expert_all_map_3d') or 0:.4f} pi0 {report['routing']['pi_mean'][0]:.3f} "
              f"r {[round(v, 3) for v in report['routing']['reliability_mean']]}", flush=True)
        # Selection only among epochs that train the evaluated mixture output.
        if (weights["mix"] > 0) and quality >= best:
            best = quality
            save(folder / "best.pt", model, optimizer, epoch + 1, args)
            write(folder / "validation.json", report)
    write(folder / "runtime.json", {
        "elapsed_s": time.perf_counter() - started, "best_validation_ap": best,
        "gpu_peak_allocated_bytes": torch.cuda.max_memory_allocated() if device.type == "cuda" else 0,
        "gpu_peak_reserved_bytes": torch.cuda.max_memory_reserved() if device.type == "cuda" else 0,
        "process_peak_working_set_bytes": getattr(psutil.Process().memory_info(), "peak_wset", None),
        "parameters": sum(p.numel() for p in model.parameters()), "torch": torch.__version__,
        "device": torch.cuda.get_device_name() if device.type == "cuda" else "cpu",
        "expert_subset_counts": counters["subsets"], "availability_pattern_counts": counters["patterns"]})
    if args.tiny and best < .90:
        raise ValueError("Tiny-set overfit acceptance requires mAP >= .90")

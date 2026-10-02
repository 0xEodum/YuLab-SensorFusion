"""SF-11 CLI: audit/cache, tiny overfit, equal-budget baselines, freeze, sealed test."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import time

os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
import numpy as np
import psutil
import torch
from app.dataset import digest
from learning.data import PROFILE, preprocess, supervision
from learning.model import Detector, detection_loss, predictions, pack_targets, target_batch
from learning.evaluate import evaluate, match_frames, NAMES
from learning.runtime import GraphTrainer, GraphInference
from learning.matching import available as native_available


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(partial, path)


def seed_all(seed):
    random.seed(seed); np.random.seed(seed); torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.use_deterministic_algorithms(True)
    torch.backends.cudnn.benchmark = False
    torch.backends.cuda.enable_flash_sdp(False)
    torch.backends.cuda.enable_mem_efficient_sdp(False)
    torch.set_num_threads(2)


def prepare(args):
    manifest = json.loads((args.dataset / "manifest.json").read_text(encoding="utf-8"))
    requests = json.loads(args.requests.read_text(encoding="utf-8"))["requests"]
    by_id = {x["request"]["plan"]["capture_id"]: x for x in requests}
    counts, objects, ranges, visibility, groups, sites = (Counter() for _ in range(6))
    group_splits = {}; geometry_splits = {}; sequences = {}; fingerprints = set()
    records = []
    class_groups = {}
    for entry in manifest["captures"]:
        capture_id, split, group = entry["capture_id"], entry["split"], entry["group_id"]
        req = by_id[capture_id]
        if (req["split"], req["group_id"]) != (split, group):
            raise ValueError("Request split mismatch")
        for table, key in ((group_splits, group), (geometry_splits, req["request"]["plan"]["world_sha256"]),
                           (sequences, entry["sequence_id"])):
            if table.setdefault(key, split) != split:
                raise ValueError("Layout/sequence/weather variant leakage")
        condition = int(capture_id.rsplit("-", 1)[1]) % 10
        directory = args.dataset / capture_id
        obs = json.loads((directory / "observation.json").read_text(encoding="utf-8"))
        fingerprint = tuple(obs[m]["data"][k]["artifact"]["sha256"] for m, k in
                            (("rgb", "image"), ("ir", "radiance"), ("lidar", "xyz")))
        if fingerprint in fingerprints:
            raise ValueError("Duplicate observations")
        fingerprints.add(fingerprint)
        origin = np.array(obs["rig"]["T_world_from_rig"]).reshape(4, 4)[:3, 3]
        target = supervision(args.dataset, entry, origin)
        ann = json.loads((directory / "annotations.json").read_text(encoding="utf-8"))
        counts[f"{split}/condition-{condition}"] += 1
        counts[f"{split}/empty-positive"] += len(target["boxes"]) == 0
        counts[f"{split}/background-only"] += not ann["objects"]
        for obj in ann["objects"]:
            state = "eligible" if obj["eligible"] else obj["ignore_reason"]
            name = NAMES[obj["class_id"] - 8]
            objects[f"{split}/{name}/condition-{condition}/{state}"] += 1
            if obj["eligible"]:
                class_groups.setdefault(f"{split}/{name}/condition-{condition}", set()).add(group)
                distance = np.linalg.norm(np.array(obj["box_3d"]["center_m"]) - origin)
                ranges[f"{split}/{name}/" + ("0-50m" if distance < 50 else "50-100m" if distance < 100 else "100m+")] += 1
                fraction = max(obj[m]["visible_fraction"] or 0 for m in ("rgb", "ir"))
                visibility[f"{split}/{name}/" + ("0-.25" if fraction < .25 else ".25-.75" if fraction < .75 else ".75-1")] += 1
        sites[f"{split}/{group.split('-')[0]}"] += 1
        records.append({"capture_id": capture_id, "split": split, "group_id": group, "condition": condition,
                        "origin": origin.tolist()})
    for split in ("train", "validation", "test"):
        groups[split] = sum(s == split for s in group_splits.values())
    coverage = {"manifest_sha256": digest(args.dataset / "manifest.json"), "request_sha256": digest(args.requests),
                "split_counts": manifest["counts"], "independent_groups": dict(groups), "site_counts": dict(sites),
                "captures": dict(counts), "class_condition_eligibility": dict(objects),
                "range_counts": dict(ranges), "visibility_counts": dict(visibility),
                "class_condition_independent_groups": {k: len(v) for k, v in class_groups.items()},
                "underrepresented_class_conditions": [k for k, v in class_groups.items() if len(v) < 5],
                "layout_sequence_variant_isolation": True, "duplicate_observations": 0,
                "condition_order": ["day-noon", "day-morning", "night-midnight", "fog-.75", "fog-1",
                                    "rain-.7", "snow-.8", "hot-background-.9", "day-evening", "night-21h"]}
    write(args.output / "coverage-before-training.json", coverage)
    write(args.output / "index.json", {"dataset_sha256": coverage["manifest_sha256"], "records": records, "preprocessing": PROFILE})
    # This is only observation preprocessing. Test observations are not loaded here.
    for split in ("train", "validation"):
        cache = args.output / f"{split}-observations.pt"
        if cache.exists():
            continue
        tensors = []
        for i, record in enumerate(r for r in records if r["split"] == split):
            features, _ = preprocess(args.dataset, record["capture_id"])
            tensors.append(features)
            if i % 100 == 0:
                print(f"cache {split} {i}", flush=True)
        torch.save({"dataset_sha256": coverage["manifest_sha256"], "preprocessing": PROFILE,
                    "features": {k: torch.stack([f[k] for f in tensors]) for k in tensors[0]}}, cache)


def load_split(args, split, device):
    state_path = args.dataset / "job-state.json"
    if state_path.exists() and json.loads(state_path.read_text())["state"] != "succeeded":
        raise ValueError("Dataset publication/validation has not succeeded")
    index = json.loads((args.output / "index.json").read_text(encoding="utf-8"))
    if index["dataset_sha256"] != digest(args.dataset / "manifest.json"):
        raise ValueError("Dataset changed after coverage/cache publication")
    records = [r for r in index["records"] if r["split"] == split]
    if split == "test":
        # Test access occurs only after validation-selected targets/configuration freeze.
        freeze = json.loads((args.output / "sf15-targets.json").read_text(encoding="utf-8"))
        if freeze["dataset_sha256"] != index["dataset_sha256"]:
            raise ValueError("Test gate dataset mismatch")
        tensors = [preprocess(args.dataset, r["capture_id"])[0] for r in records]
        features = {k: torch.stack([f[k] for f in tensors]) for k in tensors[0]}
    else:
        cache = torch.load(args.output / f"{split}-observations.pt", weights_only=True, map_location="cpu")
        if cache["dataset_sha256"] != index["dataset_sha256"] or cache["preprocessing"] != PROFILE:
            raise ValueError("Cache provenance mismatch")
        features = cache["features"]
    # Pilot fits in GPU memory; one upload avoids repeated transfer during training.
    features = {k: v.to(device) for k, v in features.items()}
    targets = [supervision(args.dataset, r, np.array(r["origin"])) for r in records]
    return features, targets, records


def batch(features, ids):
    if isinstance(ids, list):
        ids = torch.as_tensor(ids, device=features["calibration"].device, dtype=torch.long)
    return {k: v[ids] for k, v in features.items()}


def meters(targets):
    result = []
    for target in targets:
        value = {k: v.numpy().copy() for k, v in target.items()}
        value["boxes"][:, :6] *= 200; value["ignored"][:, :6] *= 200
        result.append(value)
    return result


@torch.no_grad()
def infer(model, features, size):
    model.eval(); output = []
    if getattr(model, "graph_inference", None) is not None:
        return model.graph_inference.infer(features, size)
    for start in range(0, len(features["calibration"]), size):
        items = predictions(model(batch(features, slice(start, start + size))))
        for item in items:
            item["boxes"][:, :6] *= 200
        output.extend(items)
    return output


def score(model, features, targets, records, size, timings=None):
    started = time.perf_counter()
    predicted, actual = infer(model, features, size), meters(targets)
    inferred = time.perf_counter()
    matches = match_frames(predicted, actual)
    matched = time.perf_counter()
    report = evaluate(predicted, actual, matches)
    report["conditions"] = {}
    for condition in range(10):
        ids = [i for i, r in enumerate(records) if r["condition"] == condition]
        report["conditions"][str(condition)] = evaluate([predicted[i] for i in ids], [actual[i] for i in ids],
                                                      [matches[i] for i in ids])
    report["ignored_objects"] = sum(len(t["ignored"]) for t in targets)
    if timings is not None:
        timings.update(inference_and_readback_s=inferred-started, exact_geometry_matching_s=matched-inferred,
                       metric_reductions_s=time.perf_counter()-matched)
    return report, predicted


def checkpoint_path(args, model):
    return args.output / "runs" / model / "best.pt"


def train(args):
    seed_all(args.seed)
    device = torch.device(args.device)
    features, targets, records = load_split(args, "train", device)
    packed_targets = pack_targets(targets, device)
    val_features, val_targets, val_records = load_split(args, "validation", device)
    execution = args.execution
    if execution == "auto":
        execution = "cuda-graph" if device.type == "cuda" and native_available() else "eager"
    if execution != "eager" and (device.type != "cuda" or not native_available()):
        raise ValueError("CUDA execution requires a GPU and tools/build-learning-cuda.ps1")
    for modality in (["fusion"] if args.tiny else ["rgb", "ir", "lidar", "fusion"]):
        seed_all(args.seed)
        model = Detector(modality).to(device)
        optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=.0001)
        folder = (args.run_root or args.output) / ("tiny" if args.tiny else "runs") / modality
        folder.mkdir(parents=True, exist_ok=True)
        if device.type == "cuda":
            torch.cuda.reset_peak_memory_stats()
        started = time.perf_counter(); best = -1; history = []; tiny_ids = None
        if args.tiny:
            # Diverse train-only frames: a class-positive and empty example, repeat across conditions.
            tiny_ids = []
            for cls in range(3):
                chosen = next(i for i, t in enumerate(targets) if cls in t["classes"].tolist())
                tiny_ids.extend([chosen, chosen + 2])
            tiny_ids.append(next(i for i, t in enumerate(targets) if len(t["boxes"]) == 0))
            tiny_ids = sorted(set(tiny_ids))
        trainer = None
        setup_started = time.perf_counter()
        if execution == "cuda-graph":
            trainer = GraphTrainer(model, features, packed_targets)
            sample_count = len(tiny_ids) if args.tiny else len(targets)
            for shape in {min(sample_count, args.batch_size), sample_count % args.batch_size} - {0}:
                trainer.prepare(shape)
            model.graph_inference = GraphInference(model)
        if device.type == "cuda": torch.cuda.synchronize()
        graph_setup_s = time.perf_counter()-setup_started
        phase_seconds = {"training": 0.0, "validation": 0.0, "artifact_writes": 0.0}
        for epoch in range(args.tiny_steps if args.tiny else args.epochs):
            model.train(); losses = []
            order = tiny_ids if args.tiny else torch.randperm(len(targets)).tolist()
            device_order = torch.as_tensor(order, device=device) if trainer else None
            training_started = time.perf_counter()
            if trainer: trainer.begin_epoch()
            for start in range(0, len(order), args.batch_size):
                if trainer:
                    losses.append(trainer.step(device_order[start:start+args.batch_size], optimizer))
                    continue
                ids = order[start:start + args.batch_size]
                optimizer.zero_grad(set_to_none=True)
                loss = detection_loss(model(batch(features, ids)), target_batch(packed_targets, ids),
                                      native=execution == "cuda-native")
                loss.backward(); torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0); optimizer.step()
                losses.append(loss.detach())
            epoch_loss = float(torch.stack(losses).mean())
            if not np.isfinite(epoch_loss):
                raise ValueError("Nonfinite loss")
            if trainer: trainer.check_finite()
            phase_seconds["training"] += time.perf_counter()-training_started
            if args.tiny and epoch % 50 != 0 and epoch != args.tiny_steps - 1:
                continue
            validation_started = time.perf_counter()
            if args.tiny:
                report, predicted = score(model, batch(features, tiny_ids), [targets[i] for i in tiny_ids],
                                          [records[i] for i in tiny_ids], args.batch_size)
            else:
                report, predicted = score(model, val_features, val_targets, val_records, args.batch_size)
            phase_seconds["validation"] += time.perf_counter()-validation_started
            artifact_started = time.perf_counter()
            row = {"epoch": epoch + 1, "loss": epoch_loss, "validation": report}
            history.append(row); write(folder / "history.json", history)
            quality = report["map_3d"] or 0
            print(f"{modality} epoch {epoch+1} loss {row['loss']:.4f} AP {quality:.4f}", flush=True)
            if quality >= best:
                best = quality
                torch.save({"profile": "baseline-v1", "modality": modality, "model": model.state_dict(),
                            "optimizer": optimizer.state_dict(), "epoch": epoch + 1, "seed": args.seed,
                            "preprocessing": PROFILE, "dataset_sha256": digest(args.dataset / "manifest.json"),
                            "config": {"epochs": args.epochs, "batch_size": args.batch_size, "lr": args.lr,
                                       "queries": 16, "width": 64, "prediction_threshold": .05},
                            "source_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()}, folder / "best.pt")
                write(folder / "validation.json", report)
                write(folder / "validation-predictions.json", [{k: v.tolist() for k, v in p.items()} for p in predicted])
            phase_seconds["artifact_writes"] += time.perf_counter()-artifact_started
        summary = {"elapsed_s": time.perf_counter()-started, "process_rss_bytes": psutil.Process().memory_info().rss,
                   "process_peak_working_set_bytes": getattr(psutil.Process().memory_info(), "peak_wset", None),
                   "gpu_peak_allocated_bytes": torch.cuda.max_memory_allocated() if device.type == "cuda" else 0,
                   "gpu_peak_reserved_bytes": torch.cuda.max_memory_reserved() if device.type == "cuda" else 0,
                   "parameters": sum(p.numel() for p in model.parameters()), "torch": torch.__version__,
                   "device": torch.cuda.get_device_name() if device.type == "cuda" else "cpu",
                   "checkpoint_sha256": digest(folder / "best.pt"), "best_validation_ap": best,
                   "execution": execution, "graph_setup_s": graph_setup_s, "phase_seconds": phase_seconds,
                   "tiny_capture_ids": [records[i]["capture_id"] for i in tiny_ids] if args.tiny else None}
        write(folder / "runtime.json", summary)
        if args.tiny and best < .90:
            raise ValueError("Tiny-set overfit acceptance requires mAP >= .90")
        del model, optimizer


def freeze(args):
    summaries = {m: json.loads((args.output / "runs" / m / "validation.json").read_text())
                 for m in ("rgb", "ir", "lidar", "fusion")}
    # Absolute targets and validation-relative targets are declared before test access.
    write(args.output / "sf15-targets.json", {"version": "sf15-quality-targets.v1",
          "dataset_sha256": digest(args.dataset / "manifest.json"), "selection_split": "validation",
          "class_iou_thresholds": dict(zip(NAMES, (.25, .25, .5))),
          "class_ap_min": {c: min(.95, max(.5, max(s["classes"][c]["ap"] or 0 for s in summaries.values()) + .05))
                           for c in NAMES},
          "condition_map_min": {str(c): min(.95, max(.35, max(s["conditions"][str(c)]["map_3d"] or 0
                                                       for s in summaries.values()) + .05)) for c in range(10)},
          "recall_min_each_class": .7, "matched_center_error_max_m": 5,
          "empty_scene_fp_per_frame_max": .1, "detection_ece_max": .15,
          "latency_p95_ms_max": 500, "training_peak_allocated_gib_max": 18,
          "checkpoint_sha256": {m: digest(checkpoint_path(args, m)) for m in summaries},
          "validation_baselines": summaries})


@torch.no_grad()
def test(args):
    seed_all(args.seed); device = torch.device(args.device)
    features, targets, records = load_split(args, "test", device)
    validation_features, _, _ = load_split(args, "validation", device)
    freeze = json.loads((args.output / "sf15-targets.json").read_text())
    for modality in ("rgb", "ir", "lidar", "fusion"):
        path = checkpoint_path(args, modality)
        if digest(path) != freeze["checkpoint_sha256"][modality]:
            raise ValueError("Checkpoint changed after validation freeze")
        saved = torch.load(path, weights_only=True, map_location=device)
        if saved["preprocessing"] != PROFILE or saved["dataset_sha256"] != freeze["dataset_sha256"]:
            raise ValueError("Checkpoint preprocessing/dataset mismatch")
        model = Detector(modality).to(device); model.load_state_dict(saved["model"]); model.eval()
        reloaded_validation = infer(model, validation_features, args.batch_size)
        original = json.loads((path.parent / "validation-predictions.json").read_text())
        if len(original) != len(reloaded_validation) or any(
            not np.array_equal(p[k], np.asarray(o[k], dtype=p[k].dtype).reshape(p[k].shape))
            for p, o in zip(reloaded_validation, original) for k in p):
            raise ValueError("Checkpoint reload changed saved validation predictions")
        report, predicted = score(model, features, targets, records, args.batch_size)
        report["checkpoint_reload_exact_prediction_parity"] = True
        latencies = []
        for i in range(120):
            if device.type == "cuda": torch.cuda.synchronize()
            started = time.perf_counter()
            model(batch(features, slice(i % len(targets), i % len(targets) + 1)))
            if device.type == "cuda": torch.cuda.synchronize()
            if i >= 20: latencies.append((time.perf_counter() - started) * 1000)
        report["resident_batch_one_latency_ms"] = {"p50": float(np.percentile(latencies, 50)),
                                                   "p95": float(np.percentile(latencies, 95))}
        report["checkpoint_sha256"] = digest(path)
        write(args.output / "runs" / modality / "test.json", report)
        write(args.output / "runs" / modality / "test-predictions.json", [
            {"capture_id": r["capture_id"], **{k: v.tolist() for k, v in p.items()}} for r, p in zip(records, predicted)])
        print(f"sealed test {modality} AP {report['map_3d']}", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["prepare", "tiny", "train", "freeze", "test"])
    parser.add_argument("--dataset", type=Path, default=ROOT / "artifacts/sf11/pilot-3000")
    parser.add_argument("--requests", type=Path, default=ROOT / "artifacts/sf11/requests.json")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/sf11/learning")
    parser.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    parser.add_argument("--seed", type=int, default=11)
    parser.add_argument("--epochs", type=int, default=40)
    parser.add_argument("--tiny-steps", type=int, default=1200)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--lr", type=float, default=.001)
    parser.add_argument("--execution", choices=["auto", "eager", "cuda-native", "cuda-graph"], default="auto")
    parser.add_argument("--run-root", type=Path, help="Separate training artifacts; cache/index stay under --output")
    args = parser.parse_args(); args.tiny = args.stage == "tiny"
    if args.stage == "prepare": seed_all(args.seed); prepare(args)
    elif args.stage in ("train", "tiny"): train(args)
    elif args.stage == "freeze": freeze(args)
    else: test(args)


if __name__ == "__main__":
    main()

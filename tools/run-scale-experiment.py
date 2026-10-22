"""Resumable SF-15 ladder with a 12-hour wall budget and validation-only expansion.

Every subprocess has a durable log and an exact command record. Only a completed
stage is reusable; checkpoints without runtime completion are explicitly rejected.
Test is invoked once after all sources/checkpoints/selection have been frozen.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
import psutil
import torch
import numpy as np
from app.dataset import digest
from app.scaling import read, physical_world
from learning.data import PROFILE, preprocess, supervision
from learning.scaling_acceptance import decide_volume

PYTHON = sys.executable
API_PYTHON = str(ROOT / "backend/.venv/Scripts/python.exe")


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(partial, path)


def prepare(dataset, output):
    """No test supervision is accessed during cache/coverage preparation."""
    sha = digest(dataset / "manifest.json")
    entries = read(dataset / "manifest.json")["captures"]
    records, coverage = [], {}
    torch.set_num_threads(2)
    for split in ("train", "validation"):
        features, class_counts, groups = [], [0, 0, 0], set()
        for i, entry in enumerate(e for e in entries if e["split"] == split):
            x, origin = preprocess(dataset, entry["capture_id"])
            target = supervision(dataset, entry, origin)
            for cls in target["classes"].tolist(): class_counts[cls] += 1
            groups.add(entry["group_id"])
            features.append(x)
            records.append({"capture_id": entry["capture_id"], "split": split, "group_id": entry["group_id"],
                            "origin": origin.tolist(), "condition": int(entry["capture_id"].rsplit("-", 1)[1]) % 10})
            if i % 100 == 0: print(f"cache {split} {i}", flush=True)
        output.mkdir(parents=True, exist_ok=True)
        torch.save({"dataset_sha256": sha, "preprocessing": PROFILE,
                    "features": {k: torch.stack([x[k] for x in features]) for k in features[0]}}, output / (split + "-observations.pt"))
        coverage[split] = {"frames": len(features), "groups": len(groups), "eligible_class_counts": class_counts}
    write(output / "coverage.json", coverage)
    write(output / "index.json", {"dataset_sha256": sha, "records": records, "preprocessing": PROFILE})


def assert_no_historical_holdout_overlap(requests):
    """Physical snapshots and group IDs are checked, including earlier temporal sets."""
    groups, worlds = set(), set()
    for path in [ROOT / "artifacts/sf11/requests.json", ROOT / "artifacts/sf-quality/fresh-holdout/requests.json"]:
        if not path.exists(): raise ValueError(f"Required historical exclusion missing: {path}")
        for item in read(path)["requests"]:
            groups.add(item["group_id"]); worlds.add(physical_world(item["request"]["world"]))
    for folder in (ROOT / "artifacts/sf13-sequences", ROOT / "artifacts/sf14"):
        for path in folder.glob("*spec*.json"):
            data = read(path)
            for item in data.get("sequences", []):
                groups.add(item["group_id"]); worlds.add(physical_world(item["base_capture"]["world"]))
    for item in read(requests)["requests"]:
        if item["group_id"] in groups or physical_world(item["request"]["world"]) in worlds:
            raise ValueError("New SF-15 scenes overlap historical data")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT / "artifacts/sf15")
    parser.add_argument("--hours", type=float, default=12)
    parser.add_argument("--max-train", type=int, choices=(3000, 10000, 30000), default=30000)
    parser.add_argument("--prepare-only", type=Path)
    args = parser.parse_args()
    root = args.root.resolve(); root.mkdir(parents=True, exist_ok=True)
    if args.prepare_only:
        prepare(args.prepare_only, args.prepare_only.parent / (args.prepare_only.name + "-cache")); return
    status_path = root / "experiment-state.json"
    state = read(status_path) if status_path.exists() else {
        "profile": "sf15-experiment.v1", "started_epoch_s": time.time(), "hours": args.hours,
        "source_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(), "stages": {}}
    deadline = state["started_epoch_s"] + state["hours"] * 3600
    if state["hours"] != args.hours: raise ValueError("Cannot change frozen wall budget on resume")
    env = dict(os.environ, PLAYWRIGHT_CHANNEL="msedge", PLAYWRIGHT_GPU="1", CUBLAS_WORKSPACE_CONFIG=":4096:8")

    def run(name, command, *, capture_root=None):
        if state["stages"].get(name, {}).get("exit_code") == 0: return
        remaining = deadline - time.time()
        if remaining < 60: raise TimeoutError("Wall-time budget exhausted")
        log = root / "logs" / (name + ".log"); log.parent.mkdir(exist_ok=True)
        stage_env = dict(env)
        if capture_root: stage_env["YULAB_CAPTURE_ROOT"] = str(capture_root)
        entry = {"command": [str(x) for x in command], "started_epoch_s": time.time(), "log": str(log)}
        state["stages"][name] = entry; state["active_stage"] = name; state["state"] = "running"
        write(status_path, state)
        print("START", name, flush=True)
        with log.open("a", encoding="utf-8") as stream:
            process = subprocess.Popen(entry["command"], cwd=ROOT, env=stage_env, stdout=stream, stderr=subprocess.STDOUT)
            try:
                code = process.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                # Only this task's child tree is stopped; other serving/browser processes are untouched.
                owned = psutil.Process(process.pid)
                for child in owned.children(recursive=True):
                    try: child.terminate()
                    except psutil.NoSuchProcess: pass
                process.terminate(); process.wait(timeout=15)
                entry["exit_code"] = -1; write(status_path, state)
                raise TimeoutError("Wall-time budget exhausted")
        entry.update(exit_code=code, elapsed_s=time.time()-entry["started_epoch_s"]); write(status_path, state)
        if code: raise RuntimeError(f"Stage {name} failed; see {log}")
        print("DONE", name, round(entry["elapsed_s"], 1), flush=True)

    try:
        initial = root / "requests-initial.json"
        if not initial.exists():
            run("generate-initial", ["node", "--experimental-strip-types", "tools/generate-sf10-requests.ts", "--learning",
                "--layouts", "42", "--count", "2100", "--split-layouts", "18,12,12", "--seed-offset", "3700000",
                "--id-prefix", "sf15a", "--output", initial])
        assert_no_historical_holdout_overlap(initial)
        # An already completed initial job is verified and reused, never counted as new throughput.
        if not (root / "initial/manifest.json").exists():
            command = [API_PYTHON, "tools/dataset-job.py", "--requests", initial, "--output", root / "initial",
                       "--dataset-id", "sf15-initial", "--workers", "6"]
            if (root / "initial/job-state.json").exists(): command.append("--resume")
            run("capture-initial", command, capture_root=root / "initial-worker")
        challenge = root / "requests-heldout.json"
        run("generate-heldout", ["node", "--experimental-strip-types", "tools/generate-sf10-requests.ts", "--learning",
            "--layouts", "6", "--count", "300", "--split-layouts", "0,0,6", "--condition-profile", "sf15-heldout",
            "--seed-offset", "9700000", "--id-prefix", "sf15h", "--output", challenge])
        assert_no_historical_holdout_overlap(challenge)
        command = [API_PYTHON, "tools/dataset-job.py", "--requests", challenge, "--output", root / "heldout",
                   "--dataset-id", "sf15-heldout", "--workers", "6"]
        if (root / "heldout/job-state.json").exists(): command.append("--resume")
        run("capture-heldout", command, capture_root=root / "heldout-worker")
        additions = []
        accepted_volume = None
        for volume in (3000, 10000, 30000):
            if volume > args.max_train: break
            if volume != 3000:
                previous = 3000 if volume == 10000 else 10000
                gain = volume - previous
                request_path = root / f"requests-add-{volume}.json"
                run(f"generate-{volume}", ["node", "--experimental-strip-types", "tools/generate-sf10-requests.ts",
                    "--learning", "--layouts", str(gain//50), "--count", str(gain), "--split-layouts", f"{gain//50},0,0",
                    "--seed-offset", str(4700000 if volume == 10000 else 7700000), "--id-prefix", f"sf15b{volume}",
                    "--output", request_path])
                assert_no_historical_holdout_overlap(request_path)
                # Keep >20 GiB free; raw artifacts are hardlinked at publication, not copied.
                if shutil.disk_usage(root).free < gain * 9_000_000 + 20 * 1024**3:
                    state["resource_stop"] = "disk reserve would be exceeded"; break
                if deadline-time.time() < gain/2 + 1800:
                    state["resource_stop"] = "generation estimate plus evaluation reserve exceeds wall budget"; break
                command = [API_PYTHON, "tools/dataset-job.py", "--requests", request_path, "--output", root / f"add-{volume}",
                           "--dataset-id", f"sf15-add-{volume}", "--workers", "6"]
                if (root / f"add-{volume}/job-state.json").exists(): command.append("--resume")
                run(f"capture-{volume}", command, capture_root=root / f"worker-{volume}")
                additions.append({"dataset": str(root / f"add-{volume}"), "requests": str(request_path), "splits": ["train"]})
            dataset, training = root / f"train-{volume}", root / f"runs-{volume}"
            sources = [{"dataset": str(ROOT / "artifacts/sf11/pilot-3000"), "requests": str(ROOT / "artifacts/sf11/requests.json"), "splits": ["train"]},
                       {"dataset": str(root / "initial"), "requests": str(initial), "splits": ["train", "validation", "test"]},
                       {"dataset": str(root / "heldout"), "requests": str(challenge), "splits": ["test"]}, *additions]
            source_path = root / f"sources-{volume}.json"; write(source_path, sources)
            run(f"compose-{volume}", [PYTHON, "tools/scale-ensemble.py", "compose", "--dataset", dataset, "--run", training,
                                     "--output", root / "unused.json", "--sources", source_path])
            cache = root / f"train-{volume}-cache"
            run(f"prepare-{volume}", [PYTHON, __file__, "--prepare-only", dataset])
            for seed in range(11, 20):
                for modality in ("rgb", "ir", "lidar"):
                    output = training / f"seed-{seed}" / modality
                    name = f"train-{volume}-{seed}-{modality}"
                    # Successful stage markers are paired with completed runtime/checkpoint records.
                    if state["stages"].get(name, {}).get("exit_code") == 0 and not (output / "runtime.json").exists():
                        raise ValueError("Completed training marker lost its runtime record")
                    run(name, [PYTHON, "tools/quality-pilot.py", "train", "--output", output,
                        "--dataset", dataset, "--cache", cache, "--model", "baseline", "--loss", "baseline", "--modality", modality,
                        "--seed", str(seed), "--epochs", "120", "--eval-every", "1", "--constant-lr",
                        "--swa-start", "61", "--swa-final", "--save-raw-best"])
            validation = root / f"validation-{volume}.json"
            run(f"validation-{volume}", [PYTHON, "tools/scale-ensemble.py", "evaluate", "--dataset", dataset,
                                         "--run", training, "--output", validation])
            methods = read(validation)["methods"]
            decision = decide_volume(methods["baseline"], methods["candidate"], volume)
            if accepted_volume is not None:
                prior = read(root / f"validation-{accepted_volume}.json")["methods"]["candidate"]
                incremental = decide_volume(prior, methods["candidate"], volume)
                decision["incremental"] = incremental
                decision["expand"] &= incremental["promote"]
                if not incremental["promote"]: decision["promote"] = False
            write(root / f"decision-{volume}.json", decision)
            state["latest_decision"] = decision; write(status_path, state)
            if decision["promote"]: accepted_volume = volume
            if not decision["expand"]: break
        # Retain the smaller historical recipe when scaling gives no validated benefit.
        # The scaled contender is still scored once, alongside the retained baseline.
        tested_volume = accepted_volume or 3000
        dataset, training = root / f"train-{tested_volume}", root / f"runs-{tested_volume}"
        write(root / "selection.json", {"selected": "candidate" if accepted_volume else "baseline",
            "selected_training_samples": accepted_volume or 2100, "scaled_contender_samples": tested_volume,
            "decision": read(root / f"decision-{tested_volume}.json"), "resource_stop": state.get("resource_stop")})
        freeze_path = root / "freeze.json"
        run("freeze", [PYTHON, "tools/scale-ensemble.py", "freeze", "--dataset", dataset, "--run", training,
                        "--output", freeze_path, "--decision", root / "selection.json"])
        run("sealed-test", [PYTHON, "tools/scale-ensemble.py", "evaluate", "--dataset", dataset, "--run", training,
                             "--split", "test", "--freeze", freeze_path, "--output", root / "test-report.json"])
        state.update(state="comparison_complete", completed_epoch_s=time.time(), selected=read(root / "selection.json"))
        write(status_path, state)
    except BaseException as error:
        state.update(state="failed", error=str(error)); write(status_path, state); raise


if __name__ == "__main__": main()

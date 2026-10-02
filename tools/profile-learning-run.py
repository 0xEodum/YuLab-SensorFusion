"""Whole-budget CLI runtime and NVIDIA telemetry, without touching frozen runs."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--execution", choices=["eager", "cuda-native", "cuda-graph", "cuda-graph-body"], required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--epochs", type=int, default=40)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, str(ROOT / "tools/learning-pilot.py"), "train", "--execution", args.execution,
               "--epochs", str(args.epochs), "--run-root", str(args.output)]
    with (args.output / "gpu.csv").open("w") as gpu, (args.output / "train.log").open("w") as log:
        monitor = subprocess.Popen(["nvidia-smi", "--query-gpu=timestamp,utilization.gpu,power.draw,memory.used,clocks.sm",
                                    "--format=csv,noheader,nounits", "-lms", "100"], stdout=gpu, stderr=subprocess.STDOUT)
        started = time.perf_counter()
        try:
            result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
        finally:
            elapsed = time.perf_counter()-started
            monitor.terminate(); monitor.wait(timeout=10)
    runs = {m: json.loads((args.output / "runs" / m / "runtime.json").read_text())
            for m in ("rgb", "ir", "lidar", "fusion")} if result.returncode == 0 else {}
    samples = []
    for row in (args.output / "gpu.csv").read_text().splitlines():
        parts = row.split(",")
        if len(parts) == 5:
            try: samples.append([float(v) for v in parts[1:]])
            except ValueError: pass
    value = {"execution": args.execution, "command": command, "epochs": args.epochs,
             "exit_code": result.returncode, "complete_cli_wall_s": elapsed, "runs": runs,
             "telemetry_samples": len(samples),
             "telemetry_mean": {k: sum(s[i] for s in samples)/len(samples) for i,k in enumerate(
                 ("gpu_util_percent", "power_w", "memory_mib", "sm_clock_mhz"))} if samples else {}}
    (args.output / "summary.json").write_text(json.dumps(value,indent=2)+"\n")
    print(json.dumps(value),flush=True)
    raise SystemExit(result.returncode)


if __name__ == "__main__": main()

"""Export matched run correctness and Nsight interval evidence (CPU-only)."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import sqlite3
import torch

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(path.read_text())


def equal(a, b):
    if isinstance(a, torch.Tensor): return isinstance(b, torch.Tensor) and a.dtype == b.dtype and torch.equal(a,b)
    if isinstance(a, dict): return a.keys() == b.keys() and all(equal(a[k],b[k]) for k in a)
    if isinstance(a, (tuple,list)): return len(a) == len(b) and all(equal(x,y) for x,y in zip(a,b))
    return a == b


def nsight(path):
    connection = sqlite3.connect(path)
    result = {}
    for start,end,name in connection.execute("SELECT start,end,text FROM NVTX_EVENTS WHERE end IS NOT NULL"):
        if name not in ("complete_train_epoch", "validation"): continue
        intervals = connection.execute("SELECT start,end FROM CUPTI_ACTIVITY_KIND_KERNEL WHERE start < ? AND end > ? ORDER BY start", (end,start)).fetchall()
        busy = 0; previous = start; count = 0
        for lo,hi in intervals:
            count += 1
            lo,hi = max(start,lo),min(end,hi)
            busy += max(0,hi-max(lo,previous)); previous = max(previous,hi)
        api = dict(connection.execute("SELECT s.value,COUNT(*) FROM CUPTI_ACTIVITY_KIND_RUNTIME r JOIN StringIds s ON r.nameId=s.id WHERE r.start>=? AND r.start<? GROUP BY s.value", (start,end)))
        result[name] = {"range_s": (end-start)/1e9, "kernel_union_s": busy/1e9,
                        "kernel_active_fraction": busy/(end-start), "kernel_instances": count,
                        "cuda_api_calls": api}
    connection.close()
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--eager",type=Path,required=True)
    parser.add_argument("--accelerated",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--nsight",type=Path)
    args = parser.parse_args()
    eager,fast = read(args.eager/"summary.json"),read(args.accelerated/"summary.json")
    if eager["epochs"] != fast["epochs"] or eager["exit_code"] or fast["exit_code"]:
        raise ValueError("Comparison requires successful equal-budget runs")
    correctness = {}
    for m in ("rgb", "ir", "lidar", "fusion"):
        a,b = args.eager/"runs"/m,args.accelerated/"runs"/m
        old,new = (torch.load(p/"best.pt",weights_only=True,map_location="cpu") for p in (a,b))
        old_history,new_history = read(a/"history.json"),read(b/"history.json")
        correctness[m] = {"all_epoch_histories_exact": old_history == new_history,
                          "history_budget_complete": len(old_history) == len(new_history) == eager["epochs"],
                          "best_model_tensors_exact": equal(old["model"],new["model"]),
                          "best_optimizer_tensors_exact": equal(old["optimizer"],new["optimizer"]),
                          "selected_epoch_exact": old["epoch"] == new["epoch"],
                          "saved_validation_predictions_exact": read(a/"validation-predictions.json") == read(b/"validation-predictions.json"),
                          "dataset_preprocessing_budget_exact": all(equal(old[k],new[k]) for k in ("dataset_sha256","preprocessing","config","seed"))}
    if not all(all(v.values()) for v in correctness.values()): raise ValueError("Complete-run parity failed")
    peaks = {}
    for label,path in (("eager",args.eager),("accelerated",args.accelerated)):
        with (path/"gpu.csv").open() as stream:
            rows = []
            for r in csv.reader(stream):
                if len(r) == 5:
                    try: rows.append([float(x) for x in r[1:]])
                    except ValueError: pass
        peaks[label] = {"utilization_max_percent": max(r[0] for r in rows),
                        "power_max_w": max(r[1] for r in rows),
                        "samples_at_100_percent": sum(r[0] == 100 for r in rows), "sample_count": len(rows)}
    value = {"eager": eager, "accelerated": fast,
             "complete_cli_speedup": eager["complete_cli_wall_s"]/fast["complete_cli_wall_s"],
             "correctness": correctness, "telemetry_peaks": peaks,
             "nsight": nsight(args.nsight) if args.nsight else {},
             "source_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in list((ROOT/"backend/learning").glob("*.py"))+[ROOT/"backend/learning/cuda/matching.cu", ROOT/"tools/learning-pilot.py"]}}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(value,indent=2)+"\n")
    print(json.dumps({"speedup": value["complete_cli_speedup"],"correctness": correctness,"telemetry_peaks": peaks}),flush=True)


if __name__ == "__main__": main()

"""Summarize SF-15 sealed reports into per-domain/condition/class tables for the model card.

Reads only finished reports; it never scores or selects anything.
"""
import argparse
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
# (weather, severity, local hour) per capture_id % 10, from tools/generate-sf10-requests.ts.
PRESETS = {
    "standard": [("clear-day", 0, 12), ("clear-day", 0, 8), ("night", 1, 0), ("fog", .75, 12), ("fog", 1, 8),
                 ("rain", .7, 13), ("snow", .8, 10), ("hot-background", .9, 15), ("clear-day", 0, 17), ("night", 1, 21)],
    "heldout-environment": [("clear-day", 0, 6), ("clear-day", 0, 19), ("night", .6, 3), ("fog", .45, 6), ("fog", .9, 19),
                            ("rain", .95, 6), ("snow", .45, 19), ("hot-background", .5, 18), ("rain", .4, 22), ("snow", .95, 3)],
}
PRESETS["heldout-f22"] = PRESETS["standard"]


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def stats(values):
    values = [v for v in values if v is not None]
    return {"mean": float(np.mean(values)), "sd": float(np.std(values, ddof=1)) if len(values) > 1 else None,
            "values": values} if values else None


def groups(report, method):
    return [key for key in report["cases"] if key.startswith(method + "-group-")]


def reduce(items):
    """Mean/sd over the three disjoint ensembles of one metric block, with counts from the first."""
    first = items[0]
    return {"map_3d": stats([i["map_3d"] for i in items]), "frames": first.get("frames"),
            "ece_10_bins": stats([i["detection_ece_10_bins"] for i in items]),
            "center_error_m": stats([i["matched_center_error_m"] for i in items]),
            "false_positives": stats([i["false_positives"] for i in items]),
            "classes": {name: {"positives": cls["positives"],
                               "ap": stats([i["classes"][name]["ap"] for i in items]),
                               "recall": stats([i["classes"][name]["recall"] for i in items])}
                        for name, cls in first["classes"].items()}}


def domains(report, method):
    clean = [report["cases"][g]["availability-7"] for g in groups(report, method)]
    result = {}
    for domain in clean[0]["condition_profiles"]:
        block = reduce([c["condition_profiles"][domain] for c in clean])
        block["conditions"] = {}
        for index, preset in enumerate(PRESETS[domain]):
            key = f"{domain}/{index}"
            if key in clean[0]["conditions"]:
                block["conditions"][key] = {"weather": preset[0], "severity": preset[1], "hour": preset[2],
                                            **reduce([c["conditions"][key] for c in clean])}
        result[domain] = block
    return result


def cases(report, method):
    names = report["cases"][groups(report, method)[0]]
    return {name: stats([report["cases"][g][name]["map_3d"] for g in groups(report, method)]) for name in names}


def target_checks(report, method, targets, latency_p95_ms, training_peak_gib):
    """Frozen SF-11 targets (docs/evidence/sf11/sf15-targets.json), checked per disjoint ensemble."""
    rows = []
    for key in groups(report, method):
        clean = report["cases"][key]["availability-7"]
        standard = clean["condition_profiles"].get("standard", clean)
        classes = {n: c for n, c in clean["classes"].items() if c["positives"]}
        checks = {
            "class_ap": {n: classes[n]["ap"] >= targets["class_ap_min"][n] for n in classes},
            "recall": {n: classes[n]["recall"] >= targets["recall_min_each_class"] for n in classes},
            "standard_condition_map": {i: standard_map >= floor for i, floor in targets["condition_map_min"].items()
                                       if (standard_map := clean["conditions"].get(f"standard/{i}", {}).get("map_3d")) is not None},
            "center_error": clean["matched_center_error_m"] <= targets["matched_center_error_max_m"],
            "ece": clean["detection_ece_10_bins"] <= targets["detection_ece_max"],
            "empty_scene_fp_per_frame": (clean["empty_scene_false_positives"] / clean["empty_scenes"]
                                         if clean["empty_scenes"] else None),
        }
        efp = checks["empty_scene_fp_per_frame"]
        checks["empty_scene_fp"] = efp is None or efp <= targets["empty_scene_fp_per_frame_max"]
        rows.append({"ensemble": key, **checks})
    flat = lambda r: [v for k, v in r.items() if k not in ("ensemble", "empty_scene_fp_per_frame")
                      for v in (v.values() if isinstance(v, dict) else [v])]
    return {"per_ensemble": rows,
            "latency_p95": latency_p95_ms <= targets["latency_p95_ms_max"],
            "training_peak_allocated": training_peak_gib <= targets["training_peak_allocated_gib_max"],
            "failed": sorted({k for r in rows for k, v in r.items() if k not in ("ensemble", "empty_scene_fp_per_frame")
                              and not all(v.values() if isinstance(v, dict) else [v])}),
            "all_pass": all(all(flat(r)) for r in rows) and latency_p95_ms <= targets["latency_p95_ms_max"]
                        and training_peak_gib <= targets["training_peak_allocated_gib_max"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT / "artifacts/sf15")
    parser.add_argument("--output", type=Path, default=ROOT / "docs/evidence/sf15-scaling/results-summary.json")
    args = parser.parse_args()
    reports = {"sealed-test": read(args.root / "test-report.json"),
               "f22-asset-holdout": read(args.root / "test-asset-holdout-report.json")}
    summary = {"profile": "sf15-results-summary.v1",
               "note": "Mean/sample-sd over three disjoint 3-seed ensembles; counts are per evaluation domain",
               "reports": {}}
    for name, report in reports.items():
        summary["reports"][name] = {"frames": report["frames"], "independent_layouts": report["independent_layouts"],
            "methods": {m: {**{k: v for k, v in report["methods"][m].items() if not k.endswith("values")},
                            "domains": domains(report, m), "cases": cases(report, m)} for m in report["methods"]}}
    temporal = read(ROOT / "docs/evidence/sf15-scaling/temporal-ablation.json")
    summary["temporal"] = {"frames": temporal["frames"], "sequences": temporal["sequences"], "scope": temporal["scope"],
        "cases": {name: {variant: value["map_3d"] for variant, value in case.items() if isinstance(value, dict) and "map_3d" in value}
                  for name, case in temporal["cases"].items()}}
    summary["runtime"] = {name: read(args.root / f"profile-{name}/summary.json") for name in ("scaled", "baseline")}
    targets = read(ROOT / "docs/evidence/sf11/sf15-targets.json")
    training = read(ROOT / "docs/evidence/sf15-scaling/training-runtime.json")["runs-10000"]
    summary["sf11_targets"] = {name: target_checks(report, "candidate", targets,
                                                   summary["runtime"]["scaled"]["end_to_end_ms"]["p95"],
                                                   training["peak_allocated_bytes"] / 2**30)
                               for name, report in reports.items()}
    args.output.write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({n: {m: (round(v["clean_mean"], 4), round(v["macro_mean"], 4)) for m, v in r["methods"].items()}
                      for n, r in summary["reports"].items()}))


if __name__ == "__main__":
    main()

"""Predeclared validation-only scale decision and sealed-test integrity checks."""
from pathlib import Path

from app.dataset import digest


def frozen_digest(path):
    # Source/JSON line endings can change on Windows checkout; binary artifacts
    # retain a raw SHA-256. Text semantics are frozen after LF normalization.
    if Path(path).suffix in (".py", ".ts", ".json"):
        import hashlib
        return hashlib.sha256(Path(path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    return digest(Path(path))


def decide_volume(baseline, candidate, volume):
    if min(baseline["replicates"], candidate["replicates"]) < 3:
        raise ValueError("Three complete disjoint ensemble replicates are required")
    clean_delta = candidate["clean_mean"] - baseline["clean_mean"]
    macro_delta = candidate["macro_mean"] - baseline["macro_mean"]
    gain = (clean_delta + macro_delta) / 2
    stable = max(candidate["clean_sd"], candidate["macro_sd"]) <= .03
    quality = candidate["clean_mean"] >= .5 and candidate["macro_mean"] >= .35
    safe = clean_delta >= -.01 and macro_delta >= -.01 and candidate["all_missing_detections"] == 0
    promote = stable and quality and safe and gain >= .005
    return {"training_samples": volume, "objective_gain": gain, "clean_delta": clean_delta,
            "macro_delta": macro_delta, "stable": stable, "quality_targets": quality,
            "paired_nonregression": safe, "promote": promote,
            "expand": promote and volume < 30000,
            "reason": "gain at least .005, nonregression and stability pass" if promote else
                "insufficient validation benefit or stability/nonregression failure; retain smaller accepted model"}


def make_freeze(paths, decision):
    return {"profile": "sf15-sealed-test.v1", "decision": decision,
            "hash_policy": "LF-normalized py/ts/json, raw binary",
            "files": {str(Path(p).resolve()): frozen_digest(p) for p in paths}}


def assert_frozen(frozen):
    for name, sha in frozen["files"].items():
        if not Path(name).is_file() or frozen_digest(name) != sha:
            raise ValueError(f"Frozen file changed: {name}")

"""Prepare paired observation degradations and score frozen validation-selected models."""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import sys
os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
import torch
from learning.sf12_comparison import prepare_suite, compare


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["prepare", "evaluate"])
    parser.add_argument("--dataset", type=Path, default=ROOT / "artifacts/sf11/pilot-3000")
    parser.add_argument("--sf11", type=Path, default=ROOT / "artifacts/sf11/learning")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/sf12/essrf")
    parser.add_argument("--comparison-root", type=Path, default=ROOT / "artifacts/sf12/comparison-cache")
    parser.add_argument("--baseline-root", type=Path, default=ROOT / "artifacts/sf12/baseline-seeds")
    parser.add_argument("--essrf-run-root", type=Path)
    parser.add_argument("--seeds", type=int, nargs="+", default=[11, 12, 13])
    parser.add_argument("--report", type=Path, default=ROOT / "artifacts/sf12/comparison.json")
    parser.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    torch.set_num_threads(2)
    if args.stage == "prepare":
        prepare_suite(args)
    else:
        compare(args)


if __name__ == "__main__":
    main()

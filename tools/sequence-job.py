"""Run/resume immutable temporal sequences with durable per-frame replay states."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import sys
import threading

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"backend"))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--specs",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--resume",action="store_true")
    parser.add_argument("--stop-after",type=int,help="Deliberately stop after N new frames, for recovery tests")
    parser.add_argument("--validate",action="store_true")
    parser.add_argument("--worker-cache",type=Path,help="Optional fresh worker cache for cold recovery/replay")
    args=parser.parse_args()
    output=args.output.resolve()
    os.environ["YULAB_CAPTURE_ROOT"]=str((args.worker_cache or output/"worker").resolve())
    from app.sequence_job import run_sequence_job
    from app.dataset import validate_manifest
    if args.validate:
        manifest=validate_manifest(output/"dataset")
        print(json.dumps({"validated":len(manifest["captures"]),"counts":manifest["counts"]})); return
    payload=json.loads(args.specs.read_text(encoding="utf-8"))
    if payload.get("version")!="temporal-sequences.v1":
        raise ValueError("Unsupported temporal sequence request version")
    cancel=threading.Event()
    signal.signal(signal.SIGINT,lambda *_:cancel.set())
    print(json.dumps(run_sequence_job(payload["sequences"],output,resume=args.resume,stop_after=args.stop_after,cancel=cancel)),flush=True)


if __name__=="__main__":
    main()

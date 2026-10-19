"""Single-writer, resumable temporal capture job with immutable frame snapshots."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import sqlite3
import threading
import time

from .capture_session import CaptureWorkerSession, _retry_sharing
from .capture_worker import ARTIFACT_ROOT, RESULT_VALIDATOR, run_capture_worker
from .contracts import validate_payload
from .dataset import artifact, digest, json_file, package_capture, publish_manifest, validate_capture_files, validate_manifest
from .dataset_pipeline import catalog_records, discard_partial, resume_published
from .sequences import canonical_hash, outage_modalities, sequence_request, validate_frame_order, validate_sequences


def atomic_json(path: Path, value: dict) -> None:
    partial=path.with_suffix(path.suffix+".partial")
    json_file(partial,value)
    _retry_sharing(lambda source:os.replace(source,path),partial)


def snapshot(spec, index, request, result, truth, previous_hash):
    return {"version":"sequence-replay-state.v1","sequence_sha256":canonical_hash(spec),
        "frame_index":index,"capture_time_s":request["plan"]["simulation_time_s"],
        "capture_id":request["plan"]["capture_id"],"request_sha256":canonical_hash(request),
        "previous_snapshot_sha256":previous_hash,"nominal_rig":request["rig"],
        "actual_rig":result["actual_rig"],"objects":truth["objects"],
        "thermal_state":result["artifacts"]["thermal_state"],
        "unavailable_modalities":sorted(outage_modalities(spec,index))}


def read_frame(spec, index, request, directory, previous_hash, recorded=None):
    item={"request":request,"group_id":spec["group_id"],"split":spec["split"]}
    if recorded is not None and "files" in recorded:
        validate_capture_files(directory,recorded)
    entry=resume_published(item,directory.parent)
    observed=json.loads((directory/"observation.json").read_text(encoding="utf-8"))
    truth=json.loads((directory/"truth.json").read_text(encoding="utf-8"))
    result=json.loads((directory/"metadata_json").read_text(encoding="utf-8"))
    result["artifacts"]["metadata"]=artifact(directory/"metadata_json")
    expected=snapshot(spec,index,request,result,truth,previous_hash)
    stored=json.loads((directory/"sequence_state_json").read_text(encoding="utf-8"))
    if stored!=expected:
        raise ValueError("Sequence replay snapshot/configuration/chain mismatch")
    if observed.get("frame_index")!=index or observed.get("capture_time_s")!=request["plan"]["simulation_time_s"]:
        raise ValueError("Sequence frame identity or timestamp mismatch")
    disabled=outage_modalities(spec,index)
    for modality in ("rgb","ir","lidar"):
        if (observed[modality]["status"]=="unavailable")!=(modality in disabled):
            raise ValueError("Sequence outage state mismatch")
    thermal=directory/stored["thermal_state"]["id"]
    if digest(thermal)!=stored["thermal_state"]["sha256"] or thermal.stat().st_size!=stored["thermal_state"]["byte_length"]:
        raise ValueError("Sequence thermal snapshot corrupted")
    if json.loads(thermal.read_text(encoding="utf-8"))["simulation_time_s"]!=request["plan"]["simulation_time_s"]:
        raise ValueError("Sequence thermal history timestamp mismatch")
    state_hash=digest(directory/"sequence_state_json")
    if recorded is not None and "files" not in recorded and recorded!={"entry_sha256":canonical_hash(entry),"snapshot_sha256":state_hash}:
        raise ValueError("Published sequence frame inventory changed")
    return entry,stored,state_hash


def capture_frame(spec,index,request,root,cancel,session,previous_hash):
    capture_id=request["plan"]["capture_id"]
    job_id=f"capture-job-{capture_id}"
    raw=ARTIFACT_ROOT/job_id
    if raw.exists():
        saved=json.loads((raw/"request.json").read_text(encoding="utf-8"))
        if saved!=request:
            raise ValueError("Existing worker capture belongs to a different sequence request")
        result=json.loads((raw/"result.json").read_text(encoding="utf-8"))
        errors=list(RESULT_VALIDATOR.iter_errors(result))
        if errors:
            raise ValueError("Existing worker result violates capture contract")
    else:
        discard_partial(ARTIFACT_ROOT/f"{job_id}.partial",ARTIFACT_ROOT)
        result=run_capture_worker({**request,"_job_id":job_id},cancel,session=session)
    stage=root/f"{capture_id}.partial"
    discard_partial(stage,root)
    metadata=package_capture(request,result,raw,stage,catalog_records())
    observed=json.loads((stage/"observation.json").read_text(encoding="utf-8"))
    observed.update(frame_index=index,capture_time_s=request["plan"]["simulation_time_s"])
    disabled=outage_modalities(spec,index)
    for modality in disabled:
        observed[modality]={"status":"unavailable","reason":"disabled","message":"Recorded sequence sensor outage"}
        next(s for s in observed["rig"]["sensors"] if s["modality"]==modality)["available"]=False
    validate_payload("ObservationBundle",observed)
    metadata["observation"]=json_file(stage/"observation.json",observed)
    truth=json.loads((stage/"truth.json").read_text(encoding="utf-8"))
    state=snapshot(spec,index,request,result,truth,previous_hash)
    json_file(stage/"sequence_state_json",state)
    validate_capture_files(stage,metadata)
    final=root/capture_id
    _retry_sharing(lambda source:os.replace(source,final),stage)
    return read_frame(spec,index,request,final,previous_hash)


def restore_thermal(directory: Path, reference: dict) -> None:
    """Worker thermal resolution survives deletion/loss of the worker cache."""
    source=directory/reference["id"]
    if digest(source)!=reference["sha256"] or source.stat().st_size!=reference["byte_length"]:
        raise ValueError("Cannot restore corrupt thermal snapshot")
    state_dir=ARTIFACT_ROOT/f"replay-{reference['sha256']}"
    state_dir.mkdir(parents=True,exist_ok=True)
    target=state_dir/reference["id"]
    if not target.exists():
        target.write_bytes(source.read_bytes())
    if digest(target)!=reference["sha256"]:
        raise ValueError("Restored thermal state hash mismatch")


def run_sequence_job(specs: list[dict], output: Path, *, resume=False, stop_after=None,
                     cancel: threading.Event | None=None) -> dict:
    validate_sequences(specs)
    if stop_after is not None and (type(stop_after) is not int or stop_after<1):
        raise ValueError("stop_after must be positive")
    output=output.resolve(); output.mkdir(parents=True,exist_ok=True)
    state_path=output/"sequence-job.json"; root=output/"dataset"
    request_hash=canonical_hash(specs); started=time.perf_counter()
    cancel=cancel or threading.Event()
    # An OS-managed SQLite write lock fences a second coordinator. It releases
    # on process death; no heartbeat/PID guessing or stale-writer takeover.
    lock=sqlite3.connect(output/"sequence-lock.sqlite3",timeout=0)
    try:
        lock.execute("BEGIN IMMEDIATE")
    except sqlite3.OperationalError as error:
        lock.close(); raise ValueError("Sequence output is already owned by another writer") from error
    try:
        if state_path.exists():
            if not resume:
                raise ValueError("Existing sequence job requires --resume")
            state=json.loads(state_path.read_text(encoding="utf-8"))
            if state["request_sha256"]!=request_hash:
                raise ValueError("Resume sequence specification changed")
        else:
            state={"version":"temporal-sequence-job.v1","request_sha256":request_hash,
                "state":"queued","completed":{},"error":None}
        root.mkdir(parents=True,exist_ok=True); ARTIFACT_ROOT.mkdir(parents=True,exist_ok=True)
        known={f"{s['sequence_id']}-{i:06d}" for s in specs for i in range(s["frame_count"])}
        unexpected=[p.name for p in root.iterdir() if p.is_dir() and not p.name.endswith(".partial") and p.name not in known]
        if unexpected:
            raise ValueError("Unknown published frame in sequence dataset")
        for capture_id in state["completed"]:
            if capture_id not in known or not (root/capture_id).is_dir():
                raise ValueError("Previously published sequence frame is missing")
        for spec in specs:
            missing=False
            for index in range(spec["frame_count"]):
                exists=(root/f"{spec['sequence_id']}-{index:06d}").is_dir()
                if exists and missing:
                    raise ValueError("Published sequence contains a frame gap")
                missing=missing or not exists
        if state["state"]=="succeeded":
            manifest=validate_manifest(root)
            if canonical_hash(manifest.get("temporal_sequences",[]))!=request_hash:
                raise ValueError("Published manifest sequence configuration changed")
            return {"state":"succeeded","new_captures":0,"reused_captures":len(manifest["captures"]),"captures":len(manifest["captures"]),"counts":manifest["counts"]}
        state.update(state="running",error=None); atomic_json(state_path,state)
        entries=[]; requests=[]; new=0; reused=0
        with CaptureWorkerSession() as session:
            for spec in specs:
                previous_hash=None; thermal=None; previous_dir=None; frames=[]; found_gap=False
                for index in range(spec["frame_count"]):
                    request=sequence_request(spec,index,thermal)
                    directory=root/request["plan"]["capture_id"]
                    if directory.exists():
                        if found_gap:
                            raise ValueError("Published sequence contains a frame gap")
                        entry,saved,state_hash=read_frame(spec,index,request,directory,previous_hash,
                            state["completed"].get(request["plan"]["capture_id"]))
                        reused+=1
                    else:
                        found_gap=True
                        if cancel.is_set() or (stop_after is not None and new>=stop_after):
                            state["state"]="cancelled"; atomic_json(state_path,state)
                            return {"state":"cancelled","new_captures":new,"reused_captures":reused}
                        if previous_dir is not None:
                            restore_thermal(previous_dir,thermal)
                        entry,saved,state_hash=capture_frame(spec,index,request,root,cancel,session,previous_hash)
                        new+=1
                    frames.append({"frame_index":index,"capture_time_s":saved["capture_time_s"]})
                    validate_frame_order(spec,frames,complete=False)
                    state["completed"][entry["capture_id"]]={"entry_sha256":canonical_hash(entry),"snapshot_sha256":state_hash}
                    atomic_json(state_path,state)
                    entries.append(entry); requests.append(request)
                    thermal=saved["thermal_state"]; previous_hash=state_hash; previous_dir=directory
                    print(json.dumps({"sequence":spec["sequence_id"],"frame":index,"new":new,"reused":reused}),flush=True)
                validate_frame_order(spec,frames,complete=True)
        manifest=publish_manifest(root,"sf13-temporal-v1",entries,requests,catalog_records(),sequence_specs=specs)
        state["state"]="succeeded"; atomic_json(state_path,state)
        metrics={"state":"succeeded","new_captures":new,"reused_captures":reused,
            "captures":len(entries),"elapsed_s":time.perf_counter()-started,"counts":manifest["counts"]}
        atomic_json(output/"metrics.json",metrics)
        return metrics
    except BaseException as error:
        if "state" in locals() and state.get("request_sha256")==request_hash:
            state.update(state="cancelled" if cancel.is_set() else "failed",error=str(error))
            atomic_json(state_path,state)
        raise
    finally:
        lock.rollback(); lock.close()

"""Frozen temporal sequence semantics, deterministic frame requests and replay."""
from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path

from .contracts import validate_payload
from .temporal_capture import actual_rig_at, world_at


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()


def validate_sequences(specs: list[dict]) -> None:
    if not specs:
        raise ValueError("No sequences")
    ids=set(); variants=set(); families={}; groups={}; scenes={}
    for spec in specs:
        validate_payload("SequenceSpec",spec)
        if len(spec["sequence_id"])>88 or spec["sequence_id"] in ids:
            raise ValueError("Duplicate or overlong sequence identity")
        ids.add(spec["sequence_id"])
        pair=(spec["family_id"],spec["variant_id"])
        if pair in variants:
            raise ValueError("Duplicate family variant")
        variants.add(pair)
        base=spec["base_capture"]; motion=base.get("temporal")
        if motion is None or base["environment"]["thermal_history"]!="equilibrated" or base["environment"]["thermal_state"] is not None:
            raise ValueError("Sequence requires temporal motion and an equilibrated initial state")
        if base["environment"]["simulation_time_s"]!=spec["start_time_s"] or base["plan"]["simulation_time_s"]!=spec["start_time_s"]:
            raise ValueError("Sequence start time mismatch")
        last_time=spec["start_time_s"]+(spec["frame_count"]-1)*spec["frame_interval_s"]
        if last_time>1e9:
            raise ValueError("Sequence time exceeds contract range")
        for sensor in base["rig"]["sensors"]:
            if sensor["timestamp_offset_s"]<0 or sensor["timestamp_offset_s"]+max(sensor["scan_duration_s"],sensor["exposure_s"])>spec["frame_interval_s"]:
                raise ValueError("Frame interval cannot contain sensor acquisition window")
        actual_rig_at(base,0); world_at(base,0)
        for outage in spec["outages"]:
            if not 0<=outage["start_frame"]<outage["stop_frame"]<=spec["frame_count"]:
                raise ValueError("Invalid outage interval")
        known={i["instance_id"] for i in base["world"]["instances"]}; seen=set(); previous=-1
        for event in spec["operating_events"]:
            key=(event["frame_index"],event["instance_id"])
            if event["instance_id"] not in known or event["frame_index"]>=spec["frame_count"] or key in seen or event["frame_index"]<previous:
                raise ValueError("Invalid or disordered operating event")
            seen.add(key); previous=event["frame_index"]
        # A family may change weather, drift and outages; physical scene/trajectory
        # and its sampling grid must remain paired across its variants.
        signature=canonical_hash({"world":base["world"],"rig":base["rig"],
            "velocity":motion["velocity_world_m_per_s"],"yaw":motion["yaw_rate_rad_per_s"],
            "reference":motion["reference_time_s"],"objects":motion.get("object_motion",[]),
            "count":spec["frame_count"],"interval":spec["frame_interval_s"],"start":spec["start_time_s"],
            "events":spec["operating_events"]})
        family_state=(spec["split"],spec["group_id"],signature)
        if families.setdefault(spec["family_id"],family_state)!=family_state:
            raise ValueError("Sequence family changes scene/trajectory or leaks across splits")
        if groups.setdefault(spec["group_id"],spec["split"])!=spec["split"]:
            raise ValueError("Sequence group leaks across splits")
        scene=canonical_hash(base["world"])
        if scenes.setdefault(scene,spec["split"])!=spec["split"]:
            raise ValueError("Same reference scene leaks across splits")


def sequence_request(spec: dict, index: int, thermal_state: dict | None) -> dict:
    if type(index) is not int or not 0<=index<spec["frame_count"]:
        raise ValueError("Frame index outside sequence")
    if (index==0)!=(thermal_state is None):
        raise ValueError("Continued frame requires its predecessor thermal state")
    request=copy.deepcopy(spec["base_capture"])
    offset=index*spec["frame_interval_s"]; tick=spec["start_time_s"]+offset
    nominal=copy.deepcopy(request); nominal["temporal"]["sensor_drift"]=[]
    request["rig"]=actual_rig_at(nominal,offset)
    for sensor in request["rig"]["sensors"]:
        sensor["available"]=True
    request["rig"]["timing_profile"]="timed-scan"
    for event in spec["operating_events"]:
        if event["frame_index"]<=index:
            next(i for i in request["world"]["instances"] if i["instance_id"]==event["instance_id"])["operating_state"]=event["operating_state"]
    request["environment"].update(simulation_time_s=tick,thermal_history="equilibrated" if index==0 else "continued",thermal_state=copy.deepcopy(thermal_state))
    request["plan"].update(capture_id=f"{spec['sequence_id']}-{index:06d}",sequence_id=spec["sequence_id"],simulation_time_s=tick,modalities=["rgb","ir","lidar"])
    for key in ("world","rig","environment"):
        request["plan"][f"{key}_sha256"]=canonical_hash(request[key])
    validate_payload("CaptureRequest",request)
    return request


def outage_modalities(spec: dict, index: int) -> set[str]:
    return {m for outage in spec["outages"] if outage["start_frame"]<=index<outage["stop_frame"] for m in outage["modalities"]}


def validate_frame_order(spec: dict, frames: list[dict], *, complete: bool) -> None:
    if len(frames)>spec["frame_count"] or (complete and len(frames)!=spec["frame_count"]):
        raise ValueError("Incomplete or oversized sequence")
    for index,frame in enumerate(frames):
        expected=spec["start_time_s"]+index*spec["frame_interval_s"]
        if type(frame["frame_index"]) is not int or frame["frame_index"]!=index:
            raise ValueError("Sequence frame gap, duplicate or disorder")
        if not math.isfinite(frame["capture_time_s"]) or abs(frame["capture_time_s"]-expected)>1e-9:
            raise ValueError("Sequence timestamp disorder or drift")


def validate_temporal_manifest(root: Path, manifest: dict) -> None:
    from .sequence_job import read_frame
    specs=manifest["temporal_sequences"]; validate_sequences(specs)
    known={s["sequence_id"] for s in specs}
    if any(e["sequence_id"] not in known for e in manifest["captures"]):
        raise ValueError("Unknown sequence in temporal manifest")
    for spec in specs:
        entries=[e for e in manifest["captures"] if e["sequence_id"]==spec["sequence_id"]]
        if len(entries)!=spec["frame_count"]:
            raise ValueError("Temporal sequence incomplete")
        thermal=None; previous=None; frames=[]
        for index,entry in enumerate(entries):
            request=sequence_request(spec,index,thermal)
            if entry["capture_id"]!=request["plan"]["capture_id"] or entry["group_id"]!=spec["group_id"] or entry["split"]!=spec["split"]:
                raise ValueError("Temporal frame disorder or split mismatch")
            _,saved,previous=read_frame(spec,index,request,root/entry["capture_id"],previous,entry)
            frames.append({"frame_index":index,"capture_time_s":saved["capture_time_s"]})
            thermal=saved["thermal_state"]
        validate_frame_order(spec,frames,complete=True)

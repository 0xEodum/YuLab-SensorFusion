"""Real-worker temporal acceptance: cold recovery, paired splits and exact replay."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"backend"))
from app.dataset import digest, validate_manifest
from app.observation_input import load_observation_only
from app.sequences import canonical_hash, outage_modalities, sequence_request, validate_sequences
from app.temporal_capture import world_at


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--specs",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--resume",action="store_true",help="Continue this acceptance run after an external interruption")
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=args.resume)
    payload=json.loads(args.specs.read_text(encoding="utf-8")); specs=payload["sequences"]
    validate_sequences(specs)
    if any(s["frame_count"]<32 for s in specs):
        raise ValueError("Acceptance requires at least 32 frames per clip")
    stage_path=args.output/"acceptance-stages.json"
    if stage_path.exists():
        recorded=json.loads(stage_path.read_text())
        if recorded["specifications_sha256"]!=canonical_hash(specs):
            raise ValueError("Acceptance resume specification changed")
        stages=recorded["stages"]
    else:
        stages={}
    def command(name,arguments):
        if stages.get(name,{}).get("exit_code")==0:
            return
        start=time.time(); print(json.dumps({"stage":name,"state":"started"}),flush=True)
        with (args.output/f"{name}.log").open("w",encoding="utf-8") as log:
            result=subprocess.run([sys.executable,"tools/sequence-job.py",*map(str,arguments)],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
        stages[name]={"exit_code":result.returncode,"start_unix_s":start,"end_unix_s":time.time()}
        stage_path.write_text(json.dumps({"specifications_sha256":canonical_hash(specs),"stages":stages},indent=2)+"\n")
        if result.returncode:
            raise RuntimeError(f"{name} failed; inspect its log")
        print(json.dumps({"stage":name,**stages[name]}),flush=True)
    job=args.output/"resumed-job"
    common=["--specs",args.specs,"--output",job]
    command("stopped",[*common,"--stop-after","8"])
    if stages.get("cold-resume",{}).get("exit_code")!=0:
        assert not (job/"dataset/manifest.json").exists()
    first=specs[0]
    prefix_path=args.output/"stopped-prefix.json"
    if prefix_path.exists():
        prefix=json.loads(prefix_path.read_text())
    else:
        prefix={p.relative_to(job/"dataset").as_posix():digest(p) for p in (job/"dataset").rglob("*") if p.is_file()}
        prefix_path.write_text(json.dumps(prefix,indent=2)+"\n")
    command("cold-resume",[*common,"--resume","--worker-cache",args.output/"cold-worker-cache"])
    assert all(digest(job/"dataset"/path)==sha for path,sha in prefix.items())
    dataset=job/"dataset"; manifest=validate_manifest(dataset)
    manifest_sha=digest(dataset/"manifest.json")
    command("completed-resume",[*common,"--resume"])
    assert digest(dataset/"manifest.json")==manifest_sha
    replay_specs=args.output/"replay-specs.json"
    replay_specs.write_text(json.dumps({"version":"temporal-sequences.v1","sequences":[first]},indent=2)+"\n",encoding="utf-8")
    replay=args.output/"uninterrupted-replay"
    command("uninterrupted-replay",["--specs",replay_specs,"--output",replay])
    compared=0
    for index in range(first["frame_count"]):
        name=f"{first['sequence_id']}-{index:06d}"
        for path in (dataset/name).iterdir():
            if path.name=="metadata_json": continue
            assert path.read_bytes()==(replay/"dataset"/name/path.name).read_bytes(),str(path)
            compared+=1
    # Freeze the last frame's independently materialized object poses. Cameras
    # sample the anchor time, so all camera references must match exactly even
    # though the frozen control has no object motion during its LiDAR scan.
    index=first["frame_count"]-1
    original_dir=dataset/f"{first['sequence_id']}-{index:06d}"
    predecessor=dataset/f"{first['sequence_id']}-{index-1:06d}"
    prior=json.loads((predecessor/"sequence_state_json").read_text())["thermal_state"]
    frozen=sequence_request(first,index,prior)
    frozen["world"]=world_at(frozen,0)
    frozen["temporal"]["object_motion"]=[]
    frozen["plan"]["world_sha256"]=canonical_hash(frozen["world"])
    frozen["plan"]["capture_id"]="frozen-sequence-control"
    frozen_request=args.output/"frozen-control-request.json"
    frozen_request.write_text(json.dumps(frozen,indent=2)+"\n",encoding="utf-8")
    frozen_output=args.output/"cold-worker-cache/frozen-control"
    start=time.time()
    with (args.output/"frozen-control.log").open("w",encoding="utf-8") as log:
        subprocess.run(["node","workers/capture/index.mjs","--request",str(frozen_request.resolve()),"--output",str(frozen_output.resolve())],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
    stages["frozen-control"]={"exit_code":0,"start_unix_s":start,"end_unix_s":time.time()}
    original=json.loads((original_dir/"metadata_json").read_text())
    control=json.loads((frozen_output/"result.json").read_text())
    matched_camera_artifacts=0
    for key in ("rgb_raw","depth","instance","ir_instance","ir_radiance","ir_validity","ir_saturation","thermal_state"):
        assert original["artifacts"][key]["sha256"]==control["artifacts"][key]["sha256"],key
        matched_camera_artifacts+=1
    for name in original["posed_boxes"]:
        for field in ("center_m","extent_m","quaternion_xyzw"):
            np.testing.assert_allclose(original["posed_boxes"][name][field],control["posed_boxes"][name][field],atol=1e-7,rtol=0)
    unavailable=0; maximum_motion_error=0.; maximum_drift_error=0.; heat_change=0.
    per_sequence=[]
    for spec in specs:
        target=spec["base_capture"]["temporal"]["object_motion"][0]
        reference=next(i for i in spec["base_capture"]["world"]["instances"] if i["instance_id"]==target["instance_id"])
        start_temp=None; last_temp=None
        for index in range(spec["frame_count"]):
            name=f"{spec['sequence_id']}-{index:06d}"; directory=dataset/name
            obs,arrays=load_observation_only(dataset,{"capture_id":name})
            assert not ({"temporal","objects","actual_rig","world"}&set(obs))
            assert obs["frame_index"]==index and abs(obs["capture_time_s"]-(spec["start_time_s"]+index*spec["frame_interval_s"]))<1e-9
            disabled=outage_modalities(spec,index)
            assert {m for m in ("rgb","ir","lidar") if obs[m]["status"]=="unavailable"}==disabled
            assert all(not any(k.startswith(m+".") for k in arrays) for m in disabled)
            if len(disabled)==3: unavailable+=1; assert not arrays
            truth=json.loads((directory/"truth.json").read_text())
            actual=next(o for o in truth["objects"] if o["instance"]["instance_id"]==target["instance_id"])
            t=obs["capture_time_s"]-spec["base_capture"]["temporal"]["reference_time_s"]
            expected=np.array(reference["T_world_from_asset"],dtype=float).reshape(4,4)
            a=target["yaw_rate_rad_per_s"]*t; c,s=np.cos(a),np.sin(a)
            expected[:3,:3]=np.array([[c,0,s],[0,1,0],[-s,0,c]])@expected[:3,:3]
            expected[:3,3]+=np.array(target["velocity_world_m_per_s"])*t
            measured=np.array(actual["instance"]["T_world_from_asset"]).reshape(4,4)
            maximum_motion_error=max(maximum_motion_error,float(abs(measured-expected).max()))
            assert maximum_motion_error<1e-8
            assert actual["velocity_m_per_s"]==target["velocity_world_m_per_s"]
            # Drift displacement is evaluated independently in rig axes.
            for drift in spec["base_capture"]["temporal"]["sensor_drift"]:
                nominal=next(s for s in obs["rig"]["sensors"] if s["modality"]==drift["modality"])
                calibrated=next(s for s in truth["actual_rig"]["sensors"] if s["modality"]==drift["modality"])
                origin=np.array(nominal["T_rig_from_sensor"])[[3,7,11]]
                real=np.array(calibrated["T_rig_from_sensor"])[[3,7,11]]
                expected_delta=np.array(drift["translation_rig_m"])+np.array(drift["translation_rate_rig_m_per_s"])*t
                maximum_drift_error=max(maximum_drift_error,float(abs(real-origin-expected_delta).max()))
            temps=[n["temperature_k"] for n in actual["surface_temperatures_k"]]
            if temps:
                if start_temp is None: start_temp=np.array(temps)
                last_temp=np.array(temps)
        if start_temp is not None:
            heat_change=max(heat_change,float(abs(last_temp-start_temp).max()))
        per_sequence.append({"sequence_id":spec["sequence_id"],"family_id":spec["family_id"],"variant":spec["variant_id"],"split":spec["split"],"frames":spec["frame_count"],"duration_s":(spec["frame_count"]-1)*spec["frame_interval_s"]})
    assert maximum_drift_error<1e-8 and heat_change>0
    # Minimal observation-only export includes one available and one all-missing
    # frame, with neither labels nor replay/actual-calibration metadata.
    isolated=args.output/"observation-only"; selected=[]
    for entry in manifest["captures"]:
        obs=json.loads((dataset/entry["capture_id"]/"observation.json").read_text())
        missing=all(obs[m]["status"]=="unavailable" for m in ("rgb","ir","lidar"))
        if (not selected and not missing) or (len(selected)==1 and missing):
            dest=isolated/entry["capture_id"]; dest.mkdir(parents=True)
            os.link(dataset/entry["capture_id"]/"observation.json",dest/"observation.json")
            for modality in ("rgb","ir","lidar"):
                for value in obs[modality].get("data",{}).values():
                    if isinstance(value,dict) and "artifact" in value:
                        name=value["artifact"]["id"]; os.link(dataset/entry["capture_id"]/name,dest/name)
            load_observation_only(isolated,{"capture_id":entry["capture_id"]})
            selected.append(entry["capture_id"])
    assert len(selected)==2 and unavailable>0
    summary={"profile":"temporal-sequence.v1","specifications_sha256":canonical_hash(specs),
        "manifest_sha256":manifest_sha,"captures":len(manifest["captures"]),"counts":manifest["counts"],
        "sequences":per_sequence,"checks":{"cold_cache_resume":True,"published_prefix_unchanged_files":len(prefix),
        "uninterrupted_replay_equal_files":compared,"completed_resume_keeps_manifest":True,
        "frozen_anchor_camera_artifacts_equal":matched_camera_artifacts,"frozen_anchor_boxes_match":True,
        "all_missing_frames":unavailable,"maximum_object_transform_error":maximum_motion_error,
        "maximum_drift_translation_error_m":maximum_drift_error,"maximum_thermal_change_k":heat_change,
        "observation_only_capture_ids":selected},"stages":stages,
        "limits":["synthetic constant linear/yaw motion with global shutter, single-first-return LiDAR",
                  "no temporal detector training or quality promotion; SF-14 follows separately"]}
    (args.output/"acceptance.json").write_text(json.dumps(summary,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(summary),flush=True)


if __name__=="__main__":
    main()

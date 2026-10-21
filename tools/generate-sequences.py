"""Generate paired temporal scene families using the existing capture generator."""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import subprocess
import sys

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"backend"))
from app.sequences import validate_sequences


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--frames",type=int,default=32)
    parser.add_argument("--layouts",type=int,default=3)
    parser.add_argument("--seed-offset",type=int,default=700000)
    parser.add_argument("--prefix",default="sf13")
    parser.add_argument("--object-speed",type=float,default=.5,help="Moving target speed along world +X in m/s")
    parser.add_argument("--width",type=int,default=640)
    parser.add_argument("--height",type=int,default=384)
    parser.add_argument("--rows",type=int,default=32)
    parser.add_argument("--columns",type=int,default=256)
    args=parser.parse_args()
    if not 0<=args.object_speed<=30:
        parser.error("Object speed must be 0..30 m/s")
    if not 2<=args.frames<=100000 or not 1<=args.layouts<=6 or len(args.prefix)>40 or not args.prefix.isascii() or not args.prefix.replace('-','').replace('_','').isalnum():
        parser.error("Use 2..100000 frames, 1..6 layouts and a short ASCII ID prefix")
    args.output.parent.mkdir(parents=True,exist_ok=True)
    if args.output.exists():
        raise ValueError("Sequence specification already exists")
    source=args.output.with_suffix(".source-requests.json")
    if source.exists():
        raise ValueError("Source requests already exist")
    subprocess.run(["node","--experimental-strip-types","tools/generate-sf10-requests.ts","--learning",
        "--layouts",str(args.layouts),"--count",str(args.layouts*50),"--seed-offset",str(args.seed_offset),
        "--width",str(args.width),"--height",str(args.height),"--rows",str(args.rows),"--columns",str(args.columns),
        "--output",str(source.resolve())],cwd=ROOT,check=True)
    captures=json.loads(source.read_text(encoding="utf-8"))["requests"]
    specs=[]
    for layout in range(args.layouts):
        base=copy.deepcopy(captures[layout*50]["request"])
        for sensor in base["rig"]["sensors"]:
            sensor["available"]=True
            if sensor["modality"]=="lidar": sensor["scan_duration_s"]=.1
        base["rig"]["timing_profile"]="timed-scan"
        optical=next(s for s in base["rig"]["sensors"] if s["modality"]=="rgb")
        camera=np.array(base["rig"]["T_world_from_rig"]).reshape(4,4)@np.array(optical["T_rig_from_sensor"]).reshape(4,4)
        inverse=np.linalg.inv(camera)
        def visible_distance(instance):
            m=np.array(instance["T_world_from_asset"]).reshape(4,4)
            point=inverse@np.array([m[0,3],m[1,3]+2,m[2,3],1])
            return float(np.linalg.norm(point[:2])/point[2]) if point[2]>1 else 1e9
        target=min(base["world"]["instances"],key=visible_distance)
        target["operating_state"]="off"
        base["temporal"]={"schema_version":"lab.v1","kind":"TemporalCapture","profile":"rig-motion-drift.v1",
            "reference_time_s":0,"velocity_world_m_per_s":[.15,0,0],"yaw_rate_rad_per_s":0,"sensor_drift":[],
            "object_motion":[{"instance_id":target["instance_id"],"velocity_world_m_per_s":[args.object_speed,0,0],"yaw_rate_rad_per_s":.03}]}
        for variant in ("clean","drift-outages"):
            capture=copy.deepcopy(base)
            if variant!="clean":
                capture["temporal"]["sensor_drift"]=[{"modality":m,"translation_rig_m":[.1,0,0],
                    "translation_rate_rig_m_per_s":[.01,0,0],"yaw_rad":.005,"yaw_rate_rad_per_s":.001} for m in ("rgb","ir","lidar")]
            if args.frames>=16:
                windows=[(.125,.25,["rgb"]),(.3125,.4375,["ir"]),(.5,.625,["lidar"]),(.6875,.875,["rgb","ir","lidar"])]
            else:
                windows=[(.25,.75,["rgb","ir","lidar"])]
            outages=[] if variant=="clean" else [{"start_frame":int(a*args.frames),"stop_frame":max(int(a*args.frames)+1,int(b*args.frames)),"modalities":modalities} for a,b,modalities in windows]
            spec={"schema_version":"lab.v1","kind":"SequenceSpec","profile":"temporal-sequence.v1",
                "sequence_id":f"{args.prefix}-l{layout}-{variant}","family_id":f"{args.prefix}-family-{layout}",
                "variant_id":variant,"group_id":captures[layout*50]["group_id"],
                "split":("train","validation","test")[layout%3],"frame_count":args.frames,
                "frame_interval_s":.2,"start_time_s":0,"base_capture":capture,"outages":outages,
                "operating_events":[{"frame_index":1,"instance_id":target["instance_id"],"operating_state":"running"}]}
            specs.append(spec)
    validate_sequences(specs)
    args.output.write_text(json.dumps({"version":"temporal-sequences.v1","sequences":specs},indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"sequences":len(specs),"captures":len(specs)*args.frames,"frames":args.frames}),flush=True)


if __name__=="__main__":
    main()

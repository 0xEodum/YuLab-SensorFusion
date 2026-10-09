"""Publish all paired quality cases, failed controls, resources and byte hashes."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"backend"))
import numpy as np
import torch
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from learning.quality_acceptance import validate_freeze
from learning.decision_inference import DecisionFusionPredictor


def read(path): return json.loads(path.read_text())


def write(path,value): path.write_text(json.dumps(value,indent=2,allow_nan=False)+"\n",encoding="utf-8")


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--acceptance",type=Path,required=True)
    p.add_argument("--dataset",type=Path,required=True)
    p.add_argument("--protocol",type=Path,required=True)
    p.add_argument("--output",type=Path,default=ROOT / "docs/evidence/sf-quality")
    a=p.parse_args(); a.output.mkdir(parents=True,exist_ok=True)
    frozen=read(a.acceptance/"freeze.json")
    ensemble_mode=frozen["protocol"]["candidate"]["profile"] == "independent-experts-initialization-consensus.v1"
    snapshot_mode=ensemble_mode or frozen["protocol"]["candidate"]["profile"] == "independent-experts-snapshot-consensus.v1"
    prefix="ensemble" if ensemble_mode else ("snapshot" if snapshot_mode else "swa")
    validate_freeze(ROOT,frozen,a.protocol,a.dataset/"manifest.json")
    summaries={s:read(a.acceptance/s/"summary.json") for s in ("validation","test")}
    for split,summary in summaries.items():
        write(a.output/f"{prefix}-{split}-summary.json",summary)
        for path in (a.acceptance/split).glob("*-seed-*.json"):
            value=read(path)
            # Keep every scenario and clean per-condition results; complete
            # scenario-by-condition matrices remain in the immutable run root.
            for name,case in value["cases"].items():
                if name != "availability-7": case.pop("conditions",None)
            write(a.output/f"{prefix}-{split}-{path.name}",value)
    write(a.output/f"{prefix}-freeze.json",frozen)
    methods=list(summaries["test"]["methods"])
    fig,axes=plt.subplots(1,2,figsize=(13,5),layout="constrained")
    for ax,metric,title,limit in zip(axes,("clean_map","degradation_macro"),("Clean oriented 3D mAP","Degradation macro mAP"),(.5,.35)):
        means=[summaries["test"]["methods"][n][metric]["mean"] for n in methods]
        sd=[summaries["test"]["methods"][n][metric]["sample_sd"] for n in methods]
        colors=["#117864" if n == "candidate" else "#7f8c8d" for n in methods]
        ax.barh(methods,means,xerr=sd,color=colors,capsize=3); ax.invert_yaxis()
        ax.axvline(limit,color="#a93226",linestyle="--",label="quality target")
        ax.set(xlim=(0,1),xlabel="Mean mAP; error bars = sample SD across disjoint ensembles" if ensemble_mode else "Mean mAP; error bars = sample SD across all seeds",title=title)
        ax.grid(axis="x",alpha=.2); ax.legend(loc="lower right")
    fig.suptitle(f"Fresh 600-frame holdout; {len(summaries['test']['seeds'])} complete paired {'ensembles' if ensemble_mode else 'seeds'}")
    fig.savefig(a.output/"fresh-holdout.png",dpi=180); plt.close(fig)
    names=summaries["test"]["macro_cases"]
    fig,ax=plt.subplots(figsize=(12,5),layout="constrained")
    for method in ("candidate","fusion","fusion-360","fusion-swa","lidar","ir","rgb") + (("fusion-snapshots",) if snapshot_mode else ()):
        rows=[read(a.acceptance/"test"/f"{method}-seed-{s}.json") for s in summaries["test"]["seeds"]]
        values=np.array([[r["cases"][c]["map_3d"] for c in names] for r in rows])
        ax.plot(range(len(names)),values.mean(0),marker="o",label=method)
    ax.set(xticks=range(len(names)),xticklabels=names,ylim=(0,1),ylabel="Mean oriented 3D mAP",title="Every included degradation case; unchanged labels")
    ax.tick_params(axis="x",rotation=40); ax.grid(alpha=.2); ax.legend(ncol=2)
    fig.savefig(a.output/"fresh-degradation-cases.png",dpi=180); plt.close(fig)
    evidence={"environment":{"python":platform.python_version(),"torch":torch.__version__,"gpu":torch.cuda.get_device_name(),
                             "concurrent_unrelated_training":True},"datasets":{"training_sha256":frozen["protocol"]["dataset_sha256"],"evaluation_sha256":frozen["dataset_sha256"]},
              "checks":{"validation_accepted":summaries["validation"]["accepted"],"fresh_test_accepted":summaries["test"]["accepted"],
                        "all_missing_zero_detections":all(read(a.acceptance/"test"/f"candidate-seed-{s}.json")["cases"]["availability-0"]["detections"] == 0 for s in summaries["test"]["seeds"])},
              "scope_limits":["static synthetic three-class scene family","known/exposed corruption probes, not unseen real sensor faults","ensemble SD measures optimization variability across three disjoint three-initialization ensembles, not single-initialization stability or dataset sampling confidence" if ensemble_mode else "seed SD measures optimization variability, not dataset sampling confidence",f"{18 if ensemble_mode else (6 if snapshot_mode else 3)} inference networks, not single-network compute parity"]}
    write(a.output/"acceptance-checks.json",evidence)
    default_seed=min(frozen["protocol"].get("all_seeds",[11,12,13]))
    experts=[]
    members=frozen["protocol"]["initialization_groups"][0] if ensemble_mode else [default_seed]
    for seed in members:
        for filename in (("raw-best.pt","best.pt") if snapshot_mode else ("best.pt",)):
            for m in ("rgb","ir","lidar"):
                if filename == "raw-best.pt" and seed < 14:
                    path=f"artifacts/sf-quality/{'baseline-120' if seed == 11 else f'baseline-120-seed-{seed}'}/runs/{m}/best.pt"
                else: path=f"artifacts/sf-quality/swa-seed-{seed}/{m}/{filename}"
                record=next(x for x in frozen["checkpoints"] if x["path"] == path)
                experts.append({"modality":m,"snapshot":filename,"seed":seed,**record})
    predictor=DecisionFusionPredictor([ROOT/x["path"] for x in experts],expected_hashes=[x["sha256"] for x in experts])
    write(a.output/"model-bundle.json",{"profile":frozen["protocol"]["candidate"]["profile"],"default_seed":default_seed,"checkpoint_sha256":predictor.sha256,
                                         "training_sha256":frozen["protocol"]["dataset_sha256"],"averaged_epochs":60,"consensus_iou":.1,
                                         "weights":[1]*9,"member_seeds":members,"experts":experts,"inference_cli":"tools/infer-decision-fusion.py"})
    artifacts=[]
    for path in sorted(a.output.iterdir()):
        if path.name == "artifact-manifest.json" or not path.is_file(): continue
        artifacts.append({"path":path.relative_to(ROOT).as_posix(),"sha256":hashlib.sha256(path.read_bytes()).hexdigest(),"bytes":path.stat().st_size})
    write(a.output/"artifact-manifest.json",{"artifacts":artifacts,"manifest_excludes_itself":True})
    print(json.dumps(evidence),flush=True)


if __name__ == "__main__": main()

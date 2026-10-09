"""Observation-only late fusion of independently trained sensor detections."""
import numpy as np
from .evaluate import box_iou


def fuse(experts, available, iou_threshold=.1, weights=None):
    """Greedy class-consistent box consensus; unavailable experts never participate.

    A cluster contains at most one box from each sensor. The score is the sum
    of supporting confidence divided by available sensor weight. Pi-periodic
    yaw averaging respects the equivalence of upright box orientations.
    """
    if len(experts) != 3 or len(available) != 3:
        raise ValueError("Expected RGB, IR and LiDAR experts")
    weights = np.ones((3, 3)) if weights is None else np.asarray(weights)
    if weights.shape != (3, 3) or not np.isfinite(weights).all() or (weights <= 0).any():
        raise ValueError("Weights must be positive sensor-by-class values")
    if not 0 < iou_threshold <= 1: raise ValueError("Invalid overlap threshold")
    candidates = []
    for sensor, prediction in enumerate(experts):
        if not available[sensor]: continue
        for box, cls, score in zip(prediction["boxes"], prediction["classes"], prediction["scores"]):
            candidates.append((float(score) * weights[sensor, int(cls)], sensor, box, int(cls)))
    candidates.sort(key=lambda x: -x[0])
    used = set(); boxes=[]; classes=[]; scores=[]
    for i, (confidence, sensor, box, cls) in enumerate(candidates):
        if i in used: continue
        used.add(i); group=[(confidence, box)]; sensors={sensor}
        for j, (other_confidence, other_sensor, other_box, other_cls) in enumerate(candidates):
            if j in used or other_sensor in sensors or other_cls != cls: continue
            if box_iou(box, other_box) >= iou_threshold:
                used.add(j); sensors.add(other_sensor); group.append((other_confidence, other_box))
        confidences=np.array([x[0] for x in group]); members=np.stack([x[1] for x in group])
        merged=np.average(members,axis=0,weights=confidences)
        merged[6]=.5*np.arctan2(np.sum(confidences*np.sin(2*members[:,6])),np.sum(confidences*np.cos(2*members[:,6])))
        boxes.append(merged); classes.append(cls)
        scores.append(float(confidences.sum() / weights[np.asarray(available,dtype=bool),cls].sum()))
    # Bound output capacity for the common native evaluator. Top-16 is fixed
    # independent of labels and greatly exceeds observed eligible object counts.
    order=np.argsort(-np.asarray(scores),kind="stable")[:16]
    return {"boxes":np.asarray(boxes,dtype=np.float32).reshape(-1,7)[order],
            "classes":np.asarray(classes,dtype=np.int64)[order],"scores":np.asarray(scores,dtype=np.float32)[order]}


def snapshot_experts(snapshots, available, iou_threshold=.1):
    """Two fixed training snapshots per sensor."""
    if len(snapshots) != 3 or any(len(values) != 2 for values in snapshots):
        raise ValueError("Expected two snapshots for each of three sensors")
    empty={"boxes":np.empty((0,7),dtype=np.float32),"classes":np.empty(0,dtype=np.int64),"scores":np.empty(0,dtype=np.float32)}
    experts=[fuse([*values,empty],[True,True,False],iou_threshold) if available[m] else empty for m,values in enumerate(snapshots)]
    return experts


def fuse_snapshots(snapshots, available, iou_threshold=.1):
    return fuse(snapshot_experts(snapshots,available,iou_threshold),available,iou_threshold)


def initialization_experts(runs, available, iou_threshold=.1):
    """Exactly three independent initialization trajectories per sensor."""
    if len(runs) != 3: raise ValueError("Require three independent initializations")
    members=[snapshot_experts(r,available,iou_threshold) for r in runs]
    return [fuse([members[k][m] for k in range(3)],[True]*3,iou_threshold) for m in range(3)]


def fuse_initializations(runs, available, iou_threshold=.1):
    return fuse(initialization_experts(runs,available,iou_threshold),available,iou_threshold)

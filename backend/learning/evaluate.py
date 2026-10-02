"""Independent yaw-oriented 3D IoU and score-ranked one-to-one AP evaluator.

Boxes are in metres. Fully hidden discoveries and duplicate detections are FPs;
only eligibility controls positives, never input generation or predictions.
"""
from __future__ import annotations

import numpy as np

NAMES = ("aircraft", "ground_vehicle", "ship")
THRESHOLDS = (.25, .25, .5)


def rectangle(box):
    x, _, z, w, _, length, yaw = box
    corners = np.array([[-w/2, -length/2], [w/2, -length/2], [w/2, length/2], [-w/2, length/2]])
    c, s = np.cos(yaw), np.sin(yaw)
    return corners @ np.array([[c, -s], [s, c]]) + [x, z]


def cross(a, b):
    return a[0] * b[1] - a[1] * b[0]


def box_iou(a, b):
    if not np.isfinite(a).all() or not np.isfinite(b).all() or min(*a[3:6], *b[3:6]) <= 0:
        raise ValueError("Invalid detection box")
    height = max(0, min(a[1] + a[4]/2, b[1] + b[4]/2) - max(a[1] - a[4]/2, b[1] - b[4]/2))
    if height == 0:
        return 0.0
    polygon = list(rectangle(a))
    clip = rectangle(b)
    for start, end in zip(clip, np.roll(clip, -1, axis=0)):
        original, polygon = polygon, []
        if not original:
            break
        previous = original[-1]
        previous_side = cross(end - start, previous - start)
        for current in original:
            side = cross(end - start, current - start)
            if (side >= -1e-10) != (previous_side >= -1e-10):
                fraction = previous_side / (previous_side - side)
                polygon.append(previous + fraction * (current - previous))
            if side >= -1e-10:
                polygon.append(current)
            previous, previous_side = current, side
    area = 0.0 if len(polygon) < 3 else abs(sum(cross(p, q) for p, q in
        zip(polygon, polygon[1:] + polygon[:1]))) / 2
    intersection = area * height
    return float(np.clip(intersection / (np.prod(a[3:6]) + np.prod(b[3:6]) - intersection), 0, 1))


def match_frames(predictions, targets, overlaps=None):
    """Cache frame-local one-to-one matches for global and condition reductions."""
    result = []
    for frame_index,(prediction, target) in enumerate(zip(predictions, targets)):
        frame = {"positives": [int(np.count_nonzero(target["classes"] == cls)) for cls in range(3)],
                 "empty": len(target["boxes"]) == 0, "records": []}
        for cls in range(3):
            ranked = sorted([(float(score), box, k) for k,(box,label,score) in enumerate(
                zip(prediction["boxes"], prediction["classes"], prediction["scores"])) if label == cls], key=lambda x: -x[0])
            used = set()
            wanted_boxes = target["boxes"][target["classes"] == cls]
            # Reject disjoint bounding intervals in bulk before exact polygon
            # clipping. Broad phase never decides a hit; overlapping pairs use
            # the original scalar 3D IoU, including its tolerances.
            if len(wanted_boxes) and overlaps is None:
                rectangles = np.array([rectangle(b) for b in wanted_boxes])
                lower, upper = rectangles.min(1), rectangles.max(1)
                height_lower = wanted_boxes[:, 1] - wanted_boxes[:, 4]/2
                height_upper = wanted_boxes[:, 1] + wanted_boxes[:, 4]/2
            wanted_ids = np.flatnonzero(target["classes"] == cls)
            for score, box, prediction_index in ranked:
                candidates = []
                if overlaps is not None:
                    candidates = [(float(overlaps[frame_index][prediction_index,j]),int(j)) for j in wanted_ids if j not in used]
                elif len(wanted_boxes):
                    bounds = rectangle(box)
                    possible = ((upper >= bounds.min(0)-1e-8) & (lower <= bounds.max(0)+1e-8)).all(1)
                    possible &= (height_upper >= box[1]-box[4]/2) & (height_lower <= box[1]+box[4]/2)
                    candidates = [(box_iou(box, wanted_boxes[k]) if possible[k] else 0.0, int(j))
                                  for k,j in enumerate(wanted_ids) if j not in used]
                overlap, match = max(candidates, default=(0, -1))
                hit = overlap >= THRESHOLDS[cls]
                error = None
                if hit:
                    used.add(match)
                    error = float(np.linalg.norm(box[:3] - target["boxes"][match, :3]))
                frame["records"].append((cls, score, hit, error))
        result.append(frame)
    return result


def evaluate(predictions, targets, matches=None):
    matches = match_frames(predictions, targets) if matches is None else matches
    classes, confidence, correct, errors = {}, [], [], []
    false_positives = empty_fp = 0
    for cls, name in enumerate(NAMES):
        count = sum(frame["positives"][cls] for frame in matches)
        ranked = sorted([(score, i, hit, error) for i, frame in enumerate(matches)
                         for label, score, hit, error in frame["records"] if label == cls], key=lambda x: -x[0])
        hits = []
        for score, frame, hit, error in ranked:
            hits.append(int(hit)); confidence.append(score); correct.append(int(hit))
            if hit:
                errors.append(error)
            else:
                false_positives += 1
                empty_fp += matches[frame]["empty"]
        tp = np.cumsum(hits); fp = np.arange(1, len(hits) + 1) - tp
        recall = tp / max(count, 1); precision = tp / np.maximum(tp + fp, 1)
        r = np.r_[0, recall, 1]; p = np.r_[0, precision, 0]
        p = np.maximum.accumulate(p[::-1])[::-1]
        ap = float(np.sum((r[1:] - r[:-1]) * p[1:])) if count else None
        classes[name] = {"positives": count, "predictions": len(ranked), "iou_threshold": THRESHOLDS[cls],
                         "ap": ap, "recall": float(tp[-1] / count) if count and len(tp) else (0.0 if count else None)}
    c, y = np.array(confidence), np.array(correct)
    ece = 0.0
    for lo in np.arange(0, 1, .1):
        mask = (c >= lo) & (c < lo + .1 + (1e-8 if lo > .89 else 0))
        if mask.any():
            ece += float(mask.sum() / max(len(c), 1) * abs(c[mask].mean() - y[mask].mean()))
    values = [v["ap"] for v in classes.values() if v["ap"] is not None]
    return {"classes": classes, "map_3d": float(np.mean(values)) if values else None,
            "false_positives": false_positives, "empty_scene_false_positives": int(empty_fp),
            "empty_scenes": sum(len(t["boxes"]) == 0 for t in targets), "detection_ece_10_bins": ece,
            "matched_center_error_m": float(np.mean(errors)) if errors else None}

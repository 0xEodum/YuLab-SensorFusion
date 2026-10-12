"""essrf-static-v1 objective: focal + localization NLL + L1, subset and evidential terms.

Supervision tensors (boxes, support, corruption regions) are used only here and
in the augmentation masks; the model never receives them.
"""
from __future__ import annotations

import math
import numpy as np
import torch
import torch.nn.functional as F
from scipy.optimize import linear_sum_assignment

from .essrf_model import CENTER_UNIT

NO_OBJECT = 3
CLASS_WEIGHTS = (1., 1., 1., .15)
FOCAL_GAMMA = 2.0
WEIGHTS = {"nll": .1, "center": 8., "extent": .5, "yaw": .2, "rel": .1, "cal": .1, "vac": .05}


def pack(targets: list[dict], device) -> dict:
    counts = np.array([len(t["boxes"]) for t in targets], dtype=np.int64)
    width = max(1, int(counts.max(initial=0)))
    boxes = torch.zeros(len(targets), width, 7); boxes[..., 3:6] = 1
    classes = torch.zeros(len(targets), width, dtype=torch.long)
    support = torch.zeros(len(targets), width, 3, dtype=torch.bool)
    for i, t in enumerate(targets):
        boxes[i, :counts[i]] = t["boxes"]; classes[i, :counts[i]] = t["classes"]
        support[i, :counts[i]] = t["support"]
    return {"boxes": boxes.to(device), "classes": classes.to(device), "support": support.to(device),
            "counts": counts}


def select(packed: dict, ids) -> dict:
    index = torch.as_tensor(ids, device=packed["boxes"].device)
    return {"boxes": packed["boxes"][index], "classes": packed["classes"][index],
            "support": packed["support"][index], "counts": packed["counts"][np.asarray(ids)]}


@torch.no_grad()
def match(boxes, probability, targets, counts) -> torch.Tensor:
    """Per-frame Hungarian assignment; returns [B,Q] target column or -1."""
    batch, queries = probability.shape[:2]
    wanted, classes = targets["boxes"], targets["classes"]
    cost = 8 * torch.cdist(boxes[..., :3], wanted[..., :3], p=1) + \
        4 * torch.cdist(boxes[..., 3:6], wanted[..., 3:6], p=1) - \
        probability.gather(2, classes[:, None, :].expand(-1, queries, -1))
    costs = cost.float().cpu().numpy()
    assignment = np.full((batch, queries), -1, dtype=np.int64)
    for i, count in enumerate(counts):
        if count:
            if count > queries:
                raise ValueError("Targets exceed query capacity")
            row, col = linear_sum_assignment(costs[i, :, :count])
            assignment[i, row] = col
    return torch.from_numpy(assignment).to(boxes.device)


def heading_targets(truth, inputs):
    """World-axis scaled boxes -> heading-frame NLL parameters [.., 8]."""
    center = torch.einsum("bji,bqj->bqi", inputs["world_from_heading"], truth[..., :3]) * CENTER_UNIT
    yaw = truth[..., 6] - inputs["heading_yaw"][:, None]
    return torch.cat((center, (truth[..., 3:6] * 200).log(), torch.sin(yaw)[..., None],
                      torch.cos(yaw)[..., None]), -1)


def detection(out, targets, counts, inputs, frame_weight=None):
    """Focal on (gated) probabilities, Gaussian NLL and L1 on matched boxes."""
    probability, boxes = out["probability"], out["boxes"]
    matched = match(boxes, probability, targets, counts)
    valid = matched >= 0
    columns = matched.clamp_min(0)
    labels = targets["classes"].gather(1, columns).masked_fill(~valid, NO_OBJECT)
    weights = probability.new_tensor(CLASS_WEIGHTS)[labels]
    p_true = probability.gather(2, labels[..., None])[..., 0].clamp(1e-7, 1)
    focal = (-(1 - p_true) ** FOCAL_GAMMA * p_true.log() * weights).sum(1) / weights.sum(1)
    truth = targets["boxes"].gather(1, columns[..., None].expand(-1, -1, 7))
    target_params = heading_targets(truth, inputs)
    variance = out["variance"]
    # v1: the NLL trains the variance only; box means are trained by the L1 terms.
    nll = .5 * ((target_params - out["mean"].detach()) ** 2 / variance + variance.log()).sum(-1)
    center = (boxes[..., :3] - truth[..., :3]).abs().mean(-1)
    extent = (boxes[..., 3:6].log() - truth[..., 3:6].log()).abs().mean(-1)
    yaw = 1 - torch.cos(boxes[..., 6] - truth[..., 6])
    box = WEIGHTS["nll"] * nll + WEIGHTS["center"] * center + WEIGHTS["extent"] * extent + WEIGHTS["yaw"] * yaw
    per_frame = focal + (box * valid).sum(1) / valid.sum(1).clamp_min(1)
    if frame_weight is None:
        frame_weight = torch.ones_like(per_frame)
    loss = (per_frame * frame_weight).sum() / frame_weight.sum().clamp_min(1)
    parts = {"focal": float(focal.detach().mean()), "nll": float((nll.detach() * valid).sum() / valid.sum().clamp_min(1))}
    return loss, matched, parts


def reliability_targets(matched, targets, regions, available):
    """y, known-mask and OOD indicator [B,Q,3] for the evidential terms (reliability-targets.v1)."""
    valid = matched >= 0
    support = targets["support"].gather(1, matched.clamp_min(0)[..., None].expand(-1, -1, 3)) & valid[..., None]
    known, ood = regions["known"], regions["ood"]
    target = support & ~known
    labelled = (valid[..., None] | known) & ~ood & available[:, None, :]
    return target.float(), labelled, ood & available[:, None, :]


def evidential(out, y, labelled, ood):
    """psi-form expected NLL, reliability-mean calibration and vacuity objectives."""
    evidence = out["evidence"]
    alpha_pos, alpha_neg = evidence[..., 0] + 1, evidence[..., 1] + 1
    strength = alpha_pos + alpha_neg
    rel = torch.digamma(strength) - y * torch.digamma(alpha_pos) - (1 - y) * torch.digamma(alpha_neg)
    cal = (alpha_pos / strength - y) ** 2
    vacuity = 2 / strength
    vac = torch.where(ood, (1 - vacuity) ** 2, vacuity ** 2)
    # Class-balanced per modality: background in corrupted regions outnumbers matched queries.
    positive = labelled & (y > .5); negative = labelled & (y <= .5)
    known = positive.float() / positive.sum((0, 1), keepdim=True).clamp_min(1) +         negative.float() / negative.sum((0, 1), keepdim=True).clamp_min(1)
    known = known * labelled.sum() / known.sum().clamp_min(1e-12)
    exposed = (labelled | ood).float()
    loss = (WEIGHTS["rel"] * (rel * known).sum() + WEIGHTS["cal"] * (cal * known).sum()) / known.sum().clamp_min(1) + \
        WEIGHTS["vac"] * (vac * exposed).sum() / exposed.sum().clamp_min(1)
    rel = rel.detach()
    return loss, {"rel": float((rel * known).sum() / known.sum().clamp_min(1)),
                  "labelled": float(known.sum()), "ood": float(ood.sum())}


# ---------------------------------------------------------------- augmentation
def augment(inputs, generator, p_known=.25, p_ood=.1):
    """Local corruptions on a copy of the batch. Returns inputs and region descriptors.

    Known family (labelled unreliable, y=0): uniform noise rectangles in cameras,
    deleted points in a LiDAR azimuth wedge. OOD family (o=1, never labelled):
    stripe rectangles in cameras, large jitter in a LiDAR wedge.
    """
    device = inputs["rgb"].device
    batch = inputs["rgb"].shape[0]
    out = dict(inputs)
    out["rgb"], out["ir"], out["lidar"] = inputs["rgb"].clone(), inputs["ir"].clone(), inputs["lidar"].clone()
    out["point_valid"] = inputs["point_valid"].clone()
    rects = torch.zeros(batch, 2, 4, device=device)          # per camera: u0, v0, u1, v1 (pixels)
    wedges = torch.zeros(batch, 2, device=device)             # LiDAR azimuth start, end
    family = torch.zeros(batch, 3, dtype=torch.long, device=device)  # 0 none, 1 known, 2 ood
    draw = torch.rand(batch, 3, generator=generator, device=device)
    family[draw < p_known + p_ood] = 2
    family[draw < p_known] = 1
    rows = torch.arange(384, device=device)[:, None]; cols = torch.arange(640, device=device)[None]
    for b in range(batch):
        for c, name in enumerate(("rgb", "ir")):
            if family[b, c] == 0:
                continue
            size = torch.rand(2, generator=generator, device=device) * .35 + .25
            start = torch.rand(2, generator=generator, device=device) * (1 - size)
            u0, u1 = float(start[0] * 640), float((start[0] + size[0]) * 640)
            v0, v1 = float(start[1] * 384), float((start[1] + size[1]) * 384)
            rects[b, c] = torch.tensor([u0, v0, u1, v1], device=device)
            mask = (cols >= u0) & (cols < u1) & (rows >= v0) & (rows < v1)
            if family[b, c] == 1:
                noise = torch.rand((384, 640), generator=generator, device=device)
            else:
                noise = ((rows // 4) % 2).float().expand(384, 640)
            if name == "rgb":
                value = (noise * 254 + 1).to(torch.uint8)
                out["rgb"][b] = torch.where(mask, value, out["rgb"][b])
            else:
                out["ir"][b] = torch.where(mask, noise.half() * 2, out["ir"][b])
        if family[b, 2]:
            start = float((torch.rand(1, generator=generator, device=device) * 2 - 1) * .6)
            width = float(torch.rand(1, generator=generator, device=device) * .3 + .2)
            wedges[b] = torch.tensor([start, start + width], device=device)
            xyz = out["lidar"][b, :, :3]
            azimuth = torch.atan2(xyz[:, 0], -xyz[:, 2])
            inside = (azimuth >= start) & (azimuth < start + width) & out["point_valid"][b]
            if family[b, 2] == 1:
                out["point_valid"][b] &= ~inside
                out["lidar"][b] = torch.where(inside[:, None], torch.zeros_like(out["lidar"][b]), out["lidar"][b])
            else:
                jitter = (torch.rand(xyz.shape, generator=generator, device=device) * 2 - 1) * (10 / 200)
                out["lidar"][b, :, :3] = torch.where(inside[:, None], xyz + jitter, xyz)
    return out, {"rects": rects, "wedges": wedges, "family": family}


@torch.no_grad()
def query_regions(out, inputs, regions):
    """Which stream references fall inside each modality's corrupted region [B,Q,3]."""
    references = out["stream_references"]  # [B,Q,3,3] heading frame, per modality
    batch, queries = references.shape[:2]
    inside = torch.zeros(batch, queries, 3, dtype=torch.bool, device=references.device)
    for c, name in enumerate(("rgb", "ir")):
        x = references[:, :, c]
        homogeneous = torch.cat((x, torch.ones_like(x[..., :1])), -1)
        camera = torch.einsum("bij,bqj->bqi", inputs[f"{name}_from_heading"], homogeneous)[..., :3]
        k = inputs[f"{name}_intrinsics"]
        depth = camera[..., 2].clamp_min(.5)
        u = k[:, None, 0] * camera[..., 0] / depth + k[:, None, 2]
        v = k[:, None, 1] * camera[..., 1] / depth + k[:, None, 3]
        r = regions["rects"][:, c]
        inside[..., c] = (camera[..., 2] > .5) & (u >= r[:, None, 0]) & (u < r[:, None, 2]) & \
            (v >= r[:, None, 1]) & (v < r[:, None, 3])
    x = references[:, :, 2]
    azimuth = torch.atan2(x[..., 0], -x[..., 2])
    w = regions["wedges"]
    inside[..., 2] = (azimuth >= w[:, None, 0]) & (azimuth < w[:, None, 1])
    family = regions["family"][:, None, :]
    return {"known": inside & (family == 1), "ood": inside & (family == 2)}


def availability_patterns(batch, generator, device, p_full=.5, *, exact_full=False):
    """Legacy sampling includes pattern 7 in the random branch; curriculum excludes it."""
    if not 0 <= p_full <= 1:
        raise ValueError("Full-sensor probability must be in [0, 1]")
    pattern = torch.randint(0, 7 if exact_full else 8, (batch,), generator=generator, device=device)
    pattern = torch.where(torch.rand(batch, generator=generator, device=device) < p_full,
                          torch.full_like(pattern, 7), pattern)
    bits = torch.stack([(pattern >> m) & 1 for m in range(3)], 1).bool()
    return bits


def sample_expert_subsets(available, generator):
    """One non-empty subset of each frame's available modalities (0 when none)."""
    mask = available.long()
    available_bits = mask[:, 0] | mask[:, 1] << 1 | mask[:, 2] << 2
    choices = []
    for bits in available_bits.tolist():
        options = [s for s in range(1, 8) if s & bits == s]
        if not options:
            choices.append(0); continue
        index = int(torch.randint(0, len(options), (1,), generator=generator, device=available.device))
        choices.append(options[index])
    return torch.tensor(choices, device=available.device)

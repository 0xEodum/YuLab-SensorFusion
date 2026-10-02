"""Learned query baselines: no scene ID, weather, object lists or oracle proposals."""
from __future__ import annotations

import torch
import numpy as np
from torch import nn
import torch.nn.functional as F
from scipy.optimize import linear_sum_assignment

MODALITIES = {"rgb": ("rgb",), "ir": ("ir",), "lidar": ("lidar",), "fusion": ("rgb", "ir", "lidar")}


class ImageEncoder(nn.Module):
    def __init__(self, channels: int, width: int):
        super().__init__()
        self.net = nn.Sequential(nn.Conv2d(channels, 16, 5, 2, 2), nn.GroupNorm(4, 16), nn.GELU(),
                                 nn.Conv2d(16, 32, 3, 2, 1), nn.GroupNorm(4, 32), nn.GELU(),
                                 nn.Conv2d(32, width, 3, 2, 1), nn.GELU(), nn.AvgPool2d(2))
        self.position = nn.Parameter(torch.randn(1, 60, width) * .02)

    def forward(self, image):
        return self.net(image).flatten(2).transpose(1, 2) + self.position


class Detector(nn.Module):
    def __init__(self, modality: str, queries: int = 16, width: int = 64):
        super().__init__()
        if modality not in MODALITIES:
            raise ValueError("Unsupported baseline")
        self.modality, self.queries, self.width = modality, queries, width
        self.encoders = nn.ModuleDict({m: ImageEncoder(3 if m == "rgb" else 1, width) if m != "lidar" else
            nn.Sequential(nn.Linear(4, width), nn.GELU(), nn.Linear(width, width)) for m in MODALITIES[modality]})
        self.calibration = nn.Sequential(nn.Linear(32, width), nn.GELU(), nn.Linear(width, width))
        self.query = nn.Parameter(torch.randn(queries, width) * .1)
        self.decoder = nn.TransformerDecoder(nn.TransformerDecoderLayer(width, 4, width * 2,
            dropout=0, batch_first=True), 2)
        self.classifier = nn.Linear(width, 4)  # three classes and no-object
        self.box = nn.Sequential(nn.Linear(width, width), nn.GELU(), nn.Linear(width, 8))

    def forward(self, inputs):
        batch = inputs["calibration"].shape[0]
        tokens, masks = [], []
        for modality, encoder in self.encoders.items():
            value = encoder(inputs[modality])
            tokens.append(value)
            masks.append(~inputs["point_valid"] if modality == "lidar" else
                         torch.zeros(value.shape[:2], dtype=torch.bool, device=value.device))
        # Unmasked calibration token keeps empty scans finite, without inventing points.
        tokens.append(self.calibration(inputs["calibration"]).unsqueeze(1))
        masks.append(torch.zeros((batch, 1), dtype=torch.bool, device=tokens[0].device))
        decoded = self.decoder(self.query.unsqueeze(0).expand(batch, -1, -1), torch.cat(tokens, 1),
                               memory_key_padding_mask=torch.cat(masks, 1))
        raw = self.box(decoded)
        boxes = torch.cat((raw[..., :3], F.softplus(raw[..., 3:6]) * .15,
                           torch.atan2(raw[..., 6:7], raw[..., 7:8] + 1e-6)), -1)
        return {"logits": self.classifier(decoded), "boxes": boxes}


def detection_loss_reference(output, targets):
    loss = output["boxes"].sum() * 0
    for logits, boxes, target in zip(output["logits"], output["boxes"], targets):
        wanted = target["boxes"].to(boxes.device)
        classes = target["classes"].to(boxes.device)
        labels = torch.full((len(boxes),), 3, dtype=torch.long, device=boxes.device)
        if len(wanted):
            if len(wanted) > len(boxes):
                raise ValueError("Targets exceed learned query capacity")
            with torch.no_grad():
                cost = 8 * torch.cdist(boxes[:, :3], wanted[:, :3], p=1) + \
                       4 * torch.cdist(boxes[:, 3:6], wanted[:, 3:6], p=1) - logits.softmax(-1)[:, classes]
                row, col = linear_sum_assignment(cost.cpu().numpy())
            row = torch.as_tensor(row, device=boxes.device)
            col = torch.as_tensor(col, device=boxes.device)
            labels[row] = classes[col]
            loss = loss + 8 * F.l1_loss(boxes[row, :3], wanted[col, :3]) + \
                .5 * F.l1_loss(boxes[row, 3:6].log(), wanted[col, 3:6].log()) + \
                .2 * (1 - torch.cos(boxes[row, 6] - wanted[col, 6])).mean()
        loss = loss + F.cross_entropy(logits, labels, weight=logits.new_tensor([1, 1, 1, .15]))
    return loss / len(targets)


def pack_targets(targets, device):
    """Supervision-only padded storage; uploaded once, outside the epoch loop."""
    counts = np.array([len(t["boxes"]) for t in targets], dtype=np.int64)
    maximum = max(1, int(counts.max(initial=0)))
    if maximum > 16:
        raise ValueError("Targets exceed learned query capacity")
    boxes = torch.zeros(len(targets), maximum, 7)
    boxes[..., 3:6] = 1  # finite log extents in masked padding
    classes = torch.zeros(len(targets), maximum, dtype=torch.long)
    for i, target in enumerate(targets):
        boxes[i, :counts[i]] = target["boxes"].cpu()
        classes[i, :counts[i]] = target["classes"].cpu()
    return {"boxes": boxes.to(device), "classes": classes.to(device), "counts": counts,
            "counts_device": torch.from_numpy(counts).to(device),
            "weights": torch.tensor([1, 1, 1, .15], device=device)}


def target_batch(packed, ids):
    # counts are CPU matching metadata; neither path is supplied to Detector.
    tensor_ids = torch.as_tensor(ids, device=packed["boxes"].device, dtype=torch.long)
    return {"boxes": packed["boxes"][tensor_ids], "classes": packed["classes"][tensor_ids],
            "counts": packed["counts"][ids], "counts_device": packed["counts_device"][tensor_ids],
            "weights": packed["weights"]}


def detection_loss(output, targets, *, native=False):
    """Same per-frame objective, with one matching transfer and batched losses."""
    boxes, logits = output["boxes"], output["logits"]
    if isinstance(targets, list):
        targets = pack_targets(targets, boxes.device)
    wanted, classes, counts = targets["boxes"], targets["classes"], targets["counts"]
    batch, queries = logits.shape[:2]
    if max(counts, default=0) > queries:
        raise ValueError("Targets exceed learned query capacity")
    with torch.no_grad():
        probability = logits.softmax(-1)
        cost = 8 * torch.cdist(boxes[..., :3], wanted[..., :3], p=1) + \
               4 * torch.cdist(boxes[..., 3:6], wanted[..., 3:6], p=1) - \
               probability.gather(2, classes[:, None, :].expand(-1, queries, -1))
        if native:
            from .matching import assignment as cuda_assignment
            matched = cuda_assignment(cost.contiguous(), targets["counts_device"])
        else:
            costs = cost.cpu().numpy()  # one bounded D2H synchronization per batch
            assignment = np.full((batch, queries), -1, dtype=np.int64)
            for i, count in enumerate(counts):
                if count:
                    row, col = linear_sum_assignment(costs[i, :, :count])
                    assignment[i, row] = col
            matched = torch.from_numpy(assignment).to(boxes.device)
        valid = matched >= 0
        columns = matched.clamp_min(0)
        labels = classes.gather(1, columns).masked_fill(~valid, 3)
    truth = wanted.gather(1, columns[..., None].expand(-1, -1, 7))
    weights = targets["weights"]
    classification = F.cross_entropy(logits.transpose(1, 2), labels, weight=weights, reduction="none").sum(1) / weights[labels].sum(1)
    denominator = valid.sum(1).clamp_min(1)
    center = ((boxes[..., :3] - truth[..., :3]).abs() * valid[..., None]).sum((1, 2)) / (denominator * 3)
    extent = ((boxes[..., 3:6].log() - truth[..., 3:6].log()).abs() * valid[..., None]).sum((1, 2)) / (denominator * 3)
    yaw = ((1 - torch.cos(boxes[..., 6] - truth[..., 6])) * valid).sum(1) / denominator
    loss = (classification + 8 * center + .5 * extent + .2 * yaw).mean()
    # Device sentinel rejects invalid native supervision/costs without a host
    # branch in the captured step. Epoch finite checks report the failure.
    return loss.masked_fill((matched < -1).any(), float("nan")) if native else loss


@torch.no_grad()
def predictions(output, threshold=.05):
    probability = output["logits"].softmax(-1)
    # One transfer for all boxes/probabilities, instead of three per frame.
    arrays = torch.cat((output["boxes"], probability), -1).cpu().numpy()
    return predictions_from_arrays(arrays, threshold)


def predictions_from_arrays(arrays, threshold=.05):
    result = []
    for frame in arrays:
        boxes, probability = frame[:, :7], frame[:, 7:]
        classes = probability[:, :3].argmax(-1)
        scores = probability[np.arange(len(frame)), classes]
        keep = (scores >= threshold) & (probability.argmax(-1) != 3)
        result.append({"boxes": boxes[keep], "classes": classes[keep], "scores": scores[keep]})
    return result

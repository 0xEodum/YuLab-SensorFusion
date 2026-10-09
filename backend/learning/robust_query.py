"""Alternate static detector: size-balanced boxes and explicit sensor availability.

Training augmentations act on observation features, never labels or truth. The
query backbone is retained for a controlled loss/augmentation experiment.
"""
import numpy as np
import torch
from torch import nn
import torch.nn.functional as F
from scipy.optimize import linear_sum_assignment
from .model import Detector


def scale_balanced_loss(output, targets, *, native=False):
    boxes, logits = output["boxes"], output["logits"]
    wanted, classes = targets["boxes"], targets["classes"]
    batch, queries = logits.shape[:2]
    if max(targets["counts"], default=0) > queries:
        raise ValueError("Targets exceed query capacity")
    with torch.no_grad():
        # A fixed 0.5 m floor avoids exploding gradients for degenerate labels.
        scales = wanted[..., 3:6].clamp_min(.0025)
        center = ((boxes[:, :, None, :3] - wanted[:, None, :, :3]).abs() / scales[:, None]).mean(-1)
        extent = (boxes[:, :, None, 3:6].log() - wanted[:, None, :, 3:6].log()).abs().mean(-1)
        cost = 2 * center + .5 * extent - logits.softmax(-1).gather(2, classes[:, None].expand(-1, queries, -1))
        if native:
            from .matching import assignment
            matched = assignment(cost.contiguous(), targets["counts_device"])
        else:
            costs = cost.cpu().numpy()
            indices = np.full((batch, queries), -1, dtype=np.int64)
            for i, count in enumerate(targets["counts"]):
                if count:
                    rows, columns = linear_sum_assignment(costs[i, :, :count])
                    indices[i, rows] = columns
            matched = torch.from_numpy(indices).to(boxes.device)
        valid = matched >= 0
        columns = matched.clamp_min(0)
        labels = classes.gather(1, columns).masked_fill(~valid, 3)
    truth = wanted.gather(1, columns[..., None].expand(-1, -1, 7))
    weights = targets["weights"]
    classification = F.cross_entropy(logits.transpose(1, 2), labels, weight=weights, reduction="none").sum(1) / weights[labels].sum(1)
    denominator = valid.sum(1).clamp_min(1)
    normalized = (boxes[..., :3] - truth[..., :3]) / truth[..., 3:6].clamp_min(.0025)
    center = (F.smooth_l1_loss(normalized, torch.zeros_like(normalized), reduction="none", beta=.2) * valid[..., None]).sum((1, 2)) / (3 * denominator)
    extent = ((boxes[..., 3:6].log() - truth[..., 3:6].log()).abs() * valid[..., None]).sum((1, 2)) / (3 * denominator)
    # Upright boxes have period pi, unlike directional object headings.
    yaw = ((1 - torch.cos(2 * (boxes[..., 6] - truth[..., 6]))) * valid).sum(1) / denominator
    loss = (classification + 2 * center + .5 * extent + .2 * yaw).mean()
    return loss.masked_fill((matched < -1).any(), float("nan")) if native else loss


class RobustQuery(Detector):
    profile = "robust-query.v1"

    def __init__(self, modality="fusion", width=64, augment=False, full_probability=.5, corruption_probability=.15):
        super().__init__(modality, queries=16, width=width)
        self.augment = augment
        if not 0 <= full_probability <= 1 or not 0 <= corruption_probability <= 1:
            raise ValueError("Invalid augmentation probability")
        self.full_probability = full_probability
        self.corruption_probability = corruption_probability
        self.sensor_embedding = nn.Parameter(torch.randn(3, width) * .02)
        self.register_buffer("used_sensors", torch.tensor([m in self.encoders for m in ("rgb", "ir", "lidar")]))
        self.register_buffer("null_logits", torch.tensor([-1000., -1000., -1000., 1000.]))

    def forward(self, inputs):
        n = len(inputs["calibration"])
        available = inputs["available"].clone()
        if self.training and self.augment:
            bits = torch.randint(1, 8, (n,), device=available.device)
            full = torch.rand(n, device=available.device) < self.full_probability
            bits = torch.where(full, 7, bits)
            available &= (bits[:, None] & (1 << torch.arange(3, device=available.device))) != 0
        tokens, masks = [], []
        for name, encoder in self.encoders.items():
            m = ("rgb", "ir", "lidar").index(name)
            value = inputs[name]
            shape = (n,) + (1,) * (value.ndim - 1)
            value = torch.where(available[:, m].reshape(shape), value, torch.zeros_like(value))
            if name == "lidar":
                value = torch.where(inputs["point_valid"][..., None], value, torch.zeros_like(value))
            if self.training and self.augment and name != "lidar":
                # Random 25% central area contamination: fixed feature coordinates,
                # random noise or stripes, no simulator oracle or class masks.
                h, w = value.shape[-2:]
                region = torch.zeros((1, 1, h, w), device=value.device, dtype=torch.bool)
                region[..., h//4:3*h//4, w//4:3*w//4] = True
                corrupt = (torch.rand(n, 1, 1, 1, device=value.device) < self.corruption_probability) & region
                noise = torch.rand_like(value) * (1 if name == "rgb" else 2)
                value = torch.where(corrupt, noise, value)
            value = encoder(value) + self.sensor_embedding[m]
            invalid = ~inputs["point_valid"] if name == "lidar" else torch.zeros(value.shape[:2], dtype=torch.bool, device=value.device)
            invalid = invalid | ~available[:, m, None]
            tokens.append(value); masks.append(invalid)
        tokens.append(self.calibration(inputs["calibration"]).unsqueeze(1))
        masks.append(torch.zeros(n, 1, dtype=torch.bool, device=available.device))
        decoded = self.decoder(self.query[None].expand(n, -1, -1), torch.cat(tokens, 1), memory_key_padding_mask=torch.cat(masks, 1))
        raw = self.box(decoded)
        boxes = torch.cat((raw[..., :3], F.softplus(raw[..., 3:6]) * .15, torch.atan2(raw[..., 6:7], raw[..., 7:8] + 1e-6)), -1)
        logits = self.classifier(decoded)
        missing = ~(available & self.used_sensors).any(-1)
        logits = torch.where(missing[:, None, None], self.null_logits, logits)
        return {"boxes": boxes, "logits": logits}

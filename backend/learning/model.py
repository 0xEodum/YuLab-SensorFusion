"""Learned query baselines: no scene ID, weather, object lists or oracle proposals."""
from __future__ import annotations

import torch
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


def detection_loss(output, targets):
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


@torch.no_grad()
def predictions(output, threshold=.05):
    result = []
    for logits, boxes in zip(output["logits"], output["boxes"]):
        probability = logits.softmax(-1)
        scores, classes = probability[:, :3].max(-1)
        keep = (scores >= threshold) & (probability.argmax(-1) != 3)
        result.append({"boxes": boxes[keep].cpu().numpy(), "classes": classes[keep].cpu().numpy(),
                       "scores": scores[keep].cpu().numpy()})
    return result

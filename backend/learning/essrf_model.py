"""essrf-static-v1: evidential sparse subset-routed fusion, frame-wise.

Isolation by construction: every modality refines its own copy of the
input-independent queries/references using only its own observations. A subset
expert reads only the streams of its own modalities. Routing weights are the
product form of ESSRF section 2.6; detection emission is gated by the observation
mass kappa = 1 - pi_empty, so all-unavailable input abstains exactly.

Subset index is a bitmask: rgb=1, ir=2, lidar=4; 0 is the empty (null) subset.
"""
from __future__ import annotations

import math
import torch
from torch import nn
import torch.nn.functional as F

MODALITIES = ("rgb", "ir", "lidar")
SUBSETS = tuple(range(8))
SIGMA_MIN = .05          # NLL parameter units: decametres, log-metres, sin/cos
CENTER_UNIT = 20.0       # scaled (/200 m) coordinates -> decametres
EMPTY_SUBSET = 0


def subset_members(subset: int) -> tuple[int, ...]:
    return tuple(m for m in range(3) if subset >> m & 1)


def routing_weights(r: torch.Tensor) -> torch.Tensor:
    """pi_S = prod_{m in S} r_m prod_{m not in S} (1 - r_m); r [..., 3] -> [..., 8]."""
    terms = []
    for subset in SUBSETS:
        value = torch.ones_like(r[..., 0])
        for m in range(3):
            value = value * (r[..., m] if subset >> m & 1 else 1 - r[..., m])
        terms.append(value)
    return torch.stack(terms, -1)


def evidential_masses(evidence: torch.Tensor):
    """Subjective-logic belief/disbelief/vacuity from non-negative (e+, e-)."""
    strength = evidence.sum(-1) + 2
    return evidence[..., 0] / strength, evidence[..., 1] / strength, 2 / strength


class ImageEncoder(nn.Module):
    """Stride-8 feature map; 640 x 384 input -> 80 x 48 x C."""

    def __init__(self, channels: int, width: int):
        super().__init__()
        self.net = nn.Sequential(nn.Conv2d(channels, 32, 5, 2, 2), nn.GroupNorm(4, 32), nn.GELU(),
                                 nn.Conv2d(32, 64, 3, 2, 1), nn.GroupNorm(8, 64), nn.GELU(),
                                 nn.Conv2d(64, width, 3, 2, 1), nn.GroupNorm(8, width), nn.GELU(),
                                 nn.Conv2d(width, width, 3, 1, 1))

    def forward(self, image):
        return self.net(image)


GLOBAL_POOL = 4            # camera global tokens: 48 x 80 stride-8 map -> 12 x 20
GLOBAL_POINTS = 256        # LiDAR global tokens: uniform indices over each scan's observed points
REFINE_STEPS_M = (40.0, 10.0)


def _attend(attention, query, keys, valid, empty):
    """Cross-attention with a learned always-valid token (finite when nothing is valid)."""
    rows, _, width = keys.shape
    keys = torch.cat((empty.expand(rows, 1, width), keys), 1)
    mask = torch.cat((valid.new_ones(rows, 1), valid), 1)
    return attention(query, keys, keys, key_padding_mask=~mask, need_weights=False)[0]


class LocalLayer(nn.Module):
    """Own-modality global and query-local cross-attention, within-stream self-attention, FFN."""

    def __init__(self, width: int, heads: int = 4, global_context: bool = True):
        super().__init__()
        self.global_context = global_context
        self.cross = nn.MultiheadAttention(width, heads, batch_first=True)
        self.global_cross = nn.MultiheadAttention(width, heads, batch_first=True) if global_context else None
        self.self_attention = nn.MultiheadAttention(width, heads, batch_first=True)
        self.ffn = nn.Sequential(nn.Linear(width, width * 2), nn.GELU(), nn.Linear(width * 2, width))
        self.norms = nn.ModuleList(nn.LayerNorm(width) for _ in range(4))
        self.empty = nn.Parameter(torch.zeros(1, 1, width))
        self.global_empty = nn.Parameter(torch.zeros(1, 1, width))

    def forward(self, query, position, tokens, token_valid, samples, valid):
        batch, queries, count, width = samples.shape
        if self.global_context:
            attended = _attend(self.global_cross, query + position, tokens, token_valid, self.global_empty)
            query = self.norms[3](query + attended)
        local = _attend(self.cross, (query + position).reshape(batch * queries, 1, width),
                        samples.reshape(batch * queries, count, width), valid.reshape(batch * queries, count),
                        self.empty)
        query = self.norms[0](query + local.reshape(batch, queries, width))
        mixed = query + position
        query = self.norms[1](query + self.self_attention(mixed, mixed, query, need_weights=False)[0])
        return self.norms[2](query + self.ffn(query))


class Stream(nn.Module):
    """One modality's global context, local sampling and reference refinement."""

    def __init__(self, modality: str, width: int, samples: int, layers: int, global_context: bool = True,
                 image_sampler: str = "bilinear-v1"):
        super().__init__()
        self.modality, self.samples, self.global_context = modality, samples, global_context
        self.image_sampler = image_sampler
        self.layers = nn.ModuleList(LocalLayer(width, global_context=global_context) for _ in range(layers))
        self.offsets = nn.ModuleList(nn.Linear(width, samples * 3) for _ in range(layers))
        self.refine = nn.ModuleList(nn.Linear(width, 3) for _ in range(layers))
        self.relative = nn.Sequential(nn.Linear(3, width), nn.GELU(), nn.Linear(width, width))
        # Token keys by heading-frame view direction; queries by direction and log range.
        self.key_position = nn.Sequential(nn.Linear(3, width), nn.GELU(), nn.Linear(width, width))
        self.query_position = nn.Sequential(nn.Linear(4, width), nn.GELU(), nn.Linear(width, width))
        for layer in list(self.offsets) + list(self.refine):
            nn.init.zeros_(layer.weight); nn.init.zeros_(layer.bias)
        self.register_buffer("pattern", _sample_pattern(samples) * (8 / 200))
        self.steps = REFINE_STEPS_M if layers == 2 else (10.0,) * layers

    def encode_position(self, reference):
        distance = reference.norm(dim=-1, keepdim=True).clamp_min(1e-4)
        return self.query_position(torch.cat((reference / distance, (distance * 200).log() / 5), -1))

    def global_tokens(self, data):
        if self.modality == "lidar":
            features, xyz, valid = data["features"], data["xyz"], data["valid"]
            count = valid.sum(1)
            # Valid points are stored first; indices repeat for scans shorter than GLOBAL_POINTS.
            fraction = torch.linspace(0, 1, GLOBAL_POINTS, device=xyz.device)
            index = (fraction[None] * (count[:, None] - 1).clamp_min(0)).round().long()
            token_valid = (count[:, None] > 0).expand(-1, GLOBAL_POINTS)
            tokens = torch.gather(features, 1, index[..., None].expand(-1, -1, features.shape[-1]))
            positions = torch.gather(xyz, 1, index[..., None].expand(-1, -1, 3))
            direction = positions / positions.norm(dim=-1, keepdim=True).clamp_min(1e-4)
            return tokens + self.key_position(direction), token_valid
        pooled = F.avg_pool2d(data["features"], GLOBAL_POOL)              # [B,C,12,20]
        batch, _, rows, cols = pooled.shape
        scale = 8 * GLOBAL_POOL                                           # input pixels per pooled cell
        v = (torch.arange(rows, device=pooled.device) + .5) * scale
        u = (torch.arange(cols, device=pooled.device) + .5) * scale
        grid_v, grid_u = torch.meshgrid(v, u, indexing="ij")
        k = data["intrinsics"]
        direction = torch.stack(((grid_u[None] - k[:, None, None, 2]) / k[:, None, None, 0],
                                 (grid_v[None] - k[:, None, None, 3]) / k[:, None, None, 1],
                                 torch.ones(batch, rows, cols, device=pooled.device)), -1).reshape(batch, -1, 3)
        rotation = data["transform"][:, :3, :3]                           # camera <- heading, scaled
        heading = torch.einsum("bji,bnj->bni", rotation, direction)       # R^T d, then normalized
        heading = heading / heading.norm(dim=-1, keepdim=True)
        tokens = pooled.flatten(2).transpose(1, 2) + self.key_position(heading)
        return tokens, torch.ones(batch, rows * cols, dtype=torch.bool, device=pooled.device)

    def sample_camera(self, features, transform, intrinsics, points):
        """Project heading-frame points [B,Q,s,3] -> bilinear samples, validity."""
        batch, queries, count, _ = points.shape
        homogeneous = torch.cat((points, torch.ones_like(points[..., :1])), -1)
        camera = torch.einsum("bij,bqsj->bqsi", transform, homogeneous)[..., :3]
        depth = camera[..., 2]
        safe = depth.clamp_min(.5)
        u = intrinsics[:, None, None, 0] * camera[..., 0] / safe + intrinsics[:, None, None, 2]
        v = intrinsics[:, None, None, 1] * camera[..., 1] / safe + intrinsics[:, None, None, 3]
        height, width = 384, 640
        valid = (depth > .5) & (u >= 0) & (u <= width - 1) & (v >= 0) & (v <= height - 1)
        grid = torch.stack((u / (width - 1) * 2 - 1, v / (height - 1) * 2 - 1), -1)
        grid = torch.where(valid[..., None], grid, torch.zeros_like(grid))
        grid = grid.reshape(batch, queries * count, 1, 2)
        sampled = F.grid_sample(features, grid, align_corners=True) if self.image_sampler == "grid-sample" else bilinear_sample(features, grid)
        return sampled.reshape(batch, -1, queries, count).permute(0, 2, 3, 1), valid

    def sample_lidar(self, point_features, xyz, point_valid, reference):
        """s nearest valid observed points within 15 m of each reference."""
        distance = torch.cdist(reference, xyz).masked_fill(~point_valid[:, None, :], math.inf)
        nearest, index = distance.topk(self.samples, -1, largest=False)
        valid = nearest < 15 / 200
        # Gather from [B,N,C] with a flat index: backward allocates [B,N,C], not [B,Q,N,C].
        batch, queries, count = index.shape
        flat = index.reshape(batch, queries * count, 1)
        gathered = torch.gather(point_features, 1, flat.expand(-1, -1, point_features.shape[-1]))
        gathered = gathered.reshape(batch, queries, count, -1)
        neighbours = torch.gather(xyz, 1, flat.expand(-1, -1, 3)).reshape(batch, queries, count, 3)
        relative = torch.where(valid[..., None], neighbours - reference[:, :, None], torch.zeros_like(neighbours))
        return gathered * valid[..., None], relative, valid

    def forward(self, query, reference, data):
        last = None
        tokens, token_valid = self.global_tokens(data) if self.global_context else (None, None)
        for layer, offsets, refine, step in zip(self.layers, self.offsets, self.refine, self.steps):
            if self.modality == "lidar":
                samples, relative, valid = self.sample_lidar(data["features"], data["xyz"], data["valid"], reference)
                physical = valid.float()
            else:
                relative = (torch.tanh(offsets(query)).reshape(*query.shape[:2], self.samples, 3) * (8 / 200)
                            + self.pattern)
                points = reference[:, :, None] + relative
                samples, valid = self.sample_camera(data["features"], data["transform"], data["intrinsics"], points)
                sampled_physical = self.sample_camera(data["physical"], data["transform"], data["intrinsics"], points)[0]
                physical = sampled_physical[..., -1] * valid
            samples = samples + self.relative(relative)
            query = layer(query, self.encode_position(reference), tokens, token_valid, samples, valid)
            reference = reference.detach() + torch.tanh(refine(query)) * (step / 200)
            last = (samples, valid, physical)
        samples, valid, physical = last
        weight = valid.float()[..., None]
        count = weight.sum(2).clamp_min(1)
        mean = (samples * weight).sum(2) / count
        variance = (((samples - mean[:, :, None]) ** 2) * weight).sum(2) / count
        descriptor = torch.stack((valid.float().mean(-1), physical.float().mean(-1)), -1)
        return query, reference, mean, variance, descriptor


def _sample_pattern(samples: int) -> torch.Tensor:
    """Deterministic unit-ball pattern (Fibonacci sphere scaled by cube-root radii)."""
    index = torch.arange(samples, dtype=torch.float64) + .5
    phi = torch.acos(1 - 2 * index / samples)
    theta = math.pi * (1 + 5 ** .5) * index
    radius = (index / samples) ** (1 / 3)
    return torch.stack((radius * torch.sin(phi) * torch.cos(theta), radius * torch.cos(phi),
                        radius * torch.sin(phi) * torch.sin(theta)), -1).float()


def bilinear_sample(features: torch.Tensor, grid: torch.Tensor) -> torch.Tensor:
    """Zero-padded, align-corners bilinear interpolation with deterministic gather gradients.

    grid_sample's CUDA backward uses unordered accumulation. torch.gather has a
    deterministic implementation when deterministic algorithms are enabled.
    Coordinates and features remain differentiable; no neighborhood is detached.
    """
    batch, channels, height, width = features.shape
    x = (grid[..., 0].reshape(batch, -1) + 1) * ((width - 1) / 2)
    y = (grid[..., 1].reshape(batch, -1) + 1) * ((height - 1) / 2)
    x0, y0 = x.floor(), y.floor()
    dx, dy = x - x0, y - y0
    xx = torch.stack((x0, x0 + 1, x0, x0 + 1), -1).long()
    yy = torch.stack((y0, y0, y0 + 1, y0 + 1), -1).long()
    inside = (xx >= 0) & (xx < width) & (yy >= 0) & (yy < height)
    weights = torch.stack(((1 - dx) * (1 - dy), dx * (1 - dy), (1 - dx) * dy, dx * dy), -1)
    index = (yy.clamp(0, height - 1) * width + xx.clamp(0, width - 1)).reshape(batch, 1, -1)
    samples = features.flatten(2).gather(2, index.expand(-1, channels, -1)).reshape(batch, channels, -1, 4)
    value = (samples * (weights * inside)[:, None]).sum(-1)
    return value.reshape(batch, channels, *grid.shape[1:-1])


def default_references(queries: int, depression_rad: float = 0.0) -> torch.Tensor:
    """Input-independent heading-frame references over the declared forward frustum."""
    generator = torch.Generator().manual_seed(1201)
    azimuth = (torch.rand(queries, generator=generator) * 2 - 1) * .55
    distance = torch.exp(torch.empty(queries).uniform_(math.log(35), math.log(250), generator=generator))
    elevation = -depression_rad + (torch.rand(queries, generator=generator) * 2 - 1) * .15
    horizontal = distance * torch.cos(elevation)
    return torch.stack((horizontal * torch.sin(azimuth), distance * torch.sin(elevation),
                        -horizontal * torch.cos(azimuth)), -1) / 200


class Expert(nn.Module):
    """Small adapter D_S over the streams of the modalities in S.

    The set layer lets queries of the same subset suppress duplicates (one-to-one
    matching needs query interaction after fusion); it only mixes states that
    were themselves built from S's modalities, so isolation is preserved.
    """

    def __init__(self, members: tuple[int, ...], width: int, heads: int = 4):
        super().__init__()
        self.members = members
        self.inputs = nn.ModuleList(nn.Linear(width, width) for _ in members)
        self.mlp = nn.Sequential(nn.LayerNorm(width), nn.Linear(width, width * 2), nn.GELU(),
                                 nn.Linear(width * 2, width))
        self.set_attention = nn.MultiheadAttention(width, heads, batch_first=True)
        self.set_norm = nn.LayerNorm(width)

    def forward(self, query, streams):
        mixed = sum(project(streams[m]) for project, m in zip(self.inputs, self.members))
        state = query + self.mlp(mixed)
        normed = self.set_norm(state)
        return state + self.set_attention(normed, normed, normed, need_weights=False)[0]


class ESSRF(nn.Module):
    profile = "essrf-static-v1"

    def __init__(self, queries: int = 32, width: int = 128, samples: int = 16, layers: int = 2,
                 references: torch.Tensor | None = None, global_context: bool = True,
                 image_sampler: str = "bilinear-v1"):
        super().__init__()
        self.queries, self.width = queries, width
        if image_sampler not in ("bilinear-v1", "grid-sample"):
            raise ValueError("Unknown image sampler")
        self.config = {"queries": queries, "width": width, "samples": samples, "layers": layers,
                       "global_context": global_context, "image_sampler": image_sampler}
        self.rgb_encoder = ImageEncoder(3, width)
        self.ir_encoder = ImageEncoder(3, width)
        self.point_encoder = nn.Sequential(nn.Linear(4, width), nn.GELU(), nn.Linear(width, width))
        self.streams = nn.ModuleList(Stream(m, width, samples, layers, global_context, image_sampler) for m in MODALITIES)
        self.query = nn.Parameter(torch.randn(queries, width) * .1)
        self.reference = nn.Parameter(default_references(queries) if references is None else references.clone())
        # Reliability input: [q; mean(G); var(G); valid fraction; physical fraction].
        self.reliability = nn.ModuleList(nn.Sequential(nn.Linear(width * 3 + 2, width), nn.GELU(),
                                                       nn.Linear(width, 2)) for _ in MODALITIES)
        self.experts = nn.ModuleList(Expert(subset_members(s), width) for s in SUBSETS[1:])
        self.classifier = nn.Linear(width, 4)  # aircraft, ground vehicle, ship, no-object
        self.center = nn.Linear(width, 3)
        self.extent = nn.Linear(width, 3)
        self.yaw = nn.Linear(width, 2)
        self.variance = nn.Linear(width, 8)
        # Nominal rig heading (cos, sin): calibration, not a modality observation.
        self.calibration = nn.Sequential(nn.Linear(2, width), nn.GELU(), nn.Linear(width, width))
        nn.init.zeros_(self.center.weight); nn.init.zeros_(self.center.bias)
        nn.init.constant_(self.extent.bias, math.log(10 / 200))

    def modality_data(self, inputs, available):
        # Unavailable observations are replaced at the input, so neither values nor
        # gradients (0 * NaN) of a disabled modality can reach any parameter.
        def keep(value, m):
            on = available[:, m].view(-1, *([1] * (value.dim() - 1)))
            return torch.where(on, value, torch.zeros_like(value))
        rgb = keep(inputs["rgb"].float() / 255, 0)
        rgb_valid = (rgb > 0).any(1, keepdim=True).float()
        flags = keep(inputs["ir_flags"], 1)
        ir_valid, saturated = (flags & 1).float()[:, None], (flags >> 1 & 1).float()[:, None]
        ir = torch.cat((keep(inputs["ir"].float(), 1)[:, None], ir_valid, saturated), 1)
        lidar = keep(inputs["lidar"], 2)
        point_valid = inputs["point_valid"] & available[:, 2, None]
        return {
            "rgb": {"features": self.rgb_encoder(rgb), "physical": rgb_valid,
                    "transform": inputs["rgb_from_heading"], "intrinsics": inputs["rgb_intrinsics"]},
            "ir": {"features": self.ir_encoder(ir), "physical": 1 - saturated,
                   "transform": inputs["ir_from_heading"], "intrinsics": inputs["ir_intrinsics"]},
            "lidar": {"features": self.point_encoder(lidar), "xyz": lidar[..., :3], "valid": point_valid},
        }

    def heads(self, state, reference, heading):
        state = state + self.calibration(torch.stack((heading.cos(), heading.sin()), -1))[:, None]
        logits = self.classifier(state)
        center_heading = reference + self.center(state) / CENTER_UNIT
        log_extent = self.extent(state)
        yaw_vector = self.yaw(state)
        yaw_heading = torch.atan2(yaw_vector[..., 0], yaw_vector[..., 1] + 1e-6)
        # Box mean parameters for the localization NLL, in the heading frame.
        mean = torch.cat((center_heading * CENTER_UNIT, log_extent + math.log(200),
                          torch.sin(yaw_heading)[..., None], torch.cos(yaw_heading)[..., None]), -1)
        variance = SIGMA_MIN ** 2 + F.softplus(self.variance(state))
        return {"logits": logits, "center_heading": center_heading, "log_extent": log_extent,
                "yaw_heading": yaw_heading, "mean": mean, "variance": variance}

    def forward(self, inputs, available: torch.Tensor | None = None, expert_subsets: torch.Tensor | None = None):
        """available [B,3] bool health bits; expert_subsets [B] long selects one expert per frame."""
        batch = inputs["available"].shape[0]
        available = inputs["available"] if available is None else available & inputs["available"]
        data = self.modality_data(inputs, available)
        query0 = self.query.unsqueeze(0).expand(batch, -1, -1)
        reference0 = self.reference.unsqueeze(0).expand(batch, -1, -1)
        streams, references, rho, evidence = [], [], [], []
        for m, (name, stream) in enumerate(zip(MODALITIES, self.streams)):
            h, x, mean, variance, descriptor = stream(query0, reference0, data[name])
            on = available[:, m, None, None]
            # Unavailable modalities are replaced, never multiplied: NaN/garbage cannot leak.
            h = torch.where(on, h, torch.zeros_like(h)); x = torch.where(on, x, reference0)
            raw = self.reliability[m](torch.cat((query0, mean, variance, descriptor), -1))
            e = torch.where(on, F.softplus(raw), torch.zeros_like(raw))
            streams.append(h); references.append(x); evidence.append(e)
            rho.append(evidential_masses(e)[0])
        evidence = torch.stack(evidence, 2)                       # [B,Q,3,2]
        reliability = torch.stack(rho, -1) * available[:, None, :].float()
        pi = routing_weights(reliability)                         # [B,Q,8]
        states = [query0] + [expert(query0, streams) for expert in self.experts]
        positions = [reference0] + [sum(references[m] for m in subset_members(s)) / len(subset_members(s))
                                    for s in SUBSETS[1:]]
        state = sum(pi[..., s, None] * states[s] for s in SUBSETS)
        reference = sum(pi[..., s, None] * positions[s] for s in SUBSETS)
        kappa = 1 - pi[..., EMPTY_SUBSET]
        out = self.heads(state, reference, inputs["heading_yaw"])
        out.update(self.gate(out["logits"], kappa))
        out.update({"kappa": kappa, "pi": pi, "reliability": reliability, "evidence": evidence,
                    "stream_references": torch.stack(references, 2), "available": available})
        out["boxes"] = world_boxes(out, inputs)
        if expert_subsets is not None:
            index = expert_subsets.view(batch, 1, 1, 1).expand(-1, self.queries, 1, self.width)
            chosen = torch.stack(states, 2).gather(2, index)[:, :, 0]
            chosen_reference = torch.stack(positions, 2).gather(2, index[..., :3])[:, :, 0]
            expert = self.heads(chosen, chosen_reference, inputs["heading_yaw"])
            expert["probability"] = expert["logits"].softmax(-1)
            expert["boxes"] = world_boxes(expert, inputs)
            out["expert"] = expert
        return out

    @staticmethod
    def gate(logits, kappa):
        """Emission requires observation mass: p_k = kappa softmax_k, rest is no-object."""
        probability = logits.softmax(-1)
        objects = probability[..., :3] * kappa[..., None]
        return {"probability": torch.cat((objects, 1 - objects.sum(-1, keepdim=True)), -1)}


def world_boxes(out, inputs):
    """Heading-frame predictions -> baseline-v1 box format (world axes, scaled)."""
    center = torch.einsum("bij,bqj->bqi", inputs["world_from_heading"], out["center_heading"])
    extent = out["log_extent"].exp()
    yaw = out["yaw_heading"] + inputs["heading_yaw"][:, None]
    yaw = torch.atan2(torch.sin(yaw), torch.cos(yaw))
    return torch.cat((center, extent, yaw[..., None]), -1)

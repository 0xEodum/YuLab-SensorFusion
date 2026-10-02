"""essrf-static-v1 acceptance: routing, isolation, abstention, evidence and finiteness."""
import itertools
import math
import numpy as np
import pytest
torch = pytest.importorskip("torch", reason="Run learning tests with the locked learning environment")

from learning.essrf_model import ESSRF, SUBSETS, evidential_masses, routing_weights, subset_members

PATTERNS = [torch.tensor(p) for p in itertools.product((False, True), repeat=3)]


def synthetic_inputs(batch=2, points=64, seed=0):
    generator = torch.Generator().manual_seed(seed)
    camera = torch.tensor([[1., 0, 0, 0], [0, -1, 0, 0], [0, 0, -1, 0], [0, 0, 0, 1]])
    camera[:3, :3] *= 200  # scaled heading coordinates -> metres
    xyz = torch.rand(batch, points, 3, generator=generator) * torch.tensor([.4, .1, -.8])
    return {
        "rgb": (torch.rand(batch, 3, 384, 640, generator=generator) * 255).to(torch.uint8),
        "ir": torch.rand(batch, 384, 640, generator=generator).half(),
        "ir_flags": torch.ones(batch, 384, 640, dtype=torch.uint8),
        "lidar": torch.cat((xyz, torch.rand(batch, points, 1, generator=generator)), -1),
        "point_valid": torch.ones(batch, points, dtype=torch.bool),
        "rgb_from_heading": camera.expand(batch, 4, 4).clone(),
        "ir_from_heading": camera.expand(batch, 4, 4).clone(),
        "rgb_intrinsics": torch.tensor([463.5, 463.5, 320, 192]).expand(batch, 4).clone(),
        "ir_intrinsics": torch.tensor([463.5, 463.5, 320, 192]).expand(batch, 4).clone(),
        "available": torch.ones(batch, 3, dtype=torch.bool),
        "world_from_heading": torch.eye(3).expand(batch, 3, 3).clone(),
        "heading_yaw": torch.zeros(batch),
    }


@pytest.fixture(scope="module")
def model():
    torch.manual_seed(3)
    net = ESSRF(queries=8, width=32, samples=4, layers=2).eval()
    # Non-zero refinement/offset heads so the isolation tests exercise moving references.
    with torch.no_grad():
        for stream in net.streams:
            for layer in list(stream.offsets) + list(stream.refine):
                layer.weight.normal_(0, .2)
        net.center.weight.normal_(0, .2)
    return net


def corrupt(inputs, modality):
    changed = {k: v.clone() for k, v in inputs.items()}
    if modality == 0:
        changed["rgb"] = 255 - changed["rgb"]
    elif modality == 1:
        changed["ir"] = torch.full_like(changed["ir"], float("nan")); changed["ir_flags"] ^= 3
    else:
        changed["lidar"] = torch.full_like(changed["lidar"], float("nan"))
    return changed


def test_routing_weights_sum_to_one_and_follow_product_form():
    r = torch.rand(1000, 3, dtype=torch.float64)
    pi = routing_weights(r)
    assert torch.allclose(pi.sum(-1), torch.ones(1000, dtype=torch.float64), atol=1e-12)
    for subset in SUBSETS:
        expected = torch.ones(1000, dtype=torch.float64)
        for m in range(3):
            expected *= r[:, m] if m in subset_members(subset) else 1 - r[:, m]
        assert torch.equal(pi[:, subset], expected)


def test_zero_evidence_is_ignorance_not_half_reliability():
    belief, disbelief, vacuity = evidential_masses(torch.zeros(2))
    assert belief == 0 and disbelief == 0 and vacuity == 1
    confident_negative = evidential_masses(torch.tensor([0., 1e4]))
    assert confident_negative[0] == 0 and confident_negative[2] < 1e-3  # distinct from ignorance
    b, d, u = evidential_masses(torch.rand(100, 2) * 50)
    assert torch.allclose(b + d + u, torch.ones(100))


@pytest.mark.parametrize("pattern", PATTERNS, ids=lambda p: "".join("RTL"[i] if p[i] else "-" for i in range(3)))
def test_all_availability_patterns(model, pattern):
    inputs = synthetic_inputs()
    available = pattern.expand(2, 3)
    out = model(inputs, available=available)
    assert torch.allclose(out["pi"].sum(-1), torch.ones_like(out["kappa"]), atol=1e-6)
    for key in ("probability", "boxes", "mean", "variance", "pi", "evidence"):
        assert torch.isfinite(out[key]).all(), key
    for m in range(3):
        if not pattern[m]:
            assert torch.equal(out["reliability"][..., m], torch.zeros_like(out["reliability"][..., m]))
            for subset in SUBSETS:
                if m in subset_members(subset):
                    assert torch.equal(out["pi"][..., subset], torch.zeros_like(out["kappa"]))
            # A disabled modality contributes nothing: arbitrary (even NaN) input is ignored exactly.
            other = model(corrupt(inputs, m), available=available)
            for key in ("probability", "boxes", "pi", "kappa"):
                assert torch.equal(out[key], other[key]), key
    if not pattern.any():
        assert torch.equal(out["kappa"], torch.zeros_like(out["kappa"]))
        assert torch.equal(out["probability"][..., :3], torch.zeros_like(out["probability"][..., :3]))


def test_unavailable_hardware_bit_from_inputs_is_respected(model):
    inputs = synthetic_inputs(); inputs["available"][:, 2] = False
    out = model(inputs)
    assert torch.equal(out["reliability"][..., 2], torch.zeros_like(out["kappa"]))


@pytest.mark.parametrize("subset", SUBSETS[1:])
def test_subset_expert_never_reads_excluded_modalities(model, subset):
    inputs = synthetic_inputs()
    choice = torch.full((2,), subset)
    reference = model(inputs, expert_subsets=choice)["expert"]
    for m in range(3):
        if m in subset_members(subset):
            continue
        other = model(corrupt(inputs, m), expert_subsets=choice)["expert"]
        for key in ("logits", "boxes", "mean", "variance"):
            assert torch.equal(reference[key], other[key]), (subset, m, key)


def test_gradients_finite_for_every_pattern_with_nan_disabled_inputs():
    torch.manual_seed(0)
    net = ESSRF(queries=8, width=32, samples=4, layers=2)
    for pattern in PATTERNS:
        inputs = synthetic_inputs()
        for m in range(3):
            if not pattern[m]:
                inputs = corrupt(inputs, m)
        net.zero_grad()
        out = net(inputs, available=pattern.expand(2, 3), expert_subsets=torch.tensor([7, 1]))
        loss = out["probability"].clamp_min(1e-6).log().sum() + out["mean"].sum() + out["variance"].log().sum() + \
            out["expert"]["logits"].sum() + out["evidence"].sum()
        loss.backward()
        for name, parameter in net.named_parameters():
            if parameter.grad is not None:
                assert torch.isfinite(parameter.grad).all(), (pattern, name)


def test_empty_point_scan_and_off_image_references_are_finite(model):
    inputs = synthetic_inputs()
    inputs["point_valid"][:] = False
    inputs["rgb_from_heading"][:, 2, 3] = 1e4  # every camera sample behind/off image
    out = model(inputs)
    assert all(torch.isfinite(out[k]).all() for k in ("probability", "boxes", "evidence"))


def test_variance_has_positive_floor(model):
    out = model(synthetic_inputs())
    assert (out["variance"] >= .05 ** 2).all()


def test_evidential_loss_finite_at_zero_and_extreme_evidence():
    from learning.essrf_loss import evidential
    for value in (0., 1e-8, 1e6):
        evidence = torch.full((1, 4, 3, 2), value, requires_grad=True)
        y = torch.tensor([[[1., 0, 1], [0, 1, 0], [1, 1, 1], [0, 0, 0]]])
        labelled = torch.ones(1, 4, 3, dtype=torch.bool); ood = torch.zeros_like(labelled); ood[0, 3] = True
        loss, _ = evidential({"evidence": evidence}, y, labelled & ~ood, ood)
        loss.backward()
        assert torch.isfinite(loss) and torch.isfinite(evidence.grad).all()


def test_all_unavailable_frames_supervise_abstention_only(model):
    from learning import essrf_loss as L
    inputs = synthetic_inputs()
    targets = [{"boxes": torch.tensor([[.1, 0, -.3, .02, .02, .02, 0]]), "classes": torch.tensor([0]),
                "support": torch.ones(1, 3, dtype=torch.bool)} for _ in range(2)]
    truth = L.pack(targets, "cpu")
    out = model(inputs, available=torch.zeros(2, 3, dtype=torch.bool))
    loss, matched, _ = L.detection(out, truth, truth["counts"] * 0, inputs)
    assert (matched < 0).all() and loss == 0  # no-object probability is exactly one


def test_known_corruption_regions_label_queries_unreliable():
    from learning import essrf_loss as L
    inputs = synthetic_inputs(batch=1)
    references = torch.tensor([[[0., 0, -.5]] * 3]).unsqueeze(0).expand(1, 2, 3, 3).clone()
    references[0, 1] = torch.tensor([.3, 0, -.5])  # projects far right in both cameras
    regions = {"rects": torch.tensor([[[300., 170, 340, 210], [300., 170, 340, 210]]]),
               "wedges": torch.tensor([[-.1, .1]]), "family": torch.tensor([[1, 2, 1]])}
    inside = L.query_regions({"stream_references": references}, inputs, regions)
    assert inside["known"][0, 0].tolist() == [True, False, True]
    assert inside["ood"][0, 0].tolist() == [False, True, False]
    assert not inside["known"][0, 1].any() and not inside["ood"][0, 1].any()
    matched = torch.tensor([[0, -1]])
    truth = {"support": torch.ones(1, 1, 3, dtype=torch.bool)}
    y, labelled, ood = L.reliability_targets(matched, truth, inside, torch.ones(1, 3, dtype=torch.bool))
    assert labelled[0, 0].tolist() == [True, False, True]
    assert y[0, 0][labelled[0, 0]].tolist() == [0, 0]  # supported object, but known-corrupted locally
    assert ood[0, 0].tolist() == [False, True, False]
    assert not labelled[0, 1].any()  # unmatched, uncorrupted background stays unlabelled

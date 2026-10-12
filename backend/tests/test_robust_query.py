"""Object-scale localization contracts for the alternate query detector."""
import pytest
torch = pytest.importorskip("torch")
from learning.robust_query import RobustQuery, scale_balanced_loss
from learning.model import pack_targets


def example(extent, error):
    truth = torch.tensor([[0., 0., 0., *extent, 0.]])
    boxes = truth[None].clone(); boxes[..., 1] += error
    return {"boxes": boxes.requires_grad_(), "logits": torch.tensor([[[8., -4., -4., -4.]]], requires_grad=True)}, [
        {"boxes": truth, "classes": torch.tensor([0])}]


def test_equal_fractional_localization_errors_have_equal_cost():
    a, ta = example([.1, .01, .2], .005)
    b, tb = example([.2, .02, .4], .01)
    assert scale_balanced_loss(a, pack_targets(ta, "cpu")).item() == pytest.approx(
        scale_balanced_loss(b, pack_targets(tb, "cpu")).item(), abs=1e-6)


def test_small_object_is_more_sensitive_to_same_metric_error():
    a, ta = example([.1, .01, .2], .005)
    b, tb = example([.1, .1, .2], .005)
    assert scale_balanced_loss(a, pack_targets(ta, "cpu")) > scale_balanced_loss(b, pack_targets(tb, "cpu"))


def test_empty_and_pi_equivalent_yaw_have_finite_gradients():
    out, target = example([.1, .02, .2], 0)
    base = scale_balanced_loss(out, pack_targets(target, "cpu"))
    shifted = {**out, "boxes": out["boxes"] + torch.tensor([0, 0, 0, 0, 0, 0, torch.pi])}
    assert scale_balanced_loss(shifted, pack_targets(target, "cpu")).item() == pytest.approx(base.item(), abs=1e-6)
    empty = [{"boxes": torch.empty(0, 7), "classes": torch.empty(0, dtype=torch.long)}]
    loss = scale_balanced_loss(out, pack_targets(empty, "cpu")); loss.backward()
    assert torch.isfinite(loss)
    assert all(torch.isfinite(v.grad).all() for v in out.values())


def test_unavailable_sensor_cannot_change_predictions_and_all_missing_abstains():
    from learning.model import predictions
    torch.manual_seed(1)
    model = RobustQuery().eval()
    x = {"rgb": torch.rand(2, 3, 96, 160), "ir": torch.rand(2, 1, 96, 160),
         "lidar": torch.rand(2, 256, 4), "point_valid": torch.ones(2, 256, dtype=torch.bool),
         "calibration": torch.zeros(2, 32), "available": torch.tensor([[True, False, True], [False, False, False]])}
    first = model(x)
    x["ir"].fill_(float("nan"))
    second = model(x)
    assert torch.equal(first["boxes"], second["boxes"])
    assert torch.equal(first["logits"], second["logits"])
    assert len(predictions(second)[1]["boxes"]) == 0


@pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA unavailable")
def test_native_balanced_matching_matches_reference_gradients():
    from learning.matching import available
    if not available(): pytest.skip("Native matcher unavailable")
    torch.manual_seed(42)
    boxes = torch.rand(4, 16, 7, device="cuda"); boxes[..., 3:6] += .1
    logits = torch.randn(4, 16, 4, device="cuda")
    targets = [{"boxes": torch.rand(i, 7), "classes": torch.arange(i) % 3} for i in range(4)]
    for t in targets: t["boxes"][:, 3:6] += .1
    packed = pack_targets(targets, "cuda")
    a={"boxes":boxes.clone().requires_grad_(),"logits":logits.clone().requires_grad_()}
    b={"boxes":boxes.clone().requires_grad_(),"logits":logits.clone().requires_grad_()}
    left=scale_balanced_loss(a,packed); right=scale_balanced_loss(b,packed,native=True)
    torch.testing.assert_close(left,right); left.backward(); right.backward()
    for k in a: torch.testing.assert_close(a[k].grad,b[k].grad)

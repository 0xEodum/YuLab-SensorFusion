"""Independent geometry, matching and observation isolation acceptance."""
import numpy as np
import pytest
torch = pytest.importorskip("torch", reason="Run learning tests with the locked learning environment")

from learning.evaluate import box_iou, evaluate
from learning.model import Detector, detection_loss


def test_oriented_iou_known_volumes():
    # [center XYZ, extent XYZ, yaw]: a 4 x 2 x 2 cuboid rotated 90 degrees
    # intersects its original in 2 x 2 x 2, union volume = 24.
    a = np.array([0, 0, 0, 4, 2, 2, 0.0])
    b = a.copy(); b[-1] = np.pi / 2
    assert box_iou(a, a) == pytest.approx(1)
    assert box_iou(a, b) == pytest.approx(1 / 3)
    b[0] = 10
    assert box_iou(a, b) == 0


def test_evaluation_duplicate_empty_and_hidden_objects():
    box = [0, 0, 0, 4, 2, 2, 0]
    target = {"boxes": np.array([box]), "classes": np.array([0]), "ignored": np.empty((0, 7))}
    empty = {"boxes": np.empty((0, 7)), "classes": np.empty(0, dtype=int), "ignored": np.array([box])}
    predictions = [{"boxes": np.array([box, box]), "classes": np.array([0, 0]), "scores": np.array([.9, .8])},
                   {"boxes": np.array([box]), "classes": np.array([0]), "scores": np.array([.95])}]
    result = evaluate(predictions, [target, empty])
    assert result["classes"]["aircraft"]["recall"] == 1
    assert result["false_positives"] == 2  # duplicates and hidden discoveries count
    assert result["empty_scene_false_positives"] == 1
    assert result["classes"]["aircraft"]["ap"] == pytest.approx(.5)


def test_empty_loss_and_modality_isolation():
    model = Detector("rgb")
    inputs = {"rgb": torch.rand(2, 3, 96, 160), "ir": torch.rand(2, 1, 96, 160),
              "lidar": torch.rand(2, 128, 4), "point_valid": torch.ones(2, 128, dtype=torch.bool),
              "calibration": torch.zeros(2, 32)}
    model.eval()
    first = model(inputs)
    inputs["ir"].fill_(float("nan")); inputs["lidar"].fill_(float("nan"))
    second = model(inputs)
    assert torch.equal(first["boxes"], second["boxes"])
    targets = [{"boxes": torch.empty(0, 7), "classes": torch.empty(0, dtype=torch.long)} for _ in range(2)]
    loss = detection_loss(first, targets)
    assert torch.isfinite(loss)
    loss.backward()
    assert all(torch.isfinite(p.grad).all() for p in model.parameters() if p.grad is not None)


def test_empty_point_scan_is_finite():
    model = Detector("lidar").eval()
    result = model({"lidar": torch.zeros(1, 256, 4),
                    "point_valid": torch.zeros(1, 256, dtype=torch.bool), "calibration": torch.zeros(1, 32)})
    assert torch.isfinite(result["boxes"]).all()


def test_matching_is_permutation_invariant_and_wrong_boxes_cost_more():
    boxes = torch.tensor([[[0., 0., .2, .1, .02, .15, 0.], [.2, 0., .3, .2, .05, .6, 0.]]])
    logits = torch.tensor([[[8., -4., -4., -4.], [-4., -4., 8., -4.]]])
    target = {"boxes": boxes[0].clone(), "classes": torch.tensor([0, 2])}
    correct = detection_loss({"boxes": boxes, "logits": logits}, [target])
    reversed_target = {k: v.flip(0) for k, v in target.items()}
    assert detection_loss({"boxes": boxes, "logits": logits}, [reversed_target]) == pytest.approx(correct)
    wrong = boxes.clone(); wrong[..., :3] += .5
    assert detection_loss({"boxes": wrong, "logits": logits}, [target]) > correct + 3


def test_observation_preprocess_with_truth_files_absent(tmp_path):
    import json
    import shutil
    from pathlib import Path
    from learning.data import preprocess
    root = Path(__file__).resolve().parents[2]
    source = root / "artifacts/sf10/pilot-300-v4/sf10v4-0000"
    if not source.exists():
        pytest.skip("Local capture acceptance fixture not installed")
    obs = json.loads((source / "observation.json").read_text())
    directory = tmp_path / obs["capture_id"]; directory.mkdir()
    shutil.copy2(source / "observation.json", directory)
    for modality in ("rgb", "ir", "lidar"):
        for ref in obs[modality]["data"].values():
            if isinstance(ref, dict) and "artifact" in ref:
                name = ref["artifact"]["id"]
                shutil.copy2(source / name, directory / name)
    original, _ = preprocess(source.parent, obs["capture_id"])
    isolated, _ = preprocess(tmp_path, obs["capture_id"])
    assert all(torch.equal(original[k], isolated[k]) for k in original)
    assert not (directory / "annotations.json").exists()
    assert not (directory / "truth.json").exists()

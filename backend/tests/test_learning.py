"""Independent geometry, matching and observation isolation acceptance."""
import numpy as np
import pytest
torch = pytest.importorskip("torch", reason="Run learning tests with the locked learning environment")

from learning.evaluate import box_iou, evaluate
from learning.model import Detector, detection_loss, detection_loss_reference, pack_targets


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


@pytest.mark.parametrize("device", ["cpu", pytest.param("cuda", marks=pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA unavailable"))])
def test_batched_loss_preserves_reference_values_and_gradients(device):
    torch.manual_seed(11)
    boxes = torch.rand(8, 16, 7, device=device); boxes[..., 3:6] += .1
    logits = torch.randn(8, 16, 4, device=device)
    targets = [{"boxes": torch.rand(i % 4, 7), "classes": torch.arange(i % 4) % 3} for i in range(8)]
    for target in targets: target["boxes"][:, 3:6] += .1
    original = {"boxes": boxes.clone().requires_grad_(), "logits": logits.clone().requires_grad_()}
    batched = {"boxes": boxes.clone().requires_grad_(), "logits": logits.clone().requires_grad_()}
    old = detection_loss_reference(original, targets)
    new = detection_loss(batched, pack_targets(targets, device))
    torch.testing.assert_close(new, old, rtol=2e-6, atol=1e-6)
    old.backward(); new.backward()
    for key in original:
        torch.testing.assert_close(batched[key].grad, original[key].grad, rtol=3e-6, atol=1e-6)


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


@pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA unavailable")
def test_native_assignment_optimality_and_graph_stream():
    from learning.matching import available, assignment, load
    from scipy.optimize import linear_sum_assignment
    if not available(): pytest.skip("Native matcher has not been built")
    load()
    generator = torch.Generator().manual_seed(921)
    # Empty/full targets, continuous costs and many ties; negative costs are valid.
    for queries in (1, 5, 16):
        capacity = queries
        costs = torch.randn(80, queries, capacity, generator=generator)
        costs[40:] = costs[40:].round()
        costs[0] = 0
        counts = torch.arange(80, dtype=torch.int64) % (capacity + 1)
        counts[0] = capacity
        gpu_cost, gpu_counts = costs.cuda(), counts.cuda()
        with torch.cuda.stream(torch.cuda.Stream()):
            matched = assignment(gpu_cost, gpu_counts)
            graph = torch.cuda.CUDAGraph()
            with torch.cuda.graph(graph): replayed = assignment(gpu_cost, gpu_counts)
            graph.replay()
        torch.cuda.synchronize()
        torch.testing.assert_close(matched, replayed, rtol=0, atol=0)
        actual = matched.cpu().numpy()
        for i, count in enumerate(counts.tolist()):
            rows = np.flatnonzero(actual[i] >= 0)
            assert len(rows) == count
            assert len(set(actual[i, rows])) == count
            r, c = linear_sum_assignment(costs[i, :, :count].numpy())
            assert float(costs[i, rows, actual[i, rows]].double().sum()) == pytest.approx(
                float(costs[i, r, c].double().sum()), abs=1e-7)
    invalid = torch.zeros(3,16,2,device="cuda")
    invalid[2,0,0] = float("nan")
    result = assignment(invalid, torch.tensor([-1,3,1],device="cuda",dtype=torch.int64))
    assert (result == -2).all()


@pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA unavailable")
def test_native_loss_preserves_reference_values_and_gradients():
    from learning.matching import available
    if not available(): pytest.skip("Native matcher has not been built")
    torch.manual_seed(321)
    boxes = torch.rand(17, 16, 7, device="cuda"); boxes[..., 3:6] += .1
    logits = torch.randn(17, 16, 4, device="cuda")
    targets = [{"boxes": torch.rand(i, 7), "classes": torch.arange(i) % 3} for i in range(17)]
    for target in targets: target["boxes"][:, 3:6] += .1
    left = {"boxes": boxes.clone().requires_grad_(), "logits": logits.clone().requires_grad_()}
    right = {k: v.detach().clone().requires_grad_() for k,v in left.items()}
    old = detection_loss_reference(left, targets)
    new = detection_loss(right, pack_targets(targets, "cuda"), native=True)
    torch.testing.assert_close(new, old, rtol=2e-6, atol=1e-6)
    old.backward(); new.backward()
    for key in left: torch.testing.assert_close(right[key].grad, left[key].grad, rtol=3e-6, atol=1e-6)


@pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA unavailable")
@pytest.mark.parametrize("modality", ["rgb", "ir", "lidar", "fusion"])
@pytest.mark.parametrize("graph_optimizer", [False, True])
def test_graph_training_mixed_shapes_matches_eager_and_inference(modality, graph_optimizer):
    import copy
    from learning.matching import available
    from learning.model import target_batch, predictions
    from learning.runtime import GraphTrainer, GraphInference
    if not available(): pytest.skip("Native matcher has not been built")
    torch.manual_seed(981)
    torch.use_deterministic_algorithms(True)
    torch.backends.cuda.enable_flash_sdp(False)
    torch.backends.cuda.enable_mem_efficient_sdp(False)
    inputs = {"rgb": torch.rand(5, 3, 96, 160, device="cuda"), "ir": torch.rand(5, 1, 96, 160, device="cuda"),
              "lidar": torch.rand(5, 256, 4, device="cuda"),
              "point_valid": torch.ones(5, 256, dtype=torch.bool, device="cuda"),
              "calibration": torch.rand(5, 32, device="cuda")}
    targets = [{"boxes": torch.rand(i % 4, 7), "classes": torch.arange(i % 4) % 3} for i in range(5)]
    for t in targets: t["boxes"][:, 3:6] += .1
    packed = pack_targets(targets, "cuda")
    eager = Detector(modality).cuda(); graphed = copy.deepcopy(eager)
    left = torch.optim.AdamW(eager.parameters(), lr=.001, weight_decay=.0001)
    right = torch.optim.AdamW(graphed.parameters(), lr=.001, weight_decay=.0001)
    trainer = GraphTrainer(graphed, inputs, packed, right if graph_optimizer else None)
    trainer.prepare(3); trainer.prepare(2)
    for indices in ([0, 2, 4], [3, 1], [2, 1, 0], [4, 0]):
        eager.train(); graphed.train()
        ids = torch.tensor(indices, device="cuda")
        left.zero_grad(set_to_none=True)
        loss = detection_loss(eager({k:v[ids] for k,v in inputs.items()}), target_batch(packed, indices), native=True)
        loss.backward(); torch.nn.utils.clip_grad_norm_(eager.parameters(), 1.0); left.step()
        graph_loss = trainer.step(ids, right)
        torch.testing.assert_close(graph_loss, loss, rtol=0, atol=0)
        for a,b in zip(eager.parameters(), graphed.parameters()): torch.testing.assert_close(a,b,rtol=0,atol=0)
        for a,b in zip(eager.parameters(), graphed.parameters()):
            for key in left.state[a]: torch.testing.assert_close(left.state[a][key],right.state[b][key],rtol=0,atol=0)
    graphed.eval()
    reference = []
    with torch.no_grad():
        for start in range(0,5,3): reference.extend(predictions(graphed({k:v[start:start+3] for k,v in inputs.items()})))
    for p in reference: p["boxes"][:, :6] *= 200
    runner = GraphInference(graphed)
    actual = runner.infer(inputs,3)
    for a,b in zip(reference,actual):
        for k in a: np.testing.assert_array_equal(a[k], b[k])
    # Capture must not perform a hidden optimizer update.
    assert all(float(s["step"]) == 4 for s in right.state.values())

"""Deterministic bilinear sampling preserves the sparse image observation operation."""
import os
os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
import pytest
torch = pytest.importorskip("torch")
import torch.nn.functional as F


@pytest.mark.parametrize("dtype,tolerance", [(torch.float64, 1e-12), (torch.float32, 2e-6)])
def test_sampling_matches_grid_sample_values_and_feature_and_coordinate_gradients(dtype, tolerance):
    from learning.essrf_model import bilinear_sample
    generator = torch.Generator().manual_seed(7)
    features = torch.randn(2, 3, 4, 5, generator=generator, dtype=dtype, requires_grad=True)
    grid = (torch.rand(2, 31, 1, 2, generator=generator, dtype=dtype) * 4 - 2).requires_grad_()
    expected = F.grid_sample(features, grid, align_corners=True)
    actual = bilinear_sample(features, grid)
    weights = torch.randn(expected.shape, generator=generator, dtype=dtype)
    ref_grads = torch.autograd.grad((expected * weights).sum(), (features, grid), retain_graph=True)
    grads = torch.autograd.grad((actual * weights).sum(), (features, grid))
    assert torch.allclose(actual, expected, atol=tolerance, rtol=tolerance)
    for actual_grad, expected_grad in zip(grads, ref_grads):
        assert torch.allclose(actual_grad, expected_grad, atol=tolerance, rtol=tolerance)


def test_sampler_edges_and_off_image_neighborhoods_preserve_zero_padding():
    from learning.essrf_model import bilinear_sample
    features = torch.arange(20.).reshape(1, 1, 4, 5).requires_grad_()
    grid = torch.tensor([[[[-1., -1.]], [[1., 1.]], [[-1.2, -.3]], [[3., 3.]], [[0., 0.]]]], requires_grad=True)
    assert torch.allclose(bilinear_sample(features, grid), F.grid_sample(features, grid, align_corners=True), atol=1e-6)


@pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA acceptance")
def test_complete_essrf_backward_is_repeatable_under_deterministic_cuda():
    from learning.essrf_model import ESSRF
    from learning.essrf_training import seed_all
    from test_essrf import synthetic_inputs
    previous = torch.are_deterministic_algorithms_enabled()
    previous_fill = torch.utils.deterministic.fill_uninitialized_memory
    torch.use_deterministic_algorithms(True)
    torch.utils.deterministic.fill_uninitialized_memory = False
    try:
        inputs = {k: v.cuda() for k, v in synthetic_inputs(batch=2).items()}
        results = []
        for _ in range(2):
            seed_all(11)
            model = ESSRF(queries=8, width=32, samples=4, layers=2, global_context=False).cuda()
            out = model(inputs, expert_subsets=torch.tensor([3, 7], device="cuda"))
            loss = out["probability"].square().sum() + out["boxes"].sum() + out["expert"]["probability"].sum()
            loss.backward()
            results.append((out["probability"].detach().clone(),
                            {k: v.grad.clone() for k, v in model.named_parameters() if v.grad is not None}))
        assert torch.equal(results[0][0], results[1][0])
        assert all(torch.equal(v, results[1][1][k]) for k, v in results[0][1].items())
    finally:
        torch.use_deterministic_algorithms(previous)
        torch.utils.deterministic.fill_uninitialized_memory = previous_fill

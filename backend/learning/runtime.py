"""Fixed-shape CUDA graph compute with unchanged eager AdamW arithmetic.

Graph capture runs forward, exact device assignment, loss, backward and clipping.
It never steps the optimizer during warmup/capture. AdamW retains CPU step counts
and the original update arithmetic. Tail batches get their actual shape.
"""
import numpy as np
import torch
from .model import detection_loss
from .matching import load


class AdamWGraphPrefix:
    """Capture fixed AdamW work; keep changing bias corrections on CPU.

    Uses the same foreach operations and their original order as PyTorch's
    non-capturable AdamW. CPU step counters and checkpoint state stay standard.
    Only the three bias-correction/update operations remain eager.
    """
    def __init__(self, optimizer):
        if len(optimizer.param_groups) != 1:
            raise ValueError("Graph AdamW requires one parameter group")
        self.optimizer = optimizer
        self.group = optimizer.param_groups[0]
        if not isinstance(optimizer, torch.optim.AdamW) or not self.group["decoupled_weight_decay"]:
            raise ValueError("Graph optimizer requires AdamW")
        if (self.group["amsgrad"] or self.group["maximize"] or self.group["capturable"]
            or self.group["differentiable"] or self.group["fused"] or self.group["foreach"] is False):
            raise ValueError("Graph AdamW requires the baseline foreach FP32 profile")
        self.parameters = self.group["params"]
        for p in self.parameters:
            if not p.is_cuda or p.dtype != torch.float32 or not p.is_contiguous():
                raise ValueError("Graph AdamW requires contiguous CUDA FP32 parameters")
            state = optimizer.state[p]
            if not state:
                state.update(step=torch.tensor(0.0), exp_avg=torch.zeros_like(p), exp_avg_sq=torch.zeros_like(p))
            if not state["step"].is_cpu:
                raise ValueError("Non-capturable AdamW step counters must stay on CPU")
        self.means = [optimizer.state[p]["exp_avg"] for p in self.parameters]
        self.variances = [optimizer.state[p]["exp_avg_sq"] for p in self.parameters]
        self.steps = [optimizer.state[p]["step"] for p in self.parameters]

    @torch.no_grad()
    def prepare(self, gradients, stream):
        beta1, beta2 = self.group["betas"]

        def compute():
            torch._foreach_mul_(self.parameters, 1-self.group["lr"]*self.group["weight_decay"])
            torch._foreach_lerp_(self.means, gradients, 1-beta1)
            torch._foreach_mul_(self.variances, beta2)
            torch._foreach_addcmul_(self.variances, gradients, gradients, 1-beta2)
            return torch._foreach_sqrt(self.variances)

        # Warmup and capture mutate live tensors; restore every value before
        # returning. Step counters are never incremented during preparation.
        tensors = self.parameters + self.means + self.variances
        saved = [t.clone() for t in tensors]
        stream.wait_stream(torch.cuda.current_stream())
        with torch.cuda.stream(stream):
            for _ in range(3): compute()
        torch.cuda.current_stream().wait_stream(stream)
        graph = torch.cuda.CUDAGraph()
        with torch.cuda.graph(graph, stream=stream): denominators = compute()
        torch.cuda.current_stream().wait_stream(stream)
        for t,value in zip(tensors, saved): t.copy_(value)
        return graph, denominators

    @torch.no_grad()
    def step(self, captured):
        graph, denominators = captured
        graph.replay()
        torch._foreach_add_(self.steps, torch.tensor(1.0), alpha=1.0)
        beta1, beta2 = self.group["betas"]
        numbers = [float(s) for s in self.steps]
        corrections = [(1-beta2**s)**.5 for s in numbers]
        sizes = [-self.group["lr"]/(1-beta1**s) for s in numbers]
        torch._foreach_div_(denominators, corrections)
        torch._foreach_add_(denominators, self.group["eps"])
        torch._foreach_addcdiv_(self.parameters, self.means, denominators, sizes)


class GraphTrainer:
    def __init__(self, model, features, targets, optimizer=None):
        if not features["calibration"].is_cuda:
            raise ValueError("CUDA graphs require CUDA-resident observations")
        load()  # DLL loading is outside graph capture.
        self.model, self.features, self.targets = model, features, targets
        self.graphs = {}
        self.stream = torch.cuda.Stream(device=features["calibration"].device)
        self.optimizer_prefix = AdamWGraphPrefix(optimizer) if optimizer is not None else None
        self.finite = torch.ones((), dtype=torch.bool, device=features["calibration"].device)

    def prepare(self, size):
        if size in self.graphs:
            return
        device = self.features["calibration"].device
        ids = torch.arange(size, device=device) % len(self.features["calibration"])
        # CPU metadata is a capacity guard only. Native matching reads current GPU counts.
        counts = np.full(size, self.targets["boxes"].shape[1], dtype=np.int64)

        def compute():
            self.model.zero_grad(set_to_none=True)
            features = {k: v[ids] for k, v in self.features.items()}
            targets = {k: self.targets[k][ids] for k in ("boxes", "classes", "counts_device")}
            targets["counts"] = counts
            targets["weights"] = self.targets["weights"]
            loss = detection_loss(self.model(features), targets, native=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(self.model.parameters(), 1.0)
            self.finite.logical_and_(torch.isfinite(loss))
            return loss

        stream = self.stream
        stream.wait_stream(torch.cuda.current_stream(device))
        with torch.cuda.stream(stream):
            for _ in range(3): compute()
        torch.cuda.current_stream(device).wait_stream(stream)
        graph = torch.cuda.CUDAGraph()
        with torch.cuda.graph(graph, stream=stream):
            loss = compute()
        torch.cuda.current_stream(device).wait_stream(stream)
        loss = loss.detach()
        # Keep the exact gradient buffers belonging to this graph. Other batch
        # sizes and eager fallbacks must not replace their optimizer bindings.
        gradients = [p.grad for p in self.model.parameters()]
        prefix = self.optimizer_prefix.prepare(gradients, stream) if self.optimizer_prefix else None
        self.graphs[size] = (graph, ids, loss, gradients, prefix)

    def step(self, ids, optimizer):
        graph, static_ids, loss, gradients, prefix = self.graphs[len(ids)]
        static_ids.copy_(ids)
        for parameter, gradient in zip(self.model.parameters(), gradients):
            parameter.grad = gradient
        graph.replay()
        if prefix:
            if optimizer is not self.optimizer_prefix.optimizer:
                raise ValueError("Graph optimizer identity changed")
            self.optimizer_prefix.step(prefix)
        else:
            optimizer.step()
        return loss.detach().clone()  # loss buffer is overwritten on replay

    def begin_epoch(self):
        self.finite.fill_(True)

    def check_finite(self):
        if not bool(self.finite):
            raise ValueError("Nonfinite loss during graph training")


class GraphInference:
    def __init__(self, model):
        self.model, self.graphs = model, {}
        self.stream = torch.cuda.Stream(device=next(model.parameters()).device)

    @torch.no_grad()
    def prepare(self, features, size):
        if size in self.graphs: return
        inputs = {k: v[:size].clone() for k,v in features.items()}

        def compute():
            output = self.model(inputs)
            return torch.cat((output["boxes"], output["logits"].softmax(-1)), -1)

        self.stream.wait_stream(torch.cuda.current_stream())
        with torch.cuda.stream(self.stream):
            for _ in range(3): compute()
        torch.cuda.current_stream().wait_stream(self.stream)
        graph = torch.cuda.CUDAGraph()
        with torch.cuda.graph(graph, stream=self.stream): arrays = compute()
        torch.cuda.current_stream().wait_stream(self.stream)
        self.graphs[size] = graph, inputs, arrays

    @torch.no_grad()
    def infer(self, features, size):
        from .model import predictions_from_arrays
        self.model.eval()
        count = len(features["calibration"])
        for shape in {min(size, count), count % size} - {0}: self.prepare(features, shape)
        output = []
        for start in range(0, count, size):
            length = min(size, count-start)
            graph, inputs, arrays = self.graphs[length]
            for k,v in features.items(): inputs[k].copy_(v[start:start+length])
            graph.replay()
            output.append(arrays.clone())
        # One D2H boundary for the entire validation split, after all forwards.
        predicted = predictions_from_arrays(torch.cat(output).cpu().numpy())
        for item in predicted: item["boxes"][:, :6] *= 200
        return predicted

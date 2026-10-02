"""Fixed-shape CUDA graph compute with unchanged eager AdamW arithmetic.

Graph capture runs forward, exact device assignment, loss, backward and clipping.
It never steps the optimizer during warmup/capture. AdamW retains CPU step counts
and the original update arithmetic. Tail batches get their actual shape.
"""
import numpy as np
import torch
from .model import detection_loss
from .matching import load


class GraphTrainer:
    def __init__(self, model, features, targets):
        if not features["calibration"].is_cuda:
            raise ValueError("CUDA graphs require CUDA-resident observations")
        load()  # DLL loading is outside graph capture.
        self.model, self.features, self.targets = model, features, targets
        self.graphs = {}
        self.stream = torch.cuda.Stream(device=features["calibration"].device)
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
        self.graphs[size] = (graph, ids, loss, gradients)

    def step(self, ids, optimizer):
        graph, static_ids, loss, gradients = self.graphs[len(ids)]
        static_ids.copy_(ids)
        for parameter, gradient in zip(self.model.parameters(), gradients):
            parameter.grad = gradient
        graph.replay()
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

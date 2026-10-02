"""Stream-aware native matching; CPU/SciPy remains the portable reference."""
import ctypes
import hashlib
import json
from pathlib import Path
import torch

LIBRARY = Path(__file__).resolve().parents[2] / "artifacts/sf11/cuda/learning_matching.dll"
SOURCE = Path(__file__).parent / "cuda/matching.cu"
_library = None


def available():
    manifest = LIBRARY.with_suffix(".json")
    if not LIBRARY.is_file() or not manifest.is_file(): return False
    try:
        provenance = json.loads(manifest.read_text(encoding="utf-8-sig"))
        return (provenance["source_sha256"] == hashlib.sha256(SOURCE.read_bytes()).hexdigest()
                and provenance["library_sha256"] == hashlib.sha256(LIBRARY.read_bytes()).hexdigest())
    except (ValueError, KeyError, OSError): return False


def load():
    global _library
    if _library is None:
        if not available():
            raise RuntimeError("Build the CUDA matcher with tools/build-learning-cuda.ps1")
        _library = ctypes.CDLL(str(LIBRARY))
        _library.learning_assign.argtypes = [ctypes.c_void_p] * 3 + [ctypes.c_int] * 3 + [ctypes.c_void_p]
        _library.learning_assign.restype = ctypes.c_int
        _library.learning_overlaps.argtypes = [ctypes.c_void_p] * 5 + [ctypes.c_int] * 3 + [ctypes.c_void_p]
        _library.learning_overlaps.restype = ctypes.c_int
    return _library


def assignment(cost, counts):
    if not cost.is_cuda or cost.dtype != torch.float32 or not cost.is_contiguous():
        raise ValueError("Native matching requires contiguous CUDA FP32 costs")
    if counts.device != cost.device or counts.dtype != torch.int64 or not counts.is_contiguous():
        raise ValueError("Native matching requires same-device contiguous int64 counts")
    batch, queries, capacity = cost.shape
    if counts.shape != (batch,) or not 1 <= capacity <= queries <= 16:
        raise ValueError("Native matching supports 1..16 queries and bounded targets")
    result = torch.empty((batch, queries), device=cost.device, dtype=torch.int64)
    with torch.cuda.device(cost.device):
        error = load().learning_assign(cost.data_ptr(), counts.data_ptr(), result.data_ptr(),
                                      batch, queries, capacity, torch.cuda.current_stream().cuda_stream)
    if error:
        raise RuntimeError(f"CUDA assignment launch failed: {error}")
    return result


def frame_overlaps(predictions, targets, device=None):
    """Exact FP32 clipping over CPU-prepared geometry, one transfer per split."""
    import numpy as np
    from .evaluate import rectangle
    count = len(predictions)
    device = torch.device("cuda") if device is None else torch.device(device)
    if count != len(targets) or count == 0: raise ValueError("Evaluation frame count mismatch")

    def packed(frames):
        counts = np.array([len(f["boxes"]) for f in frames],dtype=np.int64)
        capacity = max(1,int(counts.max()))
        if capacity > 16: raise ValueError("Native evaluation supports at most 16 boxes per frame")
        data = np.zeros((count,capacity,11),dtype=np.float32)
        for i,frame in enumerate(frames):
            boxes = frame["boxes"]
            if boxes.dtype != np.float32: raise ValueError("Native evaluation requires the FP32 baseline profile")
            if not np.isfinite(boxes).all() or (boxes[:,3:6] <= 0).any(): raise ValueError("Invalid detection box")
            for j,box in enumerate(boxes):
                data[i,j,:8] = rectangle(box).ravel()
                data[i,j,8:10] = [box[1]-box[4]/2,box[1]+box[4]/2]
                data[i,j,10] = np.prod(box[3:6])
        if not np.isfinite(data).all(): raise ValueError("Nonfinite evaluation geometry")
        return torch.from_numpy(data).to(device),torch.from_numpy(counts).to(device)

    left,na = packed(predictions); right,nb = packed(targets)
    output = torch.empty((count,left.shape[1],right.shape[1]),device=left.device,dtype=torch.float32)
    with torch.cuda.device(left.device):
        error = load().learning_overlaps(left.data_ptr(),right.data_ptr(),na.data_ptr(),nb.data_ptr(),output.data_ptr(),
                                        count,left.shape[1],right.shape[1],torch.cuda.current_stream().cuda_stream)
    if error: raise RuntimeError(f"CUDA overlap launch failed: {error}")
    matrices = output.cpu().numpy()
    if not np.isfinite(matrices).all(): raise ValueError("Invalid native overlap result")
    return [matrices[i,:len(p["boxes"]),:len(t["boxes"])] for i,(p,t) in enumerate(zip(predictions,targets))]

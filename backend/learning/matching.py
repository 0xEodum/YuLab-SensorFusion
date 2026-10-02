"""Stream-aware native matching; CPU/SciPy remains the portable reference."""
import ctypes
from pathlib import Path
import torch

LIBRARY = Path(__file__).resolve().parents[2] / "artifacts/sf11/cuda/learning_matching.dll"
_library = None


def available():
    return LIBRARY.is_file()


def load():
    global _library
    if _library is None:
        if not available():
            raise RuntimeError("Build the CUDA matcher with tools/build-learning-cuda.ps1")
        _library = ctypes.CDLL(str(LIBRARY))
        _library.learning_assign.argtypes = [ctypes.c_void_p] * 3 + [ctypes.c_int] * 3 + [ctypes.c_void_p]
        _library.learning_assign.restype = ctypes.c_int
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

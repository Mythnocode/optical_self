
from __future__ import annotations

from pathlib import Path
from typing import Any
import numpy as np


def _open_descriptor(value: dict[str, Any]) -> np.memmap:
    path = Path(str(value["__local_npy__"]))
    if not path.is_file():
        raise FileNotFoundError(path)
    stat = path.stat()
    expected_size = int(value.get("file_size", 0) or 0)
    expected_mtime = int(value.get("mtime_ns", 0) or 0)
    if expected_size and stat.st_size != expected_size:
        raise RuntimeError(f"本地数组文件大小已变化：{path}")
    if expected_mtime and stat.st_mtime_ns != expected_mtime:
        raise RuntimeError(f"本地数组文件已被替换：{path}")
    array = np.load(path, mmap_mode="r", allow_pickle=False)
    expected_shape = tuple(int(item) for item in value.get("shape", array.shape))
    expected_dtype = str(value.get("dtype", array.dtype))
    if tuple(array.shape) != expected_shape or str(array.dtype) != expected_dtype:
        close = getattr(getattr(array, "_mmap", None), "close", None)
        if callable(close):
            close()
        raise RuntimeError(f"本地数组描述与文件不一致：{path}")
    if array.flags.writeable:
        array.flags.writeable = False
    return array


def materialize_local_arrays(value: Any) -> Any:
    if isinstance(value, dict) and "__local_npy__" in value:
        return _open_descriptor(value)
    if isinstance(value, dict):
        return {key: materialize_local_arrays(item) for key, item in value.items()}
    if isinstance(value, list):
        return [materialize_local_arrays(item) for item in value]
    return value


__all__ = ["materialize_local_arrays"]

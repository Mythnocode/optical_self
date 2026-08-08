
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import numpy as np


def save_numeric_arrays_npz(arrays: Mapping[str, Any], path: str | Path) -> Path:


    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    numeric: dict[str, np.ndarray] = {}
    for name, value in arrays.items():
        array = np.asarray(value)
        if array.dtype.kind in "biufc" and array.size > 0:
            numeric[str(name)] = array
    np.savez_compressed(destination, **numeric)
    return destination

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np


def save_npz_bundle(path: str | Path, *, arrays: dict[str, Any], metadata: dict[str, Any] | None = None) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {key: np.asarray(value) for key, value in arrays.items()}
    payload["__metadata_json__"] = np.asarray(json.dumps(metadata or {}, ensure_ascii=False))
    np.savez_compressed(target, **payload)
    return target


def load_npz_bundle(path: str | Path) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    source = Path(path)
    arrays: dict[str, np.ndarray] = {}
    metadata: dict[str, Any] = {}
    with np.load(source, allow_pickle=False) as data:
        for key in data.files:
            if key == "__metadata_json__":
                metadata = json.loads(str(data[key].item()))
            else:
                arrays[key] = data[key]
    return arrays, metadata

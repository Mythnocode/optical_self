"""数值计算后端选择入口。"""
from __future__ import annotations

import numpy as np


def get_array_module(name: str = "numpy"):

    normalized = str(name or "numpy").lower()
    if normalized != "numpy":
        raise ValueError(f"当前重构版本只启用 numpy 后端，不支持: {name}")
    return np


__all__ = ["get_array_module", "np"]

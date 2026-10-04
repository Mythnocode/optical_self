"""仿真数组适配辅助函数。

本模块统一处理结果字典中的数组读取、有限值过滤、形状归一化和数值安全转换，
避免各个绘图适配器重复编写兼容不同后端返回格式的代码。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
import os
import numpy as np

def _first(mapping: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return None

def _as_1d(value: Any, dtype=float) -> np.ndarray:
    try:
        array = np.asarray(value if value is not None else [], dtype=dtype).reshape(-1)
    except (TypeError, ValueError):
        return np.asarray([], dtype=dtype)
    return array

def _as_2d(value: Any, columns: int | None = None) -> np.ndarray:
    try:
        array = np.asarray(value if value is not None else [], dtype=float)
    except (TypeError, ValueError):
        return np.empty((0, columns or 0), dtype=float)
    if not array.size:
        return np.empty((0, columns or 0), dtype=float)
    if columns is not None:
        try:
            array = array.reshape(-1, columns)
        except ValueError:
            return np.empty((0, columns), dtype=float)
    elif array.ndim != 2:
        return np.empty((0, 0), dtype=float)
    return array

def _error_text(item: Any) -> str:
    if isinstance(item, Mapping):
        code = str(item.get("code", "ERROR"))
        message = str(item.get("message", item))
        return f"{code}: {message}"
    return str(item)


def _preview_indices(shape: tuple[int, int], max_side: int | None = None) -> tuple[np.ndarray, np.ndarray]:

    limit = int(max_side or os.environ.get("OPTICAL_PREVIEW_MAX_SIDE", "321") or 321)
    limit = max(65, limit)
    rows, cols = int(shape[0]), int(shape[1])
    row_index = (
        np.arange(rows, dtype=int)
        if rows <= limit
        else np.unique(np.linspace(0, rows - 1, limit).round().astype(int))
    )
    col_index = (
        np.arange(cols, dtype=int)
        if cols <= limit
        else np.unique(np.linspace(0, cols - 1, limit).round().astype(int))
    )
    return row_index, col_index


def _preview_grid(
    values: np.ndarray,
    x: np.ndarray,
    y: np.ndarray,
    *,
    max_side: int | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    values = np.asarray(values)
    if values.ndim != 2 or not values.size:
        return values, np.asarray(x), np.asarray(y), np.arange(0), np.arange(0)
    row_index, col_index = _preview_indices(values.shape, max_side)
    preview = values[np.ix_(row_index, col_index)]
    x_values = np.asarray(x)
    y_values = np.asarray(y)
    if len(x_values) == values.shape[1]:
        x_values = x_values[col_index]
    if len(y_values) == values.shape[0]:
        y_values = y_values[row_index]
    return preview, x_values, y_values, row_index, col_index

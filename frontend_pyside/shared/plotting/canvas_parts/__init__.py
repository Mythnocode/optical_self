
"""按绘图维度和职责拆分的画布实现。

``canvas_2d`` 负责二维绘图分发，``canvas_3d`` 负责 3D 场景入口，
``data_utils`` 和 ``interaction`` 提供它们共用的数据与交互辅助。
"""

from __future__ import annotations

from importlib import import_module

_EXPORTS = {
    "Canvas2DMixin": (".canvas_2d", "Canvas2DMixin"),
    "Canvas3DMixin": (".canvas_3d", "Canvas3DMixin"),
    "CanvasInteractionMixin": (".interaction", "CanvasInteractionMixin"),
}


def __getattr__(name: str):
    module_name, attr_name = _EXPORTS.get(name, (None, None))
    if module_name is None:
        raise AttributeError(name)
    value = getattr(import_module(module_name, __name__), attr_name)
    globals()[name] = value
    return value


__all__ = list(_EXPORTS)

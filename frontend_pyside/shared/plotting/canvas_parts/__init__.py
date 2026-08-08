
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

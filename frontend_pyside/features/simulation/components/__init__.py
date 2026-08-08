
from __future__ import annotations

from importlib import import_module

_EXPORTS = {
    "SurfaceTypeDelegate": (".surface_delegate", "SurfaceTypeDelegate"),
    "OpticalSystemEditor": (".optical_system_editor", "OpticalSystemEditor"),
    "SimpleParameterTabs": (".parameter_tabs", "SimpleParameterTabs"),
}


def __getattr__(name: str):
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(name)
    module_name, attr_name = target
    value = getattr(import_module(module_name, __name__), attr_name)
    globals()[name] = value
    return value


__all__ = list(_EXPORTS)

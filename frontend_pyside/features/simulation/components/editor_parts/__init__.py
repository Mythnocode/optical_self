
from __future__ import annotations

from importlib import import_module

_EXPORTS = {
    "SurfacePropertyMixin": (".property_behavior", "SurfacePropertyMixin"),
    "SurfaceTableMixin": (".table_behavior", "SurfaceTableMixin"),
    "SurfaceCommandMixin": (".command_behavior", "SurfaceCommandMixin"),
}


def __getattr__(name: str):
    try:
        module_name, attribute = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
    value = getattr(import_module(module_name, __name__), attribute)
    globals()[name] = value
    return value


__all__ = list(_EXPORTS)

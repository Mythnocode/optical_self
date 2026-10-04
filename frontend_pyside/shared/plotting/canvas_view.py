"""Compatibility facade for the shared presentation implementation."""
from shared_presentation.plotting import canvas_view as _implementation

globals().update({name: value for name, value in vars(_implementation).items() if not name.startswith("__")})

__all__ = _implementation.__all__

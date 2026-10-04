"""Compatibility facade for the shared presentation implementation."""
import shared_presentation.plotting.canvas_2d as _implementation

globals().update({name: value for name, value in vars(_implementation).items() if not name.startswith("__")})

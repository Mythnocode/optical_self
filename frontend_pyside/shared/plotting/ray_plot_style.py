"""Compatibility facade for the shared presentation implementation."""
import shared_presentation.plotting.ray_plot_style as _implementation

globals().update({name: value for name, value in vars(_implementation).items() if not name.startswith("__")})

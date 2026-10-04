"""Compatibility facade for the shared presentation implementation."""
from shared_presentation.plotting.optical_scene_models import __dict__ as _implementation
globals().update({key: value for key, value in _implementation.items() if not key.startswith("__")})

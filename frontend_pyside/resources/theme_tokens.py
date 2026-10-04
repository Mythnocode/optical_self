"""Compatibility facade for shared presentation colors."""
from shared_presentation.theme_tokens import __dict__ as _implementation
globals().update({key: value for key, value in _implementation.items() if not key.startswith("__")})

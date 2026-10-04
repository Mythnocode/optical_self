"""Compatibility exports for the shared original quantity parser."""
from shared_presentation.quantities import UnitDefinition, can_parse_quantity, parse_quantity

__all__ = ["parse_quantity", "can_parse_quantity", "UnitDefinition"]

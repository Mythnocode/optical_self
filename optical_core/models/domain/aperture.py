# 定义圆形光阑

from dataclasses import dataclass


@dataclass(frozen=True)
class CircularApertureDefinition:
    radius_mm: float

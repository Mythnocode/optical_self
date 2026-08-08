# 定义探测器模型

from dataclasses import dataclass


@dataclass(frozen=True)
class DetectorDefinition:
    detector_id: str
    z_mm: float

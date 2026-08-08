# 定义多光路系统
 
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from optical_core.models.domain.system import SequentialOpticalSystem


@dataclass(slots=True)
class OpticalPathSpec:
    path_id: str
    system: SequentialOpticalSystem
    label: str = ""
    analyses: list[dict[str, Any]] = field(default_factory=list)
    options: dict[str, Any] = field(default_factory=dict)
    source: dict[str, Any] = field(default_factory=dict)
    receiver: dict[str, Any] = field(default_factory=dict)
    weight: float = 1.0
    enabled: bool = True


@dataclass(slots=True)
class MultiPathOpticalSystem:
    paths: list[OpticalPathSpec]
    combination_mode: str = "independent"

    def enabled_paths(self) -> list[OpticalPathSpec]:
        return [path for path in self.paths if path.enabled]

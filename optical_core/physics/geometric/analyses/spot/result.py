# 定义点列图结果数据结构。

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class SpotResult:
    metrics: dict[str, Any]
    arrays: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

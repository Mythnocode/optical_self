from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from optical_core.models.representations.scalar_field import ScalarField2D


@dataclass(frozen=True, slots=True)
class AliasingAudit:
    metrics: dict[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.warnings


def audit_field_edge_energy(field: ScalarField2D, *, edge_pixels: int | None = None, threshold: float = 0.05) -> AliasingAudit:


    intensity = np.abs(field.values) ** 2
    if intensity.size == 0:
        return AliasingAudit(metrics={"aliasing_edge_energy_ratio": 0.0}, warnings=("空光场无法进行混叠检查。",))

    n_y, n_x = intensity.shape
    border = edge_pixels if edge_pixels is not None else max(1, min(n_x, n_y) // 32)
    border = int(max(1, min(border, n_x // 2, n_y // 2)))

    mask = np.zeros_like(intensity, dtype=bool)
    mask[:border, :] = True
    mask[-border:, :] = True
    mask[:, :border] = True
    mask[:, -border:] = True

    total = float(np.sum(intensity))
    edge = float(np.sum(intensity[mask]))
    ratio = edge / total if total > 0 else 0.0
    warnings: list[str] = []
    if ratio > threshold:
        warnings.append(f"输出场边缘能量占比 {ratio:.3g}，存在窗口截断或混叠风险。")
    return AliasingAudit(
        metrics={
            "aliasing_edge_pixels": border,
            "aliasing_edge_energy_ratio": float(ratio),
        },
        warnings=tuple(warnings),
    )


__all__ = ["AliasingAudit", "audit_field_edge_energy"]

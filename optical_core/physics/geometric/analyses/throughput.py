# 几何通光效率计算。
# 根据追迹后仍有效的光线权重，计算通过系统的几何功率比例。
from __future__ import annotations

from optical_core.models.representations.trace import TraceBundle
from optical_core.physics.geometric.solvers.throughput_solver import geometric_throughput


def evaluate_throughput(trace: TraceBundle) -> dict[str, float]:
    return {"geometric_throughput": geometric_throughput(trace)}

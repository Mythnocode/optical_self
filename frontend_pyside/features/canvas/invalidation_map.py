"""DirtyScope → 失效分析种类映射表（方案 §6.3，纯数据 + 无副作用）。

节点侧的匹配键 = NodeSpec.analyses 中的分析标签：
raytrace / spot / mtf / psf / coupling / beam_propagation / catalogue。

物理语义对照（评审可调，见方案 §12）：
- RAY_TRACE：光源或系统参数（含镜头组表面）修改 → 几何量与波前全面失效；
- COUPLING：光纤/五轴参数修改 → 只影响模场匹配与耦合效率类图；
- WAVE_PROPAGATION：采样/传播参数修改 → 光束传播、PSF、相位、焦面；
- ANALYSIS_PLAN：分析清单修改 → 结果目录；
- FULL_SIMULATION：其他正式输入修改 → 全部（返回 None 表示不过滤）。
"""

from __future__ import annotations

from frontend_pyside.features.simulation.dirty_state import DirtyScope

_ALL = frozenset({"raytrace", "spot", "mtf", "psf", "coupling", "beam_propagation", "catalogue"})

INVALID_ANALYSES_BY_SCOPE: dict[DirtyScope, frozenset[str] | None] = {
    DirtyScope.CLEAN: frozenset(),
    DirtyScope.RAY_TRACE: _ALL,
    DirtyScope.COUPLING: frozenset({"coupling"}),
    DirtyScope.WAVE_PROPAGATION: frozenset({"psf", "beam_propagation"}),
    DirtyScope.ANALYSIS_PLAN: frozenset({"catalogue"}),
    DirtyScope.FULL_SIMULATION: None,  # None = 全部失效（不按标签过滤）
}


def affected_analyses(scope: int | DirtyScope | None) -> frozenset[str] | None:
    """DirtyScope → 失效分析标签集合；None 表示全量失效（scope 未知/未分级）。"""
    if scope is None:
        return None
    try:
        scope = DirtyScope(int(scope))
    except ValueError:
        return None
    return INVALID_ANALYSES_BY_SCOPE.get(scope, None)


def node_affected(analyses: frozenset[str] | set[str], scope: int | DirtyScope | None) -> bool:
    """节点是否受该 scope 影响：全量失效或声明标签与失效标签相交。"""
    affected = affected_analyses(scope)
    if affected is None:
        return True
    return bool(set(analyses) & affected)


__all__ = ["INVALID_ANALYSES_BY_SCOPE", "affected_analyses", "node_affected"]

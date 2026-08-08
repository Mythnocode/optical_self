
from __future__ import annotations

from collections.abc import Iterable


VIEW_ANALYSES: dict[str, frozenset[str]] = {
    "光路": frozenset({"raytrace"}),
    "3D光路": frozenset({"raytrace"}),
    "点列图": frozenset({"spot"}),
    "PSF": frozenset({"psf"}),
    "MTF": frozenset({"mtf"}),
    "端面匹配": frozenset({"coupling"}),
    "光束包络": frozenset({"coupling"}),
    "束腰位置": frozenset({"coupling"}),
    "相位对比": frozenset({"coupling"}),
    "多平面演化": frozenset({"coupling"}),
    "能量分解": frozenset({"coupling", "power_audit"}),
    "模式重叠": frozenset({"coupling"}),
    "耦合场": frozenset({"coupling"}),
    "中心截面": frozenset({"coupling"}),
    "振幅": frozenset({"coupling"}),
    "相位": frozenset({"coupling"}),
}

SPECIAL_ANALYSES = frozenset({
    "focus_search",
    "fiber_alignment",
    "power_audit",
})


def analyses_for_views(views: Iterable[str]) -> frozenset[str]:
    result: set[str] = set()
    for view in views:
        result.update(VIEW_ANALYSES.get(str(view), ()))
    return frozenset(result)


def plan_analyses(
    selected: Iterable[str],
    visible_views: Iterable[str],
    *,
    visible_only: bool,
) -> tuple[str, ...]:
    selected_set = {str(item) for item in selected if str(item)}
    if visible_only:
        
        
        
        planned = set(analyses_for_views(visible_views))
    else:
        planned = selected_set

    if not planned:
        planned.add("raytrace")
    return tuple(sorted(planned))


def views_missing_analyses(
    views: Iterable[str],
    available_analyses: Iterable[str],
) -> tuple[str, ...]:
    available = {str(item) for item in available_analyses}
    missing = [
        str(view)
        for view in views
        if not VIEW_ANALYSES.get(str(view), frozenset()).issubset(available)
    ]
    return tuple(missing)


__all__ = [
    "SPECIAL_ANALYSES",
    "VIEW_ANALYSES",
    "analyses_for_views",
    "plan_analyses",
    "views_missing_analyses",
]

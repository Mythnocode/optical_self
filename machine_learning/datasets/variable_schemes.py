"""Resolve user-facing lens presets to the sequential surface feature paths."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


_AIR_NAMES = {"", "AIR", "VACUUM", "空气", "真空"}
_NON_CURVED_TYPES = {"", "plane", "平面", "detector", "stop", "coordinate_break"}


@dataclass(frozen=True, slots=True)
class LensBinding:
    lens_index: int
    front_surface_index: int
    back_surface_index: int


@dataclass(frozen=True, slots=True)
class ResolvedVariableScheme:
    scheme_id: str
    label: str
    lens_count: int
    include_conic: bool
    bindings: tuple[LensBinding, ...]
    design_variable_paths: tuple[str, ...]


def _material(value: object) -> str:
    return str(value or "").strip().upper()


def _is_curved(surface: Mapping[str, Any]) -> bool:
    surface_type = str(surface.get("surface_type") or "").strip().lower()
    try:
        radius = float(surface.get("radius_mm"))
    except (TypeError, ValueError):
        return False
    return surface_type not in _NON_CURVED_TYPES and abs(radius) > 1.0e-9


def resolve_lens_bindings(project: Mapping[str, Any]) -> tuple[LensBinding, ...]:
    """Treat every solid segment after a surface as one physical lens element."""
    surfaces = [row for row in (project.get("surfaces") or []) if isinstance(row, Mapping)]
    result: list[LensBinding] = []
    for surface_index, surface in enumerate(surfaces[:-1]):
        if _material(surface.get("material_after")) in _AIR_NAMES:
            continue
        result.append(LensBinding(len(result) + 1, surface_index, surface_index + 1))
    return tuple(result)


def resolve_variable_scheme(
    project: Mapping[str, Any], *, lens_count: int, include_conic: bool = False
) -> ResolvedVariableScheme:
    count = max(1, min(4, int(lens_count)))
    available = resolve_lens_bindings(project)
    if len(available) < count:
        raise ValueError(f"当前系统只识别到 {len(available)} 个实体透镜，无法使用 {count} 透镜方案。")
    bindings = available[:count]
    paths: list[str] = []
    for binding in bindings:
        front, back = binding.front_surface_index, binding.back_surface_index
        surfaces = [row for row in (project.get("surfaces") or []) if isinstance(row, Mapping)]
        paths.append(f"surfaces[{front}].distance_to_next_mm")
        if _is_curved(surfaces[front]):
            paths.insert(len(paths) - 1, f"surfaces[{front}].radius_mm")
        if _is_curved(surfaces[back]):
            paths.insert(len(paths), f"surfaces[{back}].radius_mm")
        if include_conic:
            if _is_curved(surfaces[front]):
                paths.append(f"surfaces[{front}].conic")
            if _is_curved(surfaces[back]):
                paths.append(f"surfaces[{back}].conic")
    prefix = ("单", "双", "三", "四")[count - 1]
    kind = "asphere" if include_conic else "basic"
    return ResolvedVariableScheme(
        scheme_id=f"{kind}_{count}_lens",
        label=f"{prefix}透镜·{'非球面' if include_conic else '基础'}方案",
        lens_count=count,
        include_conic=bool(include_conic),
        bindings=bindings,
        design_variable_paths=tuple(paths),
    )


def design_path_labels(scheme: ResolvedVariableScheme) -> dict[str, str]:
    labels: dict[str, str] = {}
    for binding in scheme.bindings:
        lens = f"第{binding.lens_index}片"
        front, back = binding.front_surface_index, binding.back_surface_index
        labels[f"surfaces[{front}].radius_mm"] = lens + "前表面曲率半径"
        labels[f"surfaces[{back}].radius_mm"] = lens + "后表面曲率半径"
        labels[f"surfaces[{front}].distance_to_next_mm"] = lens + "厚度"
        labels[f"surfaces[{front}].conic"] = lens + "前表面圆锥系数"
        labels[f"surfaces[{back}].conic"] = lens + "后表面圆锥系数"
    return labels


__all__ = ["LensBinding", "ResolvedVariableScheme", "design_path_labels", "resolve_lens_bindings", "resolve_variable_scheme"]

from __future__ import annotations

import math
import re
from dataclasses import dataclass


_NUMBER_RE = re.compile(
    r"^[\s\u00a0]*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*(.*?)\s*$"
)


@dataclass(frozen=True)
class UnitDefinition:
    dimension: str
    scale_to_si: float
    canonical: str


_UNIT_ALIASES: dict[str, UnitDefinition] = {}


def _register(canonical: str, dimension: str, scale: float, *aliases: str) -> None:
    definition = UnitDefinition(dimension=dimension, scale_to_si=float(scale), canonical=canonical)
    for item in (canonical, *aliases):
        _UNIT_ALIASES[_normalize_unit_token(item)] = definition


def _normalize_unit_token(text: str) -> str:
    return (
        str(text or "")
        .strip()
        .lower()
        .replace("µ", "μ")
        .replace("μ", "u")
        .replace("（", "(")
        .replace("）", ")")
        .replace("／", "/")
        .replace("·", "")
        .replace(" ", "")
    )


_register("m", "length", 1.0, "meter", "metre", "米")
_register("cm", "length", 1e-2, "厘米")
_register("mm", "length", 1e-3, "毫米")
_register("μm", "length", 1e-6, "um", "micron", "micrometer", "micrometre", "微米")
_register("nm", "length", 1e-9, "nanometer", "nanometre", "纳米")
_register("rad", "angle", 1.0, "radian", "弧度")
_register("mrad", "angle", 1e-3, "毫弧度")
_register("μrad", "angle", 1e-6, "urad", "微弧度")
_register("deg", "angle", math.pi / 180.0, "degree", "degrees", "°", "度")
_register("%", "percent", 1.0, "percent", "pct", "百分比")


def _recognized_unit_from_suffix(text: str) -> str:
    """Return the first unit token embedded in a widget suffix/label."""
    raw = str(text or "").strip()
    if not raw:
        return ""
    # Exact unit first.
    normalized = _normalize_unit_token(raw)
    if normalized in _UNIT_ALIASES:
        return _UNIT_ALIASES[normalized].canonical
    # Suffixes can contain explanatory Chinese text, e.g. "% 光斑半径".
    candidates = sorted(_UNIT_ALIASES.keys(), key=len, reverse=True)
    compact = _normalize_unit_token(raw)
    for token in candidates:
        if token and (compact.startswith(token) or token in compact):
            return _UNIT_ALIASES[token].canonical
    return ""


def parse_quantity(text: str, target_unit: str = "") -> float:
    """Parse a numeric quantity and convert it to ``target_unit``.

    A unitless value is interpreted in the target unit, matching normal spin-box
    behaviour.  Length and angular units can be mixed safely (e.g. ``200 μm``
    entered into an ``mm`` control).  Cross-dimension conversions are rejected.
    """
    match = _NUMBER_RE.match(str(text or ""))
    if not match:
        raise ValueError(f"无法解析数值：{text!r}")
    value = float(match.group(1))
    source_raw = match.group(2).strip()
    target = _recognized_unit_from_suffix(target_unit)

    if not source_raw:
        return value

    # QDoubleSpinBox may leave explanatory suffix text in valueFromText input.
    source = _recognized_unit_from_suffix(source_raw)
    if not source:
        raise ValueError(f"无法识别单位：{source_raw}")
    if not target:
        # With no target unit we only accept an effectively unitless entry.
        raise ValueError(f"当前输入框没有可换算的目标单位：{source_raw}")

    source_def = _UNIT_ALIASES[_normalize_unit_token(source)]
    target_def = _UNIT_ALIASES[_normalize_unit_token(target)]
    if source_def.dimension != target_def.dimension:
        raise ValueError(f"单位维度不一致：{source} → {target}")
    return value * source_def.scale_to_si / target_def.scale_to_si


def can_parse_quantity(text: str, target_unit: str = "") -> bool:
    try:
        parse_quantity(text, target_unit)
        return True
    except (TypeError, ValueError, OverflowError):
        return False


__all__ = ["parse_quantity", "can_parse_quantity", "UnitDefinition"]

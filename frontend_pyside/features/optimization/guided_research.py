
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any


SCAN_SUPPORTED_KEYS = frozenset(
    {"wavelength", "curvature", "spacing", "fiber_axial", "fiber_lateral", "fiber_tilt"}
)


@dataclass(frozen=True, slots=True)
class GuidedValidation:
    ok: bool
    message: str = ""


def normalize_contents(values: Iterable[object] | None) -> list[str]:

    result: list[str] = []
    seen: set[str] = set()
    for value in values or ():
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def validate_guided_research(
    *,
    contents: Iterable[object] | None,
    surface_count: int,
    variable_structure: bool,
    minimum_lenses: int = 1,
    maximum_lenses: int = 1,
) -> GuidedValidation:
    selected = normalize_contents(contents)
    if surface_count <= 0:
        return GuidedValidation(False, "当前项目没有可研究的镜头表面，请先在仿真系统中建立光学结构。")
    if not selected:
        return GuidedValidation(False, "请至少选择一项研究内容。")
    if variable_structure:
        if minimum_lenses < 1 or maximum_lenses < 1:
            return GuidedValidation(False, "镜片数量必须大于零。")
        if minimum_lenses > maximum_lenses:
            return GuidedValidation(False, "镜片数量下限不能大于上限。")
    return GuidedValidation(True, "")


def choose_guided_mode(*, contents: Iterable[object] | None, variable_structure: bool) -> str:

    selected = normalize_contents(contents)
    if not variable_structure and len(selected) == 1 and selected[0] in SCAN_SUPPORTED_KEYS:
        return "scan"
    return "optimization"


def first_surface(project: Any) -> Any | None:
    surfaces = list(getattr(project, "surfaces", []) or [])
    return surfaces[0] if surfaces else None


def last_surface(project: Any) -> Any | None:
    surfaces = list(getattr(project, "surfaces", []) or [])
    return surfaces[-1] if surfaces else None


def first_air_gap_surface(project: Any) -> Any | None:
    for surface in list(getattr(project, "surfaces", []) or []):
        if str(getattr(surface, "material", "")).strip().upper() == "AIR":
            return surface
    return None


def friendly_warning_message(message: object) -> str:

    text = str(message or "").strip()
    low = text.lower()
    translations = {
        "no compatible surrogate model; coarse search used formal simulation":
            "未找到与当前参数兼容的代理模型；粗搜索已自动改用正式仿真。",
        "optimisation failed to find a valid solution":
            "优化未找到满足当前约束的有效候选。",
        "optimization failed to find a valid solution":
            "优化未找到满足当前约束的有效候选。",
    }
    if low in translations:
        return translations[low]
    if "surrogate model" in low and "formal simulation" in low:
        return "未找到兼容的代理模型；当前搜索已使用正式仿真完成。"
    if "simulation" in low and "failed" in low:
        return "部分候选结果的正式仿真失败，请检查任务日志和参数范围。"
    return text or "当前结果包含需要注意的信息。"


def friendly_failure_message(message: object) -> str:

    text = str(message or "").strip()
    low = text.lower()
    if "list index out of range" in low or "indexerror" in low:
        return (
            "研究配置没有生成有效参数或后端返回了空结果。"
            "请确认已选择研究内容、镜头结构完整，然后重新提交。"
        )
    if "no enabled optimization variables" in low:
        return "当前选择没有对应到可优化参数，请更换研究内容或检查镜头结构。"
    if "at least" in low and "parameter" in low:
        return "当前扫描缺少有效参数，请重新选择研究内容。"
    return text or "研究任务失败，请检查任务日志。"


__all__ = [
    "GuidedValidation",
    "SCAN_SUPPORTED_KEYS",
    "choose_guided_mode",
    "first_air_gap_surface",
    "first_surface",
    "friendly_failure_message",
    "friendly_warning_message",
    "last_surface",
    "normalize_contents",
    "validate_guided_research",
]

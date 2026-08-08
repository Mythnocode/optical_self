
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Any


@dataclass(frozen=True, slots=True)
class MetricDefinition:
    name: str
    label: str
    unit: str = ""
    analyses: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    higher_is_better: bool = True


_DEFINITIONS: tuple[MetricDefinition, ...] = (
    MetricDefinition(
        "coupling_efficiency", "耦合效率", "", ("coupling",),
        aliases=("fiber_coupling_efficiency", "fibre_coupling_efficiency"),
    ),
    MetricDefinition(
        "coupling_loss_db", "耦合损耗", "dB", ("coupling",),
        aliases=("insertion_loss_db", "fiber_coupling_loss_db"),
        higher_is_better=False,
    ),
    MetricDefinition(
        "rms_spot_radius_um", "RMS 光斑半径", "μm", ("spot",),
        aliases=("rms_spot_um", "spot_rms_radius_um"), higher_is_better=False,
    ),
    MetricDefinition(
        "strehl_estimate_marechal", "Strehl 估计", "", ("wavefront_quality",),
        aliases=("strehl", "strehl_ratio"),
    ),
    MetricDefinition(
        "psf_peak_normalized", "PSF 峰值", "", ("psf",),
        aliases=("hybrid_psf_peak_normalized",),
    ),
    MetricDefinition(
        "mtf_dc", "MTF 零频值", "", ("mtf",),
        aliases=("hybrid_mtf_dc",),
    ),
    MetricDefinition(
        "propagation_edge_power_fraction", "边缘功率占比", "", ("coupling",),
        aliases=("edge_power", "edge_power_fraction", "coupling_propagation_edge_power_fraction"),
        higher_is_better=False,
    ),
    MetricDefinition(
        "collimation_score", "准直评分", "", ("collimation",),
    ),
    MetricDefinition(
        "collimation_radius_change_fraction", "准直段光束半径变化率", "", ("collimation",),
        higher_is_better=False,
    ),
    MetricDefinition(
        "collimation_normalized_curvature", "准直归一化波前曲率", "", ("collimation",),
        higher_is_better=False,
    ),
    MetricDefinition(
        "collimation_centroid_drift_fraction", "准直段质心漂移率", "", ("collimation",),
        higher_is_better=False,
    ),
    MetricDefinition(
        "collimation_axis_tilt_mrad", "准直光轴倾角", "mrad", ("collimation",),
        higher_is_better=False,
    ),
    MetricDefinition(
        "geometric_throughput", "几何通光率", "", ("throughput", "power_audit"),
    ),
    MetricDefinition(
        "power_loss_fraction", "功率损失占比", "", ("power_audit",),
        higher_is_better=False,
    ),
    MetricDefinition(
        "material_total_transmission", "材料总透射率", "", ("material_transmission",),
    ),
    MetricDefinition(
        "best_focus_rms_radius_um", "最佳焦面 RMS 半径", "μm", ("focus_search",),
        higher_is_better=False,
    ),
    MetricDefinition(
        "diffraction_peak_intensity", "衍射峰值强度", "a.u.", ("diffraction",),
    ),
    MetricDefinition(
        "wavefront_rms_nm", "波前 RMS", "nm", ("wavefront_quality",),
        higher_is_better=False,
    ),
    MetricDefinition("coupling_breakdown_total_estimate", "耦合总效率估计", "", ("coupling",)),
    MetricDefinition("fiber_v_number", "光纤 V 数", "", ("coupling", "na_stop_fiber")),
    MetricDefinition("interference_visibility", "干涉可见度", "", ("interference",)),
    MetricDefinition("coherence_length_mm", "相干长度", "mm", ("coherence",)),
    MetricDefinition("polarization_transmittance", "偏振透射率", "", ("polarization",)),
    MetricDefinition("detector_total_power_a.u.", "探测器总功率", "a.u.", ("detector",)),
    MetricDefinition("exit_pupil_peak_intensity", "出瞳峰值强度", "a.u.", ("exit_pupil",)),
    MetricDefinition("hybrid_psf_peak_normalized", "混合 PSF 峰值", "", ("psf_mtf",), aliases=("psf_peak_normalized",)),
    MetricDefinition("quality_audit", "质量审计", "", ("quality_audit",)),
)

_BY_NAME = {item.name: item for item in _DEFINITIONS}
_ALIAS_TO_NAME = {
    alias: item.name
    for item in _DEFINITIONS
    for alias in (item.name, *item.aliases)
}
_LABEL_TO_NAME = {item.label: item.name for item in _DEFINITIONS}


def canonical_metric_name(value: str) -> str:
    text = str(value or "").strip()
    return _LABEL_TO_NAME.get(text, _ALIAS_TO_NAME.get(text, text))


def metric_definition(value: str) -> MetricDefinition | None:
    return _BY_NAME.get(canonical_metric_name(value))


def metric_definitions() -> tuple[MetricDefinition, ...]:
    return _DEFINITIONS


def analyses_for_metrics(metrics: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for metric in metrics:
        definition = metric_definition(metric)
        analyses = definition.analyses if definition is not None else ("spot",)
        for analysis in analyses:
            if analysis not in seen:
                seen.add(analysis)
                result.append(analysis)
    return result


def read_metric(metrics: Mapping[str, Any], value: str, default: Any = None) -> Any:

    canonical = canonical_metric_name(value)
    definition = _BY_NAME.get(canonical)
    candidates = (canonical, *(definition.aliases if definition else ()))
    for key in candidates:
        if key in metrics:
            return metrics[key]
    for candidate in candidates:
        matches = [item for key, item in metrics.items() if str(key).endswith(f".{candidate}")]
        if len(matches) == 1:
            return matches[0]
    return default


__all__ = [
    "MetricDefinition",
    "analyses_for_metrics",
    "canonical_metric_name",
    "metric_definition",
    "metric_definitions",
    "read_metric",
]

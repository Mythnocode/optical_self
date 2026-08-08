
from __future__ import annotations

from dataclasses import dataclass
from math import exp, hypot, isfinite, log10, pi, sqrt
from typing import Callable, Iterable, Mapping

import numpy as np


class PhysicsFeatureError(ValueError):
    pass


@dataclass(frozen=True)
class PhysicsFeatureDefinition:


    key: str
    display_name: str
    symbol_latex: str
    formula_latex: str
    efficiency_formula_latex: str
    source_parameters: tuple[str, ...]
    description: str
    ideal_value: float
    compute: Callable[[Mapping[str, float]], float]
    efficiency_ratio: Callable[[float], float]
    unit: str = "1"

    def evaluate(self, raw_parameters: Mapping[str, float]) -> float:
        return float(self.compute(raw_parameters))

    def relative_efficiency(self, feature_value: float) -> float:
        value = float(self.efficiency_ratio(float(feature_value)))
        if not isfinite(value):
            raise PhysicsFeatureError(
                f"{self.key} 的解析效率不是有限数: {feature_value!r}"
            )
        return float(np.clip(value, 1.0e-15, 1.0))

    def loss_db(self, feature_value: float) -> float:
        return float(-10.0 * log10(self.relative_efficiency(feature_value)))

    def to_metadata(self) -> dict[str, object]:
        return {
            "key": self.key,
            "display_name": self.display_name,
            "symbol_latex": self.symbol_latex,
            "formula_latex": self.formula_latex,
            "efficiency_formula_latex": self.efficiency_formula_latex,
            "source_parameters": list(self.source_parameters),
            "description": self.description,
            "ideal_value": self.ideal_value,
            "unit": self.unit,
        }


def _positive(raw: Mapping[str, float], key: str) -> float:
    try:
        value = float(raw[key])
    except KeyError as exc:
        raise PhysicsFeatureError(f"缺少必需参数: {key}") from exc
    if not isfinite(value) or value <= 0.0:
        raise PhysicsFeatureError(f"{key} 必须为正有限数，实际为 {value!r}")
    return value


def _finite(raw: Mapping[str, float], key: str, default: float = 0.0) -> float:
    value = float(raw.get(key, default))
    if not isfinite(value):
        raise PhysicsFeatureError(f"{key} 必须为有限数，实际为 {value!r}")
    return value


def _inverse_radius(value: float) -> float:
    if np.isinf(value):
        return 0.0
    if not isfinite(value) or value == 0.0:
        raise PhysicsFeatureError("曲率半径必须为非零有限数或无穷大")
    return 1.0 / value


def canonicalize_raw_parameters(raw: Mapping[str, float]) -> dict[str, float]:


    out: dict[str, float] = {str(k): float(v) for k, v in raw.items()}

    def first_present(*keys: str) -> float | None:
        for key in keys:
            if key in out:
                return float(out[key])
        return None

    beam_radius = first_present("beam_radius_um", "beam_waist_um")
    if beam_radius is None:
        bx = first_present("beam_radius_x_um", "beam_waist_x_um", "source.waist_x_um")
        by = first_present("beam_radius_y_um", "beam_waist_y_um", "source.waist_y_um")
        if bx is not None and by is not None:
            beam_radius = sqrt(bx * by)
    if beam_radius is None:
        bx_mm = first_present("beam_radius_x_mm", "beam_waist_x_mm", "source.waist_x_mm")
        by_mm = first_present("beam_radius_y_mm", "beam_waist_y_mm", "source.waist_y_mm")
        if bx_mm is not None and by_mm is not None:
            beam_radius = 1000.0 * sqrt(bx_mm * by_mm)
    if beam_radius is not None:
        out["beam_radius_um"] = beam_radius

    fiber_radius = first_present("fiber_mode_radius_um")
    if fiber_radius is None:
        mfd = first_present(
            "fiber_mfd_um",
            "mode_field_diameter_um",
            "receiver.mode_field_diameter_um",
        )
        if mfd is not None:
            fiber_radius = mfd / 2.0
    if fiber_radius is None:
        fx = first_present("fiber_mode_radius_x_um")
        fy = first_present("fiber_mode_radius_y_um")
        if fx is not None and fy is not None:
            fiber_radius = sqrt(fx * fy)
    if fiber_radius is None:
        mfd_x = first_present("receiver.mode_field_diameter_x_um")
        mfd_y = first_present("receiver.mode_field_diameter_y_um")
        if mfd_x is not None and mfd_y is not None:
            fiber_radius = 0.5 * sqrt(mfd_x * mfd_y)
    if fiber_radius is not None:
        out["fiber_mode_radius_um"] = fiber_radius

    wavelength = first_present("wavelength_um", "source.wavelength_um")
    if wavelength is None:
        wavelength_nm = first_present("wavelength_nm", "source.wavelength_nm")
        if wavelength_nm is not None:
            wavelength = wavelength_nm / 1000.0
    if wavelength is not None:
        out["wavelength_um"] = wavelength

    for axis in ("x", "y"):
        offset = first_present(
            f"offset_{axis}_um",
            f"receiver_offset_{axis}_um",
            f"receiver.offset_{axis}_um",
        )
        if offset is None:
            offset_mm = first_present(
                f"offset_{axis}_mm",
                f"receiver_offset_{axis}_mm",
                f"receiver.offset_{axis}_mm",
            )
            if offset_mm is not None:
                offset = offset_mm * 1000.0
        out[f"offset_{axis}_um"] = 0.0 if offset is None else offset

        tilt = first_present(
            f"tilt_{axis}_rad",
            f"receiver_tilt_{axis}_rad",
            f"receiver.tilt_{axis}_rad",
        )
        if tilt is None:
            tilt_mrad = first_present(
                f"tilt_{axis}_mrad",
                f"receiver_tilt_{axis}_mrad",
                f"receiver.tilt_{axis}_mrad",
            )
            if tilt_mrad is not None:
                tilt = tilt_mrad / 1000.0
        if tilt is None:
            tilt_deg = first_present(
                f"tilt_{axis}_deg",
                f"receiver_tilt_{axis}_deg",
                f"receiver.tilt_{axis}_deg",
            )
            if tilt_deg is not None:
                tilt = np.deg2rad(tilt_deg)
        out[f"tilt_{axis}_rad"] = 0.0 if tilt is None else float(tilt)

    axial = first_present(
        "axial_offset_um",
        "defocus_um",
        "receiver.axial_offset_z_um",
    )
    if axial is None:
        axial_mm = first_present(
            "axial_offset_mm",
            "defocus_mm",
            "receiver.axial_offset_z_mm",
        )
        if axial_mm is not None:
            axial = axial_mm * 1000.0
    out["axial_offset_um"] = 0.0 if axial is None else axial

    beam_curv = first_present(
        "beam_curvature_radius_um",
        "beam.curvature_radius_um",
    )
    if beam_curv is None:
        beam_curv_mm = first_present(
            "beam_curvature_radius_mm",
            "beam.curvature_radius_mm",
        )
        if beam_curv_mm is not None:
            beam_curv = beam_curv_mm * 1000.0
    out["beam_curvature_radius_um"] = (
        float("inf") if beam_curv is None else beam_curv
    )

    fiber_curv = first_present(
        "fiber_curvature_radius_um",
        "receiver.mode_curvature_radius_um",
    )
    if fiber_curv is None:
        fiber_curv_mm = first_present(
            "fiber_curvature_radius_mm",
            "receiver.mode_curvature_radius_mm",
        )
        if fiber_curv_mm is not None:
            fiber_curv = fiber_curv_mm * 1000.0
    out["fiber_curvature_radius_um"] = (
        float("inf") if fiber_curv is None else fiber_curv
    )

    return out


def _size_ratio(raw: Mapping[str, float]) -> float:
    return _positive(raw, "beam_radius_um") / _positive(
        raw, "fiber_mode_radius_um"
    )


def _lateral_mismatch(raw: Mapping[str, float]) -> float:
    wf = _positive(raw, "fiber_mode_radius_um")
    return hypot(_finite(raw, "offset_x_um"), _finite(raw, "offset_y_um")) / wf


def _angular_mismatch(raw: Mapping[str, float]) -> float:
    wf = _positive(raw, "fiber_mode_radius_um")
    wavelength = _positive(raw, "wavelength_um")
    tilt = hypot(_finite(raw, "tilt_x_rad"), _finite(raw, "tilt_y_rad"))
    return pi * wf * tilt / wavelength


def _axial_mismatch(raw: Mapping[str, float]) -> float:
    wf = _positive(raw, "fiber_mode_radius_um")
    wavelength = _positive(raw, "wavelength_um")
    rayleigh_length = pi * wf * wf / wavelength
    return _finite(raw, "axial_offset_um") / rayleigh_length


def _curvature_mismatch(raw: Mapping[str, float]) -> float:
    wf = _positive(raw, "fiber_mode_radius_um")
    wavelength = _positive(raw, "wavelength_um")
    beam_radius = float(raw.get("beam_curvature_radius_um", float("inf")))
    fiber_radius = float(raw.get("fiber_curvature_radius_um", float("inf")))
    k = 2.0 * pi / wavelength
    return (k * wf * wf / 4.0) * (
        _inverse_radius(beam_radius) - _inverse_radius(fiber_radius)
    )


def _size_efficiency(rho: float) -> float:
    if rho <= 0.0 or not isfinite(rho):
        raise PhysicsFeatureError("尺寸比 rho 必须为正有限数")
    return (2.0 * rho / (1.0 + rho * rho)) ** 2


def _exp_efficiency(value: float) -> float:
    return exp(-(value * value))


def _axial_efficiency(value: float) -> float:
    return 1.0 / (1.0 + (value / 2.0) ** 2)


def _curvature_efficiency(value: float) -> float:
    return 1.0 / (1.0 + value * value)


PHYSICS_FEATURE_ORDER: tuple[str, ...] = (
    "size_ratio",
    "lateral_mismatch",
    "angular_mismatch",
    "axial_mismatch",
    "curvature_mismatch",
)

PHYSICS_FEATURES: dict[str, PhysicsFeatureDefinition] = {
    "size_ratio": PhysicsFeatureDefinition(
        key="size_ratio",
        display_name="尺寸失配",
        symbol_latex=r"\rho",
        formula_latex=r"\rho=\frac{w_b}{w_f}",
        efficiency_formula_latex=(
            r"\eta_{\mathrm{size}}="
            r"\left(\frac{2\rho}{1+\rho^2}\right)^2"
        ),
        source_parameters=("beam_radius_um", "fiber_mode_radius_um"),
        description="入射光斑半径与光纤模场半径之比",
        ideal_value=1.0,
        compute=_size_ratio,
        efficiency_ratio=_size_efficiency,
    ),
    "lateral_mismatch": PhysicsFeatureDefinition(
        key="lateral_mismatch",
        display_name="横向偏移",
        symbol_latex=r"u_r",
        formula_latex=(
            r"u_r=\frac{\sqrt{\Delta x^2+\Delta y^2}}{w_f}"
        ),
        efficiency_formula_latex=r"\eta/\eta_0=\exp(-u_r^2)",
        source_parameters=("offset_x_um", "offset_y_um", "fiber_mode_radius_um"),
        description="光斑中心与光纤模式中心的归一化距离",
        ideal_value=0.0,
        compute=_lateral_mismatch,
        efficiency_ratio=_exp_efficiency,
    ),
    "angular_mismatch": PhysicsFeatureDefinition(
        key="angular_mismatch",
        display_name="角度失配",
        symbol_latex=r"u_\theta",
        formula_latex=(
            r"u_\theta=\frac{\pi w_f\sqrt{\theta_x^2+\theta_y^2}}{\lambda}"
        ),
        efficiency_formula_latex=r"\eta/\eta_0=\exp(-u_\theta^2)",
        source_parameters=(
            "tilt_x_rad",
            "tilt_y_rad",
            "fiber_mode_radius_um",
            "wavelength_um",
        ),
        description="倾斜波前在线性相位上的归一化失配",
        ideal_value=0.0,
        compute=_angular_mismatch,
        efficiency_ratio=_exp_efficiency,
    ),
    "axial_mismatch": PhysicsFeatureDefinition(
        key="axial_mismatch",
        display_name="轴向离焦",
        symbol_latex=r"u_z",
        formula_latex=(
            r"u_z=\frac{\Delta z}{z_R},\quad "
            r"z_R=\frac{\pi w_f^2}{\lambda}"
        ),
        efficiency_formula_latex=(
            r"\eta/\eta_0\approx\frac{1}{1+(u_z/2)^2}"
        ),
        source_parameters=(
            "axial_offset_um",
            "fiber_mode_radius_um",
            "wavelength_um",
        ),
        description="端面相对最佳束腰面的归一化轴向偏移",
        ideal_value=0.0,
        compute=_axial_mismatch,
        efficiency_ratio=_axial_efficiency,
    ),
    "curvature_mismatch": PhysicsFeatureDefinition(
        key="curvature_mismatch",
        display_name="曲率失配",
        symbol_latex=r"u_R",
        formula_latex=(
            r"u_R=\frac{k w_f^2}{4}"
            r"\left(\frac{1}{R_b}-\frac{1}{R_f}\right)"
        ),
        efficiency_formula_latex=r"\eta/\eta_0=\frac{1}{1+u_R^2}",
        source_parameters=(
            "beam_curvature_radius_um",
            "fiber_curvature_radius_um",
            "fiber_mode_radius_um",
            "wavelength_um",
        ),
        description="入射场与目标模式二次相位曲率的归一化差异",
        ideal_value=0.0,
        compute=_curvature_mismatch,
        efficiency_ratio=_curvature_efficiency,
    ),
}


def compute_physics_features(
    raw_parameters: Mapping[str, float],
    feature_order: Iterable[str] = PHYSICS_FEATURE_ORDER,
) -> dict[str, float]:
    canonical = canonicalize_raw_parameters(raw_parameters)
    output: dict[str, float] = {}
    for key in feature_order:
        try:
            definition = PHYSICS_FEATURES[key]
        except KeyError as exc:
            raise PhysicsFeatureError(f"未知物理特征: {key}") from exc
        output[key] = definition.evaluate(canonical)
    return output


def evaluate_formula_components(
    feature_values: Mapping[str, float],
) -> dict[str, dict[str, float]]:
    output: dict[str, dict[str, float]] = {}
    for key, value in feature_values.items():
        definition = PHYSICS_FEATURES.get(key)
        if definition is None:
            continue
        eta = definition.relative_efficiency(float(value))
        output[key] = {
            "feature_value": float(value),
            "relative_efficiency": eta,
            "loss_db": definition.loss_db(float(value)),
        }
    return output


def formula_registry_metadata() -> dict[str, dict[str, object]]:
    return {key: definition.to_metadata() for key, definition in PHYSICS_FEATURES.items()}

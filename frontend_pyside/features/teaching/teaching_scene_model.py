
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import math
import random
from typing import Any


@dataclass(frozen=True, slots=True)
class TeachingOpticalState:
    wavelength_nm: float = 808.0
    input_beam_radius_mm: float = 0.72
    focal_length_mm: float = 6.20
    fiber_na: float = 0.12
    fiber_mode_radius_um: float = 2.80

    offset_x_um: float = 0.0
    offset_y_um: float = 0.0
    offset_z_um: float = 0.0
    pitch_mrad: float = 0.0
    yaw_mrad: float = 0.0
    curvature_waves: float = 0.0

    input_power_mw: float = 100.0
    monitor_fraction: float = 0.05
    system_transmission: float = 0.94

    def updated(self, **changes: Any) -> "TeachingOpticalState":
        candidate = replace(self, **changes)
        return replace(
            candidate,
            wavelength_nm=max(200.0, float(candidate.wavelength_nm)),
            input_beam_radius_mm=max(0.03, float(candidate.input_beam_radius_mm)),
            focal_length_mm=max(0.2, float(candidate.focal_length_mm)),
            fiber_na=min(1.0, max(0.001, float(candidate.fiber_na))),
            fiber_mode_radius_um=max(0.10, float(candidate.fiber_mode_radius_um)),
            curvature_waves=max(-2.0, min(2.0, float(candidate.curvature_waves))),
            input_power_mw=max(0.0, float(candidate.input_power_mw)),
            monitor_fraction=min(0.50, max(0.0, float(candidate.monitor_fraction))),
            system_transmission=min(1.0, max(0.0, float(candidate.system_transmission))),
        )

    def to_dict(self) -> dict[str, float]:
        return {key: float(value) for key, value in asdict(self).items()}


@dataclass(frozen=True, slots=True)
class TeachingOpticalMetrics:
    ideal_waist_radius_um: float
    rayleigh_range_um: float
    beam_radius_at_fiber_um: float

    size_match: float
    position_match: float
    angle_match: float
    defocus_match: float
    curvature_match: float
    receiver_efficiency: float
    system_efficiency: float
    total_efficiency: float

    monitor_power_mw: float
    main_path_power_mw: float
    output_power_mw: float
    loss_db: float

    dominant_mismatch: str
    status: str
    explanation: str
    recommendation: str

    @property
    def waist_radius_um(self) -> float:

        return self.ideal_waist_radius_um

    @property
    def coupling_efficiency(self) -> float:

        return self.total_efficiency

    def factor_items(self) -> tuple[tuple[str, float], ...]:
        return (
            ("尺寸匹配", self.size_match),
            ("位置匹配", self.position_match),
            ("角度匹配", self.angle_match),
            ("轴向匹配", self.defocus_match),
            ("曲率匹配", self.curvature_match),
        )


def _clip01(value: float) -> float:
    return min(1.0, max(0.0, float(value)))


def evaluate_teaching_state(state: TeachingOpticalState) -> TeachingOpticalMetrics:


    s = state.updated()
    wavelength_um = s.wavelength_nm / 1000.0
    wavelength_mm = s.wavelength_nm * 1.0e-6

    ideal_waist_radius_um = (
        wavelength_mm * s.focal_length_mm / (math.pi * s.input_beam_radius_mm)
    ) * 1000.0
    ideal_waist_radius_um = max(0.08, ideal_waist_radius_um)
    rayleigh_range_um = math.pi * ideal_waist_radius_um**2 / max(wavelength_um, 1.0e-9)

    normalized_z = s.offset_z_um / max(rayleigh_range_um, 1.0e-9)
    beam_radius_at_fiber_um = ideal_waist_radius_um * math.sqrt(1.0 + normalized_z**2)

    
    
    w_beam = ideal_waist_radius_um
    w_fiber = s.fiber_mode_radius_um
    size_match = (2.0 * w_beam * w_fiber / max(w_beam**2 + w_fiber**2, 1.0e-12)) ** 2

    lateral_sq = s.offset_x_um**2 + s.offset_y_um**2
    position_match = math.exp(
        -2.0 * lateral_sq / max(w_beam**2 + w_fiber**2, 1.0e-12)
    )

    theta_rad = math.hypot(s.pitch_mrad, s.yaw_mrad) * 1.0e-3
    effective_radius = math.sqrt(2.0 * w_beam**2 * w_fiber**2 / max(w_beam**2 + w_fiber**2, 1e-12))
    angle_phase = math.pi * effective_radius * theta_rad / max(wavelength_um, 1e-9)
    na_ratio = theta_rad / max(s.fiber_na, 1e-9)
    angle_match = math.exp(-(angle_phase**2)) * math.exp(-0.5 * na_ratio**4)

    
    
    defocus_match = 1.0 / (1.0 + (normalized_z / 1.35) ** 2)

    
    
    pure_curvature_match = 1.0 / (1.0 + (math.pi * s.curvature_waves) ** 2)
    
    
    curvature_match = pure_curvature_match * defocus_match

    receiver = _clip01(size_match * position_match * angle_match * defocus_match * pure_curvature_match)
    system = _clip01(s.system_transmission)
    total = _clip01(receiver * system)

    monitor_power_mw = s.input_power_mw * s.monitor_fraction
    main_path_power_mw = s.input_power_mw * (1.0 - s.monitor_fraction) * system
    output_power_mw = s.input_power_mw * (1.0 - s.monitor_fraction) * total
    loss_db = -10.0 * math.log10(max(total, 1.0e-12))

    factors = {
        "尺寸失配": size_match,
        "位置失配": position_match,
        "角度失配": angle_match,
        "轴向失配": defocus_match,
        "曲率失配": curvature_match,
    }
    dominant_mismatch, _weakest = min(factors.items(), key=lambda item: item[1])

    if total >= 0.85:
        status = "匹配良好"
    elif total >= 0.55:
        status = "可继续优化"
    else:
        status = "失配明显"

    explanations = {
        "尺寸失配": "端面光斑半径与光纤模场半径不同，振幅分布不能充分重叠。",
        "位置失配": "入射光斑中心没有落在纤芯中心，横向空间重叠快速减小。",
        "角度失配": "光束方向与光纤轴线不平行，端面产生线性相位坡度。",
        "轴向失配": "光纤端面偏离最佳束腰，q 参数与目标模式不一致。",
        "曲率失配": "强度轮廓可能相同，但二次相位不同，复场积分发生抵消。",
    }
    recommendations = {
        "尺寸失配": "调整入射束径、镜组位置或焦距，使端面束腰接近目标MFD。",
        "位置失配": "优先调节五轴架 X/Y，并从输出功率峰值确认中心重合。",
        "角度失配": "调节 Pitch/Yaw，使光束方向与光纤轴线平行。",
        "轴向失配": "沿 Z 轴移动光纤端面，找到输出功率峰值后再微调 X/Y。",
        "曲率失配": "调整镜组或端面位置，使端面波前曲率接近目标模式。",
    }

    return TeachingOpticalMetrics(
        ideal_waist_radius_um=ideal_waist_radius_um,
        rayleigh_range_um=rayleigh_range_um,
        beam_radius_at_fiber_um=beam_radius_at_fiber_um,
        size_match=_clip01(size_match),
        position_match=_clip01(position_match),
        angle_match=_clip01(angle_match),
        defocus_match=_clip01(defocus_match),
        curvature_match=_clip01(curvature_match),
        receiver_efficiency=receiver,
        system_efficiency=system,
        total_efficiency=total,
        monitor_power_mw=monitor_power_mw,
        main_path_power_mw=main_path_power_mw,
        output_power_mw=output_power_mw,
        loss_db=loss_db,
        dominant_mismatch=dominant_mismatch,
        status=status,
        explanation=explanations[dominant_mismatch],
        recommendation=recommendations[dominant_mismatch],
    )


SEMI_FREE_PRESETS: dict[str, dict[str, float | str]] = {
    "position": {
        "name": "位置类失配",
        "task": "请选择合适测量结果判断 X、Y 或 Z 中的主要问题，并将总效率恢复到 80% 以上。",
        "offset_x_um": 2.4,
        "offset_y_um": -1.1,
        "offset_z_um": 20.0,
    },
    "direction": {
        "name": "方向类失配",
        "task": "光斑中心接近正常，但输出明显下降。请判断角度误差并完成方向装调。",
        "pitch_mrad": 42.0,
        "yaw_mrad": -24.0,
    },
    "shape": {
        "name": "光束形状失配",
        "task": "位置和方向基本正常。请利用光斑与波前证据修正尺寸、离焦或曲率问题。",
        "input_beam_radius_mm": 0.46,
        "offset_z_um": -38.0,
        "curvature_waves": 0.18,
    },
    "five_axis": {
        "name": "五轴综合入门",
        "task": "系统同时存在轻微位置与方向误差。请确定调整顺序并恢复耦合。",
        "offset_x_um": 1.8,
        "offset_y_um": 0.9,
        "offset_z_um": 25.0,
        "pitch_mrad": 11.0,
        "yaw_mrad": -7.0,
    },
}


def apply_preset(state: TeachingOpticalState, key: str) -> TeachingOpticalState:
    preset = SEMI_FREE_PRESETS.get(str(key), {})
    reset = state.updated(
        input_beam_radius_mm=0.72,
        offset_x_um=0.0,
        offset_y_um=0.0,
        offset_z_um=0.0,
        pitch_mrad=0.0,
        yaw_mrad=0.0,
        curvature_waves=0.0,
    )
    changes = {
        name: value
        for name, value in preset.items()
        if name in reset.to_dict() and isinstance(value, (int, float))
    }
    return reset.updated(**changes)


def random_free_fault(state: TeachingOpticalState, seed: int | None = None) -> TeachingOpticalState:
    rng = random.Random(seed)
    candidates: list[tuple[str, float]] = [
        ("offset_x_um", rng.choice([-1.0, 1.0]) * rng.uniform(1.0, 3.5)),
        ("offset_y_um", rng.choice([-1.0, 1.0]) * rng.uniform(0.6, 2.5)),
        ("offset_z_um", rng.choice([-1.0, 1.0]) * rng.uniform(18.0, 65.0)),
        ("pitch_mrad", rng.choice([-1.0, 1.0]) * rng.uniform(7.0, 28.0)),
        ("yaw_mrad", rng.choice([-1.0, 1.0]) * rng.uniform(5.0, 22.0)),
        ("curvature_waves", rng.choice([-1.0, 1.0]) * rng.uniform(0.10, 0.35)),
        ("input_beam_radius_mm", rng.uniform(0.42, 1.05)),
    ]
    count = rng.randint(2, 4)
    selected = rng.sample(candidates, count)
    reset = apply_preset(state, "")
    return reset.updated(**dict(selected))


__all__ = [
    "SEMI_FREE_PRESETS",
    "TeachingOpticalMetrics",
    "TeachingOpticalState",
    "apply_preset",
    "evaluate_teaching_state",
    "random_free_fault",
]



FAULT_PRESETS = SEMI_FREE_PRESETS

def apply_fault_preset(state: TeachingOpticalState, key: str) -> TeachingOpticalState:
    return apply_preset(state, key)

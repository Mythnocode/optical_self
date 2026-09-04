
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

NodeSpec = tuple[str, float, float, float, str, dict[str, Any]]


@dataclass(frozen=True, slots=True)
class ExperimentPreset:
    key: str
    group: str
    label: str
    active_control: str
    coupled_quantities: str
    diagnostics: str
    compensation: str
    result: str
    description: str
    specs: tuple[NodeSpec, ...]


def _common_prefix(*, y: float = 310.0) -> list[NodeSpec]:
    return [
        ("laser", 80, y, 0, "808 nm激光器", {"wavelength_nm": 808.0}),
        ("isolator", 205, y, 0, "光隔离器", {}),
        ("half_wave_plate", 325, y, 0, "半波片", {"axis_angle_deg": 0.0}),
        ("pbs", 445, y, 90, "PBS功率调节", {"monitor_fraction": 0.02, "split_ratio": 0.02}),
        ("beam_sampler", 575, y, 90, "参考取样片", {"monitor_fraction": 0.01, "split_ratio": 0.01}),
        ("photodetector", 575, 565, 270, "参考探测器 P_ref", {}),
        ("mirror", 700, y, 45, "M1", {}),
        ("mirror", 820, y, 45, "M2", {}),
    ]


def _coupling_tail(*, start: float = 1040.0, y: float = 310.0, lenses: int = 2, fiber_params: dict[str, Any] | None = None) -> list[NodeSpec]:
    focal_sets = {
        2: (50.0, 12.0),
        3: (75.0, 35.0, 10.0),
        4: (100.0, 50.0, 25.0, 8.0),
    }
    focals = focal_sets.get(lenses, focal_sets[2])
    spacing = 115.0 if lenses <= 3 else 100.0
    specs: list[NodeSpec] = []
    for index, focal in enumerate(focals):
        specs.append(("lens", start + index * spacing, y, 0, f"L{index + 1}", {"focal_mm": focal, "enabled": True}))
    fiber_x = start + len(focals) * spacing + 100.0
    specs.extend([
        ("fiber", fiber_x, y, 180, "五轴光纤架", dict(fiber_params or {})),
        ("power_meter", fiber_x + 165.0, y, 180, "输出功率计 P_out", {"range_mw": 20.0}),
    ])
    return specs


def _diagnostic_sampler(*, x: float = 930.0, y: float = 310.0, instrument: str = "beam_analyzer", label: str = "光束分析仪") -> list[NodeSpec]:
    return [
        ("beam_sampler", x, y, 0, "诊断取样片", {"monitor_fraction": 0.01, "split_ratio": 0.01, "branch_offset_deg": -90.0}),
        (instrument, x, 90, 90, label, {"plane_offset_mm": 0.0}),
    ]


_PRESETS: list[ExperimentPreset] = []


def _add(**kwargs: Any) -> None:
    _PRESETS.append(ExperimentPreset(**kwargs))



_add(
    key="common_platform", group="公共平台", label="增强型公共耦合平台",
    active_control="按实验插入整形或诊断模块",
    coupled_quantities="参考功率、诊断支路和主耦合路同步工作",
    diagnostics="P_ref、光束分析仪、焦面扫描或波前传感器",
    compensation="五轴光纤架与可更换耦合镜组",
    result="归一化系统效率与纯耦合效率",
    description="真实公共平台：功率归一化、可插拔整形、诊断取样、双/三/四透镜耦合与五轴接收共用机械基准。",
    specs=tuple(_common_prefix() + _diagnostic_sampler() + _coupling_tail(start=1040, lenses=2)),
)

_add(
    key="lm135c_four_lens_benchmark", group="实验基准", label="780 nm · 四透镜 · LM135C",
    active_control="保持四透镜顺序，扫描 L4 后 10/15/17.5/27.5/37.5 mm 接收面",
    coupled_quantities="X/Y 束腰、像散、质心、椭圆率和二阶矩半径随接收面位置共同变化",
    diagnostics="LM135C 4.65 µm 像元、M=1、像元积分、背景扣除和饱和检查",
    compensation="先统一 ISO 11146 二阶矩与 ROI，再比较实验和正式仿真残差",
    result="RMSx、RMSy、径向 RMS、1/e² 半径、拟合残差、椭圆率和质心",
    description="LM135C 四透镜实验基准。当前镜片按焦距推导近似处方；补齐厂家曲率、厚度、材料、口径与镀膜后方可作为器件级验证。",
    specs=(
        ("laser", 90, 310, 0, "780 nm 椭圆高斯源", {
            "wavelength_nm": 780.0, "source_type": "gaussian", "object_distance_mm": 10.0,
            "waist_x_um": 800.0, "waist_y_um": 670.0,
            "beam_quality_m2_x": 7.5, "beam_quality_m2_y": 2.4,
        }),
        ("lens", 570, 310, 0, "L1 f=50 mm", {
            "focal_mm": 50.0, "air_gap_after_mm": 7.5, "material": "N-BK7",
            "thickness_mm": 3.0, "semi_aperture_mm": 12.5,
            "coating": "780 nm AR（待器件资料核验）", "coating_min_nm": 650.0, "coating_max_nm": 1050.0,
        }),
        ("lens", 790, 310, 0, "L2 f=100 mm", {
            "focal_mm": 100.0, "air_gap_after_mm": 7.5, "material": "N-BK7",
            "thickness_mm": 3.0, "semi_aperture_mm": 12.5,
            "coating": "780 nm AR（待器件资料核验）", "coating_min_nm": 650.0, "coating_max_nm": 1050.0,
        }),
        ("lens", 1010, 310, 0, "L3 f=200 mm", {
            "focal_mm": 200.0, "air_gap_after_mm": 10.0, "material": "N-BK7",
            "thickness_mm": 3.0, "semi_aperture_mm": 12.5,
            "coating": "780 nm AR（待器件资料核验）", "coating_min_nm": 650.0, "coating_max_nm": 1050.0,
        }),
        ("lens", 1230, 310, 0, "L4 f=200 mm", {
            "focal_mm": 200.0, "air_gap_after_mm": 17.5, "material": "N-BK7",
            "thickness_mm": 3.0, "semi_aperture_mm": 12.5,
            "coating": "780 nm AR（待器件资料核验）", "coating_min_nm": 650.0, "coating_max_nm": 1050.0,
        }),
        ("imaging_camera", 1480, 310, 180, "LM135C 接收面", {
            "camera_model": "LM135C", "pixel_pitch_um": 4.65, "magnification": 1.0,
            "pixel_integration": True, "background_subtraction": True, "saturation_check": True,
            "scan_positions_mm": "10,15,17.5,27.5,37.5", "plane_offset_mm": 0.0,
            "spot_definition": "ISO 11146 二阶矩",
        }),
    ),
)
_add(
    key="lateral_scan", group="五轴装调", label="横向偏移扫描",
    active_control="五轴光纤架 Δx 或 Δy（每次一个方向）",
    coupled_quantities="入射光束尺寸与曲率保持由固定光路自然决定；只改变纤芯相对中心",
    diagnostics="P_ref、P_out、焦面光斑中心",
    compensation="不重新调焦；确认入射光中心没有漂移",
    result="η(Δx) 与 η(Δy)",
    description="横向失配最接近单因素实验：固定光路，仅扫描光纤横向位置并进行输入功率归一化。",
    specs=tuple(_common_prefix() + _diagnostic_sampler() + _coupling_tail(start=1040, lenses=2, fiber_params={"offset_x_um": 2.0, "offset_y_um": 0.0})),
)
_add(
    key="axial_defocus", group="五轴装调", label="轴向离焦＋焦面检测",
    active_control="光纤架 Z 或末级聚焦模块 Z（二选一）",
    coupled_quantities="端面束径、波前曲率、相位和耦合效率随 Z 共同变化",
    diagnostics="焦面扫描模块测 w_x(z)、w_y(z)，再换回光纤扫描 η(Z)",
    compensation="保持 X/Y/Pitch/Yaw 在峰值；不人为锁定束径或曲率",
    result="束腰位置、束腰半径、瑞利长度和 η(Δz)",
    description="焦面检测面与光纤端面共享机械基准，明确展示离焦引起的尺寸和曲率联动。",
    specs=tuple(_common_prefix() + _diagnostic_sampler(instrument="focus_scan_module", label="焦面扫描模块") + _coupling_tail(start=1040, lenses=2, fiber_params={"offset_z_um": 35.0})),
)
_add(
    key="fiber_angle", group="五轴装调", label="光纤端面中心角度扫描",
    active_control="五轴架 Pitch 或 Yaw",
    coupled_quantities="角度变化可能伴随中心走离",
    diagnostics="焦面中心、波前倾斜和 P_out",
    compensation="用 X/Y 小幅补偿，使光斑重新落在纤芯附近",
    result="补偿前后 η(θx)、η(θy) 及横向补偿量",
    description="以光纤端面中心为旋转中心，保留真实角度—位置耦合并记录补偿量。",
    specs=tuple(_common_prefix() + _diagnostic_sampler(instrument="wavefront_sensor", label="波前传感器") + _coupling_tail(start=1040, lenses=2, fiber_params={"pitch_mrad": 10.0, "yaw_mrad": 0.0, "offset_x_um": 0.4})),
)


_add(
    key="dual_mirror_position", group="光束指向", label="双镜位置主导调节",
    active_control="M1、M2 成对调节",
    coupled_quantities="端面光斑位置变化，传播方向变化尽量小",
    diagnostics="近场中心与远场中心",
    compensation="迭代调整第二面镜，压低角度变化",
    result="端面位移与残余角度",
    description="两面相隔传播距离的转向镜用于位置主导调节，训练实际光路的双镜解耦。",
    specs=tuple(_common_prefix() + _diagnostic_sampler(instrument="imaging_camera", label="近场/远场相机") + _coupling_tail(start=1040, lenses=2)),
)
_add(
    key="dual_mirror_angle", group="光束指向", label="双镜角度主导调节",
    active_control="M1 改变方向，M2 补偿端面中心",
    coupled_quantities="光束角度与位置天然耦合",
    diagnostics="两个观察面中心差、波前倾斜与 P_out",
    compensation="保持光纤端面中心基本不变",
    result="η(θx)、η(θy) 与所需位置补偿",
    description="双转向镜联合产生近似纯角度扰动，不使用不真实的独立角度滑条。",
    specs=tuple(_common_prefix() + _diagnostic_sampler(instrument="wavefront_sensor", label="波前传感器") + _coupling_tail(start=1040, lenses=2, fiber_params={"pitch_mrad": 8.0})),
)


_add(
    key="spherical_expansion", group="模场整形", label="球面扩束与 q 参数",
    active_control="扩束镜间距、扩束器整体位置或焦距组合",
    coupled_quantities="输入束径、发散角、束腰尺寸、束腰位置和曲率共同变化",
    diagnostics="耦合镜前束径＋多位置束径/近远场拟合 q",
    compensation="每个输入状态允许重新寻找最佳光纤 Z",
    result="η_max(D_in) 与拟合 q 参数",
    description="可调 Kepler 扩束器改变完整 q 参数；比较每个输入状态重新寻焦后的最高耦合效率。",
    specs=tuple(_common_prefix() + [("beam_expander", 915, 310, 0, "可调球面扩束器", {"magnification": 2.0, "spacing_mm": 150.0, "design_spacing_mm": 150.0, "module_offset_mm": 0.0})] + _diagnostic_sampler(x=1015, instrument="focus_scan_module", label="多位置束径测量") + _coupling_tail(start=1135, lenses=2)),
)
_add(
    key="curvature_matching", group="模场整形", label="波前曲率匹配筛选",
    active_control="扩束器内部间距 d1 与模块到耦合镜组距离 d2",
    coupled_quantities="端面 w 与 R 同时变化",
    diagnostics="多位置束径或近场＋远场/波前传感器",
    compensation="从实测状态中筛选 w 近似相同而 R 不同的组合",
    result="η(R)|w≈constant",
    description="尺寸近似不变来自双变量实测筛选，而不是软件锁定；用于辨认强度匹配但复场重叠偏低。",
    specs=tuple(_common_prefix() + [("beam_expander", 900, 310, 0, "曲率调节扩束器", {"magnification": 1.8, "spacing_mm": 145.0, "design_spacing_mm": 150.0, "module_offset_mm": 3.0})] + _diagnostic_sampler(x=1010, instrument="wavefront_sensor", label="波前传感器") + _coupling_tail(start=1130, lenses=2)),
)
_add(
    key="cylindrical_astigmatism", group="模场整形", label="柱面整形与像散",
    active_control="柱面镜间距、整体旋转角和模块位置",
    coupled_quantities="椭圆率、X/Y 发散角、两方向束腰位置与像散共同变化",
    diagnostics="多位置 w_x(z)、w_y(z) 与波前像散",
    compensation="分别拟合 q_x、q_y，再优化光纤 Z",
    result="η(q_x,q_y)、整形前后效率和束腰位置差",
    description="两片柱面镜组成可调单轴整形模块，区分单平面椭圆与真正的两方向束腰分离。",
    specs=tuple(_common_prefix() + [
        ("cylindrical_lens", 905, 310, 0, "负柱面镜", {"focal_mm": -25.0, "axis_angle_deg": 0.0, "pair_spacing_mm": 70.0}),
        ("cylindrical_lens", 1000, 310, 0, "正柱面镜", {"focal_mm": 50.0, "axis_angle_deg": 0.0, "pair_spacing_mm": 70.0}),
    ] + _diagnostic_sampler(x=1110, instrument="focus_scan_module", label="X/Y焦面扫描") + _coupling_tail(start=1230, lenses=2)),
)


for count, label in ((2, "双透镜耦合"), (3, "三透镜耦合"), (4, "四透镜耦合")):
    _add(
        key=f"coupling_{count}_lens", group="耦合模块比较", label=label,
        active_control=f"更换为{count}片可调耦合镜组并优化空气间隔",
        coupled_quantities="有效焦距、最终束腰、焦面位置和像差共同改变",
        diagnostics="端面匹配、束腰位置和正式复场耦合",
        compensation="先寻焦，再优化空气间隔，最后替换不合适透镜",
        result="检查耦合效率、系统效率与可实现空气间隔",
        description=f"公共平台保持不变，仅替换{count}透镜耦合模块，用于比较结构自由度与可实现效率。",
        specs=tuple(_common_prefix() + _diagnostic_sampler() + _coupling_tail(start=1040, lenses=count)),
    )

EXPERIMENT_PRESETS: dict[str, ExperimentPreset] = {item.key: item for item in _PRESETS}
EXPERIMENT_GROUPS: tuple[str, ...] = ("实验基准", "公共平台", "五轴装调", "光束指向", "模场整形", "耦合模块比较")


def presets_for_group(group: str) -> tuple[ExperimentPreset, ...]:
    return tuple(item for item in _PRESETS if item.group == group)


def metadata_lines(preset: ExperimentPreset) -> tuple[str, ...]:
    return (
        f"主动操作：{preset.active_control}",
        f"自然联动：{preset.coupled_quantities}",
        f"同步测量：{preset.diagnostics}",
        f"允许补偿：{preset.compensation}",
        f"比较结果：{preset.result}",
    )


__all__ = [
    "EXPERIMENT_GROUPS", "EXPERIMENT_PRESETS", "ExperimentPreset", "NodeSpec",
    "metadata_lines", "presets_for_group",
]

from __future__ import annotations

from copy import deepcopy
from typing import Any

CONTRACT_VERSION = "3.0-local-approximation"


def parameter(label: str, unit: str, default: float, minimum: float, maximum: float, step: float,
              levels=("demo", "experiment", "research")) -> dict[str, Any]:
    return {
        "label": label, "unit": unit, "default": default, "minimum": minimum,
        "maximum": maximum, "step": step, "levels": list(levels),
    }


def metric(label: str, unit: str = "", digits: int = 3, scale: float = 1.0) -> dict[str, Any]:
    return {"label": label, "unit": unit, "digits": digits, "scale": scale}


MODULES: dict[str, dict[str, Any]] = {
    "gaussian": {
        "title": "Gaussian 光源传播", "short_title": "Gaussian 传播",
        "summary": "观察束腰、波长、M² 与传播距离如何共同决定光束包络。",
        "objectives": ["理解瑞利长度", "判断束腰区与发散区", "认识 M² 的作用"],
        "parameters": {
            "wavelength_nm": parameter("波长 λ", "nm", 1550.0, 380.0, 2200.0, 10.0),
            "waist_um": parameter("束腰半径 w₀", "μm", 6.0, 0.5, 30.0, 0.1),
            "beam_quality_m2": parameter("光束质量 M²", "", 1.0, 1.0, 4.0, 0.05, ("experiment", "research")),
            "observation_distance_mm": parameter("观察距离 z", "mm", 5.0, -20.0, 20.0, 0.1),
        },
        "metrics": {
            "rayleigh_range_mm": metric("瑞利长度", "mm", 3),
            "observation_radius_um": metric("观察面光斑半径", "μm", 2),
            "divergence_half_angle_mrad": metric("发散半角", "mrad", 3),
        },
        "scan_metrics": ["rayleigh_range_mm", "observation_radius_um", "divergence_half_angle_mrad"],
        "prediction": {
            "prompt": "保持波长和 M² 不变，束腰半径增大为 2 倍，瑞利长度怎样变化？",
            "choices": [("quarter", "变为 1/4"), ("same", "基本不变"), ("double", "变为 2 倍"), ("quadruple", "变为 4 倍")],
            "answer": "quadruple", "explanation": "瑞利长度与束腰半径平方成正比。",
        },
        "task": "调节参数，使观察面光斑半径不超过 50 μm。",
        "formula": "z_R = πw₀²/(M²λ)，w(z)=w₀√(1+(z/z_R)²)",
        "assumptions": ["近轴传播", "均匀介质", "标量 Gaussian 光束"],
        "theory": "束腰越大，瑞利长度通常越长，但初始光斑也更大；M² 增大表示光束偏离理想基模，远场发散增强。",
    },
    "fiber": {
        "title": "光纤 NA 与单模条件", "short_title": "光纤导光",
        "summary": "区分接受角、全反射、V 数和单模条件。",
        "objectives": ["计算光纤 NA", "用 V 数判断单模", "区分接受与高耦合"],
        "parameters": {
            "wavelength_nm": parameter("波长 λ", "nm", 1550.0, 380.0, 2200.0, 10.0),
            "core_radius_um": parameter("纤芯半径 a", "μm", 4.1, 0.5, 20.0, 0.1),
            "n_core": parameter("纤芯折射率", "", 1.450, 1.40, 1.60, 0.0005, ("experiment", "research")),
            "n_clad": parameter("包层折射率", "", 1.444, 1.39, 1.599, 0.0005, ("experiment", "research")),
            "launch_angle_deg": parameter("入射角", "°", 4.0, 0.0, 25.0, 0.1),
        },
        "metrics": {
            "numerical_aperture": metric("数值孔径 NA", "", 4),
            "v_number": metric("归一化频率 V", "", 3),
            "acceptance_half_angle_deg": metric("接受半角", "°", 2),
            "mfd_um": metric("近似基模 MFD", "μm", 2),
        },
        "scan_metrics": ["v_number", "numerical_aperture", "acceptance_half_angle_deg", "mfd_um"],
        "prediction": {
            "prompt": "弱导阶跃光纤的 V 数不超过约 2.405 时，通常处于什么状态？",
            "choices": [("no", "不能导光"), ("single", "单模状态"), ("many", "大量高阶模式")],
            "answer": "single", "explanation": "LP11 的近似截止 V 数约为 2.405。",
        },
        "task": "使光纤保持单模，并让当前入射角位于接受锥内。",
        "formula": "NA=√(n_core²-n_clad²)，V=2πa·NA/λ",
        "assumptions": ["弱导近似", "阶跃型圆对称光纤", "空气入射"],
        "theory": "满足接受角只表示光线可被导入；满足单模条件还要求 V 数不超过截止值；二者都不等同于模式耦合效率高。",
    },
    "coupling": {
        "title": "光纤耦合五轴对准", "short_title": "五轴耦合",
        "summary": "观察横向偏移、轴向离焦和角度倾斜如何降低复场重叠。",
        "objectives": ["理解复场重叠", "比较五轴误差", "完成对准任务"],
        "parameters": {
            "wavelength_nm": parameter("波长 λ", "nm", 1550.0, 380.0, 2200.0, 10.0, ("experiment", "research")),
            "beam_radius_um": parameter("入射场半径", "μm", 5.2, 0.5, 20.0, 0.1),
            "mfd_um": parameter("光纤 MFD", "μm", 10.4, 1.0, 30.0, 0.1),
            "offset_x_um": parameter("X 偏移", "μm", 0.0, -15.0, 15.0, 0.1),
            "offset_y_um": parameter("Y 偏移", "μm", 0.0, -15.0, 15.0, 0.1),
            "axial_offset_um": parameter("轴向离焦", "μm", 0.0, -500.0, 500.0, 2.0, ("experiment", "research")),
            "tilt_x_mrad": parameter("X 倾角", "mrad", 0.0, -40.0, 40.0, 0.2, ("experiment", "research")),
            "tilt_y_mrad": parameter("Y 倾角", "mrad", 0.0, -40.0, 40.0, 0.2, ("experiment", "research")),
            "facet_transmission": parameter("端面透射率", "", 0.965, 0.80, 1.0, 0.001, ("research",)),
        },
        "metrics": {
            "field_efficiency": metric("复场耦合效率", "%", 2, 100.0),
            "total_efficiency": metric("总耦合效率", "%", 2, 100.0),
            "lateral_factor": metric("横向因子", "%", 2, 100.0),
            "angular_factor": metric("角度因子", "%", 2, 100.0),
        },
        "scan_metrics": ["field_efficiency", "total_efficiency", "lateral_factor", "angular_factor"],
        "prediction": {
            "prompt": "强度中心重合但存在明显倾角时，耦合效率通常怎样变化？",
            "choices": [("same", "保持不变"), ("down", "下降"), ("zero", "一定为零")],
            "answer": "down", "explanation": "倾角引入线性相位坡度，复场积分发生抵消。",
        },
        "task": "完成五轴对准，使总耦合效率达到 80%。",
        "formula": "η≈η_size·η_xy·η_θ·η_z·T_facet",
        "assumptions": ["两个场近似 Gaussian", "标量场", "小倾角和近轴条件"],
        "theory": "横向偏移改变模式中心，倾角改变相位，离焦改变光斑和波前曲率。强度看似重合并不保证复场重叠高。",
    },
    "psf": {
        "title": "PSF、Airy 与像差", "short_title": "聚焦成像",
        "summary": "比较衍射极限、离焦、球差、Strehl ratio 和 MTF。",
        "objectives": ["计算 Airy 尺度", "观察像差展宽 PSF", "理解 Strehl 判据"],
        "parameters": {
            "wavelength_nm": parameter("波长 λ", "nm", 550.0, 380.0, 1000.0, 5.0),
            "focal_length_mm": parameter("焦距 f", "mm", 10.0, 1.0, 50.0, 0.1),
            "aperture_diameter_mm": parameter("通光孔径 D", "mm", 2.0, 0.1, 10.0, 0.05),
            "spherical_aberration_waves": parameter("球差 W₀₄₀", "waves", 0.0, -1.5, 1.5, 0.01, ("experiment", "research")),
            "defocus_waves": parameter("离焦 W₀₂₀", "waves", 0.0, -1.5, 1.5, 0.01),
        },
        "metrics": {
            "airy_radius_um": metric("Airy 半径", "μm", 3),
            "strehl_ratio": metric("Strehl ratio", "", 3),
            "psf_rms_radius_um": metric("PSF RMS 半径", "μm", 2),
            "geometric_rms_radius_um": metric("几何 RMS 半径", "μm", 2),
        },
        "scan_metrics": ["strehl_ratio", "psf_rms_radius_um", "geometric_rms_radius_um", "airy_radius_um"],
        "prediction": {
            "prompt": "保持孔径和波长不变，球差增大后，Strehl ratio 通常怎样变化？",
            "choices": [("up", "增大"), ("same", "不变"), ("down", "减小")],
            "answer": "down", "explanation": "球差破坏光瞳相位一致性，使中心峰值下降。",
        },
        "task": "调节离焦和球差，使 Strehl ratio 达到 0.80。",
        "formula": "r_Airy=1.22λf/D，S≈exp[-(2πσ_W)²]",
        "assumptions": ["圆形均匀光瞳", "标量衍射", "简化 RMS 波前误差估计"],
        "theory": "Airy 尺度由波长和 F 数决定；像差降低中心峰值并把能量推向旁瓣。Strehl≥0.8 常用作接近衍射极限的教学判据。",
    },
}

LEVELS = {
    "demo": {"label": "演示", "description": "少量核心参数，侧重观察现象。"},
    "experiment": {"label": "实验", "description": "预测、记录、扫描和评分。"},
    "research": {"label": "研究", "description": "开放全部近似参数和数值采样演示。"},
}


def get_catalog() -> dict[str, Any]:
    return {"contract_version": CONTRACT_VERSION, "teaching_levels": deepcopy(LEVELS), "modules": deepcopy(MODULES)}


def get_module(module: str) -> dict[str, Any]:
    if module not in MODULES:
        raise ValueError(f"unknown teaching module: {module}")
    return deepcopy(MODULES[module])


def defaults_for(module: str) -> dict[str, float]:
    return {key: float(spec["default"]) for key, spec in get_module(module)["parameters"].items()}


def parameter_keys_for_level(module: str, level: str) -> list[str]:
    return [k for k, v in get_module(module)["parameters"].items() if level in v.get("levels", [])]

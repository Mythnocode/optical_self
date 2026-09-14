from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class SurfaceParameterSpec:


    key: str
    label: str
    kind: str = "float"  
    default: Any = 0.0
    unit: str = ""
    minimum: float = -1.0e12
    maximum: float = 1.0e12
    decimals: int = 6
    choices: tuple[str, ...] = ()
    helper: str = ""


@dataclass(frozen=True)
class SurfaceTypeSpec:


    name: str
    category: str
    description: str
    group_prefix: str
    parameters: tuple[SurfaceParameterSpec, ...] = ()
    disabled_common_fields: tuple[str, ...] = ()


SURFACE_TYPES: tuple[SurfaceTypeSpec, ...] = (
    SurfaceTypeSpec(
        name="球面",
        category="折射面",
        description="标准旋转对称球面。公共列中的曲率、厚度、材料和半口径即可完整描述。",
        group_prefix="S",
    ),
    SurfaceTypeSpec(
        name="柱面",
        category="折射面",
        description=(
            "柱面在柱轴方向曲率为零，只在垂直柱轴的方向具有公共列所给曲率。"
            "角度遵循局部 x-y 面内的 Zemax 式方位角定义。"
        ),
        group_prefix="CYL",
        parameters=(
            SurfaceParameterSpec(
                "cylinder_axis_deg",
                "柱轴方位角（零光焦度轴）",
                default=0.0,
                unit="°",
                minimum=-360.0,
                maximum=360.0,
                decimals=6,
                helper="0°：柱轴沿局部 X、光焦度作用于 Y；90°：柱轴沿局部 Y、光焦度作用于 X。",
            ),
        ),
    ),
    SurfaceTypeSpec(
        name="非球面",
        category="折射面",
        description="圆锥基底叠加偶次非球面系数；系数在本页单独管理。",
        group_prefix="A",
        parameters=(
            SurfaceParameterSpec("a4", "非球面 A4", default=0.0, minimum=-1.0, maximum=1.0, decimals=12),
            SurfaceParameterSpec("a6", "非球面 A6", default=0.0, minimum=-1.0, maximum=1.0, decimals=12),
            SurfaceParameterSpec("a8", "非球面 A8", default=0.0, minimum=-1.0, maximum=1.0, decimals=12),
            SurfaceParameterSpec("normalization_radius_mm", "归一化半径", default=1.0, unit="mm", minimum=1e-6, maximum=1e6, decimals=6),
        ),
    ),
    SurfaceTypeSpec(
        name="平面",
        category="折射面",
        description="零曲率平面。曲率字段自动禁用，其他公共参数仍可编辑。",
        group_prefix="P",
        disabled_common_fields=("radius",),
    ),
    SurfaceTypeSpec(
        name="光阑",
        category="孔径元件",
        description="定义孔径或系统光阑位置，不引入折射材料。",
        group_prefix="ST",
        disabled_common_fields=("radius", "material"),
        parameters=(
            SurfaceParameterSpec("stop_role", "光阑角色", kind="choice", default="孔径光阑", choices=("孔径光阑", "视场光阑", "遮拦", "普通孔径")),
            SurfaceParameterSpec("aperture_shape", "孔径形状", kind="choice", default="圆形", choices=("圆形", "矩形", "椭圆", "用户孔径")),
            SurfaceParameterSpec("width_mm", "矩形宽度", default=6.0, unit="mm", minimum=0.001, maximum=1e5),
            SurfaceParameterSpec("height_mm", "矩形高度", default=6.0, unit="mm", minimum=0.001, maximum=1e5),
        ),
    ),
    SurfaceTypeSpec(
        name="反射镜",
        category="反射元件",
        description="反射表面。可设置反射模型、反射率和设计入射角。",
        group_prefix="M",
        parameters=(
            SurfaceParameterSpec("mirror_mode", "反射模型", kind="choice", default="理想反射", choices=("理想反射", "金属膜", "介质高反膜", "用户模型")),
            SurfaceParameterSpec("reflectivity", "标称反射率", default=0.98, minimum=0.0, maximum=1.0, decimals=6),
            SurfaceParameterSpec("design_incidence_deg", "设计入射角", default=0.0, unit="°", minimum=-89.9, maximum=89.9, decimals=4),
        ),
    ),
    SurfaceTypeSpec(
        name="衍射光栅",
        category="衍射元件",
        description="反射式或透射式光栅。沟槽密度、级次、沟槽方向和闪耀角在此独立编辑。",
        group_prefix="G",
        parameters=(
            SurfaceParameterSpec("grating_mode", "光栅形式", kind="choice", default="反射式", choices=("反射式", "透射式")),
            SurfaceParameterSpec("groove_density_lpm", "沟槽密度", default=600.0, unit="线/mm", minimum=0.001, maximum=1e6, decimals=6),
            SurfaceParameterSpec("diffraction_order", "衍射级次 m", kind="int", default=1, minimum=-100, maximum=100),
            SurfaceParameterSpec("groove_angle_deg", "沟槽方向角", default=0.0, unit="°", minimum=-360.0, maximum=360.0, decimals=5),
            SurfaceParameterSpec("blaze_angle_deg", "闪耀角", default=0.0, unit="°", minimum=-89.9, maximum=89.9, decimals=5),
            SurfaceParameterSpec("efficiency_model", "效率模型", kind="choice", default="标量近似", choices=("理想", "标量近似", "RCWA 数据表", "用户模型")),
        ),
    ),
    SurfaceTypeSpec(
        name="坐标断点",
        category="坐标变换",
        description="在顺序系统中施加偏心和倾斜。不会使用曲率、材料或半口径。",
        group_prefix="CB",
        disabled_common_fields=("radius", "material", "aperture"),
        parameters=(
            SurfaceParameterSpec("decenter_x_mm", "X 偏心", default=0.0, unit="mm", minimum=-1e5, maximum=1e5),
            SurfaceParameterSpec("decenter_y_mm", "Y 偏心", default=0.0, unit="mm", minimum=-1e5, maximum=1e5),
            SurfaceParameterSpec("tilt_x_deg", "X 倾斜", default=0.0, unit="°", minimum=-360, maximum=360),
            SurfaceParameterSpec("tilt_y_deg", "Y 倾斜", default=0.0, unit="°", minimum=-360, maximum=360),
            SurfaceParameterSpec("tilt_z_deg", "Z 旋转", default=0.0, unit="°", minimum=-360, maximum=360),
            SurfaceParameterSpec("return_to_previous", "后续恢复原坐标", kind="bool", default=False),
        ),
    ),
    SurfaceTypeSpec(
        name="二元衍射面",
        category="衍射元件",
        description="以径向多项式相位描述的二元衍射面。",
        group_prefix="DOE",
        parameters=(
            SurfaceParameterSpec("diffraction_order", "衍射级次 m", kind="int", default=1, minimum=-100, maximum=100),
            SurfaceParameterSpec("phase_a2", "相位系数 A2", default=0.0, minimum=-1e9, maximum=1e9, decimals=12),
            SurfaceParameterSpec("phase_a4", "相位系数 A4", default=0.0, minimum=-1e9, maximum=1e9, decimals=12),
            SurfaceParameterSpec("phase_a6", "相位系数 A6", default=0.0, minimum=-1e9, maximum=1e9, decimals=12),
        ),
    ),
    SurfaceTypeSpec(
        name="探测器/像面",
        category="接收面",
        description="定义像面或探测器采样区域。曲率和材料不参与。",
        group_prefix="IMG",
        disabled_common_fields=("radius", "material"),
        parameters=(
            SurfaceParameterSpec("pixel_pitch_um", "像元尺寸", default=5.0, unit="μm", minimum=0.001, maximum=1e6),
            SurfaceParameterSpec("pixels_x", "X 像元数", kind="int", default=1024, minimum=1, maximum=1000000),
            SurfaceParameterSpec("pixels_y", "Y 像元数", kind="int", default=1024, minimum=1, maximum=1000000),
            SurfaceParameterSpec("sampling_mode", "采样模式", kind="choice", default="中心采样", choices=("中心采样", "面积积分", "用户响应")),
        ),
    ),
    SurfaceTypeSpec(
        name="用户自定义面",
        category="扩展",
        description="为后续插件或后端自定义表面预留。公共列保持不变，扩展标识和参数说明在此保存。",
        group_prefix="USR",
        parameters=(
            SurfaceParameterSpec("plugin_id", "插件/模型标识", kind="text", default=""),
            SurfaceParameterSpec("parameter_note", "扩展参数说明", kind="text", default=""),
        ),
    ),
)

_SURFACE_BY_NAME = {spec.name: spec for spec in SURFACE_TYPES}


def surface_type_names() -> list[str]:
    return [spec.name for spec in SURFACE_TYPES]


def get_surface_type(name: str) -> SurfaceTypeSpec:
    return _SURFACE_BY_NAME.get(name, _SURFACE_BY_NAME["用户自定义面"])


def ensure_surface_defaults(surface: Any, fallback_group: str = "") -> None:


    if not hasattr(surface, "group_id") or not surface.group_id:
        surface.group_id = fallback_group or "S1"
    if not hasattr(surface, "enabled"):
        surface.enabled = True
    if not hasattr(surface, "type_parameters") or surface.type_parameters is None:
        surface.type_parameters = {}
    if not hasattr(surface, "coating"):
        surface.coating = "无"
    if not hasattr(surface, "roughness_nm"):
        surface.roughness_nm = 0.0
    if not hasattr(surface, "mechanical_diameter_mm"):
        surface.mechanical_diameter_mm = max(0.1, 2.0 * float(getattr(surface, "semi_aperture_mm", 1.0)))
    if not hasattr(surface, "note"):
        surface.note = ""
    spec = get_surface_type(getattr(surface, "surface_type", "球面"))
    for parameter in spec.parameters:
        surface.type_parameters.setdefault(parameter.key, parameter.default)


def apply_type_defaults(surface: Any, type_name: str) -> None:
    surface.surface_type = type_name if type_name in _SURFACE_BY_NAME else "用户自定义面"
    ensure_surface_defaults(surface)
    spec = get_surface_type(surface.surface_type)
    for parameter in spec.parameters:
        surface.type_parameters.setdefault(parameter.key, parameter.default)
    if "radius" in spec.disabled_common_fields:
        surface.radius_mm = 0.0
    if "material" in spec.disabled_common_fields:
        surface.material = "AIR"


def _format_value(value: Any, parameter: SurfaceParameterSpec) -> str:
    if parameter.kind == "bool":
        return "是" if bool(value) else "否"
    if parameter.kind == "float":
        try:
            text = f"{float(value):.6g}"
        except (TypeError, ValueError):
            text = str(value)
    else:
        text = str(value)
    return f"{text} {parameter.unit}".strip()


def surface_feature_summary(surface: Any, max_items: int = 3) -> str:
    ensure_surface_defaults(surface)
    spec = get_surface_type(surface.surface_type)
    if not spec.parameters:
        if surface.surface_type == "非球面":
            return f"k={surface.conic:.4g}"
        return "—"
    preferred_keys: dict[str, tuple[str, ...]] = {
        "柱面": ("cylinder_axis_deg",),
        "衍射光栅": ("groove_density_lpm", "diffraction_order", "grating_mode"),
        "坐标断点": ("decenter_x_mm", "tilt_x_deg", "tilt_y_deg"),
        "反射镜": ("mirror_mode", "reflectivity", "design_incidence_deg"),
        "光阑": ("stop_role", "aperture_shape"),
        "探测器/像面": ("pixel_pitch_um", "pixels_x", "pixels_y"),
        "非球面": ("a4", "a6", "a8"),
        "二元衍射面": ("diffraction_order", "phase_a2", "phase_a4"),
        "用户自定义面": ("plugin_id",),
    }
    by_key = {parameter.key: parameter for parameter in spec.parameters}
    keys: Iterable[str] = preferred_keys.get(spec.name, tuple(by_key))
    parts: list[str] = []
    for key in keys:
        parameter = by_key.get(key)
        if parameter is None:
            continue
        value = surface.type_parameters.get(key, parameter.default)
        if spec.name == "衍射光栅" and key == "groove_density_lpm":
            parts.append(f"{_format_value(value, parameter)}")
        elif key == "diffraction_order":
            parts.append(f"m={value}")
        elif key in {"decenter_x_mm", "decenter_y_mm"}:
            parts.append(f"{parameter.label}={_format_value(value, parameter)}")
        elif key.startswith("tilt_"):
            parts.append(f"{parameter.label}={_format_value(value, parameter)}")
        elif key in {"pixels_x", "pixels_y"}:
            parts.append(f"{parameter.label}={value}")
        else:
            parts.append(_format_value(value, parameter))
        if len(parts) >= max_items:
            break
    return " · ".join(parts) if parts else "—"


def extra_parameter_columns(surfaces: Iterable[Any]) -> tuple[SurfaceParameterSpec, ...]:
    ordered: list[SurfaceParameterSpec] = []
    seen: set[str] = set()
    for surface in surfaces:
        spec = get_surface_type(getattr(surface, "surface_type", "球面"))
        for parameter in spec.parameters:
            if parameter.key in seen:
                continue
            seen.add(parameter.key)
            ordered.append(parameter)
    return tuple(ordered)


def extra_header_label(parameter: SurfaceParameterSpec) -> str:
    label = str(parameter.label or parameter.key)
    if parameter.unit and parameter.unit not in label:
        return f"{label} / {parameter.unit}"
    return label


def surface_uses_parameter(surface: Any, key: str) -> bool:
    spec = get_surface_type(getattr(surface, "surface_type", "球面"))
    return any(parameter.key == key for parameter in spec.parameters)


def format_parameter_cell(value: Any, parameter: SurfaceParameterSpec) -> str:
    if parameter.kind == "bool":
        return "是" if bool(value) else "否"
    if parameter.kind == "float":
        try:
            return f"{float(value):.8g}"
        except (TypeError, ValueError):
            return str(value)
    if parameter.kind == "int":
        try:
            return str(int(value))
        except (TypeError, ValueError):
            return str(value)
    if value is None:
        return str(parameter.default)
    return str(value)


def parse_parameter_cell(text: str, parameter: SurfaceParameterSpec) -> Any:
    raw = str(text).strip()
    if parameter.kind == "bool":
        return raw.lower() not in {"否", "no", "false", "0", "禁用"}
    if parameter.kind == "int":
        value = int(float(raw))
        return int(max(parameter.minimum, min(parameter.maximum, value)))
    if parameter.kind == "float":
        value = float(raw)
        return max(parameter.minimum, min(parameter.maximum, value))
    if parameter.kind == "choice" and parameter.choices and raw not in parameter.choices:
        raise ValueError("invalid choice")
    return raw


def next_group_id(existing: Iterable[str], prefix: str) -> str:
    used = {str(value) for value in existing}
    index = 1
    while f"{prefix}{index}" in used:
        index += 1
    return f"{prefix}{index}"

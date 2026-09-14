"""Authoritative state model for the isolated Teaching Center V2.

The legacy teaching package is intentionally not imported here.  This module is
the single source of truth for placement, optical parameters and revision
numbers.  Renderers and inspectors receive snapshots; they never own a second
copy of the scene.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
import copy
import json
import math
from enum import Enum
from pathlib import Path
from typing import Any

from .qt_compat import QObject, Signal
from .coordinates import AXIS_HEIGHT_MM


PITCH_DEG_MAX = 89.99
PITCH_RAD_MAX = math.radians(PITCH_DEG_MAX)

RESERVED_COMPONENT_IDS = frozenset({"table", "axisheight", "beamheight"})
RESERVED_COMPONENT_ID_PREFIXES = ("gizmo", "ray", "stem", "node")

RUNTIME_KIND_ALIAS = {"ccd": "imaging_camera"}
MIRROR_RUNTIME_FOLD_DEG = 45.0
DEFAULT_BEAM_RADIUS_MM = 0.72
DEFAULT_LENS_INDEX = 1.5168
DEFAULT_CENTER_THICKNESS_MM = 2.0
CCD_SENSOR_WIDTH_MM = 4.968
CCD_SENSOR_HEIGHT_MM = 3.726

FLOAT_PARAM_NAMES = frozenset(
    {
        "wavelength_nm",
        "power_mw",
        "beam_radius_mm",
        "focal_length_mm",
        "focal_mm",
        "diameter_mm",
        "radius1_mm",
        "radius2_mm",
        "center_thickness_mm",
        "clear_aperture_mm",
        "aperture_radius_mm",
        "design_refractive_index",
        "mfd_um",
        "na",
        "sensor_width_mm",
        "sensor_height_mm",
        "active_area_mm",
        "isolation_db",
        "insertion_loss_db",
        "split_ratio",
        "magnification",
        "groove_density_mm",
        "retardance_waves",
    }
)

OPTIONAL_UNSET_PARAM_NAMES = frozenset(
    {"radius1_mm", "radius2_mm", "clear_aperture_mm", "aperture_radius_mm"}
)

KIND_PARAM_SPECS: dict[str, tuple[tuple[str, str, str], ...]] = {
    "laser": (
        ("wavelength_nm", "波长", "nm"),
        ("power_mw", "功率", "mW"),
        ("beam_radius_mm", "束腰半径", "mm"),
    ),
    "lens": (
        ("focal_length_mm", "焦距", "mm"),
        ("diameter_mm", "外径", "mm"),
        ("material", "材料", ""),
        ("radius1_mm", "前表面半径", "mm"),
        ("radius2_mm", "后表面半径", "mm"),
        ("center_thickness_mm", "中心厚度", "mm"),
        ("clear_aperture_mm", "通光孔径半径", "mm"),
    ),
    "fiber": (
        ("mfd_um", "模场直径", "µm"),
        ("na", "数值孔径", ""),
    ),
    "ccd": (
        ("sensor_width_mm", "靶面宽", "mm"),
        ("sensor_height_mm", "靶面高", "mm"),
    ),
    "mirror": (
        ("diameter_mm", "外径", "mm"),
    ),
    "isolator": (
        ("isolation_db", "隔离度", "dB"),
        ("insertion_loss_db", "插损", "dB"),
        ("clear_aperture_mm", "通光孔径半径", "mm"),
        ("diameter_mm", "外壳外径", "mm"),
    ),
    "waveplate": (
        ("plate_type", "类型", ""),
        ("retardance_waves", "延迟", "λ"),
        ("diameter_mm", "外径", "mm"),
    ),
    "cylindrical_lens": (
        ("focal_length_mm", "焦距", "mm"),
        ("diameter_mm", "外径", "mm"),
        ("center_thickness_mm", "中心厚度", "mm"),
    ),
    "beam_expander": (
        ("magnification", "倍率", "×"),
        ("diameter_mm", "外径", "mm"),
    ),
    "aperture": (
        ("diameter_mm", "孔径", "mm"),
        ("shape", "形状", ""),
    ),
    "pbs": (
        ("split_ratio", "透射比", ""),
        ("diameter_mm", "立方边长", "mm"),
    ),
    "splitter": (
        ("split_ratio", "透射比", ""),
        ("diameter_mm", "外径", "mm"),
    ),
    "beam_sampler": (
        ("split_ratio", "取样比", ""),
        ("diameter_mm", "外径", "mm"),
    ),
    "grating": (
        ("groove_density_mm", "线密度", "/mm"),
        ("diameter_mm", "边长", "mm"),
    ),
    "power_meter": (
        ("diameter_mm", "靶面直径", "mm"),
    ),
    "wavefront_sensor": (
        ("sensor_width_mm", "靶面宽", "mm"),
        ("sensor_height_mm", "靶面高", "mm"),
    ),
    "oscilloscope": (),
}

KIND_DEFAULT_PARAMS: dict[str, dict[str, Any]] = {
    "laser": {"wavelength_nm": 780.0, "power_mw": 100.0, "beam_radius_mm": DEFAULT_BEAM_RADIUS_MM},
    "lens": {
        "focal_length_mm": 25.0,
        "focal_mm": 25.0,
        "diameter_mm": 12.7,
        "material": "N-BK7",
        "radius1_mm": 0.0,
        "radius2_mm": 0.0,
        "center_thickness_mm": DEFAULT_CENTER_THICKNESS_MM,
        "clear_aperture_mm": 0.0,
    },
    "fiber": {"mfd_um": 5.6, "na": 0.12},
    "ccd": {"sensor_width_mm": CCD_SENSOR_WIDTH_MM, "sensor_height_mm": CCD_SENSOR_HEIGHT_MM},
    "mirror": {"diameter_mm": 12.7},
    "isolator": {
        "isolation_db": 38.0,
        "insertion_loss_db": 0.4,
        "clear_aperture_mm": 1.8,
        "diameter_mm": 25.0,
    },
    "waveplate": {"plate_type": "hwp", "retardance_waves": 0.5, "diameter_mm": 12.7},
    "cylindrical_lens": {
        "focal_length_mm": 50.0,
        "focal_mm": 50.0,
        "diameter_mm": 12.7,
        "center_thickness_mm": DEFAULT_CENTER_THICKNESS_MM,
    },
    "beam_expander": {"magnification": 2.0, "diameter_mm": 25.0},
    "aperture": {"diameter_mm": 5.0, "shape": "circle"},
    "pbs": {"split_ratio": 0.5, "diameter_mm": 12.7},
    "splitter": {"split_ratio": 0.5, "diameter_mm": 12.7},
    "beam_sampler": {"split_ratio": 0.05, "diameter_mm": 12.7},
    "grating": {"groove_density_mm": 600.0, "diameter_mm": 12.7},
    "power_meter": {"diameter_mm": 9.5},
    "wavefront_sensor": {"sensor_width_mm": 4.968, "sensor_height_mm": 3.726},
    "oscilloscope": {},
}

TEACHING_KIND_MIME = "application/x-teaching-kind"

PLACEABLE_KINDS: tuple[tuple[str, str], ...] = (
    ("laser", "激光器"),
    ("isolator", "隔离器"),
    ("waveplate", "波片"),
    ("lens", "透镜"),
    ("cylindrical_lens", "柱面镜"),
    ("beam_expander", "扩束器"),
    ("aperture", "光阑"),
    ("pbs", "PBS"),
    ("splitter", "分束镜"),
    ("beam_sampler", "取样镜"),
    ("grating", "光栅"),
    ("mirror", "反射镜"),
    ("fiber", "光纤架"),
    ("ccd", "CCD 相机"),
    ("power_meter", "功率计"),
    ("wavefront_sensor", "波前传感器"),
    ("oscilloscope", "示波器"),
)


def component_id_is_reserved(component_id: str) -> bool:
    raw = str(component_id or "").strip()
    if not raw or ":" in raw or "/" in raw or "\\" in raw:
        return True
    lower = raw.lower()
    if lower in RESERVED_COMPONENT_IDS:
        return True
    return lower.split("-", 1)[0] in RESERVED_COMPONENT_ID_PREFIXES


class ComponentKind(str, Enum):
    LASER = "laser"
    ISOLATOR = "isolator"
    WAVEPLATE = "waveplate"
    LENS = "lens"
    CYLINDRICAL_LENS = "cylindrical_lens"
    BEAM_EXPANDER = "beam_expander"
    APERTURE = "aperture"
    PBS = "pbs"
    SPLITTER = "splitter"
    BEAM_SAMPLER = "beam_sampler"
    GRATING = "grating"
    MIRROR = "mirror"
    FIBER = "fiber"
    CCD = "ccd"
    POWER_METER = "power_meter"
    WAVEFRONT_SENSOR = "wavefront_sensor"
    OSCILLOSCOPE = "oscilloscope"


class ResultKind(str, Enum):
    GEOMETRY = "geometry"
    RAYTRACE = "raytrace"
    SPOT = "spot"
    FIELD = "field"
    COUPLING = "coupling"
    WAVEFRONT = "wavefront"


@dataclass(slots=True)
class Pose:
    """Teaching coordinates in millimetres and radians.

    x_mm is the axial direction on the bench, y_mm is the lateral direction,
    and z_mm is the vertical height.  The physics adapter converts this to its
    own explicit frame; no renderer coordinate is ever sent to the engine.
    """

    x_mm: float = 0.0
    y_mm: float = 0.0
    z_mm: float = AXIS_HEIGHT_MM
    yaw_rad: float = 0.0
    pitch_rad: float = 0.0
    roll_rad: float = 0.0

    @classmethod
    def from_degrees(
        cls,
        x_mm: float = 0.0,
        y_mm: float = 0.0,
        z_mm: float = AXIS_HEIGHT_MM,
        yaw_deg: float = 0.0,
        pitch_deg: float = 0.0,
        roll_deg: float = 0.0,
    ) -> "Pose":
        return cls(x_mm, y_mm, z_mm, math.radians(yaw_deg), math.radians(pitch_deg), math.radians(roll_deg))

    @property
    def yaw_deg(self) -> float:
        return math.degrees(self.yaw_rad)

    @property
    def pitch_deg(self) -> float:
        return math.degrees(self.pitch_rad)

    @property
    def roll_deg(self) -> float:
        return math.degrees(self.roll_rad)

    def normalized(self) -> "Pose":
        return Pose(
            x_mm=float(self.x_mm),
            y_mm=float(self.y_mm),
            z_mm=max(0.0, float(self.z_mm)),
            yaw_rad=float(self.yaw_rad) % math.tau,
            pitch_rad=max(-PITCH_RAD_MAX, min(PITCH_RAD_MAX, float(self.pitch_rad))),
            roll_rad=float(self.roll_rad) % math.tau,
        )


def _filter_fields(type_, data: dict[str, Any]) -> dict[str, Any]:
    allowed = {item.name for item in fields(type_)}
    return {key: value for key, value in data.items() if key in allowed}


def runtime_kind(kind: str) -> str:
    """Map a teaching component kind onto the runtime surface kind."""
    return RUNTIME_KIND_ALIAS.get(str(kind), str(kind))


def _optional_nonzero(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if abs(number) < 1.0e-12:
        return None
    return number


def default_params_for_kind(kind: str) -> dict[str, Any]:
    return copy.deepcopy(KIND_DEFAULT_PARAMS.get(str(kind), {}))


def normalize_component_params(kind: str, params: dict[str, Any] | None) -> dict[str, Any]:
    """Fill industrial defaults and migrate legacy CCD area into width × height."""
    kind = str(kind)
    incoming = dict(params or {})
    merged = {**default_params_for_kind(kind), **incoming}
    if kind == "laser":
        merged.setdefault("beam_radius_mm", DEFAULT_BEAM_RADIUS_MM)
    elif kind == "lens":
        focal = incoming.get("focal_length_mm", incoming.get("focal_mm", merged.get("focal_length_mm", 25.0)))
        try:
            focal_value = float(focal)
        except (TypeError, ValueError):
            focal_value = 25.0
        merged["focal_length_mm"] = focal_value
        merged["focal_mm"] = focal_value
        merged.setdefault("center_thickness_mm", DEFAULT_CENTER_THICKNESS_MM)
        merged.setdefault("material", "N-BK7")
        merged.setdefault("radius1_mm", 0.0)
        merged.setdefault("radius2_mm", 0.0)
        merged.setdefault("clear_aperture_mm", 0.0)
    elif kind == "ccd":
        if "active_area_mm" in incoming and "sensor_width_mm" not in incoming and "sensor_height_mm" not in incoming:
            try:
                area_value = float(incoming["active_area_mm"])
            except (TypeError, ValueError):
                area_value = CCD_SENSOR_WIDTH_MM
            merged["sensor_width_mm"] = area_value
            merged["sensor_height_mm"] = area_value
        merged.setdefault("sensor_width_mm", CCD_SENSOR_WIDTH_MM)
        merged.setdefault("sensor_height_mm", CCD_SENSOR_HEIGHT_MM)
        merged.pop("active_area_mm", None)
    return merged


def compile_component_params(kind: str, params: dict[str, Any], *, label: str = "") -> tuple[dict[str, Any], tuple[str, ...]]:
    """Prescription sent to the runtime.  Zero radii mean 'unset', not flat plates."""
    kind = str(kind)
    compiled = dict(params)
    warnings: list[str] = []
    name = label or kind
    if kind == "laser":
        compiled.setdefault("beam_radius_mm", DEFAULT_BEAM_RADIUS_MM)
    elif kind == "lens":
        focal = compiled.get("focal_length_mm", compiled.get("focal_mm", 50.0))
        compiled["focal_mm"] = float(focal)
        compiled.setdefault("center_thickness_mm", DEFAULT_CENTER_THICKNESS_MM)
        compiled.setdefault("design_refractive_index", DEFAULT_LENS_INDEX)
        radius1 = _optional_nonzero(compiled.get("radius1_mm"))
        radius2 = _optional_nonzero(compiled.get("radius2_mm"))
        if radius1 is not None and radius2 is not None:
            compiled["radius1_mm"] = radius1
            compiled["radius2_mm"] = radius2
        else:
            compiled.pop("radius1_mm", None)
            compiled.pop("radius2_mm", None)
            warnings.append(f"{name}未提供两面真实曲率，使用双凸等效（n={DEFAULT_LENS_INDEX}，厚 {DEFAULT_CENTER_THICKNESS_MM:g} mm）。")
        for key in ("clear_aperture_mm", "aperture_radius_mm"):
            optional = _optional_nonzero(compiled.get(key))
            if optional is None:
                compiled.pop(key, None)
            else:
                compiled[key] = optional
    elif kind == "ccd":
        width = float(compiled.get("sensor_width_mm") or compiled.get("active_area_mm") or CCD_SENSOR_WIDTH_MM)
        height = float(compiled.get("sensor_height_mm") or compiled.get("active_area_mm") or CCD_SENSOR_HEIGHT_MM)
        compiled["sensor_width_mm"] = width
        compiled["sensor_height_mm"] = height
        compiled["diameter_mm"] = max(width, height)
        compiled.pop("active_area_mm", None)
    elif kind == "isolator":
        compiled.setdefault("isolation_db", 38.0)
        compiled.setdefault("insertion_loss_db", 0.4)
        compiled.setdefault("diameter_mm", 25.0)
        aperture = _optional_nonzero(compiled.get("clear_aperture_mm"))
        compiled["clear_aperture_mm"] = aperture if aperture is not None else 1.8
        warnings.append(
            f"{name}按法拉第隔离器摆在激光后；正向只计插损 {float(compiled['insertion_loss_db']):g} dB，"
            f"反向隔离 {float(compiled['isolation_db']):g} dB 这一版不追回光。"
        )
    elif kind == "cylindrical_lens":
        focal = compiled.get("focal_length_mm", compiled.get("focal_mm", 50.0))
        compiled["focal_length_mm"] = float(focal)
        compiled["focal_mm"] = float(focal)
        compiled.setdefault("center_thickness_mm", DEFAULT_CENTER_THICKNESS_MM)
    elif kind in {"pbs", "splitter", "beam_sampler"}:
        default_ratio = 0.5 if kind == "pbs" else (0.05 if kind == "beam_sampler" else 0.5)
        compiled.setdefault("split_ratio", default_ratio)
        compiled.setdefault("diameter_mm", 12.7)
    elif kind == "waveplate":
        compiled.setdefault("plate_type", "hwp")
        compiled.setdefault("retardance_waves", 0.5)
        compiled.setdefault("diameter_mm", 12.7)
        warnings.append(f"{name}这一版只占位；Jones 偏振未进耦合/追迹。")
    elif kind == "beam_expander":
        compiled.setdefault("magnification", 2.0)
        warnings.append(f"{name}这一版按通光窗占位，倍率不改变束腰。")
    elif kind == "grating":
        compiled.setdefault("groove_density_mm", 600.0)
        warnings.append(f"{name}这一版按通光窗占位，不追衍射级次。")
    elif kind == "aperture":
        compiled.setdefault("diameter_mm", 5.0)
        compiled.setdefault("shape", "circle")
    return compiled, tuple(warnings)


@dataclass(slots=True)
class OpticalComponent:
    component_id: str
    kind: str
    label: str
    pose: Pose = field(default_factory=Pose)
    params: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    category: str = "光学器件"
    asset_key: str = ""

    def copy(self) -> "OpticalComponent":
        return OpticalComponent(
            component_id=self.component_id,
            kind=self.kind,
            label=self.label,
            pose=copy.deepcopy(self.pose),
            params=copy.deepcopy(self.params),
            enabled=bool(self.enabled),
            category=self.category,
            asset_key=self.asset_key,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "component_id": self.component_id,
            "kind": self.kind,
            "label": self.label,
            "pose": asdict(self.pose.normalized()),
            "params": copy.deepcopy(self.params),
            "enabled": bool(self.enabled),
            "category": self.category,
            "asset_key": self.asset_key,
        }

    def to_compat_node(self) -> dict[str, Any]:
        """Legacy-shaped node used by older teaching snapshot importers."""
        return {
            "id": self.component_id,
            "kind": self.kind,
            "label": self.label,
            "x": float(self.pose.x_mm),
            "y": float(self.pose.y_mm),
            "z": float(self.pose.z_mm),
            "yaw": float(self.pose.yaw_deg),
            "pitch": float(self.pose.pitch_deg),
            "roll": float(self.pose.roll_deg),
            "enabled": bool(self.enabled),
            "params": copy.deepcopy(self.params),
        }


@dataclass(slots=True)
class SceneReference:
    """Bench datum for the teaching world frame.

    Origin is the rail start on the table surface, not a laser.  Lasers are
    components in this frame.
    """

    name: str = "实验台坐标系"
    origin: str = "bench"
    axial_axis: str = "+X_t → +Z_engine"
    lateral_axis: str = "+Y_t → +X_engine"
    vertical_axis: str = "+Z_t → +Y_engine"
    view_frame: str = "view3d_render"
    view_up: str = "+Z_t → +Y_render"
    view_depth: str = "+Y_t → −Z_render"
    unit: str = "mm"
    axis_height_mm: float = AXIS_HEIGHT_MM
    origin_teaching_mm: tuple[float, float, float] = (0.0, 0.0, 0.0)
    pixels_per_mm: float = 8.0
    render_units_per_mm: float = 1.0

    def __post_init__(self) -> None:
        self.origin_teaching_mm = (0.0, 0.0, 0.0)
        self.axis_height_mm = float(self.axis_height_mm)
        self.render_units_per_mm = float(self.render_units_per_mm)
        self.origin = "bench"
        self.view_frame = str(self.view_frame or "view3d_render")


@dataclass(slots=True)
class SceneSnapshot:
    schema_version: int
    scene_id: str
    revision: int
    reference: SceneReference
    components: list[OpticalComponent]
    baseline_enabled: bool
    baseline_x_mm: float
    selected_component_id: str | None
    active_result_revision: int | None
    results: dict[str, dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "scene_id": self.scene_id,
            "revision": self.revision,
            "reference": asdict(self.reference),
            "components": [item.to_dict() for item in self.components],
            "baseline_enabled": bool(self.baseline_enabled),
            "baseline_x_mm": float(self.baseline_x_mm),
            "selected_component_id": self.selected_component_id,
            "active_result_revision": self.active_result_revision,
            "results": copy.deepcopy(self.results),
        }

    def to_publish_dict(self) -> dict[str, Any]:
        from .coordinates import FRAMES, FRAME_TEACHING, engine_orientation_fields, teaching_pose_to_simulation, transform_from_reference

        payload = self.to_dict()
        transform = transform_from_reference(self.reference)
        payload["source"] = "teaching_v2"
        payload["frame"] = FRAME_TEACHING
        payload["frames"] = dict(FRAMES)
        payload["nodes"] = [item.to_compat_node() for item in self.components]
        laser = next((item for item in self.components if item.kind == "laser"), None)
        fiber = next((item for item in self.components if item.kind == "fiber"), None)
        if laser is not None:
            payload["wavelength_nm"] = float(laser.params.get("wavelength_nm") or 780.0)
            payload["input_power_mw"] = float(laser.params.get("power_mw") or 100.0)
        if fiber is not None:
            mfd = float(fiber.params.get("mfd_um") or 5.6)
            payload["receiver_mode_radius_um"] = mfd * 0.5
            payload["receiver_na"] = float(fiber.params.get("na") or 0.12)
        payload["engine_nodes"] = []
        for item in self.components:
            params, _warnings = compile_component_params(item.kind, item.params, label=item.label)
            yaw = item.pose.yaw_rad
            if item.kind == "mirror":
                yaw = yaw + math.radians(MIRROR_RUNTIME_FOLD_DEG)
            orientation = engine_orientation_fields(
                yaw, item.pose.pitch_rad, item.pose.roll_rad, transform
            )
            params = {**params, **orientation}
            if item.kind == "laser":
                params["source_direction_engine"] = list(orientation["axis_engine"])
            payload["engine_nodes"].append(
                {
                    "id": item.component_id,
                    "kind": runtime_kind(item.kind),
                    "teaching_kind": item.kind,
                    "label": item.label,
                    "enabled": bool(item.enabled),
                    "params": params,
                    **teaching_pose_to_simulation(
                        item.pose.x_mm,
                        item.pose.y_mm,
                        item.pose.z_mm,
                        yaw,
                        item.pose.pitch_rad,
                        item.pose.roll_rad,
                        transform,
                    ),
                }
            )
        return payload


class SceneStore(QObject):
    """Mutable scene store with explicit revision and selection signals."""

    sceneChanged = Signal(object, str)
    selectionChanged = Signal(object)
    resultChanged = Signal(str, object)
    saved = Signal(str)

    SCHEMA_VERSION = 2

    def __init__(self, parent: QObject | None = None, *, start_empty: bool = False) -> None:
        super().__init__(parent)
        self.scene_id = "teaching-v2-scene"
        self.revision = 0
        self.reference = SceneReference()
        self.components: dict[str, OpticalComponent] = {}
        self.baseline_enabled = True
        self.baseline_x_mm = 0.0
        self.selected_component_id: str | None = None
        self.active_result_revision: int | None = None
        self.results: dict[str, dict[str, Any]] = {}
        self._counter = 0
        self._undo_stack: list[dict[str, Any]] = []
        self._redo_stack: list[dict[str, Any]] = []
        # Keep the store's demo-scene default for isolated callers, while the
        # live teaching centre can start with a genuinely empty optical bench.
        if start_empty:
            self.revision = 1
        else:
            self.reset_standard(emit=False)

    def reset_standard(self, *, emit: bool = True) -> None:
        if emit:
            self._record_history()
        self.components.clear()
        self._counter = 0
        self._add_raw("laser", "激光器", 0.0, 0.0, AXIS_HEIGHT_MM, params=default_params_for_kind("laser"))
        self._add_raw(
            "lens",
            "L1 透镜",
            24.0,
            0.0,
            AXIS_HEIGHT_MM,
            params={**default_params_for_kind("lens"), "focal_length_mm": 50.0, "focal_mm": 50.0, "diameter_mm": 12.7},
        )
        self._add_raw(
            "lens",
            "L2 透镜",
            48.0,
            0.0,
            AXIS_HEIGHT_MM,
            params={**default_params_for_kind("lens"), "focal_length_mm": 12.0, "focal_mm": 12.0, "diameter_mm": 8.0},
        )
        self._add_raw("fiber", "五轴光纤架", 72.0, 0.0, AXIS_HEIGHT_MM, params=default_params_for_kind("fiber"))
        self.selected_component_id = "lens-002"
        self.revision = 1
        self.results.clear()
        self.active_result_revision = None
        if emit:
            self._emit_changed("恢复标准教学实验台")

    def apply_optical_scheme(self, lens_count: int) -> None:
        """Replace the bench with a teaching-ready laser/lens/fiber scheme.

        The presets intentionally use the same +X propagation convention as the
        teaching canvas.  They are coherent starting systems, not a promise of
        a finished production design.
        """
        count = max(1, min(4, int(lens_count)))
        self._record_history()
        self.components.clear()
        self._counter = 0
        self.results.clear()
        self.active_result_revision = None
        wavelength_nm = 780.0 if count == 4 else 808.0
        laser_params = {
            **default_params_for_kind("laser"),
            "wavelength_nm": wavelength_nm,
            "power_mw": 100.0,
            "beam_radius_mm": 0.50,
        }
        self._add_raw("laser", f"{wavelength_nm:.0f} nm 半导体激光器", 0.0, 0.0, AXIS_HEIGHT_MM, params=laser_params)

        # Values are transcribed from the user's four-lens Zemax reference.
        # Earlier schemes use the leading subset so that their physical meaning
        # remains comparable while their layout stays compact on the bench.
        four_lens = (
            (20.0, 6.425, -9.892, 5.360, 12.7),
            (42.0, 4.593, 29.948, 2.426, 12.7),
            (66.0, 36.204, -4.098, 2.610, 12.7),
            (90.0, 20.383, -5.443, 5.360, 12.7),
        )
        for index, (x_mm, r1, r2, thickness, diameter) in enumerate(four_lens[:count], start=1):
            focal = (50.0, 35.0, 25.0, 18.0)[index - 1]
            self._add_raw(
                "lens",
                f"L{index} 透镜",
                x_mm,
                0.0,
                AXIS_HEIGHT_MM,
                params={
                    **default_params_for_kind("lens"),
                    "focal_length_mm": focal,
                    "focal_mm": focal,
                    "diameter_mm": diameter,
                    "material": "N-BK7",
                    "radius1_mm": r1,
                    "radius2_mm": r2,
                    "center_thickness_mm": thickness,
                    "clear_aperture_mm": diameter / 2.0,
                },
            )
        fiber_x = (58.0, 78.0, 102.0, 120.0)[count - 1]
        self._add_raw(
            "fiber",
            "单模光纤接收端",
            fiber_x,
            0.0,
            AXIS_HEIGHT_MM,
            params={**default_params_for_kind("fiber"), "mfd_um": 5.6, "na": 0.12},
        )
        self.selected_component_id = f"lens-{count + 1:03d}"
        self._touch(f"切换到{count}透镜教学方案")
        self.selectionChanged.emit(self.selected_component_id)

    def _next_id(self, kind: str) -> str:
        self._counter += 1
        return f"{kind}-{self._counter:03d}"

    def _allocate_id(self, kind: str, requested: str | None = None) -> str:
        kind = str(kind or "component")
        candidate = str(requested or "").strip()
        if candidate and not component_id_is_reserved(candidate) and candidate not in self.components:
            return candidate
        while True:
            cid = self._next_id(kind)
            if cid not in self.components and not component_id_is_reserved(cid):
                return cid

    def _add_raw(
        self,
        kind: str,
        label: str,
        x: float,
        y: float,
        z: float,
        *,
        params: dict[str, Any] | None = None,
        component_id: str | None = None,
    ) -> str:
        cid = self._allocate_id(kind, component_id)
        self.components[cid] = OpticalComponent(
            component_id=cid,
            kind=str(kind),
            label=str(label),
            pose=Pose(x, y, z),
            params=normalize_component_params(kind, params),
            category="光学器件" if kind in {"lens", "mirror"} else "实验对象",
            asset_key=str(kind),
        )
        return cid

    def add_component(
        self,
        kind: str,
        *,
        label: str | None = None,
        pose: Pose | None = None,
        params: dict[str, Any] | None = None,
    ) -> str:
        kind = str(kind).lower()
        labels = dict(PLACEABLE_KINDS)
        default_label = labels.get(kind, kind)
        if pose is None and kind == "oscilloscope":
            p = Pose(x_mm=self._next_x(), y_mm=50.0, z_mm=0.0)
        else:
            p = pose or Pose(x_mm=self._next_x())
        self._record_history()
        cid = self._add_raw(
            kind,
            label or default_label,
            p.x_mm,
            p.y_mm,
            p.z_mm,
            params=normalize_component_params(kind, params),
        )
        self._touch(f"添加{label or default_label}")
        self.select(cid)
        return cid

    def _next_x(self) -> float:
        if not self.components:
            return 0.0
        return max(c.pose.x_mm for c in self.components.values()) + 12.0

    def remove_component(self, component_id: str) -> bool:
        if component_id not in self.components:
            return False
        self._record_history()
        label = self.components[component_id].label
        del self.components[component_id]
        if self.selected_component_id == component_id:
            self.selected_component_id = None
        self._touch(f"移除{label}")
        self.selectionChanged.emit(self.selected_component_id)
        return True

    def select(self, component_id: str | None) -> None:
        selected = str(component_id) if component_id in self.components else None
        if selected == self.selected_component_id:
            return
        self.selected_component_id = selected
        self.selectionChanged.emit(selected)

    def update_pose(self, component_id: str, pose: Pose, *, reason: str = "调整器件位置") -> bool:
        component = self.components.get(component_id)
        if component is None:
            return False
        self._record_history()
        component.pose = pose.normalized()
        self._touch(reason)
        return True

    def update_param(self, component_id: str, name: str, value: Any, *, reason: str | None = None) -> bool:
        component = self.components.get(component_id)
        if component is None:
            return False
        if name in FLOAT_PARAM_NAMES:
            try:
                value = float(value)
            except (TypeError, ValueError):
                return False
        self._record_history()
        component.params[str(name)] = value
        if name == "focal_length_mm":
            component.params["focal_mm"] = value
        elif name == "focal_mm":
            component.params["focal_length_mm"] = value
        self._touch(reason or f"修改{component.label}的{name}")
        return True

    def update_params(self, component_id: str, values: dict[str, Any], *, reason: str = "应用工程规格") -> bool:
        """Atomically apply a coherent component preset and create one revision."""
        component = self.components.get(component_id)
        if component is None:
            return False
        prepared: dict[str, Any] = {}
        for name, value in dict(values or {}).items():
            if name in FLOAT_PARAM_NAMES:
                try:
                    value = float(value)
                except (TypeError, ValueError):
                    return False
            prepared[str(name)] = value
        if not prepared:
            return False
        self._record_history()
        component.params.update(prepared)
        if "focal_length_mm" in prepared:
            component.params["focal_mm"] = prepared["focal_length_mm"]
        elif "focal_mm" in prepared:
            component.params["focal_length_mm"] = prepared["focal_mm"]
        self._touch(reason)
        return True

    def set_enabled(self, component_id: str, enabled: bool) -> bool:
        component = self.components.get(component_id)
        if component is None:
            return False
        self._record_history()
        component.enabled = bool(enabled)
        self._touch(f"{'启用' if enabled else '停用'}{component.label}")
        return True

    def set_baseline(self, enabled: bool, x_mm: float | None = None) -> None:
        self._record_history()
        self.baseline_enabled = bool(enabled)
        if x_mm is not None:
            self.baseline_x_mm = float(x_mm)
        self._touch("更新基准线")

    def clear_result(self, kind: str | ResultKind) -> None:
        key = str(kind.value if isinstance(kind, ResultKind) else kind)
        if key in self.results:
            self.results.pop(key, None)
            self.resultChanged.emit(key, None)

    def apply_result(self, kind: str | ResultKind, result: dict[str, Any], *, source_revision: int) -> bool:
        """Apply only a result calculated from the current scene revision."""
        if int(source_revision) != int(self.revision):
            return False
        key = str(kind.value if isinstance(kind, ResultKind) else kind)
        payload = copy.deepcopy(dict(result))
        payload["scene_revision"] = int(source_revision)
        payload.pop("stale", None)
        self.results[key] = payload
        self.active_result_revision = int(source_revision)
        self.resultChanged.emit(key, copy.deepcopy(payload))
        return True

    def snapshot(self) -> SceneSnapshot:
        return SceneSnapshot(
            schema_version=self.SCHEMA_VERSION,
            scene_id=self.scene_id,
            revision=self.revision,
            reference=copy.deepcopy(self.reference),
            components=[c.copy() for c in self.components.values()],
            baseline_enabled=self.baseline_enabled,
            baseline_x_mm=self.baseline_x_mm,
            selected_component_id=self.selected_component_id,
            active_result_revision=self.active_result_revision,
            results=copy.deepcopy(self.results),
        )

    def to_dict(self) -> dict[str, Any]:
        return self.snapshot().to_dict()

    def to_publish_dict(self) -> dict[str, Any]:
        return self.snapshot().to_publish_dict()

    def save_json(self, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        self.saved.emit(str(target))

    def load_json(self, path: str | Path) -> None:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        self.restore_dict(data)
        self.saved.emit(str(path))

    def restore_dict(self, data: dict[str, Any], *, reset_history: bool = True, reason: str = "载入教学场景") -> None:
        if int(data.get("schema_version", 0)) not in {1, self.SCHEMA_VERSION}:
            raise ValueError("不支持的教学场景版本")
        self.scene_id = str(data.get("scene_id") or self.scene_id)
        reference_payload = {**asdict(SceneReference()), **dict(data.get("reference") or {})}
        self.reference = SceneReference(**_filter_fields(SceneReference, reference_payload))
        self.components.clear()
        self._counter = 0
        id_remap: dict[str, str] = {}
        for item in data.get("components") or []:
            raw_pose = dict(item.get("pose") or {})
            if any(key in raw_pose for key in ("yaw_deg", "pitch_deg", "roll_deg")):
                pose = Pose.from_degrees(
                    raw_pose.get("x_mm", 0.0),
                    raw_pose.get("y_mm", 0.0),
                    raw_pose.get("z_mm", AXIS_HEIGHT_MM),
                    raw_pose.get("yaw_deg", 0.0),
                    raw_pose.get("pitch_deg", 0.0),
                    raw_pose.get("roll_deg", 0.0),
                ).normalized()
            else:
                pose = Pose(**_filter_fields(Pose, {**asdict(Pose()), **raw_pose})).normalized()
            requested = str(item.get("component_id") or "")
            cid = self._allocate_id(str(item.get("kind") or "component"), requested or None)
            if requested:
                id_remap[requested] = cid
            self.components[cid] = OpticalComponent(
                component_id=cid,
                kind=str(item.get("kind") or "lens"),
                label=str(item.get("label") or cid),
                pose=pose,
                params=normalize_component_params(str(item.get("kind") or "lens"), dict(item.get("params") or {})),
                enabled=bool(item.get("enabled", True)),
                category=str(item.get("category") or "光学器件"),
                asset_key=str(item.get("asset_key") or item.get("kind") or ""),
            )
            try:
                self._counter = max(self._counter, int(cid.rsplit("-", 1)[-1]))
            except (ValueError, IndexError):
                pass
        self.revision = max(1, int(data.get("revision", 1)))
        self.baseline_enabled = bool(data.get("baseline_enabled", True))
        self.baseline_x_mm = float(data.get("baseline_x_mm", 0.0))
        raw_selected = data.get("selected_component_id")
        mapped_selected = id_remap.get(raw_selected, raw_selected)
        self.selected_component_id = mapped_selected if mapped_selected in self.components else None
        self.active_result_revision = data.get("active_result_revision")
        self.results = copy.deepcopy(dict(data.get("results") or {}))
        if reset_history:
            self._undo_stack.clear()
            self._redo_stack.clear()
        self._emit_changed(reason)
        self.selectionChanged.emit(self.selected_component_id)

    def clear_scene(self) -> None:
        if not self.components:
            return
        self._record_history()
        self.components.clear()
        self.selected_component_id = None
        self._counter = 0
        self.results.clear()
        self.active_result_revision = None
        self._touch("清空教学台")
        self.selectionChanged.emit(None)

    def can_undo(self) -> bool:
        return bool(self._undo_stack)

    def can_redo(self) -> bool:
        return bool(self._redo_stack)

    def undo(self) -> bool:
        if not self._undo_stack:
            return False
        self._redo_stack.append(copy.deepcopy(self.to_dict()))
        state = self._undo_stack.pop()
        self.restore_dict(state, reset_history=False, reason="撤销")
        return True

    def redo(self) -> bool:
        if not self._redo_stack:
            return False
        self._undo_stack.append(copy.deepcopy(self.to_dict()))
        state = self._redo_stack.pop()
        self.restore_dict(state, reset_history=False, reason="重做")
        return True

    def _record_history(self) -> None:
        self._undo_stack.append(copy.deepcopy(self.to_dict()))
        if len(self._undo_stack) > 50:
            self._undo_stack.pop(0)
        self._redo_stack.clear()

    def _touch(self, reason: str) -> None:
        self.revision += 1
        for key, payload in self.results.items():
            if str(key) == ResultKind.GEOMETRY.value:
                continue
            payload["stale"] = True
        self.active_result_revision = None
        self._emit_changed(reason)

    def _emit_changed(self, reason: str) -> None:
        self.sceneChanged.emit(self.snapshot(), str(reason))


def component_kind_label(kind: str) -> str:
    return dict(PLACEABLE_KINDS).get(str(kind), str(kind))


__all__ = [
    "CCD_SENSOR_HEIGHT_MM",
    "CCD_SENSOR_WIDTH_MM",
    "ComponentKind",
    "DEFAULT_BEAM_RADIUS_MM",
    "KIND_PARAM_SPECS",
    "PLACEABLE_KINDS",
    "TEACHING_KIND_MIME",
    "OPTIONAL_UNSET_PARAM_NAMES",
    "OpticalComponent",
    "PITCH_DEG_MAX",
    "PITCH_RAD_MAX",
    "Pose",
    "RESERVED_COMPONENT_IDS",
    "ResultKind",
    "SceneReference",
    "SceneSnapshot",
    "compile_component_params",
    "normalize_component_params",
    "runtime_kind",
    "SceneStore",
    "component_id_is_reserved",
    "component_kind_label",
]

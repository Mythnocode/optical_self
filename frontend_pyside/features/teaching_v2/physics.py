"""Physics boundary for Teaching Center V2.

The UI talks to this small gateway instead of importing solver internals.  A
formal adapter is provided for the existing ``teaching_runtime`` engine.  If
that engine is unavailable, the adapter returns an explicit error; it never
silently substitutes a fake result for a requested formal computation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
import time
import uuid
from typing import Any, Iterable, Protocol

from .coordinates import (
    DEFAULT_TRANSFORM,
    FrameTransform,
    beam_direction_teaching,
    engine_orientation_fields,
    mm_per_scene_unit,
    physical_scene_scale_mm,
    transform_from_reference,
)
from .model import (
    MIRROR_RUNTIME_FOLD_DEG,
    OpticalComponent,
    SceneSnapshot,
    compile_component_params,
    runtime_kind,
)


FORMAL_ANALYSES = frozenset({"raytrace", "spot", "field", "wavefront", "coupling"})
ANALYSIS_ALIASES = {"wave": "coupling", "formal": "raytrace", "geometry": "raytrace"}
ENGINE_ANALYSES: dict[str, tuple[str, ...]] = {
    "raytrace": ("raytrace",),
    "spot": ("raytrace", "spot"),
    "field": ("raytrace", "exit_pupil"),
    "wavefront": ("raytrace", "exit_pupil", "wavefront_quality"),
    "coupling": ("raytrace", "exit_pupil", "coupling"),
}


@dataclass(frozen=True, slots=True)
class ApplicabilityReport:
    allowed: bool
    messages: tuple[str, ...] = ()
    estimated_seconds: float = 0.0


@dataclass(frozen=True, slots=True)
class RaySegment:
    start_teaching_mm: tuple[float, float, float]
    end_teaching_mm: tuple[float, float, float]
    power_fraction: float = 1.0


@dataclass(frozen=True, slots=True)
class PhysicsRequest:
    scene: SceneSnapshot
    analysis: str
    transform: FrameTransform = DEFAULT_TRANSFORM


@dataclass(frozen=True, slots=True)
class PhysicsResult:
    success: bool
    analysis: str
    scene_revision: int
    source: str
    status: str
    metrics: dict[str, Any] = field(default_factory=dict)
    rays: tuple[RaySegment, ...] = ()
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    elapsed_ms: float = 0.0
    artifacts: dict[str, dict[str, Any]] = field(default_factory=dict)


class PhysicsGateway(Protocol):
    def inspect(self, scene: SceneSnapshot, analysis: str = "") -> ApplicabilityReport: ...
    def compute(self, request: PhysicsRequest) -> PhysicsResult: ...


def canonicalize_analysis(name: str) -> str:
    key = str(name or "raytrace").strip().lower() or "raytrace"
    return ANALYSIS_ALIASES.get(key, key)


def _enabled_components(scene: SceneSnapshot) -> list[OpticalComponent]:
    return [item for item in scene.components if item.enabled]


def _fibers(enabled: list[OpticalComponent]) -> list[OpticalComponent]:
    return [item for item in enabled if item.kind == "fiber"]


def _imaging_terminals(enabled: list[OpticalComponent]) -> list[OpticalComponent]:
    return [item for item in enabled if item.kind in {"fiber", "ccd", "imaging_camera"}]


EMPTY_BEAM_MESSAGE = "顺序追迹没有返回光线。请看画面上的示意红线；若器件已对齐仍无光线，再检查引擎。"
INVALID_METRIC_MESSAGE = "计算结果不是有效数字。光线可能没有打到接收面。"
LASER_TILT_WARN_DEG = 5.0
OPTIC_TILT_WARN_DEG = 6.0
RECEIVER_OFFSET_WARN_MM = 2.0


def _acute_deg(angle_deg: float) -> float:
    wrapped = abs(float(angle_deg)) % 360.0
    return min(wrapped, 360.0 - wrapped)


def beam_miss_notes(scene: SceneSnapshot) -> tuple[str, ...]:
    """Describe optics the current beam would pass by, for 五轴失配 teaching."""
    enabled = _enabled_components(scene)
    laser = next((item for item in enabled if item.kind == "laser"), None)
    if laser is None:
        return ()
    notes: list[str] = []
    beam_y = float(laser.pose.y_mm)
    beam_z = float(laser.pose.z_mm)
    for item in enabled:
        if item.kind == "laser":
            continue
        radius = _preview_capture_radius_mm(item)
        dy = float(item.pose.y_mm) - beam_y
        dz = float(item.pose.z_mm) - beam_z
        if abs(dz) > radius + 0.5:
            side = "下方" if dz < 0 else "上方"
            notes.append(
                f"{item.label}在光束{side}（离台 {item.pose.z_mm:.1f} mm，光束高度 {beam_z:.1f} mm）。"
                "这是位置失配：示意红线会从旁边过去，不是程序坏了。"
            )
        elif abs(dy) > radius + 0.5:
            notes.append(
                f"{item.label}横向偏离光束 {abs(dy):.1f} mm（口径约 {radius:.1f} mm）。"
                "这是位置失配：示意红线会从旁边过去，不是程序坏了。"
            )
    return tuple(notes)


def setup_warnings(scene: SceneSnapshot) -> tuple[str, ...]:
    """Hints shown while editing.  These do not block optical calculation."""
    notes: list[str] = []
    notes.extend(beam_miss_notes(scene))
    enabled = _enabled_components(scene)
    table_z = float(transform_from_reference(scene.reference).axis_height_mm)
    for item in enabled:
        yaw = _acute_deg(item.pose.yaw_deg)
        pitch = abs(float(item.pose.pitch_deg))
        if item.kind == "laser" and (yaw > LASER_TILT_WARN_DEG or pitch > LASER_TILT_WARN_DEG):
            notes.append(
                f"{item.label}倾斜较大（绕Z {item.pose.yaw_deg:.1f}°，绕Y {item.pose.pitch_deg:.1f}°），"
                "后面的器件可能接不到光。"
            )
        elif item.kind in {"lens", "mirror", "fiber", "ccd"} and (yaw > OPTIC_TILT_WARN_DEG or pitch > OPTIC_TILT_WARN_DEG):
            notes.append(
                f"{item.label}倾斜较大（绕Z {item.pose.yaw_deg:.1f}°，绕Y {item.pose.pitch_deg:.1f}°），"
                "光学计算可能没有光线或结果无效。"
            )
        if item.kind == "fiber" and (
            abs(item.pose.y_mm) > RECEIVER_OFFSET_WARN_MM
            or abs(item.pose.z_mm - table_z) > RECEIVER_OFFSET_WARN_MM
        ):
            notes.append(f"{item.label}偏离光轴较多，耦合计算可能失败或效率极低。")
    seen: list[str] = []
    for note in notes:
        if note not in seen:
            seen.append(note)
    return tuple(seen)


def inspect_scene(scene: SceneSnapshot, analysis: str = "") -> ApplicabilityReport:
    enabled = _enabled_components(scene)
    lasers = [item for item in enabled if item.kind == "laser"]
    if not lasers:
        return ApplicabilityReport(False, ("请先放一个启用的激光器。",), 0.0)
    if len(lasers) > 1:
        return ApplicabilityReport(False, ("这一版只支持一个启用的激光器。",), 0.0)
    requested = canonicalize_analysis(analysis) if analysis else ""
    if requested in {"coupling", "field", "wavefront"} and not _fibers(enabled):
        return ApplicabilityReport(False, ("计算耦合、端面场或波前需要启用的光纤，示意不会填写效率。",), 0.0)
    if requested in {"spot"} and not _imaging_terminals(enabled):
        return ApplicabilityReport(False, ("计算光斑需要 CCD 或光纤。",), 0.0)
    messages = ["可以计算。", "光路示意随拖动更新；光斑和耦合请用「光学计算」。"]
    if requested in {"coupling", "field", "wavefront"}:
        messages.append("已接光纤。耦合效率只来自光学计算。")
    elif requested == "spot":
        messages.append("已接成像终端。")
    messages.extend(setup_warnings(scene))
    return ApplicabilityReport(True, tuple(messages), 1.5)


def ray_segment_to_dict(ray: RaySegment) -> dict[str, Any]:
    return {
        "start": list(ray.start_teaching_mm),
        "end": list(ray.end_teaching_mm),
        "power_fraction": float(ray.power_fraction),
    }


def _unit(vector: tuple[float, float, float]) -> tuple[float, float, float]:
    length = math.sqrt(sum(value * value for value in vector))
    if length < 1.0e-12:
        return (1.0, 0.0, 0.0)
    return (vector[0] / length, vector[1] / length, vector[2] / length)


def _cross(a: tuple[float, float, float], b: tuple[float, float, float]) -> tuple[float, float, float]:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _perp_basis(direction: tuple[float, float, float]) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    axis = _unit(direction)
    helper = (0.0, 1.0, 0.0) if abs(axis[0]) > 0.9 else (1.0, 0.0, 0.0)
    lateral = _unit(_cross(axis, helper))
    vertical = _unit(_cross(axis, lateral))
    return lateral, vertical


def _thin_lens_redirect(
    direction: tuple[float, float, float],
    hit: tuple[float, float, float],
    lens: OpticalComponent,
) -> tuple[float, float, float]:
    """Near-axis sketch only.  Does not produce coupling or wave metrics."""
    focal = float(lens.params.get("focal_length_mm") or lens.params.get("focal_mm") or 0.0)
    if abs(focal) < 1.0:
        return _unit(direction)
    axis = _unit(beam_direction_teaching(lens.pose.yaw_rad, lens.pose.pitch_rad, lens.pose.roll_rad))
    center = (lens.pose.x_mm, lens.pose.y_mm, lens.pose.z_mm)
    rel = (hit[0] - center[0], hit[1] - center[1], hit[2] - center[2])
    along = rel[0] * axis[0] + rel[1] * axis[1] + rel[2] * axis[2]
    height = (rel[0] - along * axis[0], rel[1] - along * axis[1], rel[2] - along * axis[2])
    incoming = _unit(direction)
    parallel = incoming[0] * axis[0] + incoming[1] * axis[1] + incoming[2] * axis[2]
    perp = (
        incoming[0] - parallel * axis[0],
        incoming[1] - parallel * axis[1],
        incoming[2] - parallel * axis[2],
    )
    out_perp = (perp[0] - height[0] / focal, perp[1] - height[1] / focal, perp[2] - height[2] / focal)
    return _unit(
        (
            parallel * axis[0] + out_perp[0],
            parallel * axis[1] + out_perp[1],
            parallel * axis[2] + out_perp[2],
        )
    )


def _preview_fan_offsets(laser: OpticalComponent) -> tuple[tuple[float, float, float], ...]:
    radius = max(0.25, float(laser.params.get("beam_radius_mm") or 0.72) * 0.65)
    lateral, vertical = _perp_basis(
        beam_direction_teaching(laser.pose.yaw_rad, laser.pose.pitch_rad, laser.pose.roll_rad)
    )
    offsets = [(0.0, 0.0, 0.0)]
    for index in range(6):
        angle = index * math.tau / 6.0
        uy = math.cos(angle) * radius
        uz = math.sin(angle) * radius
        offsets.append(
            (
                lateral[0] * uy + vertical[0] * uz,
                lateral[1] * uy + vertical[1] * uz,
                lateral[2] * uy + vertical[2] * uz,
            )
        )
    return tuple(offsets)


def _reflect(incident: tuple[float, float, float], normal: tuple[float, float, float]) -> tuple[float, float, float]:
    incoming = _unit(incident)
    face = _unit(normal)
    dot = incoming[0] * face[0] + incoming[1] * face[1] + incoming[2] * face[2]
    return (
        incoming[0] - 2.0 * dot * face[0],
        incoming[1] - 2.0 * dot * face[1],
        incoming[2] - 2.0 * dot * face[2],
    )


def _mirror_face_normal(component: OpticalComponent) -> tuple[float, float, float]:
    """Runtime yaw=0 already means a 45° fold; meshes must not pre-rotate."""
    return beam_direction_teaching(
        component.pose.yaw_rad + math.radians(MIRROR_RUNTIME_FOLD_DEG),
        component.pose.pitch_rad,
        component.pose.roll_rad,
    )


def _preview_capture_radius_mm(component: OpticalComponent) -> float:
    """Radius that the geometry preview will treat as an intercept."""
    params = component.params
    if component.kind == "fiber":
        return 1.6
    if component.kind == "ccd":
        width = float(params.get("sensor_width_mm") or params.get("active_area_mm") or 4.968)
        height = float(params.get("sensor_height_mm") or params.get("active_area_mm") or 3.726)
        return 0.5 * math.hypot(max(width, 0.4), max(height, 0.4))
    if component.kind == "laser":
        return float(params.get("beam_radius_mm") or 0.72)
    clear_radius = float(params.get("clear_aperture_mm") or 0.0)
    if clear_radius > 0.05:
        return clear_radius
    diameter = float(params.get("diameter_mm") or 12.7)
    return max(diameter, 1.0) * 0.5


def _trace_preview_path(
    position: tuple[float, float, float],
    direction: tuple[float, float, float],
    remaining: list[OpticalComponent],
    power: float,
) -> list[RaySegment]:
    rays: list[RaySegment] = []
    pending = list(remaining)
    while pending:
        best: OpticalComponent | None = None
        best_along: float | None = None
        for node in pending:
            delta = (
                node.pose.x_mm - position[0],
                node.pose.y_mm - position[1],
                node.pose.z_mm - position[2],
            )
            distance = math.sqrt(sum(value * value for value in delta))
            if distance < 0.05:
                continue
            along = delta[0] * direction[0] + delta[1] * direction[1] + delta[2] * direction[2]
            if along < 0.2:
                continue
            perp = math.sqrt(max(0.0, distance * distance - along * along))
            if perp > _preview_capture_radius_mm(node) + 0.25:
                continue
            if best_along is None or along < best_along:
                best = node
                best_along = along
        if best is None or best_along is None:
            escape = (
                position[0] + direction[0] * 16.0,
                position[1] + direction[1] * 16.0,
                position[2] + direction[2] * 16.0,
            )
            rays.append(RaySegment(position, escape, power))
            break
        target = (
            position[0] + direction[0] * best_along,
            position[1] + direction[1] * best_along,
            position[2] + direction[2] * best_along,
        )
        rays.append(RaySegment(position, target, power))
        if best.kind in {"fiber", "ccd"}:
            break
        if best.kind == "mirror":
            direction = _unit(_reflect(direction, _mirror_face_normal(best)))
        elif best.kind == "lens":
            direction = _thin_lens_redirect(direction, target, best)
        elif best.kind == "isolator":
            loss_db = float(best.params.get("insertion_loss_db") or 0.4)
            power *= 10.0 ** (-max(loss_db, 0.0) / 10.0)
        position = target
        pending = [item for item in pending if item.component_id != best.component_id]
    return rays


def compute_geometry_preview(scene: SceneSnapshot, transform: FrameTransform) -> PhysicsResult:
    """Fast, deterministic preview used while dragging.

    This is visual guidance only.  Provenance is always ``geometry_preview`` and
    it must not be presented as a coupling-efficiency or wave-optics result.
    The beam stays on its current ray, only intercepts apertures it actually
    hits, stops at the first fiber/CCD, and folds on mirrors with the same 45°
    convention as the runtime.  A small near-axis fan and thin-lens fold are
    for display; they do not fill coupling numbers.
    """
    t0 = time.perf_counter()
    enabled = _enabled_components(scene)
    source = next((item for item in enabled if item.kind == "laser"), enabled[0] if enabled else None)
    rays: list[RaySegment] = []
    if source is not None:
        remaining = [item for item in enabled if item.component_id != source.component_id]
        direction = _unit(
            beam_direction_teaching(source.pose.yaw_rad, source.pose.pitch_rad, source.pose.roll_rad)
        )
        origin = (source.pose.x_mm, source.pose.y_mm, source.pose.z_mm)
        offsets = _preview_fan_offsets(source) if source.kind == "laser" else ((0.0, 0.0, 0.0),)
        for index, offset in enumerate(offsets):
            start = (origin[0] + offset[0], origin[1] + offset[1], origin[2] + offset[2])
            power = 1.0 if index == 0 else 0.42
            rays.extend(_trace_preview_path(start, direction, remaining, power))
    receiver = next((item for item in enabled if item.kind in {"fiber", "ccd"}), None)
    lens_count = sum(item.kind == "lens" for item in enabled)
    table_z = float(transform.axis_height_mm)
    if receiver is None:
        message = "等待接收端"
        axial_span_mm = 0.0
        lateral_mm = 0.0
        height_offset_mm = 0.0
    else:
        last_lens = next((item for item in reversed(enabled) if item.kind == "lens"), None)
        origin_x = last_lens.pose.x_mm if last_lens is not None else (source.pose.x_mm if source is not None else 0.0)
        axial_span_mm = abs(receiver.pose.x_mm - origin_x)
        lateral_mm = abs(receiver.pose.y_mm)
        height_offset_mm = abs(receiver.pose.z_mm - table_z)
        message = "光路示意已更新"
    return PhysicsResult(
        success=True,
        analysis="geometry",
        scene_revision=scene.revision,
        source="geometry_preview",
        status="completed",
        metrics={
            "lens_count": lens_count,
            "axial_span_mm": axial_span_mm,
            "receiver_lateral_mm": lateral_mm,
            "receiver_height_offset_mm": height_offset_mm,
            "message": message,
        },
        rays=tuple(rays),
        elapsed_ms=(time.perf_counter() - t0) * 1000.0,
    )


def collimated_biconvex_focus_offset_mm(
    focal_mm: float,
    *,
    thickness_mm: float = 2.0,
    index: float = 1.5168,
) -> float:
    """Paraxial distance from optical center for the runtime focal-equivalent lens."""
    radius = 2.0 * max(float(index) - 1.0, 0.05) * abs(float(focal_mm))
    phi = (float(index) - 1.0) * (
        2.0 / radius - float(thickness_mm) * (float(index) - 1.0) / (float(index) * radius * radius)
    )
    if abs(phi) < 1.0e-12:
        return float(focal_mm)
    return 1.0 / phi


def _axial_span_mm(scene: SceneSnapshot) -> float:
    enabled = _enabled_components(scene)
    if not enabled:
        return 80.0
    xs = [item.pose.x_mm for item in enabled]
    return max(xs) - min(xs) + 20.0


def snapshot_to_physical_scene(scene: SceneSnapshot):
    """Compile a teaching snapshot into the runtime scene with 1 mm per scene unit."""
    from teaching_runtime.physical_scene import TeachingPhysicalNode, TeachingPhysicalScene

    max_length, scene_width = physical_scene_scale_mm(_axial_span_mm(scene))
    laser = next((item for item in scene.components if item.kind == "laser" and item.enabled), None)
    nodes = []
    for item in scene.components:
        params, _node_warnings = compile_component_params(item.kind, item.params, label=item.label)
        yaw = item.pose.yaw_rad
        if item.kind == "mirror":
            yaw = yaw + math.radians(MIRROR_RUNTIME_FOLD_DEG)
        orientation = engine_orientation_fields(
            yaw,
            item.pose.pitch_rad,
            item.pose.roll_rad,
            transform_from_reference(scene.reference),
        )
        params = {**params, **orientation}
        if item.kind == "laser":
            params["source_direction_engine"] = list(orientation["axis_engine"])
        nodes.append(
            TeachingPhysicalNode(
                node_id=item.component_id,
                kind=runtime_kind(item.kind),
                label=item.label,
                scene_x=float(item.pose.x_mm),
                scene_y=float(item.pose.y_mm),
                height_mm=float(item.pose.z_mm),
                yaw_deg=float(item.pose.yaw_deg),
                pitch_deg=float(item.pose.pitch_deg),
                roll_deg=float(item.pose.roll_deg),
                enabled=bool(item.enabled),
                params=params,
            )
        )
    wavelength = float((laser.params if laser else {}).get("wavelength_nm", 780.0))
    power = float((laser.params if laser else {}).get("power_mw", 100.0))
    compiled = TeachingPhysicalScene(
        nodes=tuple(nodes),
        wavelength_nm=wavelength,
        input_power_mw=power,
        max_system_length_mm=max_length,
        scene_width_units=scene_width,
        generation=int(scene.revision),
        trace_quality="settled",
    )
    return compiled


def rays_from_trace(trace: Any) -> tuple[RaySegment, ...]:
    rays: list[RaySegment] = []
    for path in getattr(trace, "paths", ()) or ():
        points = list(getattr(path, "points", ()) or ())
        power = float(getattr(path, "power_fraction", 1.0))
        for first, second in zip(points, points[1:]):
            rays.append(
                RaySegment(
                    (float(first.scene_x), float(first.scene_y), float(first.height_mm)),
                    (float(second.scene_x), float(second.scene_y), float(second.height_mm)),
                    power,
                )
            )
    return tuple(rays)


def _error_text(item: Any) -> str:
    message = getattr(item, "message", None)
    if message:
        return str(message)
    return str(item)


def _flatten_engine_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    flat = dict(metrics or {})
    for key, value in list((metrics or {}).items()):
        text = str(key)
        if "." in text:
            flat[text.rsplit(".", 1)[-1]] = value
    return flat


METRIC_DISPLAY_ALIASES: dict[str, tuple[str, ...]] = {
    "strehl_ratio": ("strehl_ratio", "strehl_estimate_marechal", "best_focus_strehl_estimate"),
    "rms_waves": ("rms_waves", "wavefront_rms_waves"),
    "pv_waves": ("pv_waves", "wavefront_pv_waves"),
    "rms_spot_radius_um": ("rms_spot_radius_um", "rms_um"),
    "rms_um": ("rms_um", "rms_spot_radius_um"),
    "valid_ray_count": ("valid_ray_count",),
    "centroid_x_mm": ("centroid_x_mm",),
    "centroid_y_mm": ("centroid_y_mm",),
    "exit_pupil_width_mm": ("exit_pupil_width_mm",),
    "exit_pupil_height_mm": ("exit_pupil_height_mm",),
    "exit_pupil_rms_um": ("exit_pupil_rms_um",),
    "coupling_efficiency": ("coupling_efficiency", "total_coupling_efficiency", "mode_overlap_efficiency"),
    "mode_overlap_efficiency": ("mode_overlap_efficiency", "coupling_efficiency"),
    "total_coupling_efficiency": ("total_coupling_efficiency", "coupling_efficiency"),
}


def _is_invalid_number(value: Any) -> bool:
    try:
        return isinstance(value, (int, float)) and not math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _pick_metrics(metrics: dict[str, Any], names: Iterable[str]) -> dict[str, Any]:
    flat = _flatten_engine_metrics(metrics)
    picked: dict[str, Any] = {}
    for name in names:
        aliases = METRIC_DISPLAY_ALIASES.get(str(name), (str(name),))
        for alias in aliases:
            if alias not in flat or flat[alias] is None:
                continue
            value = flat[alias]
            try:
                if isinstance(value, (int, float)) and math.isnan(float(value)):
                    continue
            except (TypeError, ValueError):
                pass
            picked[str(name)] = value
            break
    return picked


def _image_distance_to_terminal_mm(project: Any) -> float | None:
    surfaces = list(getattr(project, "surfaces", ()) or ())
    terminal_index = next(
        (index for index, surface in enumerate(surfaces) if (getattr(surface, "metadata", None) or {}).get("terminal")),
        None,
    )
    back_index = None
    for index, surface in enumerate(surfaces):
        if (getattr(surface, "metadata", None) or {}).get("component_surface") == "back":
            back_index = index
    if terminal_index is None or back_index is None or terminal_index <= back_index:
        return None
    total = 0.0
    for surface in surfaces[back_index:terminal_index]:
        total += float(getattr(surface, "distance_to_next_mm", 0.0) or 0.0)
    return total


_IMAGE_AFTER_TERMINAL_MM = 1.0e-3


def _sequential_image_distance_mm(project: Any) -> float | None:
    """Air gap the sequential solver should add after the last vertex.

    The engine evaluates at ``last_vertex + image_distance_mm`` and requires the
    image plane to sit strictly after the exit surface.  When the terminal is
    already last, the lens-to-detector gap lives in ``distance_to_next_mm``, so
    only a tiny extra offset is applied.
    """
    surfaces = list(getattr(project, "surfaces", ()) or ())
    if not surfaces:
        return None
    last_meta = getattr(surfaces[-1], "metadata", None) or {}
    if last_meta.get("terminal"):
        return _IMAGE_AFTER_TERMINAL_MM
    return _image_distance_to_terminal_mm(project)


def _fiber_receiver_offsets_mm(scene: Any) -> tuple[float, float]:
    laser = next((node for node in scene.nodes if node.kind == "laser" and getattr(node, "enabled", True)), None)
    fiber = next((node for node in scene.nodes if node.kind == "fiber" and getattr(node, "enabled", True)), None)
    if fiber is None:
        return (0.0, 0.0)
    fiber_engine = DEFAULT_TRANSFORM.teaching_to_engine(
        (float(fiber.scene_x), float(fiber.scene_y), float(fiber.height_mm))
    )
    if laser is None:
        return (float(fiber_engine[0]), float(fiber_engine[1]))
    laser_engine = DEFAULT_TRANSFORM.teaching_to_engine(
        (float(laser.scene_x), float(laser.scene_y), float(laser.height_mm))
    )
    return (
        float(fiber_engine[0] - laser_engine[0]),
        float(fiber_engine[1] - laser_engine[1]),
    )


class FormalTeachingGateway:
    """Adapter to the existing scene-ray engine, isolated behind a protocol.

    ``engineering_request_provider`` is deliberately optional.  A teaching
    bench remains useful when it is assembled freely, but it must not pretend
    that its temporary scene prescription is identical to the engineering
    prescription.  When the teaching shell has just synchronised an
    engineering project, the provider supplies that exact project and its
    numerical options so the displayed analysis has the same calculation
    basis as formal simulation.
    """

    def __init__(
        self,
        bridge: Any | None = None,
        *,
        engineering_request_provider: Any | None = None,
    ) -> None:
        self._engineering_request_provider = engineering_request_provider
        if bridge is not None:
            self._bridge = bridge
            self._import_error = ""
            return
        try:
            from teaching_runtime.physical_scene import TeachingOpticalEngineBridge
        except Exception as exc:  # pragma: no cover - depends on deployment
            self._bridge = None
            self._import_error = str(exc)
        else:
            self._bridge = TeachingOpticalEngineBridge()
            self._import_error = ""

    def inspect(self, scene: SceneSnapshot, analysis: str = "") -> ApplicabilityReport:
        report = inspect_scene(scene, analysis)
        if self._bridge is None:
            return ApplicabilityReport(False, report.messages + (f"光学引擎不可用：{self._import_error}",), 0.0)
        return report

    def compute(self, request: PhysicsRequest) -> PhysicsResult:
        analysis = canonicalize_analysis(request.analysis)
        if self._bridge is None:
            return PhysicsResult(
                False,
                analysis,
                request.scene.revision,
                "formal_engine",
                "failed",
                errors=(f"光学引擎不可用：{self._import_error}",),
            )
        if analysis not in FORMAL_ANALYSES:
            return PhysicsResult(
                False,
                analysis,
                request.scene.revision,
                "formal_engine",
                "failed",
                errors=(f"不支持的计算类型：{analysis}",),
            )
        report = self.inspect(request.scene, analysis)
        if not report.allowed:
            return PhysicsResult(
                False,
                analysis,
                request.scene.revision,
                "formal_engine",
                "blocked",
                errors=report.messages,
            )
        try:
            physical = snapshot_to_physical_scene(request.scene)
            scale = mm_per_scene_unit(physical.max_system_length_mm, physical.scene_width_units)
            if abs(scale - 1.0) > 1.0e-9:
                return PhysicsResult(
                    False,
                    analysis,
                    request.scene.revision,
                    "formal_engine",
                    "failed",
                    errors=(f"教学毫米未能按 1:1 进入光学引擎（scale={scale:.6g}）。",),
                )
            trace = self._bridge.trace(physical)
            rays = rays_from_trace(trace)
            empty_beam = not rays
            miss_notes = beam_miss_notes(request.scene)
            setup_notes = setup_warnings(request.scene)
            if empty_beam and miss_notes:
                ray_status = "missed"
            elif trace.success and not empty_beam:
                ray_status = "completed"
            else:
                ray_status = "failed"
            ray_errors = [_error_text(item) for item in (getattr(trace, "errors", ()) or ())]
            if empty_beam and ray_status == "failed" and EMPTY_BEAM_MESSAGE not in ray_errors:
                ray_errors.append(EMPTY_BEAM_MESSAGE)
            if ray_status == "missed":
                ray_errors = []
            ray_artifact = {
                "source": "formal_raytrace",
                "status": ray_status,
                "metrics": {
                    "sample_count": getattr(trace, "sample_count", 0),
                    "path_count": len(getattr(trace, "paths", ()) or ()),
                    "solver": "scene_ray_tree",
                    "mm_per_scene_unit": scale,
                },
                "rays": [ray_segment_to_dict(ray) for ray in rays],
                "errors": ray_errors,
                "warnings": list(dict.fromkeys(list(getattr(trace, "warnings", ()) or ()) + list(setup_notes))),
            }
            artifacts: dict[str, dict[str, Any]] = {"raytrace": ray_artifact}
            engineering_mode = bool(self._engineering_request())
            if ray_status != "completed" and not (engineering_mode and analysis != "raytrace"):
                miss_success = ray_status == "missed" and analysis == "raytrace"
                return PhysicsResult(
                    miss_success,
                    analysis,
                    request.scene.revision,
                    "formal_engine",
                    ray_status,
                    metrics=dict(ray_artifact["metrics"]),
                    rays=rays,
                    warnings=tuple(dict.fromkeys(ray_artifact["warnings"])),
                    errors=() if miss_success else (tuple(ray_errors) or ("光线追迹失败。",)),
                    elapsed_ms=float(getattr(trace, "elapsed_ms", 0.0)),
                    artifacts=artifacts,
                )
            if analysis != "raytrace":
                artifacts.update(self._evaluate_formal_analysis(analysis, physical, request.scene))
            layer = artifacts.get(analysis, ray_artifact)
            success = str(layer.get("status")) == "completed"
            errors = tuple(layer.get("errors") or ())
            warnings = tuple(trace.warnings) + tuple(layer.get("warnings") or ())
            if ray_status != "completed" and engineering_mode:
                warnings += ("教学几何光路未完成；正式指标来自已同步工程处方。",)
            return PhysicsResult(
                success=success,
                analysis=analysis,
                scene_revision=request.scene.revision,
                source="formal_engine",
                status="completed" if success else "failed",
                metrics=dict(layer.get("metrics") or {}),
                rays=rays,
                warnings=warnings,
                errors=errors,
                elapsed_ms=float(layer.get("elapsed_ms", getattr(trace, "elapsed_ms", 0.0)) or 0.0),
                artifacts=artifacts,
            )
        except Exception as exc:
            return PhysicsResult(
                False,
                analysis,
                request.scene.revision,
                "formal_engine",
                "failed",
                errors=(str(exc),),
            )

    def _engineering_request(self) -> dict[str, Any] | None:
        provider = self._engineering_request_provider
        if not callable(provider):
            return None
        try:
            value = provider()
        except Exception:
            # A stale or unavailable shared project must not block a valid
            # teaching-scene calculation.  The returned artifact will say that
            # it is not comparable to the engineering result.
            return None
        return dict(value) if isinstance(value, dict) else None

    def _evaluate_formal_analysis(
        self,
        analysis: str,
        scene: Any,
        snapshot: SceneSnapshot | None = None,
    ) -> dict[str, dict[str, Any]]:
        engineering_request = self._engineering_request()
        custom = getattr(self._bridge, "evaluate_analyses", None)
        # A test/demo bridge may expose a scene-only shortcut.  It is useful
        # for a free teaching bench, but it must never supersede a synchronised
        # engineering prescription.
        if callable(custom) and not engineering_request:
            payload = custom(analysis, scene)
            if isinstance(payload, dict):
                return payload
        compile_project = getattr(self._bridge, "compile_project", None)
        engine = getattr(self._bridge, "engine", None)
        if not callable(compile_project) or engine is None or not hasattr(engine, "evaluate"):
            return {
                analysis: {
                    "source": "formal_engine",
                    "status": "failed",
                    "errors": ["光学引擎未提供 compile_project / evaluate 接口。"],
                }
            }
        try:
            from shared_contracts.project import ReceiverSnapshot
            from shared_contracts.simulation import SimulationRequest

            engineering_mode = bool(engineering_request and engineering_request.get("project"))
            if engineering_mode:
                from shared_contracts.project import ProjectSnapshot

                project_payload = dict(engineering_request["project"])
                # The UI keeps the numerical contract beside the serialised
                # project.  It is intentionally not part of the strict engine
                # project schema.
                project_payload.pop("calculation_contract", None)
                project = ProjectSnapshot.model_validate(project_payload)
                options = dict(engineering_request.get("options") or {})
                precision = str(engineering_request.get("precision") or "standard")
                calculation_scope = "engineering_project"
                comparison_note = "与当前仿真工程同处方、同数值配置"
            else:
                project, options = compile_project(scene)
                precision = "standard"
                calculation_scope = "teaching_scene"
                comparison_note = "教学台场景已改动，不能直接与工程仿真指标比较"

            sequential_image = _sequential_image_distance_mm(project)
            fiber = next((node for node in scene.nodes if node.kind == "fiber" and node.enabled), None)
            if not engineering_mode and analysis in {"coupling", "field", "wavefront"}:
                if fiber is None:
                    return {
                        analysis: {
                            "source": "formal_engine",
                            "status": "failed",
                            "errors": ["耦合 / 场 / 波前需要启用的光纤终端，不会写入假效率。"],
                        }
                    }
                params = dict(fiber.params)
                offset_x_mm, offset_y_mm = _fiber_receiver_offsets_mm(scene)
                receiver = ReceiverSnapshot(
                    na_x=float(params.get("na", 0.12)),
                    na_y=float(params.get("na", 0.12)),
                    mode_field_diameter_x_um=float(params.get("mfd_um", 5.6)),
                    mode_field_diameter_y_um=float(params.get("mfd_um", 5.6)),
                    offset_x_mm=offset_x_mm,
                    offset_y_mm=offset_y_mm,
                    receiver_type="single_mode_fiber",
                    mode_model=str(params.get("mode_model", "gaussian")),
                )
                updates: dict[str, Any] = {"receiver": receiver}
                if sequential_image is not None:
                    updates["image_distance_mm"] = float(sequential_image)
                project = project.model_copy(update=updates)
            elif not engineering_mode and analysis == "spot":
                terminals = [
                    node
                    for node in scene.nodes
                    if node.enabled and node.kind in {"fiber", "imaging_camera", "ccd"}
                ]
                if not terminals:
                    return {
                        analysis: {
                            "source": "formal_engine",
                            "status": "failed",
                            "errors": ["光斑 / 成像需要 CCD 或光纤终端。"],
                        }
                    }
                if sequential_image is not None:
                    project = project.model_copy(update={"image_distance_mm": float(sequential_image)})
            requested = list(ENGINE_ANALYSES[analysis])
            result = engine.evaluate(
                SimulationRequest(
                    request_id=f"teaching-v2-{uuid.uuid4().hex}",
                    project=project,
                    analyses=requested,
                    precision=precision,
                    options=options,
                )
            )
            errors = [_error_text(item) for item in (result.errors or [])]
            if result.status != "completed":
                return {
                    analysis: {
                        "source": "formal_engine",
                        "status": "failed",
                        "errors": errors or [f"光学计算未完成（status={result.status}）。"],
                        "warnings": list(result.warnings or []),
                    }
                }
            metrics = dict(result.metrics or {})
            display_keys = {
                "spot": ("rms_spot_radius_um", "rms_um", "valid_ray_count", "centroid_x_mm", "centroid_y_mm"),
                "field": ("exit_pupil_width_mm", "exit_pupil_height_mm", "exit_pupil_rms_um"),
                "wavefront": ("strehl_ratio", "rms_waves", "pv_waves", "wavefront_rms_waves"),
                "coupling": ("coupling_efficiency", "mode_overlap_efficiency", "total_coupling_efficiency"),
            }.get(analysis, ())
            picked = _pick_metrics(metrics, display_keys)
            invalid = [
                key
                for key in display_keys
                if _is_invalid_number((metrics or {}).get(key))
            ]
            if invalid:
                return {
                    analysis: {
                        "source": "formal_engine",
                        "status": "failed",
                        "metrics": picked,
                        "engine_metrics": metrics,
                        "errors": [INVALID_METRIC_MESSAGE],
                        "warnings": list(result.warnings or []),
                        "engine_analyses": requested,
                        "calculation_scope": calculation_scope,
                        "comparison_note": comparison_note,
                    }
                }
            return {
                analysis: {
                    "source": "formal_engine",
                    "status": "completed",
                    "metrics": {**picked, **({"raw_metric_count": len(metrics)} if metrics else {})},
                    "engine_metrics": metrics,
                    "warnings": list(result.warnings or []),
                    "engine_analyses": requested,
                    "calculation_scope": calculation_scope,
                    "comparison_note": comparison_note,
                    "elapsed_ms": float(getattr(result, "elapsed_ms", 0.0) or 0.0),
                }
            }
        except Exception as exc:
            return {
                analysis: {
                    "source": "formal_engine",
                    "status": "failed",
                    "errors": [str(exc)],
                }
            }


__all__ = [
    "ApplicabilityReport",
    "ENGINE_ANALYSES",
    "FORMAL_ANALYSES",
    "FormalTeachingGateway",
    "PhysicsGateway",
    "PhysicsRequest",
    "PhysicsResult",
    "RaySegment",
    "canonicalize_analysis",
    "collimated_biconvex_focus_offset_mm",
    "compute_geometry_preview",
    "inspect_scene",
    "ray_segment_to_dict",
    "rays_from_trace",
    "setup_warnings",
    "beam_miss_notes",
    "snapshot_to_physical_scene",
]

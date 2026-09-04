from __future__ import annotations

from dataclasses import dataclass, field, replace
import hashlib
import json
import math
from typing import Any, Iterable

from optical_runtime.engine import OpticalSimulationEngine
from shared_contracts.project import ProjectSnapshot, SourceSnapshot, SurfaceSnapshot
from shared_contracts.simulation import SimulationRequest, SimulationResult


@dataclass(frozen=True, slots=True)
class TeachingPhysicalNode:
    node_id: str
    kind: str
    label: str
    scene_x: float
    scene_y: float
    height_mm: float
    yaw_deg: float
    pitch_deg: float = 0.0
    roll_deg: float = 0.0
    enabled: bool = True
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TeachingPhysicalScene:
    nodes: tuple[TeachingPhysicalNode, ...]
    wavelength_nm: float
    input_power_mw: float
    max_system_length_mm: float
    scene_width_units: float = 1600.0
    scene_height_units: float = 900.0
    generation: int = 0
    trace_quality: str = "settled"

    @property
    def laser(self) -> TeachingPhysicalNode | None:
        return next((node for node in self.nodes if node.kind == "laser" and node.enabled), None)

    def fingerprint_key(self) -> str:
        """用于结果级缓存的轻量指纹：仅包含影响追迹结果的字段，不含 generation。"""
        parts: list[tuple[Any, ...]] = []
        for node in self.nodes:
            parts.append((
                node.node_id, node.kind, node.enabled,
                round(float(node.scene_x), 3), round(float(node.scene_y), 3),
                round(float(node.height_mm), 3), round(float(node.yaw_deg), 3),
                round(float(node.pitch_deg), 3), round(float(node.roll_deg), 3),
                tuple(sorted((key, str(value)) for key, value in node.params.items())),
            ))
        return repr((parts, round(float(self.wavelength_nm), 4), round(float(self.input_power_mw), 4),
                    round(float(self.max_system_length_mm), 3), float(self.scene_width_units),
                    float(self.scene_height_units)))


@dataclass(frozen=True, slots=True)
class TeachingSceneCoordinateFrame:
    laser_scene_x: float
    laser_scene_y: float
    laser_height_mm: float
    laser_yaw_deg: float
    mm_per_scene_unit: float
    axial_shift_mm: float = 0.0

    def scene_to_world(self, x: float, y: float, height_mm: float) -> tuple[float, float, float]:
        yaw = math.radians(self.laser_yaw_deg)
        dx_scene = float(x) - self.laser_scene_x
        dy_scene = float(y) - self.laser_scene_y
        forward_x, forward_y = math.cos(yaw), math.sin(yaw)
        transverse_x, transverse_y = -math.sin(yaw), math.cos(yaw)
        axial = (dx_scene * forward_x + dy_scene * forward_y) * self.mm_per_scene_unit
        lateral = (dx_scene * transverse_x + dy_scene * transverse_y) * self.mm_per_scene_unit
        vertical = float(height_mm) - self.laser_height_mm
        return lateral, vertical, axial

    def world_to_scene(self, point_mm: Iterable[float]) -> tuple[float, float, float]:
        lateral, vertical, axial = (float(v) for v in point_mm)
        yaw = math.radians(self.laser_yaw_deg)
        forward_x, forward_y = math.cos(yaw), math.sin(yaw)
        transverse_x, transverse_y = -math.sin(yaw), math.cos(yaw)
        dx_scene = (forward_x * axial + transverse_x * lateral) / self.mm_per_scene_unit
        dy_scene = (forward_y * axial + transverse_y * lateral) / self.mm_per_scene_unit
        return (
            self.laser_scene_x + dx_scene,
            self.laser_scene_y + dy_scene,
            self.laser_height_mm + vertical,
        )

    def scene_to_engine(self, x: float, y: float, height_mm: float) -> tuple[float, float, float]:
        lateral, vertical, axial = self.scene_to_world(x, y, height_mm)
        return lateral, vertical, axial - self.axial_shift_mm

    def engine_to_scene(self, point_mm: Iterable[float]) -> tuple[float, float, float]:
        lateral, vertical, axial_shifted = (float(v) for v in point_mm)
        return self.world_to_scene((lateral, vertical, axial_shifted + self.axial_shift_mm))

    def direction_to_scene_angle_deg(self, direction: Iterable[float]) -> float:
        lateral, _vertical, axial = (float(v) for v in direction)
        scene_forward = axial
        scene_transverse = lateral
        local_angle = math.degrees(math.atan2(scene_transverse, scene_forward))
        return (self.laser_yaw_deg + local_angle) % 360.0


@dataclass(frozen=True, slots=True)
class TeachingTracePoint:
    scene_x: float
    scene_y: float
    height_mm: float
    engine_point_mm: tuple[float, float, float]
    engine_direction: tuple[float, float, float]
    node_id: str | None
    surface_index: int


@dataclass(frozen=True, slots=True)
class TeachingTracePath:
    path_id: str
    parent_id: str | None
    ray_id: str
    signature: str
    power_fraction: float
    points: tuple[TeachingTracePoint, ...]
    termination_reason: str


@dataclass(frozen=True, slots=True)
class TeachingTraceRay:
    ray_id: str
    source_position_mm: tuple[float, float, float]
    source_direction: tuple[float, float, float]
    normalized_offset: tuple[float, float]
    source_weight: float
    paths: tuple[TeachingTracePath, ...]


@dataclass(frozen=True, slots=True)
class TeachingEngineTrace:
    success: bool
    generation: int
    quality: str
    sample_count: int
    paths: tuple[TeachingTracePath, ...]
    rays: tuple[TeachingTraceRay, ...]
    warnings: tuple[str, ...]
    errors: tuple[str, ...]
    elapsed_ms: float
    metadata: dict[str, Any]
    frame: TeachingSceneCoordinateFrame | None


@dataclass(slots=True)
class _SurfaceBuild:
    desired_z_mm: float
    center_x_mm: float
    center_y_mm: float
    radius_mm: float | None
    surface_type: str
    material_before: str
    material_after: str
    clear_aperture_mm: float | None
    tilt_x_deg: float
    tilt_y_deg: float
    tilt_z_deg: float
    metadata: dict[str, Any]
    conic: float = 0.0
    asphere_a2: float = 0.0
    asphere_coefficients: tuple[float, ...] = ()


def _axis_vector(node: TeachingPhysicalNode, laser_yaw_deg: float) -> tuple[float, float, float]:
    relative_yaw = math.radians((float(node.yaw_deg) - float(laser_yaw_deg) + 180.0) % 360.0 - 180.0)
    pitch = math.radians(float(node.pitch_deg))
    cp = math.cos(pitch)
    return (
        math.sin(relative_yaw) * cp,
        math.sin(pitch),
        math.cos(relative_yaw) * cp,
    )


def _tilts_from_engine_normal(normal: tuple[float, float, float], roll_deg: float = 0.0) -> tuple[float, float, float]:
    """Map an engine-frame surface normal onto OpticalSurface Euler tilts (Rx→Ry→Rz)."""
    nx, ny, nz = (float(v) for v in normal)
    norm = math.sqrt(nx * nx + ny * ny + nz * nz)
    if not math.isfinite(norm) or norm <= 1.0e-15:
        return 0.0, 0.0, float(roll_deg)
    nx, ny, nz = nx / norm, ny / norm, nz / norm
    # n = Ry(ty) @ Rx(tx) @ (0,0,1) = (sin(ty)cos(tx), -sin(tx), cos(ty)cos(tx))
    tilt_x = -math.degrees(math.asin(max(-1.0, min(1.0, ny))))
    cos_tx = math.cos(math.radians(tilt_x))
    if abs(cos_tx) < 1.0e-9:
        tilt_y = 0.0
    else:
        tilt_y = math.degrees(math.atan2(nx / cos_tx, nz / cos_tx))
    return float(tilt_x), float(tilt_y), float(roll_deg)


def _mirror_surface_tangent_yaw_deg(node: TeachingPhysicalNode) -> float:
    """Teaching mirror mount convention: rotation_deg = 45 + 0.5*(in+out).

    The reflective face (surface tangent in the horizontal plane) therefore sits at
    ``rotation_deg - 45``. Explicit ``surface_angle_deg`` overrides the mount rule.
    """
    if node.params.get("surface_angle_deg") is not None:
        return float(node.params.get("surface_angle_deg") or 0.0)
    return float(node.yaw_deg) - 45.0


def _surface_tilts_from_axis(node: TeachingPhysicalNode, laser_yaw_deg: float, *, mirror: bool = False) -> tuple[float, float, float]:
    if mirror:
        normal_yaw = _mirror_surface_tangent_yaw_deg(node) + 90.0
        normal_node = TeachingPhysicalNode(
            node_id=node.node_id, kind=node.kind, label=node.label,
            scene_x=node.scene_x, scene_y=node.scene_y, height_mm=node.height_mm,
            yaw_deg=normal_yaw, pitch_deg=node.pitch_deg, roll_deg=node.roll_deg,
            enabled=node.enabled, params=node.params,
        )
        return _tilts_from_engine_normal(_axis_vector(normal_node, laser_yaw_deg), node.roll_deg)
    return _tilts_from_engine_normal(_axis_vector(node, laser_yaw_deg), node.roll_deg)


def _nearest_facing_yaw_deg(node: TeachingPhysicalNode, scene: TeachingPhysicalScene) -> float | None:
    """Yaw that aims a terminal face toward the nearest upstream-capable optic."""
    optic_kinds = {
        "laser", "mirror", "lens", "cylindrical_lens", "splitter", "pbs",
        "beam_sampler", "aperture", "isolator", "half_wave_plate",
    }
    best_optic: tuple[float, float] | None = None
    best_any: tuple[float, float] | None = None
    for other in scene.nodes:
        if other.node_id == node.node_id or not other.enabled:
            continue
        if other.kind in {"oscilloscope"}:
            continue
        dx = float(other.scene_x) - float(node.scene_x)
        dy = float(other.scene_y) - float(node.scene_y)
        dh = float(other.height_mm) - float(node.height_mm)
        distance = math.sqrt(dx * dx + dy * dy + dh * dh)
        if distance < 1.0e-6:
            continue
        # Face toward the neighbor (normal points against typical incoming beam).
        yaw = math.degrees(math.atan2(dy, dx)) % 360.0
        candidate = (distance, yaw)
        if other.kind in optic_kinds:
            if best_optic is None or distance < best_optic[0]:
                best_optic = candidate
        if best_any is None or distance < best_any[0]:
            best_any = candidate
    chosen = best_optic if best_optic is not None else best_any
    return None if chosen is None else float(chosen[1])


def _node_radius_mm(node: TeachingPhysicalNode, default_radius_mm: float) -> float:
    raw = node.params.get("clear_aperture_mm", node.params.get("aperture_radius_mm"))
    if raw is not None:
        return max(0.02, float(raw))
    diameter = node.params.get("diameter_mm")
    if diameter is not None:
        return max(0.02, float(diameter) * 0.5)
    return float(default_radius_mm)


def _design_lens_radii(node: TeachingPhysicalNode) -> tuple[float, float]:
    r1 = node.params.get("radius1_mm")
    r2 = node.params.get("radius2_mm")
    if r1 is not None and r2 is not None:
        values = (float(r1), float(r2))
    else:
        focal = float(node.params.get("focal_mm", 50.0) or 50.0)
        design_index = float(node.params.get("design_refractive_index", 1.5168) or 1.5168)
        magnitude = max(0.5, 2.0 * max(design_index - 1.0, 0.05) * abs(focal))
        values = (magnitude, -magnitude) if focal >= 0.0 else (-magnitude, magnitude)
    if bool(node.params.get("reversed", False)):
        return -float(values[1]), -float(values[0])
    return float(values[0]), float(values[1])


def resolve_teaching_optical_params(node: TeachingPhysicalNode) -> dict[str, Any]:
    params = dict(node.params)
    if node.kind not in {"lens", "cylindrical_lens"}:
        return params
    params.setdefault("optical_model", "physical_surface")
    params.setdefault("material", "N-BK7")
    params.setdefault("diameter_mm", 12.7)
    params.setdefault("center_thickness_mm", 2.0)
    params.setdefault("design_refractive_index", 1.5168)
    params.setdefault("conic1", 0.0)
    params.setdefault("conic2", 0.0)
    params.setdefault("asphere_a2_1", 0.0)
    params.setdefault("asphere_a2_2", 0.0)
    params.setdefault("asphere_coefficients_1", ())
    params.setdefault("asphere_coefficients_2", ())
    explicit = params.get("radius1_mm") is not None and params.get("radius2_mm") is not None
    if explicit:
        params["geometry_source"] = "explicit_surfaces"
    else:
        params["geometry_source"] = "focal_derived_physical"
        probe = TeachingPhysicalNode(
            node_id=node.node_id, kind=node.kind, label=node.label,
            scene_x=node.scene_x, scene_y=node.scene_y, height_mm=node.height_mm,
            yaw_deg=node.yaw_deg, pitch_deg=node.pitch_deg, roll_deg=node.roll_deg,
            enabled=node.enabled, params=params,
        )
        r1, r2 = _design_lens_radii(probe)
        params["resolved_radius1_mm"] = r1
        params["resolved_radius2_mm"] = r2
    if node.kind == "cylindrical_lens":
        params["surface_geometry"] = "cylindrical"
        # axis_angle_deg 统一表示传统柱面轴：沿该方向无光焦度。
        axis_deg = float(params.get("axis_angle_deg", params.get("cylinder_axis_deg", 0.0)) or 0.0) % 180.0
        params["axis_angle_deg"] = axis_deg
        params["cylinder_axis_deg"] = axis_deg
        params["cylinder_power_axis_deg"] = (axis_deg + 90.0) % 180.0
        params["cylinder_axis_definition"] = "zero_power_axis"
    else:
        params["surface_geometry"] = "spherical_or_aspheric"
    return params


def _append_lens_surfaces(
    items: list[_SurfaceBuild],
    node: TeachingPhysicalNode,
    frame: TeachingSceneCoordinateFrame,
    *,
    cylindrical: bool = False,
) -> None:
    resolved = resolve_teaching_optical_params(node)
    resolved_node = TeachingPhysicalNode(
        node_id=node.node_id, kind=node.kind, label=node.label,
        scene_x=node.scene_x, scene_y=node.scene_y, height_mm=node.height_mm,
        yaw_deg=node.yaw_deg, pitch_deg=node.pitch_deg, roll_deg=node.roll_deg,
        enabled=node.enabled, params=resolved,
    )
    center = frame.scene_to_engine(node.scene_x, node.scene_y, node.height_mm)
    axis = _axis_vector(node, frame.laser_yaw_deg)
    thickness = max(0.05, float(resolved.get("center_thickness_mm", resolved.get("thickness_mm", 2.0)) or 2.0))
    if resolved.get("radius1_mm") is None or resolved.get("radius2_mm") is None:
        # resolve_teaching_optical_params 已经把 reversed 作用到等效曲率上，这里不再重复翻转。
        r1 = float(resolved["resolved_radius1_mm"])
        r2 = float(resolved["resolved_radius2_mm"])
    else:
        r1, r2 = _design_lens_radii(resolved_node)
    radius = _node_radius_mm(resolved_node, 6.35)
    material = str(resolved.get("material", "N-BK7") or "N-BK7")
    tilt_x, tilt_y, tilt_z = _surface_tilts_from_axis(node, frame.laser_yaw_deg)
    half = thickness * 0.5
    front = tuple(center[i] - axis[i] * half for i in range(3))
    back = tuple(center[i] + axis[i] * half for i in range(3))
    geometry = "cylindrical" if cylindrical else "spherical"
    common = {
        "teaching_node_id": node.node_id,
        "teaching_kind": node.kind,
        "teaching_label": node.label,
        "teaching_role": "refractive",
        "pass_if_missed": True,
        "terminal": False,
        "geometry_source": str(resolved.get("geometry_source", "explicit_surfaces")),
        "cylindrical_approximation": False,
    }
    if cylindrical:
        common["cylinder_axis_deg"] = float(resolved.get("cylinder_axis_deg", resolved.get("axis_angle_deg", 0.0)) or 0.0) % 180.0
        common["cylinder_power_axis_deg"] = float(90.0 if resolved.get("cylinder_power_axis_deg") is None else resolved.get("cylinder_power_axis_deg")) % 180.0
        common["cylinder_axis_definition"] = "zero_power_axis"
    front_conic = float(resolved.get("conic1", resolved.get("conic", 0.0)) or 0.0)
    back_conic = float(resolved.get("conic2", 0.0) or 0.0)
    front_a2 = float(resolved.get("asphere_a2_1", resolved.get("asphere_a2", 0.0)) or 0.0)
    back_a2 = float(resolved.get("asphere_a2_2", 0.0) or 0.0)
    front_coeffs = tuple(float(v) for v in resolved.get("asphere_coefficients_1", resolved.get("asphere_coefficients", ())) or ())
    back_coeffs = tuple(float(v) for v in resolved.get("asphere_coefficients_2", ()) or ())
    if bool(resolved.get("reversed", False)):
        front_conic, back_conic = back_conic, front_conic
        front_a2, back_a2 = back_a2, front_a2
        front_coeffs, back_coeffs = back_coeffs, front_coeffs
    items.append(_SurfaceBuild(
        desired_z_mm=float(front[2]), center_x_mm=float(front[0]), center_y_mm=float(front[1]),
        radius_mm=float(r1), surface_type=geometry, material_before="AIR", material_after=material,
        clear_aperture_mm=radius, tilt_x_deg=tilt_x, tilt_y_deg=tilt_y, tilt_z_deg=tilt_z,
        metadata={**common, "component_surface": "front"},
        conic=front_conic, asphere_a2=front_a2, asphere_coefficients=front_coeffs,
    ))
    items.append(_SurfaceBuild(
        desired_z_mm=float(back[2]), center_x_mm=float(back[0]), center_y_mm=float(back[1]),
        radius_mm=float(r2), surface_type=geometry, material_before=material, material_after="AIR",
        clear_aperture_mm=radius, tilt_x_deg=tilt_x, tilt_y_deg=tilt_y, tilt_z_deg=tilt_z,
        metadata={**common, "component_surface": "back"},
        conic=back_conic, asphere_a2=back_a2, asphere_coefficients=back_coeffs,
    ))


def _append_plane_surface(
    items: list[_SurfaceBuild],
    node: TeachingPhysicalNode,
    frame: TeachingSceneCoordinateFrame,
    *,
    role: str,
    radius_mm: float,
    surface_type: str = "spherical",
    mirror_orientation: bool = False,
    terminal: bool = False,
    block_outside: bool = False,
    split_ratio: float | None = None,
    hit_shape: str | None = None,
    facing_node: TeachingPhysicalNode | None = None,
) -> None:
    x, y, z = frame.scene_to_engine(node.scene_x, node.scene_y, node.height_mm)
    pose_node = facing_node if facing_node is not None else node
    tilt_x, tilt_y, tilt_z = _surface_tilts_from_axis(
        pose_node, frame.laser_yaw_deg, mirror=mirror_orientation,
    )
    metadata: dict[str, Any] = {
        "teaching_node_id": node.node_id,
        "teaching_kind": node.kind,
        "teaching_label": node.label,
        "teaching_role": role,
        "terminal": bool(terminal),
        "block_outside_aperture": bool(block_outside),
        "pass_if_missed": not bool(block_outside),
    }
    if hit_shape:
        metadata["hit_shape"] = str(hit_shape)
        metadata["hit_radius_mm"] = max(0.02, float(radius_mm))
    if split_ratio is not None:
        metadata["split_ratio"] = float(split_ratio)
    items.append(_SurfaceBuild(
        desired_z_mm=z,
        center_x_mm=x,
        center_y_mm=y,
        radius_mm=None,
        surface_type=surface_type,
        material_before="AIR",
        material_after="AIR",
        clear_aperture_mm=max(0.02, float(radius_mm)),
        tilt_x_deg=tilt_x,
        tilt_y_deg=tilt_y,
        tilt_z_deg=tilt_z,
        metadata=metadata,
    ))


def _build_surfaces(scene: TeachingPhysicalScene, base_frame: TeachingSceneCoordinateFrame) -> tuple[list[_SurfaceBuild], list[str]]:
    items: list[_SurfaceBuild] = []
    warnings: list[str] = []
    for node in scene.nodes:
        if not node.enabled or node.kind in {"laser", "oscilloscope"}:
            continue
        if node.kind == "lens":
            resolved = resolve_teaching_optical_params(node)
            _append_lens_surfaces(items, node, base_frame)
            if resolved.get("geometry_source") == "focal_derived_physical":
                warnings.append(f"{node.label}未提供两面真实曲率，完整引擎依据焦距、材料设计折射率和厚度建立等效物理镜片；录入R1/R2后将直接使用真实曲面。")
        elif node.kind == "cylindrical_lens":
            resolved = resolve_teaching_optical_params(node)
            _append_lens_surfaces(items, node, base_frame, cylindrical=True)
            if resolved.get("geometry_source") == "focal_derived_physical":
                warnings.append(f"{node.label}未提供两面真实柱面曲率，完整引擎依据焦距和设计折射率生成等效柱面；当前追迹使用真实柱面几何而非球面近似。")
        elif node.kind == "mirror":
            _append_plane_surface(
                items, node, base_frame, role="mirror", radius_mm=_node_radius_mm(node, 12.7),
                surface_type="mirror", mirror_orientation=True,
            )
        elif node.kind in {"splitter", "pbs", "beam_sampler"}:
            default_ratio = 0.50 if node.kind == "pbs" else 0.05
            ratio = float(node.params.get("split_ratio", node.params.get("monitor_fraction", default_ratio)) or default_ratio)
            _append_plane_surface(
                items, node, base_frame, role="splitter", radius_mm=_node_radius_mm(node, 10.0),
                surface_type="spherical", mirror_orientation=True, split_ratio=ratio,
            )
        elif node.kind == "aperture":
            aperture_radius = max(0.02, float(node.params.get("diameter_mm", 5.0)) * 0.5)
            _append_plane_surface(
                items, node, base_frame, role="transparent", radius_mm=aperture_radius,
                block_outside=True,
            )
        elif node.kind in {
            "fiber", "power_meter", "beam_analyzer", "imaging_camera", "ccd", "camera",
            "focus_scan_module", "wavefront_sensor", "photodetector",
        }:
            default_radius = 2.0 if node.kind == "fiber" else 15.0
            facing_yaw = _nearest_facing_yaw_deg(node, scene)
            facing_node = node
            if facing_yaw is not None:
                facing_node = TeachingPhysicalNode(
                    node_id=node.node_id, kind=node.kind, label=node.label,
                    scene_x=node.scene_x, scene_y=node.scene_y, height_mm=node.height_mm,
                    yaw_deg=facing_yaw, pitch_deg=node.pitch_deg, roll_deg=node.roll_deg,
                    enabled=node.enabled, params=node.params,
                )
                display_delta = abs(((float(node.yaw_deg) - facing_yaw + 180.0) % 360.0) - 180.0)
                if display_delta > 35.0:
                    warnings.append(
                        f"{node.label}接收面已按最近光学件自动对准入射方向（显示朝向偏差 {display_delta:.0f}°），"
                        "保证折转后仍可命中；旋转图标主要影响外观。"
                    )
            _append_plane_surface(
                items, node, base_frame, role="terminal",
                radius_mm=_node_radius_mm(node, default_radius),
                terminal=True,
                facing_node=facing_node,
            )
        else:
            _append_plane_surface(
                items, node, base_frame, role="transparent", radius_mm=_node_radius_mm(node, 8.0),
            )
    return items, warnings


def _trace_quality_profile(quality: str) -> dict[str, Any]:
    key = str(quality or "settled").strip().lower()
    if key == "live":
        return {"quality": "live", "sample_count": 9, "precision": "preview", "max_interactions": 20, "max_branches": 12}
    if key == "formal":
        return {"quality": "formal", "sample_count": 41, "precision": "high", "max_interactions": 40, "max_branches": 32}
    return {"quality": "settled", "sample_count": 21, "precision": "standard", "max_interactions": 32, "max_branches": 24}


def _compile_project(scene: TeachingPhysicalScene) -> tuple[ProjectSnapshot, TeachingSceneCoordinateFrame, tuple[str, ...], dict[str, Any]]:
    laser = scene.laser
    if laser is None:
        raise ValueError("教学场景中没有启用的激光器。")
    usable_span = max(400.0, float(scene.scene_width_units) - 200.0)
    mm_per_scene = max(1.0e-4, float(scene.max_system_length_mm) / usable_span)
    base_frame = TeachingSceneCoordinateFrame(
        laser_scene_x=float(laser.scene_x),
        laser_scene_y=float(laser.scene_y),
        laser_height_mm=float(laser.height_mm),
        laser_yaw_deg=float(laser.yaw_deg),
        mm_per_scene_unit=mm_per_scene,
        axial_shift_mm=0.0,
    )
    raw_surfaces, build_warnings = _build_surfaces(scene, base_frame)
    if not raw_surfaces:
        axial_shift = 0.0
    else:
        axial_shift = min(item.desired_z_mm for item in raw_surfaces)
    frame = TeachingSceneCoordinateFrame(
        laser_scene_x=base_frame.laser_scene_x,
        laser_scene_y=base_frame.laser_scene_y,
        laser_height_mm=base_frame.laser_height_mm,
        laser_yaw_deg=base_frame.laser_yaw_deg,
        mm_per_scene_unit=base_frame.mm_per_scene_unit,
        axial_shift_mm=axial_shift,
    )

    shifted: list[_SurfaceBuild] = []
    for item in raw_surfaces:
        shifted.append(_SurfaceBuild(
            desired_z_mm=item.desired_z_mm - axial_shift,
            center_x_mm=item.center_x_mm,
            center_y_mm=item.center_y_mm,
            radius_mm=item.radius_mm,
            surface_type=item.surface_type,
            material_before=item.material_before,
            material_after=item.material_after,
            clear_aperture_mm=item.clear_aperture_mm,
            tilt_x_deg=item.tilt_x_deg,
            tilt_y_deg=item.tilt_y_deg,
            tilt_z_deg=item.tilt_z_deg,
            metadata=item.metadata,
            conic=item.conic,
            asphere_a2=item.asphere_a2,
            asphere_coefficients=item.asphere_coefficients,
        ))
    shifted.sort(key=lambda item: (item.desired_z_mm, item.center_x_mm, item.center_y_mm))

    surface_snapshots: list[SurfaceSnapshot] = []
    for index, item in enumerate(shifted):
        next_z = shifted[index + 1].desired_z_mm if index + 1 < len(shifted) else item.desired_z_mm
        surface_snapshots.append(SurfaceSnapshot(
            index=index,
            surface_type=item.surface_type,
            radius_mm=item.radius_mm,
            distance_to_next_mm=float(next_z - item.desired_z_mm),
            material_before=item.material_before,
            material_after=item.material_after,
            clear_aperture_mm=item.clear_aperture_mm,
            conic=item.conic,
            asphere_a2=item.asphere_a2,
            asphere_coefficients=list(item.asphere_coefficients),
            decenter_x_mm=float(item.center_x_mm),
            decenter_y_mm=float(item.center_y_mm),
            tilt_x_deg=float(item.tilt_x_deg),
            tilt_y_deg=float(item.tilt_y_deg),
            tilt_z_deg=float(item.tilt_z_deg),
            metadata=dict(item.metadata),
        ))

    source_position = frame.scene_to_engine(laser.scene_x, laser.scene_y, laser.height_mm)
    pitch = math.radians(float(laser.pitch_deg))
    source_direction = (0.0, math.sin(pitch), math.cos(pitch))
    beam_radius = max(0.02, float(laser.params.get("beam_radius_mm", 0.72) or 0.72))
    payload = {
        "nodes": [
            {
                "id": node.node_id,
                "kind": node.kind,
                "x": node.scene_x,
                "y": node.scene_y,
                "z": node.height_mm,
                "yaw": node.yaw_deg,
                "pitch": node.pitch_deg,
                "roll": node.roll_deg,
                "enabled": node.enabled,
                "params": node.params,
            }
            for node in scene.nodes
        ],
        "wavelength_nm": scene.wavelength_nm,
        "max_system_length_mm": scene.max_system_length_mm,
    }
    fingerprint = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    project = ProjectSnapshot(
        project_id="teaching-physical-scene",
        surfaces=surface_snapshots,
        object_distance_mm=0.0,
        image_distance_mm=0.0,
        pupil_radius_mm=beam_radius,
        source=SourceSnapshot(
            wavelength_nm=float(scene.wavelength_nm),
            source_type="parallel_pupil",
            object_na_x=0.0,
            object_na_y=0.0,
            field_x_deg=0.0,
            field_y_deg=float(laser.pitch_deg),
            waist_x_mm=beam_radius,
            waist_y_mm=beam_radius,
            power_value=float(scene.input_power_mw),
            power_unit="mW",
        ),
        receiver=None,
        aperture={"radius_mm": beam_radius},
        analysis_settings={},
        fingerprint=fingerprint,
    )
    quality = _trace_quality_profile(scene.trace_quality)
    engine_options = {
        "geometric": {
            "wavelength_nm": float(scene.wavelength_nm),
            "scene_source_position_mm": list(source_position),
            "scene_source_direction": list(source_direction),
            "scene_bundle_sample_count": int(quality["sample_count"]),
            "scene_bundle_radius_x_mm": beam_radius,
            "scene_bundle_radius_y_mm": max(0.02, float(laser.params.get("beam_radius_y_mm", beam_radius) or beam_radius)),
            "scene_bundle_pattern": "rings" if int(quality["sample_count"]) in {9, 21} else "fibonacci_disk",
            "scene_bundle_gaussian_edge_fraction": math.exp(-2.0),
            "scene_max_interactions": int(quality["max_interactions"]),
            "scene_max_branches": int(quality["max_branches"]),
            "scene_min_power_fraction": 1.0e-5 if quality["quality"] != "live" else 5.0e-4,
            "scene_escape_distance_mm": max(40.0, float(scene.max_system_length_mm) * 1.25),
            "scene_intersection_epsilon_mm": 1.0e-5,
            "teaching_generation": int(scene.generation),
            "teaching_trace_quality": str(quality["quality"]),
        }
    }
    return project, frame, tuple(build_warnings), engine_options


class TeachingOpticalEngineBridge:
    def __init__(self, engine: OpticalSimulationEngine | None = None) -> None:
        self.engine = engine or OpticalSimulationEngine(trace_cache_max_bytes=96 * 1024**2)
        # 结果级 LRU：相同场景指纹 + 质量档直接复用，避免拖动中重复追迹。
        self._result_cache: dict[tuple[str, str], TeachingEngineTrace] = {}
        self._result_cache_order: list[tuple[str, str]] = []
        self._result_cache_max = 16

    def _cache_put(self, key: tuple[str, str], result: TeachingEngineTrace) -> None:
        if key in self._result_cache:
            self._result_cache_order.remove(key)
        self._result_cache[key] = result
        self._result_cache_order.append(key)
        if len(self._result_cache_order) > self._result_cache_max:
            oldest = self._result_cache_order.pop(0)
            self._result_cache.pop(oldest, None)

    def _cache_get(self, key: tuple[str, str]) -> TeachingEngineTrace | None:
        result = self._result_cache.get(key)
        if result is not None:
            self._result_cache_order.remove(key)
            self._result_cache_order.append(key)
        return result

    def compile_project(self, scene: TeachingPhysicalScene) -> tuple[ProjectSnapshot, dict[str, Any]]:
        """将教学场景编译为正式 ProjectSnapshot 与引擎选项，供后台正式仿真任务复用。"""
        project, _frame, _warnings, engine_options = _compile_project(scene)
        return project, dict(engine_options)

    def trace(self, scene: TeachingPhysicalScene) -> TeachingEngineTrace:
        """Free-placement scene raytrace via nearest-hit solver (not sequential z-order)."""
        quality = _trace_quality_profile(scene.trace_quality)
        cache_key = (scene.fingerprint_key(), str(quality["quality"]))
        cached = self._cache_get(cache_key)
        if cached is not None:
            return replace(cached, generation=int(scene.generation), quality=str(quality["quality"]))
        try:
            import time as _time
            from optical_core.models.project_mapper import build_optical_system
            from optical_core.physics.nonsequential.scene_tracer import trace_scene_ray_tree

            t0 = _time.perf_counter()
            project, frame, build_warnings, engine_options = _compile_project(scene)
            system = build_optical_system(project)
            geo = dict(engine_options.get("geometric", {}) or {})
            origin = tuple(float(v) for v in geo.get("scene_source_position_mm", (0.0, 0.0, 0.0)))
            direction = tuple(float(v) for v in geo.get("scene_source_direction", (0.0, 0.0, 1.0)))
            radius_x = float(geo.get("scene_bundle_radius_x_mm", 0.72) or 0.72)
            radius_y = float(geo.get("scene_bundle_radius_y_mm", radius_x) or radius_x)
            sample_count = max(1, int(geo.get("scene_bundle_sample_count", quality["sample_count"]) or 1))
            wavelength = float(scene.wavelength_nm)
            bundle = _scene_source_bundle(
                origin, direction, radius_x=radius_x, radius_y=radius_y, sample_count=sample_count,
            )
            paths: list[TeachingTracePath] = []
            rays: list[TeachingTraceRay] = []
            all_warnings = list(build_warnings)
            for ray_index, (position, ray_direction, weight, offset) in enumerate(bundle):
                ray_id = f"R{ray_index:04d}"
                traced = trace_scene_ray_tree(
                    system,
                    source_position_mm=position,
                    source_direction=ray_direction,
                    wavelength_nm=wavelength,
                    max_interactions=int(geo.get("scene_max_interactions", quality["max_interactions"])),
                    max_branches=int(geo.get("scene_max_branches", quality["max_branches"])),
                    min_power_fraction=float(geo.get("scene_min_power_fraction", 1.0e-5)),
                    escape_distance_mm=float(geo.get("scene_escape_distance_mm", 160.0)),
                    epsilon_mm=float(geo.get("scene_intersection_epsilon_mm", 1.0e-5)),
                )
                all_warnings.extend(traced.warnings)
                ray_paths: list[TeachingTracePath] = []
                for path_index, raw_path in enumerate(traced.paths):
                    converted: list[TeachingTracePoint] = []
                    for point_index, raw_point in enumerate(raw_path.points_mm):
                        engine_point = tuple(float(v) for v in raw_point)
                        sx, sy, height = frame.engine_to_scene(engine_point)
                        raw_node = (
                            raw_path.node_ids[point_index]
                            if point_index < len(raw_path.node_ids) else None
                        )
                        if raw_node == "__source__":
                            raw_node = scene.laser.node_id if scene.laser is not None else None
                        raw_dir = (
                            raw_path.directions[point_index]
                            if point_index < len(raw_path.directions)
                            else ray_direction
                        )
                        converted.append(TeachingTracePoint(
                            scene_x=sx, scene_y=sy, height_mm=height,
                            engine_point_mm=engine_point,
                            engine_direction=tuple(float(v) for v in raw_dir),
                            node_id=None if raw_node in {None, ""} else str(raw_node),
                            surface_index=(
                                int(raw_path.surface_indices[point_index])
                                if point_index < len(raw_path.surface_indices) else -2
                            ),
                        ))
                    path = TeachingTracePath(
                        path_id=f"{ray_id}:P{path_index}",
                        parent_id=None,
                        ray_id=ray_id,
                        signature=str(raw_path.signature or ""),
                        power_fraction=float(raw_path.power_fraction) * float(weight),
                        points=tuple(converted),
                        termination_reason=str(raw_path.termination_reason or ""),
                    )
                    paths.append(path)
                    ray_paths.append(path)
                rays.append(TeachingTraceRay(
                    ray_id=ray_id,
                    source_position_mm=position,
                    source_direction=ray_direction,
                    normalized_offset=offset,
                    source_weight=float(weight),
                    paths=tuple(ray_paths),
                ))
            elapsed_ms = (_time.perf_counter() - t0) * 1000.0
            traced_out = TeachingEngineTrace(
                success=True,
                generation=int(scene.generation),
                quality=str(quality["quality"]),
                sample_count=int(sample_count),
                paths=tuple(paths),
                rays=tuple(rays),
                warnings=tuple(all_warnings),
                errors=(),
                elapsed_ms=float(elapsed_ms),
                metadata={
                    "teaching_generation": int(scene.generation),
                    "teaching_trace_quality": str(quality["quality"]),
                    "teaching_sample_count": int(sample_count),
                    "teaching_solver": "scene_ray_tree",
                },
                frame=frame,
            )
            self._cache_put(cache_key, traced_out)
            return traced_out
        except Exception as exc:
            traced_out = TeachingEngineTrace(
                success=False, generation=int(scene.generation), quality=str(quality["quality"]),
                sample_count=int(quality["sample_count"]), paths=(), rays=(), warnings=(),
                errors=(str(exc),), elapsed_ms=0.0, metadata={}, frame=None,
            )
            self._cache_put(cache_key, traced_out)
            return traced_out


def _scene_source_bundle(
    origin: tuple[float, float, float],
    direction: tuple[float, float, float],
    *,
    radius_x: float,
    radius_y: float,
    sample_count: int,
) -> list[tuple[tuple[float, float, float], tuple[float, float, float], float, tuple[float, float]]]:
    """Disk pupil samples in the plane perpendicular to the laser axis."""
    import numpy as np

    axis = np.asarray(direction, dtype=float)
    norm = float(np.linalg.norm(axis))
    if not np.isfinite(norm) or norm <= 1e-15:
        axis = np.asarray((0.0, 0.0, 1.0), dtype=float)
    else:
        axis = axis / norm
    helper = np.asarray((0.0, 1.0, 0.0), dtype=float) if abs(axis[1]) < 0.9 else np.asarray((1.0, 0.0, 0.0), dtype=float)
    across = np.cross(axis, helper)
    across = across / max(float(np.linalg.norm(across)), 1e-15)
    up = np.cross(axis, across)
    count = max(1, int(sample_count))
    offsets: list[tuple[float, float]] = [(0.0, 0.0)]
    if count > 1:
        rings = max(1, int(math.ceil((-1.0 + math.sqrt(1.0 + 4.0 * (count - 1) / 3.0)) / 2.0)))
        for ring in range(1, rings + 1):
            on_ring = max(4, 6 * ring)
            for k in range(on_ring):
                angle = 2.0 * math.pi * k / on_ring
                frac = ring / rings
                offsets.append((frac * math.cos(angle), frac * math.sin(angle)))
                if len(offsets) >= count:
                    break
            if len(offsets) >= count:
                break
    offsets = offsets[:count]
    weight = 1.0 / max(len(offsets), 1)
    origin_v = np.asarray(origin, dtype=float)
    bundle: list[tuple[tuple[float, float, float], tuple[float, float, float], float, tuple[float, float]]] = []
    for nx, ny in offsets:
        point = origin_v + across * (nx * float(radius_x)) + up * (ny * float(radius_y))
        bundle.append((
            (float(point[0]), float(point[1]), float(point[2])),
            (float(axis[0]), float(axis[1]), float(axis[2])),
            float(weight),
            (float(nx), float(ny)),
        ))
    return bundle

__all__ = [
    "TeachingPhysicalNode",
    "TeachingPhysicalScene",
    "TeachingSceneCoordinateFrame",
    "TeachingTracePoint",
    "TeachingTracePath",
    "TeachingTraceRay",
    "TeachingEngineTrace",
    "TeachingOpticalEngineBridge",
    "resolve_teaching_optical_params",
]

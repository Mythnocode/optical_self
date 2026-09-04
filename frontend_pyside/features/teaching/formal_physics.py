from __future__ import annotations

"""Formal-physics bridge for the teaching/virtual-experiment workbench.

Displayed light comes from TeachingPhysicalScene + scene ray-tree solver
(nearest-hit free placement).  Sequential build_scene_project remains available
for regression tests and lens-train compilation helpers.
"""

from typing import Any

from PySide6.QtCore import QObject, QTimer, Signal

from frontend_pyside.core.types import LensSurface, ProjectSnapshot
from teaching_runtime.physical_scene import TeachingOpticalEngineBridge

from .applicability import RECEIVER_KINDS, evaluate_scene_applicability, lens_prescription
from .ccd_detector import ccd_metrics_from_ray_result, parse_scan_positions_mm
from .experiment_scene import SCENE_MM_PER_PX
from .optical_components import TeachingOpticalSystem
from .scene_bridge import (
    experiment_model_to_physical_scene,
    scene_rays_to_world_3d,
    trace_paths_to_engine_rays,
    trace_paths_to_scene_rays,
)


def build_scene_project(model: Any) -> tuple[ProjectSnapshot, float] | None:
    """Compile a validated lens→receiver train into a sequential project.

    Kept for tests and tooling.  Interactive teaching no longer depends on this
    sequential compiler for displayed rays.
    """
    report = evaluate_scene_applicability(model)
    if not report.allowed and not any(
        str(getattr(node, "kind", "")) == "laser" for node in dict(getattr(model, "nodes", {}) or {}).values()
    ):
        return None
    nodes = dict(getattr(model, "nodes", {}) or {})
    lenses = sorted(
        (
            node for node in nodes.values()
            if str(getattr(node, "kind", "")) == "lens"
            and bool(getattr(node, "params", {}).get("enabled", True))
        ),
        key=lambda node: float(getattr(node, "x", 0.0)),
    )
    receivers = sorted(
        (node for node in nodes.values() if str(getattr(node, "kind", "")) in RECEIVER_KINDS),
        key=lambda node: float(getattr(node, "x", 0.0)),
    )
    receiver = next(
        (node for node in receivers if (not lenses) or float(getattr(node, "x", 0.0)) > float(getattr(lenses[-1], "x", 0.0))),
        receivers[0] if receivers else None,
    )
    if not lenses or receiver is None:
        return None
    x_first = float(getattr(lenses[0], "x", 0.0))

    def z_of(x: float) -> float:
        return (float(x) - x_first) * SCENE_MM_PER_PX

    surfaces: list[LensSurface] = []
    for index, lens in enumerate(lenses):
        prescription = lens_prescription(lens)
        thickness = float(prescription["thickness_mm"])
        lens_params = dict(getattr(lens, "params", {}) or {})
        if index + 1 < len(lenses):
            next_node = lenses[index + 1]
        else:
            next_node = receiver
        scene_centre_distance = z_of(float(getattr(next_node, "x", 0.0))) - z_of(float(getattr(lens, "x", 0.0)))
        if "air_gap_after_mm" in lens_params:
            centre_distance = thickness + float(lens_params.get("air_gap_after_mm", 0.0) or 0.0)
        else:
            centre_distance = float(lens_params.get("distance_to_next_mm", scene_centre_distance) or scene_centre_distance)
        air_gap = max(0.0, centre_distance - thickness)
        surfaces.append(LensSurface(
            name=f"{lens.label or '透镜'}前表面",
            radius_mm=float(prescription["front_radius_mm"]),
            thickness_mm=thickness,
            material=str(prescription["material"]),
            semi_aperture_mm=float(prescription["semi_aperture_mm"]),
            surface_type="球面",
            conic=float(prescription["front_conic"]),
            group_id=lens.id,
            coating=str(prescription["coating"]),
            mechanical_diameter_mm=float(prescription["mechanical_diameter_mm"]),
            note=f"处方来源：{prescription['source']}",
        ))
        surfaces.append(LensSurface(
            name=f"{lens.label or '透镜'}后表面",
            radius_mm=float(prescription["back_radius_mm"]),
            thickness_mm=air_gap,
            material="AIR",
            semi_aperture_mm=float(prescription["semi_aperture_mm"]),
            surface_type="球面",
            conic=float(prescription["back_conic"]),
            group_id=lens.id,
            coating=str(prescription["coating"]),
            mechanical_diameter_mm=float(prescription["mechanical_diameter_mm"]),
            note=f"处方来源：{prescription['source']}",
        ))
    last_params = dict(getattr(lenses[-1], "params", {}) or {})
    last_scene_distance = z_of(float(getattr(receiver, "x", 0.0))) - z_of(float(getattr(lenses[-1], "x", 0.0)))
    if "air_gap_after_mm" in last_params:
        last_centre_distance = float(lens_prescription(lenses[-1])["thickness_mm"]) + float(last_params.get("air_gap_after_mm", 0.0) or 0.0)
    else:
        last_centre_distance = float(last_params.get("distance_to_next_mm", last_scene_distance) or last_scene_distance)
    image_distance_mm = max(0.0, last_centre_distance - float(lens_prescription(lenses[-1])["thickness_mm"]))
    if image_distance_mm <= 1e-6:
        return None
    laser = next((node for node in nodes.values() if str(getattr(node, "kind", "")) == "laser"), None)
    laser_params = dict(getattr(laser, "params", {}) or {}) if laser is not None else {}
    wavelength_nm = float(laser_params.get("wavelength_nm", getattr(model, "wavelength_nm", 808.0)) or 808.0)
    project = ProjectSnapshot(
        name=f"教学场景 · sequential",
        wavelength_nm=wavelength_nm,
        surfaces=surfaces,
        receiver_mfd_um=2.0 * float(getattr(model, "receiver_mode_radius_um", 2.8) or 2.8),
        metrics={},
    )
    return project, image_distance_mm


class TeachingFormalPhysicsController(QObject):
    resultReady = Signal(object, object, int)
    stateChanged = Signal(str, str)

    def __init__(self, context, parent=None) -> None:
        super().__init__(parent)
        self.context = context
        self._bridge = TeachingOpticalEngineBridge()
        self._model = None
        self._requested_revision = -1
        self._submitted_revision = -1
        self._last_completed_revision = -1
        self._rerun_pending = False
        self._failure_revision = -1
        self._failure_count = 0
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(260)
        self._debounce.timeout.connect(self._submit_latest)

    @property
    def controller(self):
        """Compatibility shim for older callers that probed SimulationController."""
        return self

    @property
    def is_running(self) -> bool:
        return False

    def request(self, model) -> None:
        self._model = model
        revision = int(getattr(model, "revision", -1))
        self._requested_revision = revision
        if revision == self._last_completed_revision:
            return
        self.stateChanged.emit("pending", "实验状态已改变 · 等待场景光学计算")
        self._debounce.start()

    def _submit_latest(self) -> None:
        model = self._model
        if model is None:
            return
        self._rerun_pending = False
        revision = int(getattr(model, "revision", -1))
        report = evaluate_scene_applicability(model)
        if hasattr(model, "set_formal_validation"):
            model.set_formal_validation(revision, report.messages)
        if hasattr(model, "sync_optical_system"):
            model.sync_optical_system()
        elif hasattr(model, "optical_system") and isinstance(getattr(model, "optical_system"), TeachingOpticalSystem):
            model.optical_system.sync_from_nodes(getattr(model, "nodes", {}) or {})

        has_laser = any(str(getattr(n, "kind", "")) == "laser" for n in dict(getattr(model, "nodes", {}) or {}).values())
        if not has_laser:
            self._submitted_revision = revision
            self._last_completed_revision = revision
            self.stateChanged.emit("blocked", "场景追迹需要至少一台启用的激光器")
            return

        self._submitted_revision = revision
        self.stateChanged.emit("running", "场景光学引擎计算中（自由搭建）")
        try:
            scene = experiment_model_to_physical_scene(
                model, generation=revision, trace_quality="live",
            )
            traced = self._bridge.trace(scene)
            if not traced.success:
                self._on_failed("raytrace", "；".join(traced.errors) or "场景追迹失败")
                return
            if not traced.paths:
                self._on_failed("raytrace", "场景追迹未产生有效光路")
                return

            scene_rays = trace_paths_to_scene_rays(traced.paths, max_rays=5)
            engine_rays = trace_paths_to_engine_rays(traced.paths, max_rays=32)
            world_rays = scene_rays_to_world_3d(scene_rays)
            result_body = {
                "status": "completed",
                "metrics": {
                    "teaching_solver": "scene_ray_tree",
                    "teaching_path_count": len(traced.paths),
                    "teaching_sample_count": traced.sample_count,
                },
                "arrays": {
                    "raytrace_final_positions_mm": [
                        list(path.points[-1].engine_point_mm)
                        for path in traced.paths
                        if path.points and path.termination_reason == "terminal_hit"
                    ],
                    "raytrace_valid_mask": [
                        path.termination_reason == "terminal_hit"
                        for path in traced.paths
                        if path.points
                    ],
                    "raytrace_power_weights": [
                        float(path.power_fraction)
                        for path in traced.paths
                        if path.points
                    ],
                },
                "scene_rays": scene_rays,
                "world_rays": world_rays,
                "engine_rays": engine_rays,
                "warnings": list(traced.warnings),
            }
            # CCD metrics from terminal hits when a detector is present.
            ccd_body = dict(result_body)
            primary = ccd_metrics_from_ray_result(ccd_body)
            if primary.get("valid"):
                result_body["ccd"] = primary
                result_body["metrics"]["ccd_rms_x_um"] = primary.get("rms_x_um")
                result_body["metrics"]["ccd_rms_y_um"] = primary.get("rms_y_um")
                result_body["metrics"]["ccd_radial_rms_um"] = primary.get("radial_rms_um")
                scan_raw = None
                for node in dict(getattr(model, "nodes", {}) or {}).values():
                    if str(getattr(node, "kind", "")) in {"ccd", "imaging_camera", "camera"}:
                        scan_raw = dict(getattr(node, "params", {}) or {}).get("scan_positions_mm")
                        break
                positions = parse_scan_positions_mm(scan_raw)
                if len(positions) > 1:
                    result_body["ccd_scan"] = [
                        {**primary, "plane_offset_mm": float(z)} for z in positions
                    ]

            self._on_result(result_body, {"teaching_solver": "scene_ray_tree"})
        except Exception as exc:
            self._on_failed("raytrace", str(exc))

    def _on_result(self, result: object, project: object) -> None:
        result_body = dict(result or {})
        project_body = dict(project or {})
        scene_rays = tuple(result_body.get("scene_rays") or ())
        world_rays = tuple(result_body.get("world_rays") or ())
        if not scene_rays and not world_rays:
            self._on_failed("raytrace", "正式结果缺少可显示的光线路径")
            return
        revision = int(self._submitted_revision)
        self._failure_revision = -1
        self._failure_count = 0
        self._last_completed_revision = revision
        self.resultReady.emit(result_body, project_body, revision)
        self.stateChanged.emit("verified", "场景光线追迹已更新（自由搭建求解）")
        if self._rerun_pending or self._requested_revision != revision:
            self._rerun_pending = False
            self._debounce.start(80)

    def _on_failed(self, _stage: str, message: str) -> None:
        revision = int(self._submitted_revision)
        if revision != self._failure_revision:
            self._failure_revision = revision
            self._failure_count = 0
        self._failure_count += 1
        if self._failure_count <= 2:
            self.stateChanged.emit("error", f"场景光学计算失败（重试 {self._failure_count}/2）：{message}")
            self._rerun_pending = True
            self._debounce.start(700)
            return
        self._rerun_pending = False
        self._last_completed_revision = revision
        self.stateChanged.emit("error", f"场景光学计算失败，已停止自动重试：{message}")

    def dispose(self) -> None:
        self._debounce.stop()


__all__ = ["TeachingFormalPhysicsController", "build_scene_project"]

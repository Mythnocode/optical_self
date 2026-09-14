"""画布 demo 与真实光学引擎的桥接层。

进程内直调（无 HTTP）：
- build_payload(surfaces) 复刻应用真实调用链：
  SimpleNamespace 表面 + 默认 SimulationFormState → serialize_project
  → build_simulation_payload → SimulationRequest
- EngineBridge 在后台线程跑 engine.evaluate，通过 Qt 信号把
  {version, arrays, metrics, warnings, elapsed_ms} 送回主线程。

已验证：780nm 四透镜预设的 coupling_efficiency 与
REFERENCE_COUPLING_EFFICIENCY 对齐到机器精度（~5e-14）。

版本兼容注记：wave 管线 method 集合与 hybrid 耦合传播模型集合不同，
前端预设的“缩放 Fresnel”对应 wave.method="fresnel" +
hybrid.propagation_model="scaled_fresnel"。
"""

from __future__ import annotations

import threading
import time
from dataclasses import replace
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from PySide6.QtCore import QObject, Signal

from shared_contracts.simulation import SimulationRequest

from frontend_pyside.features.simulation.form_state import (
    PRECISION_MAP,
    PROPAGATION_MAP,
    RECEIVER_TYPE_MAP,
    SOURCE_TYPE_MAP,
    SimulationFormState,
    parse_grid_size,
)
from frontend_pyside.features.simulation.imported_field import load_complex_field
from frontend_pyside.features.simulation.payloads import build_simulation_payload
from frontend_pyside.presets.demo_780nm_four_lens import FOUR_LENS_SURFACES

ANALYSES = ("raytrace", "coupling", "psf", "mtf", "spot")


def surfaces_to_project(surface_rows: list[dict[str, Any]]) -> SimpleNamespace:
    """画布表格行 → serialize_project 可消费的项目对象。"""
    namespaces = [
        SimpleNamespace(
            name=str(row.get("name", "")),
            surface_type=str(row.get("surface_type", "球面")),
            radius_mm=float(row["radius_mm"]) if row.get("radius_mm") else 0.0,
            thickness_mm=float(row.get("thickness_mm", 0.0) or 0.0),
            material=str(row.get("material", "AIR")),
            semi_aperture_mm=float(row.get("semi_aperture_mm", 1.0) or 1.0),
            mechanical_diameter_mm=row.get("mechanical_diameter_mm"),
            conic=float(row.get("conic", 0.0) or 0.0),
            enabled=bool(row.get("enabled", True)),
            coating=str(row.get("coating", "无") or "无"),
            roughness_nm=float(row.get("roughness_nm", 0.0) or 0.0),
            note=str(row.get("note", "") or ""),
            group_id=str(row.get("group_id", "")),
            element_id="",
            surface_id="",
            type_parameters=dict(row.get("type_parameters", {}) or {}),
            pupil_radius_mm=float(row.get("pupil_radius_mm", 3.0) or 3.0),
        )
        for row in surface_rows
    ]
    project = SimpleNamespace(
        name="780nm 四透镜演示",
        surfaces=namespaces,
        wavelength_nm=780.0,
        version="v1",
        pupil_radius_mm=float(surface_rows[0].get("pupil_radius_mm", 3.0) if surface_rows else 3.0),
    )
    project._canvas_form_config = dict(surface_rows[0].get("_form_config", {}) or {}) if surface_rows else {}
    return project


def default_surface_rows() -> list[dict[str, Any]]:
    """四透镜预设的表面行（画布表格数据源）。"""
    return [dict(spec) for spec in FOUR_LENS_SURFACES]


def form_state(config: dict[str, Any] | None = None) -> SimulationFormState:
    """demo 使用的表单状态（默认值 + 全量分析 + 大数组）。"""
    state = SimulationFormState()
    result = state.__class__(
        **{
            **{f: getattr(state, f) for f in state.__dataclass_fields__},
            "calculation": state.calculation.__class__(
                **{
                    **{f: getattr(state.calculation, f) for f in state.calculation.__dataclass_fields__},
                    "analyses": ANALYSES,
                    "save_large_arrays": True,  # 需要 coupling_field_intensity 等诊断数组
                }
            ),
        }
    )
    config = dict(config or {})
    if not config:
        return result
    auxiliary_wavelengths: tuple[float, ...] = ()
    raw_auxiliary = str(config.get("auxiliary_wavelengths_nm", "") or "")
    if raw_auxiliary:
        values: list[float] = []
        for item in raw_auxiliary.replace("，", ",").split(","):
            try:
                value = float(item.strip())
            except (TypeError, ValueError):
                continue
            if value > 0.0:
                values.append(value)
        auxiliary_wavelengths = tuple(values)
    source = replace(
        result.source,
        source_type=SOURCE_TYPE_MAP.get(str(config.get("source_type", "")), result.source.source_type),
        waist_x_um=float(config.get("source_waist_x_um", result.source.waist_x_um)),
        waist_y_um=float(config.get("source_waist_y_um", result.source.waist_y_um)),
        waist_position_mm=float(config.get("source_waist_position_mm", result.source.waist_position_mm)),
        beam_quality_m2_x=max(1.0, float(config.get("source_m2_x", result.source.beam_quality_m2_x))),
        beam_quality_m2_y=max(1.0, float(config.get("source_m2_y", result.source.beam_quality_m2_y))),
        object_na_x=max(0.0, float(config.get("source_na_x", result.source.object_na_x))),
        object_na_y=max(0.0, float(config.get("source_na_y", result.source.object_na_y))),
        field_x_deg=float(config.get("field_x_deg", result.source.field_x_deg)),
        field_y_deg=float(config.get("field_y_deg", result.source.field_y_deg)),
        power_value=max(0.0, float(config.get("power_value", result.source.power_value))),
        power_unit=str(config.get("power_unit", result.source.power_unit)),
        auxiliary_wavelengths_nm=auxiliary_wavelengths,
    )
    mode_model = {
        "高斯近似": "gaussian", "LP01": "lp01", "HE11": "he11", "导入复场": "imported",
    }.get(str(config.get("mode_model", "")), result.receiver.mode_model)
    receiver = replace(
        result.receiver,
        receiver_type=RECEIVER_TYPE_MAP.get(str(config.get("receiver_type", "")), result.receiver.receiver_type),
        mode_model=mode_model,
        mode_field_diameter_x_um=max(0.1, float(config.get("receiver_mfd_x_um", result.receiver.mode_field_diameter_x_um))),
        mode_field_diameter_y_um=max(0.1, float(config.get("receiver_mfd_y_um", result.receiver.mode_field_diameter_y_um))),
        na_x=max(0.001, float(config.get("receiver_na_x", result.receiver.na_x))),
        na_y=max(0.001, float(config.get("receiver_na_y", result.receiver.na_y))),
        core_diameter_um=max(0.1, float(config.get("receiver_core_diameter_um", result.receiver.core_diameter_um))),
        core_refractive_index=max(0.001, float(config.get("receiver_n_core", result.receiver.core_refractive_index))),
        cladding_refractive_index=max(0.001, float(config.get("receiver_n_clad", result.receiver.cladding_refractive_index))),
        outside_refractive_index=max(0.001, float(config.get("receiver_outside_index", result.receiver.outside_refractive_index))),
        offset_x_um=float(config.get("receiver_offset_x_um", result.receiver.offset_x_um)),
        offset_y_um=float(config.get("receiver_offset_y_um", result.receiver.offset_y_um)),
        axial_offset_z_um=float(config.get("receiver_offset_z_um", result.receiver.axial_offset_z_um)),
        tilt_x_urad=float(config.get("receiver_tilt_x_urad", result.receiver.tilt_x_urad)),
        tilt_y_urad=float(config.get("receiver_tilt_y_urad", result.receiver.tilt_y_urad)),
        endface_transmission=min(1.0, max(0.0, float(config.get("receiver_endface_transmission", result.receiver.endface_transmission)))),
        fiber_length_m=max(0.0, float(config.get("receiver_length_m", result.receiver.fiber_length_m))),
        attenuation_db_per_km=max(0.0, float(config.get("receiver_attenuation_db_per_km", result.receiver.attenuation_db_per_km))),
        connector_loss_db=max(0.0, float(config.get("receiver_connector_loss_db", result.receiver.connector_loss_db))),
        imported_mode_source=str(config.get("imported_mode_source", "") or ""),
    )
    if mode_model == "imported" and receiver.imported_mode_source:
        expected_grid = parse_grid_size(str(config.get("calc_grid", "")), result.calculation.output_grid_size)
        imported = load_complex_field(receiver.imported_mode_source, expected_grid_size=expected_grid)
        receiver = replace(
            receiver,
            imported_mode_real=imported.real,
            imported_mode_imag=imported.imag,
            imported_mode_source=imported.path,
        )
    analyses = tuple(
        key
        for key in ("raytrace", "spot", "psf", "coupling", "mtf", "power_audit")
        if bool(config.get(f"analysis_{key}", True if key in {"raytrace", "spot", "psf", "coupling"} else False))
    )
    calculation = replace(
        result.calculation,
        precision=PRECISION_MAP.get(str(config.get("calc_precision", "")), result.calculation.precision),
        output_grid_size=parse_grid_size(str(config.get("calc_grid", "")), result.calculation.output_grid_size),
        layout_pupil_sample_count=parse_grid_size(str(config.get("calc_layout_pupil", "")), result.calculation.layout_pupil_sample_count),
        pupil_sample_count=parse_grid_size(str(config.get("calc_pupil", "")), result.calculation.pupil_sample_count),
        propagation_model=PROPAGATION_MAP.get(str(config.get("calc_propagation", "")), result.calculation.propagation_model),
        zero_padding_factor=max(1.0, float(config.get("calc_zero_padding", result.calculation.zero_padding_factor))),
        output_extent_mm=max(0.000001, float(config.get("calc_output_extent_mm", result.calculation.output_extent_mm))),
        auto_expand_output=bool(config.get("calc_auto_expand_output", result.calculation.auto_expand_output)),
        only_visible_results=bool(config.get("calc_only_visible_results", result.calculation.only_visible_results)),
        sampling_convergence_enabled=bool(config.get("calc_sampling_convergence", result.calculation.sampling_convergence_enabled)),
        save_large_arrays=bool(config.get("calc_save_large_arrays", result.calculation.save_large_arrays)),
        high_precision_coupling_enabled=bool(config.get("calc_high_precision_coupling", result.calculation.high_precision_coupling_enabled)),
        analyses=analyses or result.calculation.analyses,
    )
    system = replace(
        result.system,
        object_distance_mm=max(0.000001, float(config.get("object_distance_mm", result.system.object_distance_mm))),
        pupil_radius_mm=max(0.000001, float(config.get("pupil_radius_mm", result.system.pupil_radius_mm))),
        image_distance_mm=float(config.get("image_distance_mm", result.system.image_distance_mm)),
        field_x_deg=float(config.get("field_x_deg", result.system.field_x_deg)),
        field_y_deg=float(config.get("field_y_deg", result.system.field_y_deg)),
        auto_best_focus=bool(config.get("auto_best_focus", result.system.auto_best_focus)),
        environment_temperature_c=float(config.get("environment_temperature_c", result.system.environment_temperature_c)),
        environment_pressure_kpa=max(0.0, float(config.get("environment_pressure_kpa", result.system.environment_pressure_kpa))),
        thermal_compensation=bool(config.get("thermal_compensation", result.system.thermal_compensation)),
    )
    alignment = replace(
        result.alignment,
        enabled=bool(config.get("alignment_enabled", result.alignment.enabled)),
        include_dz=bool(config.get("alignment_include_dz", result.alignment.include_dz)),
        max_offset_um=max(0.0, float(config.get("alignment_max_offset_um", result.alignment.max_offset_um))),
        max_axial_offset_um=max(0.0, float(config.get("alignment_max_axial_offset_um", result.alignment.max_axial_offset_um))),
        max_tilt_urad=max(0.0, float(config.get("alignment_max_tilt_urad", result.alignment.max_tilt_urad))),
        max_iterations=max(1, int(config.get("alignment_max_iterations", result.alignment.max_iterations))),
        max_function_evaluations=max(1, int(config.get("alignment_max_function_evaluations", result.alignment.max_function_evaluations))),
        timeout_seconds=max(0.1, float(config.get("alignment_timeout_seconds", result.alignment.timeout_seconds))),
    )
    return result.__class__(source=source, receiver=receiver, system=system, calculation=calculation, alignment=alignment)


def restrict_payload(payload: dict[str, Any], analyses) -> dict[str, Any]:
    """把 payload 限制到指定分析子集（顶层 analyses + project.analysis_settings）。"""
    names = sorted({str(item) for item in analyses if str(item)})
    restricted = dict(payload)
    restricted["analyses"] = names
    project = dict(payload.get("project") or {})
    settings = dict(project.get("analysis_settings") or {})
    settings["requested_analyses"] = list(names)
    project["analysis_settings"] = settings
    restricted["project"] = project
    return restricted


def build_payload(
    surface_rows: list[dict[str, Any]],
    request_id: str,
    analyses: tuple[str, ...] | list[str] | None = None,
) -> dict[str, Any]:
    project = surfaces_to_project(surface_rows)
    payload = build_simulation_payload(project, form_state(getattr(project, "_canvas_form_config", {})))
    payload["request_id"] = request_id
    if analyses:
        payload = restrict_payload(payload, analyses)
    return payload


class EngineBridge(QObject):
    """后台线程运行真实引擎；结果经信号回主线程。

    - run_async(surface_rows) 非阻塞；运行中收到新请求会合并为“最新待跑”；
    - resultReady 携带 version（请求序号），主线程据此丢弃过期结果。
    """

    resultReady = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._engine = None
        self._lock = threading.Lock()
        self._version = 0
        self._busy = False
        self._stopped = False
        self._pending: tuple[list[dict[str, Any]], tuple[str, ...] | None] | None = None

    # ---- 主线程接口 ------------------------------------------------------

    def run_async(self, surface_rows: list[dict[str, Any]], analyses=None) -> int:
        """请求一次仿真，返回请求版本号；busy 时合并为最新待跑。"""
        with self._lock:
            if self._stopped:
                return self._version
            self._version += 1
            version = self._version
            self._pending = (list(surface_rows), tuple(analyses) if analyses else None)
            start_worker = not self._busy
            self._busy = True
        if start_worker:
            threading.Thread(target=self._worker_loop, daemon=True).start()
        return version

    def latest_version(self) -> int:
        return self._version

    def stop(self) -> None:
        """窗口关闭时调用：丢弃待跑请求，禁止再向已销毁的 QObject 发信号。"""
        with self._lock:
            self._stopped = True
            self._pending = None
            self._busy = False
        try:
            self.blockSignals(True)
        except RuntimeError:
            pass

    def _alive(self) -> bool:
        try:
            from shiboken6 import isValid

            return bool(isValid(self))
        except Exception:
            return True

    def _emit_result(self, payload: dict[str, Any]) -> None:
        with self._lock:
            if self._stopped:
                return
        if not self._alive():
            return
        try:
            self.resultReady.emit(payload)
        except RuntimeError:
            return

    # ---- 工作线程 --------------------------------------------------------

    def _ensure_engine(self):
        if self._engine is None:
            from optical_runtime import create_optical_simulation_engine

            self._engine = create_optical_simulation_engine()
        return self._engine

    def _worker_loop(self):
        while True:
            with self._lock:
                if self._stopped:
                    self._busy = False
                    return
                pending = self._pending
                version = self._version
                self._pending = None
                if pending is None:
                    self._busy = False
                    return
                rows, analyses = pending
            try:
                payload = build_payload(rows, f"canvas-{version}-{uuid4().hex[:8]}", analyses)
                request = SimulationRequest(**payload)
                started = time.perf_counter()
                result = self._ensure_engine().evaluate(request)
                elapsed_ms = int((time.perf_counter() - started) * 1000)
                self._emit_result(
                    {
                        "version": version,
                        "status": result.status,
                        "arrays": dict(result.arrays or {}),
                        "metrics": dict(result.metrics or {}),
                        "warnings": list(result.warnings or []),
                        "errors": [str(getattr(e, "message", e)) for e in (result.errors or [])],
                        "elapsed_ms": elapsed_ms,
                    }
                )
            except Exception as exc:  # 引擎异常也要回传，避免 UI 卡在“计算中”
                self._emit_result(
                    {
                        "version": version,
                        "status": "failed",
                        "arrays": {},
                        "metrics": {},
                        "warnings": [],
                        "errors": [repr(exc)],
                        "elapsed_ms": 0,
                    }
                )


__all__ = [
    "ANALYSES",
    "EngineBridge",
    "build_payload",
    "default_surface_rows",
    "form_state",
    "restrict_payload",
    "surfaces_to_project",
]

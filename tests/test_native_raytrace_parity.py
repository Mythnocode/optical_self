"""原生 C++ 光线追迹内核与 Python full 追迹的数值一致性验证。

内核移植自 scalar_raytrace.trace_single_ray_detailed / surface_interaction，
接缝点为 batch_raytrace.trace_ray_batch（coated 系统原本必走 full 慢路径）。
本测试通过运行时上下文取同一条光线束分别走两条路径，逐字段对比
TraceBundle，并对比引擎端到端的耦合指标。
"""

from __future__ import annotations

import os
from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from frontend_pyside.api.payloads import serialize_project
from frontend_pyside.core.shiboken_guard import harden_shiboken_signature_hook
from frontend_pyside.features.simulation.form_state import SimulationFormState
from frontend_pyside.state.project_context import default_project
from optical_core.physics.geometric.solvers.native_trace import native_available
from optical_runtime import create_optical_simulation_engine
from optical_runtime.request_compiler import compile_simulation_context
from shared_contracts.simulation import SimulationRequest

harden_shiboken_signature_hook()

pytestmark = pytest.mark.skipif(
    not native_available(), reason="native optical core DLL 未编译"
)


def _build_request() -> SimulationRequest:
    from machine_learning.datasets.generator import dataset_simulation_options
    from machine_learning.features.coupling_physics import paired_coupling_targets
    from shared_contracts.metrics import analyses_for_metrics, canonical_metric_name
    from shared_contracts.project import ProjectSnapshot

    snapshot = ProjectSnapshot.model_validate(
        serialize_project(default_project(), SimulationFormState())
    )
    targets = paired_coupling_targets(["coupling_loss_db"])
    return SimulationRequest(
        request_id="native-parity",
        project=snapshot,
        analyses=analyses_for_metrics(canonical_metric_name(t) for t in targets),
        parameter_changes=[],
        precision="standard",
        random_seed=1234,
        engine=None,
        options=dataset_simulation_options(snapshot, precision="standard"),
    )


def _trace_bundle(native: bool, record_surfaces: bool):
    request = _build_request()
    previous = os.environ.get("OPTICAL_NATIVE")
    os.environ["OPTICAL_NATIVE"] = "1" if native else "0"
    try:
        context = compile_simulation_context(request)
        context.scene.options.setdefault("hybrid", {})["record_surfaces"] = record_surfaces
        context.scene.options.setdefault("geometric", {})["record_surfaces"] = record_surfaces
        return context.get_or_create_trace()
    finally:
        if previous is None:
            os.environ.pop("OPTICAL_NATIVE", None)
        else:
            os.environ["OPTICAL_NATIVE"] = previous


def _assert_close(a, b, *, rtol=1.0e-8, atol=1.0e-9, name=""):
    a = np.asarray(a)
    b = np.asarray(b)
    if a.size == 0 and b.size == 0:
        return
    nan_equal = np.array_equal(np.isnan(a), np.isnan(b)) if a.dtype.kind == "f" else True
    assert nan_equal, f"{name}: NaN 布局不一致"
    np.testing.assert_allclose(a, b, rtol=rtol, atol=atol, equal_nan=True, err_msg=name)


def test_trace_bundle_parity_against_python_full_tracer() -> None:
    native = _trace_bundle(native=True, record_surfaces=False)
    reference = _trace_bundle(native=False, record_surfaces=False)

    assert native.valid_mask.dtype == bool
    np.testing.assert_array_equal(native.valid_mask, reference.valid_mask)
    assert list(native.status_codes) == list(reference.status_codes)
    assert native.termination_reasons == reference.termination_reasons
    assert len(native.warnings) == len(reference.warnings)
    assert native.surface_physics_applied == reference.surface_physics_applied

    _assert_close(native.final_positions_mm, reference.final_positions_mm, name="final_positions")
    _assert_close(native.final_directions, reference.final_directions, name="final_directions")
    _assert_close(native.optical_paths_mm, reference.optical_paths_mm, rtol=1.0e-9, name="opl")
    _assert_close(native.field_amplitudes, reference.field_amplitudes, name="amplitudes")
    _assert_close(native.power_weights, reference.power_weights, name="power")
    _assert_close(native.quadrature_weights, reference.quadrature_weights, name="quadrature")
    _assert_close(native.phase_offsets_rad, reference.phase_offsets_rad, name="phase")
    _assert_close(
        native.polarization_vectors_xyz,
        reference.polarization_vectors_xyz,
        name="polarization",
    )
    assert native.segment_lengths_mm is not None
    assert native.segment_lengths_mm.shape == reference.segment_lengths_mm.shape
    _assert_close(native.segment_lengths_mm, reference.segment_lengths_mm, name="seg_lengths")
    _assert_close(
        native.segment_refractive_indices, reference.segment_refractive_indices, name="seg_n"
    )
    _assert_close(native.segment_opl_mm, reference.segment_opl_mm, name="seg_opl")
    _assert_close(native.cumulative_opl_mm, reference.cumulative_opl_mm, name="seg_cum")

    assert native.path_points_mm.shape == reference.path_points_mm.shape
    _assert_close(native.path_points_mm, reference.path_points_mm, name="path_points")
    np.testing.assert_array_equal(native.path_offsets, reference.path_offsets)
    np.testing.assert_array_equal(native.path_surface_indices, reference.path_surface_indices)


def test_surface_records_and_interactions_parity() -> None:
    native = _trace_bundle(native=True, record_surfaces=True)
    reference = _trace_bundle(native=False, record_surfaces=True)

    assert set(native.surface_records) == set(reference.surface_records)
    for name, ref_record in reference.surface_records.items():
        nat_record = native.surface_records[name]
        assert nat_record.plane_z_mm == pytest.approx(ref_record.plane_z_mm, rel=1.0e-12)
        _assert_close(nat_record.positions_mm, ref_record.positions_mm, name=f"{name}.positions")
        _assert_close(nat_record.directions, ref_record.directions, name=f"{name}.directions")
        _assert_close(
            nat_record.optical_paths_mm, ref_record.optical_paths_mm, name=f"{name}.opl"
        )
        np.testing.assert_array_equal(nat_record.valid_mask, ref_record.valid_mask)

    # 交互诊断：逐光线逐表面数值字段一致。
    assert len(native.surface_interaction_records) == len(reference.surface_interaction_records)
    for i, (nat_list, ref_list) in enumerate(
        zip(native.surface_interaction_records, reference.surface_interaction_records)
    ):
        assert len(nat_list) == len(ref_list), f"ray {i} 交互记录数不一致"
        for nat_entry, ref_entry in zip(nat_list, ref_list):
            assert nat_entry["surface_index"] == ref_entry["surface_index"]
            assert nat_entry["polarization_model"] == ref_entry["polarization_model"]
            for key, ref_value in ref_entry.items():
                if isinstance(ref_value, float):
                    assert nat_entry[key] == pytest.approx(ref_value, rel=1.0e-7, abs=1.0e-12), (
                        f"ray {i} {key}"
                    )


def test_engine_coupling_metric_parity() -> None:
    request = _build_request()
    os.environ["OPTICAL_NATIVE"] = "0"
    try:
        reference = create_optical_simulation_engine().evaluate(request)
    finally:
        os.environ["OPTICAL_NATIVE"] = "1"
    try:
        native = create_optical_simulation_engine().evaluate(request)
    finally:
        os.environ.pop("OPTICAL_NATIVE", None)

    assert native.status == "completed", native.errors
    assert reference.status == "completed", reference.errors
    for key in ("coupling_efficiency", "total_coupling_efficiency", "coupling_loss_db"):
        if key in reference.metrics:
            assert native.metrics[key] == pytest.approx(reference.metrics[key], rel=1.0e-7), key


def test_invalid_ray_input_parity() -> None:
    from optical_core.models.representations.ray_bundle import RayBundle
    from optical_core.physics.geometric.solvers.batch_raytrace import trace_ray_batch
    from optical_core.physics.geometric.solvers.trace_options import TraceOptions
    from optical_runtime.request_compiler import _read  # noqa: F401  (确保包可用)

    request = _build_request()
    previous = os.environ.get("OPTICAL_NATIVE")
    try:
        os.environ["OPTICAL_NATIVE"] = "0"
        context = compile_simulation_context(request)
        system = context.scene.system
        positions = np.array(
            [[0.0, 0.0, -1.0e-6], [0.1, -0.1, -1.0e-6], [0.0, 0.0, -1.0e-6]],
            dtype=float,
        )
        directions = np.tile([0.0, 0.0, 1.0], (3, 1)).astype(float)
        rays = RayBundle(
            positions_mm=positions,
            directions=directions,
            field_amplitudes=np.array([1.0, 1.0, 1.0]),
            valid_mask=np.array([True, False, True]),
        )
        os.environ["OPTICAL_NATIVE"] = "1"
        native = trace_ray_batch(system, rays, TraceOptions(output_level="final"))
        os.environ["OPTICAL_NATIVE"] = "0"
        reference = trace_ray_batch(system, rays, TraceOptions(output_level="final"))
    finally:
        if previous is None:
            os.environ.pop("OPTICAL_NATIVE", None)
        else:
            os.environ["OPTICAL_NATIVE"] = previous

    np.testing.assert_array_equal(native.valid_mask, reference.valid_mask)
    assert list(native.status_codes) == list(reference.status_codes)
    assert native.termination_reasons == reference.termination_reasons
    _assert_close(native.final_positions_mm, reference.final_positions_mm, name="invalid.final")

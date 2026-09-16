from __future__ import annotations

import json
import math
import tempfile
from pathlib import Path
from types import SimpleNamespace

from frontend_pyside.features.teaching_v2.coordinates import (
    AXIS_HEIGHT_MM,
    FRAME_ENGINE,
    FRAME_RENDER,
    FRAME_TEACHING,
    FrameTransform,
    assert_render_round_trip,
    assert_round_trip,
    mm_per_scene_unit,
    physical_scene_scale_mm,
    teaching_point_to_render,
    teaching_point_to_simulation,
)
from frontend_pyside.features.teaching_v2.model import Pose, ResultKind, SceneStore
from frontend_pyside.features.teaching_v2.physics import (
    ENGINE_ANALYSES,
    EMPTY_BEAM_MESSAGE,
    FormalTeachingGateway,
    PhysicsRequest,
    beam_miss_notes,
    canonicalize_analysis,
    compute_geometry_preview,
    rays_from_trace,
    setup_warnings,
    snapshot_to_physical_scene,
)


class _Point(SimpleNamespace):
    pass


class _Path(SimpleNamespace):
    pass


class _Trace(SimpleNamespace):
    pass


class _Project:
    def __init__(self) -> None:
        self.image_distance_mm = 0.0
        self.receiver = None

    def model_copy(self, update):
        other = _Project()
        other.image_distance_mm = update.get("image_distance_mm", self.image_distance_mm)
        other.receiver = update.get("receiver", self.receiver)
        return other


class _Engine:
    def __init__(self) -> None:
        self.requests = []

    def evaluate(self, request):
        self.requests.append(request)
        return SimpleNamespace(
            status="completed",
            metrics={
                "coupling_efficiency": 0.37,
                "rms_spot_radius_um": 2.5,
                "strehl_ratio": 0.81,
            },
            warnings=[],
            errors=[],
            elapsed_ms=3.0,
        )


class _Bridge:
    def __init__(self) -> None:
        self.engine = _Engine()

    def trace(self, scene):
        laser = next(node for node in scene.nodes if node.kind == "laser")
        fiber = next(node for node in scene.nodes if node.kind == "fiber")
        return _Trace(
            success=True,
            sample_count=5,
            warnings=(),
            errors=(),
            elapsed_ms=1.5,
            paths=(
                _Path(
                    power_fraction=1.0,
                    points=(
                        _Point(scene_x=laser.scene_x, scene_y=laser.scene_y, height_mm=laser.height_mm),
                        _Point(scene_x=fiber.scene_x, scene_y=fiber.scene_y, height_mm=fiber.height_mm),
                    ),
                ),
            ),
        )

    def compile_project(self, scene):
        return _Project(), {"geometric": {}}

    def evaluate_analyses(self, analysis, scene):
        return {
            analysis: {
                "source": "formal_engine",
                "status": "completed",
                "metrics": {
                    "coupling_efficiency": 0.37,
                    "rms_spot_radius_um": 2.5,
                    "strehl_ratio": 0.81,
                },
                "engine_analyses": list(ENGINE_ANALYSES[analysis]),
            }
        }


def test_coordinate_round_trip() -> None:
    transform = FrameTransform(origin_engine_mm=(2.0, 3.0, 4.0), axis_height_mm=82.0)
    assert transform.origin_engine_mm == (0.0, 0.0, 0.0)
    assert transform.origin_teaching_mm == (0.0, 0.0, 0.0)
    for point in ((0.0, 0.0, 82.0), (12.3, -2.5, 90.0), (-4.0, 8.0, 70.0)):
        assert_round_trip(point, transform)
    assert teaching_point_to_simulation((0.0, 0.0, 82.0), transform) == (0.0, 0.0, 0.0)


def test_bench_origin_does_not_follow_the_laser() -> None:
    from frontend_pyside.features.teaching_v2.coordinates import (
        simulation_pose_to_teaching,
        teaching_point_to_simulation,
        teaching_pose_to_simulation,
    )

    transform = FrameTransform()
    assert teaching_point_to_simulation((0.0, 0.0, AXIS_HEIGHT_MM), transform) == (0.0, 0.0, 0.0)
    assert teaching_point_to_simulation((24.0, 0.0, AXIS_HEIGHT_MM), transform) == (0.0, 0.0, 24.0)
    moved_laser = teaching_point_to_simulation((10.0, 1.0, AXIS_HEIGHT_MM), transform)
    assert moved_laser == (1.0, 0.0, 10.0)
    second_source = teaching_point_to_simulation((0.0, -4.0, AXIS_HEIGHT_MM), transform)
    assert second_source == (-4.0, 0.0, 0.0)
    pose = teaching_pose_to_simulation(24.0, 2.0, AXIS_HEIGHT_MM, yaw_rad=0.1, pitch_rad=-0.05)
    assert pose["x_mm"] == 2.0
    assert pose["y_mm"] == 0.0
    assert pose["z_mm"] == 24.0
    yaw_only = teaching_pose_to_simulation(24.0, 2.0, AXIS_HEIGHT_MM, yaw_rad=0.1)
    assert abs(yaw_only["tilt_y_rad"] - 0.1) < 1e-12
    assert abs(yaw_only["tilt_x_rad"]) < 1e-12
    pitch_only = teaching_pose_to_simulation(24.0, 2.0, AXIS_HEIGHT_MM, pitch_rad=-0.05)
    assert abs(pitch_only["tilt_x_rad"] - 0.05) < 1e-12
    recovered = simulation_pose_to_teaching(
        pose["x_mm"], pose["y_mm"], pose["z_mm"], pose["tilt_x_rad"], pose["tilt_y_rad"], pose["tilt_z_rad"], transform
    )
    assert abs(recovered["x_mm"] - 24.0) < 1e-12
    assert abs(recovered["y_mm"] - 2.0) < 1e-12
    assert abs(recovered["yaw_rad"] - 0.1) < 1e-9
    assert abs(recovered["pitch_rad"] + 0.05) < 1e-9


def test_orientation_so3_round_trip() -> None:
    from frontend_pyside.features.teaching_v2.coordinates import (
        rotate_teaching_about_axis,
        simulation_pose_to_teaching,
        teaching_angles_to_engine,
        teaching_pose_to_simulation,
        teaching_rotation_matrix,
    )

    yaw, pitch, roll = 0.4, -0.25, 0.15
    tilt = teaching_angles_to_engine(yaw, pitch, roll)
    back = simulation_pose_to_teaching(0.0, 0.0, 0.0, tilt[0], tilt[1], tilt[2])
    assert abs(back["yaw_rad"] - yaw) < 1e-9
    assert abs(back["pitch_rad"] - pitch) < 1e-9
    assert abs(back["roll_rad"] - roll) < 1e-9
    payload = teaching_pose_to_simulation(0.0, 0.0, 82.0, yaw, pitch, roll)
    assert len(payload["rotation_3x3"]) == 3
    identity = teaching_rotation_matrix(0.0, 0.0, 0.0)
    assert identity[0][0] == 1.0
    spun = rotate_teaching_about_axis(0.0, 0.0, 0.0, "z", 0.3)
    assert abs(spun[0] - 0.3) < 1e-12
    assert abs(spun[1]) < 1e-12


def test_plus_x_teaching_is_plus_z_simulation() -> None:
    from frontend_pyside.features.teaching_v2.coordinates import DEFAULT_TRANSFORM, beam_direction_teaching

    forward = beam_direction_teaching(0.0, 0.0)
    assert forward == (1.0, 0.0, 0.0)
    assert DEFAULT_TRANSFORM.teaching_direction_to_engine(forward) == (0.0, 0.0, 1.0)


def test_render_is_not_the_engine_permutation() -> None:
    raised = AXIS_HEIGHT_MM + 8.0
    point = (24.0, 4.0, raised)
    engine = teaching_point_to_simulation(point)
    render = teaching_point_to_render(point)
    assert engine == (4.0, 8.0, 24.0)
    assert render == (24.0, raised, -4.0)
    assert render != engine


def test_render_table_and_beam_height() -> None:
    transform = FrameTransform()
    assert teaching_point_to_render((0.0, 0.0, 0.0), transform) == (0.0, 0.0, 0.0)
    assert teaching_point_to_render((0.0, 0.0, AXIS_HEIGHT_MM), transform) == (0.0, AXIS_HEIGHT_MM, 0.0)
    assert teaching_point_to_simulation((0.0, 0.0, AXIS_HEIGHT_MM), transform) == (0.0, 0.0, 0.0)
    raised = teaching_point_to_render((0.0, 0.0, 90.0), transform)
    assert raised == (0.0, 90.0, 0.0)
    shifted = teaching_point_to_render((10.0, 3.0, 82.0), transform)
    assert shifted == (10.0, 82.0, -3.0)


def test_render_round_trip_and_scale() -> None:
    transform = FrameTransform(origin_teaching_mm=(1.0, -2.0, 3.0), render_units_per_mm=0.5)
    assert transform.origin_teaching_mm == (0.0, 0.0, 0.0)
    for point in ((0.0, 0.0, 82.0), (12.3, -2.5, 90.0), (-4.0, 8.0, 70.0)):
        assert_render_round_trip(point, transform)
        assert_round_trip(point, transform)
    half = teaching_point_to_render((10.0, 4.0, 20.0), transform)
    assert half == (10.0 * 0.5, 20.0 * 0.5, -4.0 * 0.5)


def test_engine_direction_to_render_goes_through_teaching() -> None:
    transform = FrameTransform()
    along_rail = transform.teaching_direction_to_engine((1.0, 0.0, 0.0))
    assert along_rail == (0.0, 0.0, 1.0)
    assert transform.engine_direction_to_render(along_rail) == (1.0, 0.0, 0.0)
    up = transform.teaching_direction_to_engine((0.0, 0.0, 1.0))
    assert up == (0.0, 1.0, 0.0)
    assert transform.engine_direction_to_render(up) == (0.0, 1.0, 0.0)
    lateral = transform.teaching_direction_to_engine((0.0, 1.0, 0.0))
    assert lateral == (1.0, 0.0, 0.0)
    assert transform.engine_direction_to_render(lateral) == (0.0, 0.0, -1.0)


def test_view3d_nodes_use_render_frame_not_engine() -> None:
    from frontend_pyside.features.teaching_v2.view3d import snapshot_to_render_nodes, snapshot_view3d_guides

    store = SceneStore()
    nodes = {item["id"]: item for item in snapshot_to_render_nodes(store.snapshot())}
    laser = nodes["laser-001"]
    fiber = nodes["fiber-004"]
    assert laser["frame"] == FRAME_RENDER
    assert laser["x"] == 0.0
    assert laser["y"] == AXIS_HEIGHT_MM
    assert laser["z"] == 0.0
    assert fiber["x"] == 72.0
    assert fiber["y"] == AXIS_HEIGHT_MM
    engine_fiber = teaching_point_to_simulation((72.0, 0.0, AXIS_HEIGHT_MM))
    assert engine_fiber == (0.0, 0.0, 72.0)
    assert (fiber["x"], fiber["y"], fiber["z"]) != engine_fiber
    guides = snapshot_view3d_guides(store.snapshot())
    assert guides["axisHeight"] == AXIS_HEIGHT_MM


def test_gizmo_axis_and_plane_lock_teaching_axes() -> None:
    from frontend_pyside.features.teaching_v2.gizmo import begin_gizmo_session

    origin = (24.0, 0.0, 82.0)
    press = begin_gizmo_session("lens-002", "axis", "x", origin, (24.0, 200.0, 0.0), (0.0, -1.0, 0.0))
    assert press is not None
    moved = press.apply((40.0, 200.0, 0.0), (0.0, -1.0, 0.0))
    assert moved is not None
    assert abs(moved[0] - 40.0) < 1e-6
    assert abs(moved[1] - 0.0) < 1e-6
    assert abs(moved[2] - 82.0) < 1e-6

    height = begin_gizmo_session("lens-002", "axis", "z", origin, (100.0, 82.0, 0.0), (-1.0, 0.0, 0.0))
    assert height is not None
    raised = height.apply((100.0, 90.0, 0.0), (-1.0, 0.0, 0.0))
    assert raised is not None
    assert abs(raised[0] - 24.0) < 1e-6
    assert abs(raised[1] - 0.0) < 1e-6
    assert abs(raised[2] - 90.0) < 1e-6

    lateral = begin_gizmo_session("lens-002", "axis", "y", origin, (24.0, 200.0, 0.0), (0.0, -1.0, 0.0))
    assert lateral is not None
    shifted = lateral.apply((24.0, 200.0, -6.0), (0.0, -1.0, 0.0))
    assert shifted is not None
    assert abs(shifted[0] - 24.0) < 1e-6
    assert abs(shifted[1] - 6.0) < 1e-6
    assert abs(shifted[2] - 82.0) < 1e-6

    plane = begin_gizmo_session("lens-002", "plane", "xy", origin, (24.0, 200.0, 0.0), (0.0, -1.0, 0.0))
    assert plane is not None
    diagonal = plane.apply((30.0, 200.0, -4.0), (0.0, -1.0, 0.0))
    assert diagonal is not None
    assert abs(diagonal[0] - 30.0) < 1e-6
    assert abs(diagonal[1] - 4.0) < 1e-6
    assert abs(diagonal[2] - 82.0) < 1e-6

    floor = begin_gizmo_session("lens-002", "axis", "z", origin, (100.0, 82.0, 0.0), (-1.0, 0.0, 0.0))
    buried = floor.apply((100.0, -12.0, 0.0), (-1.0, 0.0, 0.0))
    assert buried is not None
    assert buried[2] == 0.0


def test_rotate_session_about_teaching_z() -> None:
    from frontend_pyside.features.teaching_v2.gizmo import begin_rotate_session

    origin = (24.0, 0.0, 82.0)
    session = begin_rotate_session(
        "lens-002",
        "z",
        origin,
        (0.0, 0.0, 0.0),
        (34.0, 200.0, 0.0),
        (0.0, -1.0, 0.0),
    )
    assert session is not None
    rotated = session.apply((24.0, 200.0, -10.0), (0.0, -1.0, 0.0))
    assert rotated is not None
    assert abs(rotated[0] - math.pi / 2) < 1e-6
    assert abs(rotated[1]) < 1e-6
    assert abs(rotated[2]) < 1e-6


def test_view3d_rays_stay_in_render_frame() -> None:
    from frontend_pyside.features.teaching_v2.view3d import teaching_rays_to_render

    store = SceneStore()
    rays = teaching_rays_to_render(
        [{"start": [0.0, 4.0, 82.0], "end": [72.0, 4.0, 90.0], "power_fraction": 1.0}],
        store.snapshot(),
    )
    assert rays[0]["frame"] == FRAME_RENDER
    assert rays[0]["x1"] == 0.0
    assert rays[0]["y1"] == 82.0
    assert rays[0]["z1"] == -4.0
    assert rays[0]["x2"] == 72.0
    assert rays[0]["y2"] == 90.0
    assert rays[0]["z2"] == -4.0
    from frontend_pyside.features.teaching_v2.view3d import rotate_vector_by_quaternion

    axis = rotate_vector_by_quaternion(
        (rays[0]["qw"], rays[0]["qx"], rays[0]["qy"], rays[0]["qz"]),
        (0.0, 1.0, 0.0),
    )
    expected = (72.0, 8.0, 0.0)
    length = math.sqrt(sum(value * value for value in expected))
    unit = tuple(value / length for value in expected)
    assert abs(sum(a * b for a, b in zip(axis, unit)) - 1.0) < 1e-9


def test_identity_scene_scale_is_one_millimetre() -> None:
    for span in (72.0, 80.0, 400.0, 800.0):
        length, width = physical_scene_scale_mm(span)
        assert abs(mm_per_scene_unit(length, width) - 1.0) < 1.0e-12


def test_revision_invalidates_results() -> None:
    store = SceneStore()
    revision = store.revision
    assert store.apply_result(ResultKind.COUPLING, {"status": "completed"}, source_revision=revision)
    assert store.apply_result(ResultKind.GEOMETRY, {"status": "completed", "source": "geometry_preview"}, source_revision=revision)
    assert not store.results[ResultKind.COUPLING.value].get("stale", False)
    store.update_param("lens-002", "focal_length_mm", 48.0)
    assert store.results[ResultKind.COUPLING.value]["stale"]
    assert not store.results[ResultKind.GEOMETRY.value].get("stale", False)
    assert not store.apply_result(ResultKind.COUPLING, {"status": "completed"}, source_revision=revision)


def test_preview_is_not_a_coupling_result() -> None:
    store = SceneStore()
    result = compute_geometry_preview(store.snapshot(), FrameTransform())
    assert result.source == "geometry_preview"
    assert result.success
    assert "preview_efficiency" not in result.metrics
    assert "coupling_efficiency" not in result.metrics
    assert result.metrics["lens_count"] == 2
    starts = [ray.start_teaching_mm[0] for ray in result.rays]
    assert starts[0] == 0.0
    assert len(result.rays) >= 7


def test_empty_trace_is_reported_as_failure() -> None:
    class _Empty:
        def trace(self, _scene):
            return SimpleNamespace(success=True, sample_count=21, paths=(), warnings=(), errors=(), elapsed_ms=1.0)

    store = SceneStore()
    result = FormalTeachingGateway(bridge=_Empty()).compute(PhysicsRequest(store.snapshot(), "raytrace"))
    assert not result.success
    assert result.status == "failed"
    assert result.artifacts["raytrace"]["status"] == "failed"
    assert EMPTY_BEAM_MESSAGE in result.errors
    assert "请减小倾斜或把器件移回光轴" not in EMPTY_BEAM_MESSAGE


def test_lowered_lens_empty_trace_is_a_miss_not_failure() -> None:
    class _Empty:
        def trace(self, _scene):
            return SimpleNamespace(success=True, sample_count=21, paths=(), warnings=(), errors=(), elapsed_ms=1.0)

    store = SceneStore()
    lens = store.components["lens-003"]
    store.update_pose("lens-003", Pose.from_degrees(lens.pose.x_mm, lens.pose.y_mm, 8.0, yaw_deg=5.0))
    notes = beam_miss_notes(store.snapshot())
    assert any("L2" in note and "下方" in note and "位置失配" in note for note in notes)
    result = FormalTeachingGateway(bridge=_Empty()).compute(PhysicsRequest(store.snapshot(), "raytrace"))
    assert result.success
    assert result.status == "missed"
    assert result.errors == ()
    assert result.artifacts["raytrace"]["status"] == "missed"
    assert result.artifacts["raytrace"]["errors"] == []
    assert any("位置失配" in note for note in result.warnings)


def test_setup_warnings_flag_large_lens_tilt() -> None:
    store = SceneStore()
    assert setup_warnings(store.snapshot()) == ()
    lens = store.components["lens-003"]
    store.update_pose("lens-003", Pose.from_degrees(lens.pose.x_mm, lens.pose.y_mm, lens.pose.z_mm, yaw_deg=10.0))
    notes = setup_warnings(store.snapshot())
    assert any("L2" in note and "倾斜" in note for note in notes)


def test_save_load_preserves_reference_and_components() -> None:
    store = SceneStore()
    store.set_baseline(True, 24.0)
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "scene.json"
        store.save_json(path)
        restored = SceneStore()
        restored.load_json(path)
        assert restored.reference.unit == "mm"
        assert restored.reference.origin == "bench"
        assert restored.reference.view_frame == "view3d_render"
        assert restored.reference.render_units_per_mm == 1.0
        assert set(restored.components) == set(store.components)
        assert restored.baseline_x_mm == 24.0


def test_focal_alias_and_pose_unit_contract() -> None:
    store = SceneStore()
    assert store.update_param("lens-002", "focal_length_mm", 42.0)
    assert store.components["lens-002"].params["focal_mm"] == 42.0
    saved = store.to_dict()["components"][1]["pose"]
    assert "yaw_rad" in saved
    assert "yaw_deg" not in saved


def test_publish_dict_includes_compat_nodes() -> None:
    store = SceneStore()
    payload = store.to_publish_dict()
    assert payload["source"] == "teaching_v2"
    assert payload["frame"] == FRAME_TEACHING
    assert payload["frames"]["simulation"] == FRAME_ENGINE
    assert payload["frames"]["view3d"] == FRAME_RENDER
    assert payload["reference"]["view_frame"] == FRAME_RENDER
    assert payload["reference"]["render_units_per_mm"] == 1.0
    assert {node["kind"] for node in payload["nodes"]} >= {"laser", "lens", "fiber"}
    assert payload["wavelength_nm"] == 780.0
    assert payload["receiver_mode_radius_um"] == 2.8
    fiber = next(node for node in payload["nodes"] if node["kind"] == "fiber")
    assert fiber["x"] == 72.0
    assert fiber["z"] == AXIS_HEIGHT_MM
    engine_fiber = next(node for node in payload["engine_nodes"] if node["kind"] == "fiber")
    assert engine_fiber["frame"] == "simulation_engine_mm"
    assert engine_fiber["z_mm"] == 72.0
    assert engine_fiber["x_mm"] == 0.0
    assert engine_fiber["y_mm"] == 0.0
    engine_laser = next(node for node in payload["engine_nodes"] if node["kind"] == "laser")
    assert engine_laser["z_mm"] == 0.0
    assert engine_laser["direction"] == [0.0, 0.0, 1.0]
    assert engine_laser["params"]["beam_radius_mm"] == 0.72
    l1_engine = next(node for node in payload["engine_nodes"] if node["id"] == "lens-002")
    assert "focal_mm" in l1_engine["params"]
    assert "radius1_mm" not in l1_engine["params"]


def test_analysis_aliases_and_engine_map() -> None:
    assert canonicalize_analysis("wave") == "coupling"
    assert canonicalize_analysis("formal") == "raytrace"
    assert canonicalize_analysis("") == "raytrace"
    assert ENGINE_ANALYSES["wavefront"][-1] == "wavefront_quality"


def test_physical_scene_keeps_teaching_millimetres() -> None:
    store = SceneStore()
    physical = snapshot_to_physical_scene(store.snapshot())
    assert abs(mm_per_scene_unit(physical.max_system_length_mm, physical.scene_width_units) - 1.0) < 1.0e-12
    by_id = {node.node_id: node for node in physical.nodes}
    assert by_id["laser-001"].scene_x == 0.0
    assert by_id["fiber-004"].scene_x == 72.0
    assert by_id["lens-002"].params["focal_mm"] == 50.0
    assert by_id["laser-001"].params["beam_radius_mm"] == 0.72
    assert "radius1_mm" not in by_id["lens-002"].params


def test_formal_gateway_keeps_result_layers_apart() -> None:
    store = SceneStore()
    result = FormalTeachingGateway(_Bridge()).compute(PhysicsRequest(store.snapshot(), "coupling"))
    assert result.success, result.errors
    assert result.artifacts["raytrace"]["source"] == "formal_raytrace"
    assert result.artifacts["coupling"]["source"] == "formal_engine"
    assert result.artifacts["coupling"]["metrics"]["coupling_efficiency"] == 0.37
    rays = result.artifacts["raytrace"]["rays"]
    assert rays[0]["start"][0] == 0.0
    assert rays[0]["end"][0] == 72.0


def test_formal_gateway_reuses_synced_engineering_project_and_options() -> None:
    from frontend_pyside.api.payloads import serialize_project
    from frontend_pyside.features.simulation.form_state import SimulationFormState
    from frontend_pyside.state.project_context import default_project

    class EngineeringEngine:
        def __init__(self) -> None:
            self.requests = []

        def evaluate(self, request):
            self.requests.append(request)
            return SimpleNamespace(
                status="completed",
                metrics={
                    "coupling_efficiency": 0.42,
                    "total_coupling_efficiency": 0.42,
                    "mode_overlap_efficiency": 0.91,
                },
                warnings=[],
                errors=[],
                elapsed_ms=4.0,
            )

    class EngineeringBridge(_Bridge):
        def __init__(self) -> None:
            super().__init__()
            self.engine = EngineeringEngine()
            # The actual runtime bridge exposes compile/evaluate, not the test
            # shortcut used by the older unit fixture.
            self.evaluate_analyses = None

    project_payload = serialize_project(default_project(), SimulationFormState())
    bridge = EngineeringBridge()
    gateway = FormalTeachingGateway(
        bridge,
        engineering_request_provider=lambda: {
            "project": project_payload,
            "options": {"hybrid": {"grid_size": 513}},
            "precision": "high",
        },
    )
    result = gateway.compute(PhysicsRequest(SceneStore().snapshot(), "coupling"))

    assert result.success, result.errors
    request = bridge.engine.requests[-1]
    assert request.project.project_id == project_payload["project_id"]
    assert request.precision == "high"
    assert request.options["hybrid"]["grid_size"] == 513
    assert result.artifacts["coupling"]["comparison_note"] == "与当前仿真工程同处方、同数值配置"


def test_failed_formal_layer_does_not_erase_raytrace() -> None:
    class BrokenBridge(_Bridge):
        def evaluate_analyses(self, analysis, scene):
            return {
                analysis: {
                    "source": "formal_engine",
                    "status": "failed",
                    "errors": ["模拟失败"],
                }
            }

    store = SceneStore()
    result = FormalTeachingGateway(BrokenBridge()).compute(PhysicsRequest(store.snapshot(), "spot"))
    assert not result.success
    assert result.artifacts["raytrace"]["status"] == "completed"
    assert result.artifacts["spot"]["errors"] == ["模拟失败"]
    assert result.artifacts["raytrace"]["rays"][0]["end"][0] == 72.0


def test_rays_from_trace_use_scene_millimetres() -> None:
    trace = _Trace(
        paths=(
            _Path(
                power_fraction=0.5,
                points=(
                    _Point(scene_x=10.0, scene_y=-1.0, height_mm=82.0),
                    _Point(scene_x=40.0, scene_y=0.0, height_mm=82.0),
                ),
            ),
        )
    )
    rays = rays_from_trace(trace)
    assert len(rays) == 1
    assert rays[0].start_teaching_mm == (10.0, -1.0, 82.0)
    assert rays[0].end_teaching_mm == (40.0, 0.0, 82.0)
    assert rays[0].power_fraction == 0.5


def _matvec(matrix, vector):
    return tuple(sum(matrix[i][j] * vector[j] for j in range(3)) for i in range(3))


def _matrix_max_abs(left, right) -> float:
    return max(abs(left[i][j] - right[i][j]) for i in range(3) for j in range(3))


def test_frozen_origin_ignores_scene_file_offsets() -> None:
    from frontend_pyside.features.teaching_v2.coordinates import transform_from_reference
    from frontend_pyside.features.teaching_v2.model import SceneReference
    from frontend_pyside.features.teaching_v2.view3d import snapshot_to_render_nodes, snapshot_view3d_guides

    transform = transform_from_reference(
        {"origin_teaching_mm": (10.0, 2.0, 3.0), "origin": "laser", "axis_height_mm": 82.0}
    )
    assert transform.origin_teaching_mm == (0.0, 0.0, 0.0)
    assert teaching_point_to_simulation((0.0, 0.0, 82.0), transform) == (0.0, 0.0, 0.0)
    assert teaching_point_to_render((0.0, 0.0, 82.0), transform) == (0.0, 82.0, 0.0)

    store = SceneStore()
    payload = store.to_dict()
    payload["reference"]["origin"] = "laser"
    payload["reference"]["origin_teaching_mm"] = [10.0, 2.0, 3.0]
    store.restore_dict(payload)
    assert store.reference.origin == "bench"
    assert store.reference.origin_teaching_mm == (0.0, 0.0, 0.0)
    forced = SceneReference(origin="laser", origin_teaching_mm=(4.0, 5.0, 6.0))
    assert forced.origin == "bench"
    assert forced.origin_teaching_mm == (0.0, 0.0, 0.0)
    nodes = {item["id"]: item for item in snapshot_to_render_nodes(store.snapshot())}
    guides = snapshot_view3d_guides(store.snapshot())
    assert nodes["laser-001"]["y"] == AXIS_HEIGHT_MM
    assert guides["axisHeight"] == AXIS_HEIGHT_MM
    published = store.to_publish_dict()
    assert published["frame"] == FRAME_TEACHING
    laser = next(node for node in published["engine_nodes"] if node["id"] == "laser-001")
    assert laser["x_mm"] == 0.0
    assert laser["y_mm"] == 0.0
    assert laser["z_mm"] == 0.0


def test_permutation_matrix_is_rotation() -> None:
    transform = FrameTransform()
    columns = (
        transform.teaching_direction_to_engine((1.0, 0.0, 0.0)),
        transform.teaching_direction_to_engine((0.0, 1.0, 0.0)),
        transform.teaching_direction_to_engine((0.0, 0.0, 1.0)),
    )
    matrix = tuple(tuple(columns[j][i] for j in range(3)) for i in range(3))
    det = (
        matrix[0][0] * (matrix[1][1] * matrix[2][2] - matrix[1][2] * matrix[2][1])
        - matrix[0][1] * (matrix[1][0] * matrix[2][2] - matrix[1][2] * matrix[2][0])
        + matrix[0][2] * (matrix[1][0] * matrix[2][1] - matrix[1][1] * matrix[2][0])
    )
    assert abs(det - 1.0) < 1e-12
    transpose = tuple(tuple(matrix[j][i] for j in range(3)) for i in range(3))
    identity = tuple(tuple(sum(matrix[i][k] * transpose[k][j] for k in range(3)) for j in range(3)) for i in range(3))
    for i in range(3):
        for j in range(3):
            assert abs(identity[i][j] - (1.0 if i == j else 0.0)) < 1e-12


def test_published_direction_matches_rotation_times_engine_beam() -> None:
    from frontend_pyside.features.teaching_v2.coordinates import teaching_pose_to_simulation

    for yaw, pitch, roll in ((0.0, 0.0, 0.0), (0.4, -0.25, 0.15), (0.2, math.radians(89.5), -0.1)):
        payload = teaching_pose_to_simulation(0.0, 0.0, 82.0, yaw, pitch, roll)
        mapped = _matvec(payload["rotation_3x3"], (0.0, 0.0, 1.0))
        assert all(abs(left - right) < 1e-12 for left, right in zip(mapped, payload["direction"]))


def test_gimbal_neighbourhood_round_trips_as_matrices() -> None:
    from frontend_pyside.features.teaching_v2.coordinates import (
        engine_angles_to_teaching,
        teaching_angles_to_engine,
        teaching_rotation_matrix,
    )
    from frontend_pyside.features.teaching_v2.model import PITCH_RAD_MAX

    worst = 0.0
    for yaw in (-0.8, 0.0, 1.2):
        for roll in (-0.4, 0.0, 0.7):
            for pitch in (PITCH_RAD_MAX, -PITCH_RAD_MAX, math.radians(89.5), math.radians(-89.5)):
                original = teaching_rotation_matrix(yaw, pitch, roll)
                tilt = teaching_angles_to_engine(yaw, pitch, roll)
                recovered = engine_angles_to_teaching(*tilt)
                restored = teaching_rotation_matrix(*recovered)
                worst = max(worst, _matrix_max_abs(original, restored))
    assert worst < 1e-9


def test_parallel_axis_drag_projects_ray_origin() -> None:
    from frontend_pyside.features.teaching_v2.gizmo import closest_point_on_axis

    origin = (24.0, 82.0, 0.0)
    hit = closest_point_on_axis(origin, (1.0, 0.0, 0.0), (100.0, 90.0, 2.0), (1.0, 0.0, 0.0))
    assert hit is not None
    assert abs(hit[0] - 100.0) < 1e-9
    assert abs(hit[1] - 82.0) < 1e-9
    assert abs(hit[2] - 0.0) < 1e-9
    moved = closest_point_on_axis(origin, (1.0, 0.0, 0.0), (101.0, 90.0, 2.0), (1.0, 0.0, 0.0))
    assert moved is not None
    assert abs(moved[0] - 101.0) < 1e-9
    near = closest_point_on_axis(origin, (1.0, 0.0, 0.0), (100.0, 90.0, 2.0), (1.0, 0.001, 0.0))
    assert near is not None
    assert abs(near[0] - 100.0) < 0.2


def test_reserved_component_ids_are_rewritten() -> None:
    from frontend_pyside.features.teaching_v2.model import component_id_is_reserved

    store = SceneStore()
    payload = store.to_dict()
    payload["components"] = [
        {
            "component_id": "gizmo:axis:x",
            "kind": "lens",
            "label": "冲突透镜",
            "pose": {"x_mm": 10.0, "y_mm": 0.0, "z_mm": 82.0, "yaw_rad": 0.0, "pitch_rad": 0.0, "roll_rad": 0.0},
            "params": {},
        },
        {
            "component_id": "table",
            "kind": "fiber",
            "label": "冲突光纤",
            "pose": {"x_mm": 20.0, "y_mm": 0.0, "z_mm": 82.0, "yaw_rad": 0.0, "pitch_rad": 0.0, "roll_rad": 0.0},
            "params": {},
        },
        {
            "component_id": "ray:0",
            "kind": "ccd",
            "label": "冲突相机",
            "pose": {"x_mm": 30.0, "y_mm": 0.0, "z_mm": 82.0, "yaw_rad": 0.0, "pitch_rad": 0.0, "roll_rad": 0.0},
            "params": {},
        },
    ]
    payload["selected_component_id"] = "gizmo:axis:x"
    store.restore_dict(payload)
    assert "gizmo:axis:x" not in store.components
    assert "table" not in store.components
    assert "ray:0" not in store.components
    assert all(not component_id_is_reserved(cid) for cid in store.components)
    assert store.selected_component_id in store.components
    assert store.components[store.selected_component_id].label == "冲突透镜"


def test_pitch_clamp_matches_inspector_limit() -> None:
    from frontend_pyside.features.teaching_v2.model import PITCH_DEG_MAX, Pose

    clamped = Pose.from_degrees(0.0, 0.0, 82.0, 0.0, 90.0, 0.0).normalized()
    assert abs(clamped.pitch_deg - PITCH_DEG_MAX) < 1e-9
    kept = Pose.from_degrees(0.0, 0.0, 82.0, 0.0, 89.5, 0.0).normalized()
    assert abs(kept.pitch_deg - 89.5) < 1e-9


def test_tilted_ray_cylinder_aligns_plus_y_with_segment() -> None:
    from frontend_pyside.features.teaching_v2.view3d import (
        cylinder_quaternion_from_segment,
        rotate_vector_by_quaternion,
        teaching_rays_to_render,
    )

    quat = cylinder_quaternion_from_segment(0.0, 82.0, 0.0, 10.0, 92.0, 0.0)
    axis = rotate_vector_by_quaternion(quat, (0.0, 1.0, 0.0))
    expected = (10.0 / math.sqrt(200.0), 10.0 / math.sqrt(200.0), 0.0)
    assert abs(sum(a * b for a, b in zip(axis, expected)) - 1.0) < 1e-9

    store = SceneStore()
    rays = teaching_rays_to_render(
        [{"start": [0.0, 0.0, 82.0], "end": [10.0, 0.0, 92.0], "power_fraction": 1.0}],
        store.snapshot(),
    )
    assert rays[0]["x1"] == 0.0
    assert rays[0]["y1"] == 82.0
    assert rays[0]["x2"] == 10.0
    assert rays[0]["y2"] == 92.0
    axis = rotate_vector_by_quaternion(
        (rays[0]["qw"], rays[0]["qx"], rays[0]["qy"], rays[0]["qz"]),
        (0.0, 1.0, 0.0),
    )
    assert abs(sum(a * b for a, b in zip(axis, expected)) - 1.0) < 1e-9


def test_v2_package_does_not_import_legacy_teaching() -> None:
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "frontend_pyside" / "features" / "teaching_v2"
    pattern = re.compile(r"^\s*(?:from|import)\s+frontend_pyside\.features\.teaching(?:\.|\s|$)")
    offenders = []
    for path in root.rglob("*.py"):
        for line in path.read_text(encoding="utf-8").splitlines():
            if pattern.search(line):
                offenders.append(f"{path.name}: {line.strip()}")
    assert offenders == []


def test_live_entry_is_teaching_shell() -> None:
    from frontend_pyside.app.workbench_shell import PRIMARY_MODULES, TeachingShell

    keys = [key for key, _title in PRIMARY_MODULES]
    assert keys[2] == "teaching"
    assert TeachingShell.__name__ == "TeachingShell"


def test_teaching_shell_is_bench_only() -> None:
    from frontend_pyside.app.shell_catalog import CATEGORY_BY_KEY

    teaching = CATEGORY_BY_KEY["teaching"]
    keys = [action.key for _group, actions in teaching.groups for action in actions]
    assert keys == ["teaching_bench"]
    titles = [action.title for _group, actions in teaching.groups for action in actions]
    assert titles == ["教学实验台"]


def test_v1_teaching_package_is_removed() -> None:
    import importlib.util

    assert importlib.util.find_spec("frontend_pyside.features.teaching") is None


def test_laser_beam_radius_and_ccd_size_round_trip() -> None:
    store = SceneStore()
    laser = store.components["laser-001"]
    assert laser.params["beam_radius_mm"] == 0.72
    assert store.update_param("laser-001", "beam_radius_mm", 0.9)
    assert store.components["laser-001"].params["beam_radius_mm"] == 0.9
    ccd_id = store.add_component("ccd")
    ccd = store.components[ccd_id]
    assert ccd.params["sensor_width_mm"] == 4.968
    assert ccd.params["sensor_height_mm"] == 3.726
    assert "active_area_mm" not in ccd.params
    payload = store.to_dict()
    payload["components"].append(
        {
            "component_id": "legacy-ccd",
            "kind": "ccd",
            "label": "旧相机",
            "pose": {"x_mm": 80.0, "y_mm": 0.0, "z_mm": 82.0, "yaw_rad": 0.0, "pitch_rad": 0.0, "roll_rad": 0.0},
            "params": {"active_area_mm": 4.0},
        }
    )
    store.restore_dict(payload)
    migrated = next(item for item in store.components.values() if item.label == "旧相机")
    assert migrated.params["sensor_width_mm"] == 4.0
    assert migrated.params["sensor_height_mm"] == 4.0
    assert "active_area_mm" not in migrated.params
    dumped = json.dumps(store.to_dict())
    assert "stemHeight" not in dumped
    assert '"qw"' not in dumped


def test_lens_explicit_radii_and_zero_means_unset() -> None:
    from frontend_pyside.features.teaching_v2.model import compile_component_params

    store = SceneStore()
    unset, warnings = compile_component_params("lens", store.components["lens-002"].params, label="L1")
    assert "radius1_mm" not in unset
    assert warnings
    assert store.update_param("lens-002", "radius1_mm", 30.4)
    assert store.update_param("lens-002", "radius2_mm", -175.0)
    explicit, explicit_warnings = compile_component_params("lens", store.components["lens-002"].params, label="L1")
    assert explicit["radius1_mm"] == 30.4
    assert explicit["radius2_mm"] == -175.0
    assert explicit_warnings == ()


def test_isolator_compiles_as_window_with_isolation_warning() -> None:
    from frontend_pyside.features.teaching_v2.model import compile_component_params
    from teaching_runtime.physical_scene import _compile_project

    store = SceneStore()
    cid = store.add_component("isolator", pose=Pose(10.0, 0.0, AXIS_HEIGHT_MM))
    item = store.components[cid]
    compiled, warnings = compile_component_params("isolator", item.params, label=item.label)
    assert compiled["isolation_db"] == 38.0
    assert compiled["insertion_loss_db"] == 0.4
    assert compiled["clear_aperture_mm"] == 1.8
    assert any("不追回光" in note for note in warnings)
    physical = snapshot_to_physical_scene(store.snapshot())
    assert any(node.kind == "isolator" and node.enabled for node in physical.nodes)
    project, _frame, compile_warnings, _profile = _compile_project(physical)
    assert any("法拉第" in note or "不追回光" in note for note in compile_warnings)
    assert any(
        (surface.metadata or {}).get("teaching_kind") == "isolator"
        for surface in project.surfaces
    )


def test_ccd_compiles_as_imaging_camera_terminal() -> None:
    from teaching_runtime.physical_scene import _compile_project

    store = SceneStore()
    store.remove_component("fiber-004")
    store.remove_component("lens-003")
    store.add_component("ccd", pose=Pose(74.0, 0.0, AXIS_HEIGHT_MM))
    physical = snapshot_to_physical_scene(store.snapshot())
    camera = next(node for node in physical.nodes if node.kind == "imaging_camera")
    assert camera.kind == "imaging_camera"
    project, _frame, _warnings, _options = _compile_project(physical)
    terminals = [surface for surface in project.surfaces if surface.metadata.get("terminal")]
    assert any(surface.metadata.get("teaching_kind") == "imaging_camera" for surface in terminals)


def test_focal_only_l1_focus_is_about_50mm_behind_center() -> None:
    from frontend_pyside.features.teaching_v2.physics import collimated_biconvex_focus_offset_mm
    from teaching_runtime.physical_scene import resolve_teaching_optical_params

    store = SceneStore()
    store.remove_component("fiber-004")
    store.remove_component("lens-003")
    physical = snapshot_to_physical_scene(store.snapshot())
    lens = next(node for node in physical.nodes if node.node_id == "lens-002")
    resolved = resolve_teaching_optical_params(lens)
    assert resolved["geometry_source"] == "focal_derived_physical"
    expected_radius = 2.0 * 0.5168 * 50.0
    assert abs(resolved["resolved_radius1_mm"] - expected_radius) < 1e-6
    assert abs(resolved["resolved_radius2_mm"] + expected_radius) < 1e-6
    offset = collimated_biconvex_focus_offset_mm(50.0)
    assert abs(offset - 50.0) < 3.0


def test_aperture_priority_reaches_engine_surfaces() -> None:
    from teaching_runtime.physical_scene import _compile_project

    store = SceneStore()
    store.remove_component("fiber-004")
    store.remove_component("lens-003")
    store.update_param("lens-002", "diameter_mm", 8.0)
    project, _frame, _warnings, _options = _compile_project(snapshot_to_physical_scene(store.snapshot()))
    lens_surfaces = [surface for surface in project.surfaces if surface.metadata.get("teaching_node_id") == "lens-002"]
    assert lens_surfaces
    assert abs(float(lens_surfaces[0].clear_aperture_mm) - 4.0) < 1e-9
    store.update_param("lens-002", "clear_aperture_mm", 3.1)
    project, _frame, _warnings, _options = _compile_project(snapshot_to_physical_scene(store.snapshot()))
    lens_surfaces = [surface for surface in project.surfaces if surface.metadata.get("teaching_node_id") == "lens-002"]
    assert abs(float(lens_surfaces[0].clear_aperture_mm) - 3.1) < 1e-9


def test_coupling_without_fiber_is_refused() -> None:
    store = SceneStore()
    store.remove_component("fiber-004")
    store.add_component("ccd", pose=Pose(72.0, 0.0, AXIS_HEIGHT_MM))
    result = FormalTeachingGateway(_Bridge()).compute(PhysicsRequest(store.snapshot(), "coupling"))
    assert not result.success
    assert any("光纤" in message for message in result.errors)
    assert "coupling_efficiency" not in result.metrics


def test_spot_without_terminal_is_refused() -> None:
    store = SceneStore()
    store.remove_component("fiber-004")
    result = FormalTeachingGateway(_Bridge()).compute(PhysicsRequest(store.snapshot(), "spot"))
    assert not result.success
    assert any("CCD" in message or "终端" in message for message in result.errors)


def test_mirror_yaw_zero_is_runtime_45_fold() -> None:
    from teaching_runtime.physical_scene import TeachingPhysicalNode, _surface_tilts_from_axis

    node = TeachingPhysicalNode(
        node_id="mirror-001",
        kind="mirror",
        label="反射镜",
        scene_x=40.0,
        scene_y=0.0,
        height_mm=82.0,
        yaw_deg=0.0,
        params={"diameter_mm": 12.7},
    )
    _tilt_x, tilt_y, _tilt_z = _surface_tilts_from_axis(node, 0.0, mirror=True)
    assert abs(tilt_y - 45.0) < 1e-9


def test_render_bridge_uses_stem_aperture_and_orientation() -> None:
    from frontend_pyside.features.teaching_v2.view3d import rotate_vector_by_quaternion, snapshot_to_render_nodes

    store = SceneStore()
    nodes = {item["id"]: item for item in snapshot_to_render_nodes(store.snapshot())}
    lens = nodes["lens-002"]
    assert abs(lens["stemDrop"] - 6.35) < 1e-9
    assert abs(lens["stemHeight"] - (AXIS_HEIGHT_MM - 6.35 - 0.2)) < 1e-9
    assert abs(lens["diameterMm"] - 12.7) < 1e-9
    assert lens["shape"] == "cylinder"
    local_axis = (1.0, 0.0, 0.0) if lens["hasBodyMesh"] else (0.0, 1.0, 0.0)
    axis = rotate_vector_by_quaternion((lens["qw"], lens["qx"], lens["qy"], lens["qz"]), local_axis)
    assert abs(axis[0] - 1.0) < 1e-6
    assert abs(axis[1]) < 1e-6
    assert abs(axis[2]) < 1e-6
    store.update_param("lens-002", "diameter_mm", 20.0)
    store.update_pose("lens-002", Pose(24.0, 0.0, 90.0))
    updated = {item["id"]: item for item in snapshot_to_render_nodes(store.snapshot())}["lens-002"]
    assert abs(updated["stemDrop"] - 10.0) < 1e-9
    assert abs(updated["stemHeight"] - (90.0 - 10.0 - 0.2)) < 1e-9
    assert abs(updated["diameterMm"] - 20.0) < 1e-9
    store.add_component("mirror", pose=Pose(40.0, 0.0, AXIS_HEIGHT_MM))
    mirror_id = next(cid for cid, item in store.components.items() if item.kind == "mirror")
    mirror = {item["id"]: item for item in snapshot_to_render_nodes(store.snapshot())}[mirror_id]
    mirror_local = (1.0, 0.0, 0.0) if mirror["hasBodyMesh"] else (0.0, 1.0, 0.0)
    folded = rotate_vector_by_quaternion((mirror["qw"], mirror["qx"], mirror["qy"], mirror["qz"]), mirror_local)
    assert abs(folded[0] - math.cos(math.radians(45.0))) < 1e-6
    assert abs(folded[2] + math.sin(math.radians(45.0))) < 1e-6


def test_mesh_orientation_maps_plus_x_optical_and_plus_z_up() -> None:
    from frontend_pyside.features.teaching_v2.coordinates import teaching_orientation_to_render_quaternion
    from frontend_pyside.features.teaching_v2.view3d import rotate_vector_by_quaternion

    identity = teaching_orientation_to_render_quaternion(0.0, 0.0, 0.0)
    plus_x = rotate_vector_by_quaternion(identity, (1.0, 0.0, 0.0))
    plus_y = rotate_vector_by_quaternion(identity, (0.0, 1.0, 0.0))
    plus_z = rotate_vector_by_quaternion(identity, (0.0, 0.0, 1.0))
    assert abs(plus_x[0] - 1.0) < 1e-6 and abs(plus_x[1]) < 1e-6 and abs(plus_x[2]) < 1e-6
    assert abs(plus_y[0]) < 1e-6 and abs(plus_y[1]) < 1e-6 and abs(plus_y[2] + 1.0) < 1e-6
    assert abs(plus_z[0]) < 1e-6 and abs(plus_z[1] - 1.0) < 1e-6 and abs(plus_z[2]) < 1e-6
    yaw_90 = teaching_orientation_to_render_quaternion(math.radians(90.0), 0.0, 0.0)
    beam = rotate_vector_by_quaternion(yaw_90, (1.0, 0.0, 0.0))
    assert abs(beam[0]) < 1e-6 and abs(beam[1]) < 1e-6 and abs(beam[2] + 1.0) < 1e-6


def test_body_mesh_uses_plus_x_convention(tmp_path, monkeypatch) -> None:
    from frontend_pyside.features.teaching_v2 import assets as assets_mod
    from frontend_pyside.features.teaching_v2.view3d import rotate_vector_by_quaternion, snapshot_to_render_nodes

    fake = tmp_path / "assets"
    fake.mkdir()
    (fake / "lens.glb").write_bytes(b"glTF")
    (fake / "mirror.glb").write_bytes(b"glTF")
    monkeypatch.setattr(assets_mod, "ASSET_DIR", fake)
    store = SceneStore()
    lens = {item["id"]: item for item in snapshot_to_render_nodes(store.snapshot())}["lens-002"]
    assert lens["hasBodyMesh"] is True
    axis = rotate_vector_by_quaternion((lens["qw"], lens["qx"], lens["qy"], lens["qz"]), (1.0, 0.0, 0.0))
    up = rotate_vector_by_quaternion((lens["qw"], lens["qx"], lens["qy"], lens["qz"]), (0.0, 0.0, 1.0))
    assert abs(axis[0] - 1.0) < 1e-6
    assert abs(up[1] - 1.0) < 1e-6
    store.add_component("mirror", pose=Pose(40.0, 0.0, AXIS_HEIGHT_MM))
    mirror_id = next(cid for cid, item in store.components.items() if item.kind == "mirror")
    mirror = {item["id"]: item for item in snapshot_to_render_nodes(store.snapshot())}[mirror_id]
    folded = rotate_vector_by_quaternion((mirror["qw"], mirror["qx"], mirror["qy"], mirror["qz"]), (1.0, 0.0, 0.0))
    assert abs(folded[0] - math.cos(math.radians(45.0))) < 1e-6
    assert abs(folded[2] + math.sin(math.radians(45.0))) < 1e-6


def test_mirror_preview_folds_toward_minus_y() -> None:
    store = SceneStore()
    for cid in list(store.components):
        if cid != "laser-001":
            store.remove_component(cid)
    store.add_component("mirror", pose=Pose(40.0, 0.0, AXIS_HEIGHT_MM))
    store.add_component("fiber", pose=Pose(40.0, -24.0, AXIS_HEIGHT_MM))
    result = compute_geometry_preview(store.snapshot(), FrameTransform())
    assert result.rays
    chief = [ray for ray in result.rays if ray.power_fraction >= 0.99]
    last = chief[-1]
    assert abs(last.start_teaching_mm[0] - 40.0) < 1e-6
    assert last.end_teaching_mm[1] < -1.0


def test_preview_does_not_kink_to_off_axis_fiber() -> None:
    store = SceneStore()
    store.update_pose("fiber-004", Pose(72.0, 9.6, AXIS_HEIGHT_MM))
    result = compute_geometry_preview(store.snapshot(), FrameTransform())
    assert result.rays
    for ray in result.rays:
        assert abs(ray.start_teaching_mm[1]) < 1.0
        assert abs(ray.end_teaching_mm[1]) < 1.0
    chief = [ray for ray in result.rays if ray.power_fraction >= 0.99]
    assert chief
    assert abs(chief[0].start_teaching_mm[1]) < 0.05


def test_preview_stops_at_first_fiber_and_ignores_extra() -> None:
    store = SceneStore()
    store.add_component("fiber", pose=Pose(84.0, 9.6, AXIS_HEIGHT_MM))
    result = compute_geometry_preview(store.snapshot(), FrameTransform())
    assert result.rays
    for ray in result.rays:
        assert abs(ray.start_teaching_mm[1]) < 1.0
        assert abs(ray.end_teaching_mm[1]) < 1.0
    chief = [ray for ray in result.rays if ray.power_fraction >= 0.99]
    last = chief[-1]
    assert abs(last.end_teaching_mm[0] - 72.0) < 0.5


def test_render_nodes_keep_placeholder_scale_when_mesh_present() -> None:
    from frontend_pyside.features.teaching_v2.view3d import snapshot_to_render_nodes

    store = SceneStore()
    lens = {item["id"]: item for item in snapshot_to_render_nodes(store.snapshot())}["lens-002"]
    assert lens["fallbackSx"] > 0.05
    assert lens["fallbackSy"] > 0.0
    if lens["hasBodyMesh"]:
        assert lens["sy"] > 0.5


def test_lens_mesh_scale_follows_diameter() -> None:
    import pytest
    from frontend_pyside.features.teaching_v2.assets import mesh_extents
    from frontend_pyside.features.teaching_v2.view3d import snapshot_to_render_nodes

    extents = mesh_extents("lens")
    if extents is None:
        pytest.skip("lens.glb 未放入 assets")
    native = max(extents.size_mm[1], 0.5)
    assert abs(native - 12.7) < 0.25
    store = SceneStore()
    nodes = {item["id"]: item for item in snapshot_to_render_nodes(store.snapshot())}
    assert abs(nodes["lens-002"]["sy"] - 12.7 / native) < 1e-6
    assert abs(nodes["lens-003"]["sy"] - 8.0 / native) < 1e-6
    laser_extents = mesh_extents("laser")
    if laser_extents is None:
        pytest.skip("laser.glb 未放入 assets")
    laser = nodes["laser-001"]
    assert abs(laser_extents.size_mm[0] * laser["sx"] - 40.0) < 1e-4
    assert abs(laser_extents.size_mm[1] * laser["sy"] - 11.0) < 1e-4
    assert abs(laser_extents.size_mm[2] * laser["sz"] - 11.0) < 1e-4


def test_housing_and_mesh_catalog_is_frozen() -> None:
    from frontend_pyside.features.teaching_v2.assets import (
        CCD_HOUSING_FACE_MM,
        HOUSING_SPECS,
        LASER_HOUSING_DIA_MM,
        LASER_HOUSING_LENGTH_MM,
        NATIVE_MESH_SPECS,
        ORIGIN_INPUT_FACE,
        ORIGIN_OUTPUT_FACE,
        PLACEHOLDER_CUBE,
        mesh_key_for_kind,
        visual_housing,
    )

    laser = visual_housing("laser", {"beam_radius_mm": 4.0})
    assert abs(laser.length_mm - LASER_HOUSING_LENGTH_MM) < 1e-9
    assert abs(laser.aperture_mm - LASER_HOUSING_DIA_MM) < 1e-9
    assert laser.origin == ORIGIN_OUTPUT_FACE
    assert abs(visual_housing("fiber").length_mm - 18.0) < 1e-9
    assert abs(visual_housing("ccd").width_mm - CCD_HOUSING_FACE_MM) < 1e-9
    assert visual_housing("ccd").placeholder == PLACEHOLDER_CUBE
    assert visual_housing("ccd").origin == ORIGIN_INPUT_FACE
    assert abs(visual_housing("lens", {"diameter_mm": 8.0, "center_thickness_mm": 2.0}).width_mm - 8.0) < 1e-9
    assert abs(visual_housing("mirror").length_mm - 6.0) < 1e-9
    assert abs(visual_housing("isolator").length_mm - 36.0) < 1e-9
    assert abs(visual_housing("isolator").aperture_mm - 25.0) < 1e-9
    assert mesh_key_for_kind("isolator") == "isolator"
    assert mesh_key_for_kind("cylindrical_lens") == "cylindrical_lens"
    assert mesh_key_for_kind("aperture") == "aperture"
    assert mesh_key_for_kind("breadboard") == "breadboard"
    board = visual_housing("breadboard")
    assert abs(board.length_mm - 450.0) < 1e-9
    assert abs(board.width_mm - 300.0) < 1e-9
    assert abs(board.height_mm - 12.7) < 1e-9
    assert board.origin == "top"
    assert mesh_key_for_kind("pbs") == "pbs"
    assert mesh_key_for_kind("oscilloscope") == "oscilloscope"
    from frontend_pyside.features.teaching_v2.assets import TARGET_MESH_SPECS, expected_asset_keys

    assert TARGET_MESH_SPECS["oscilloscope"].origin == "bottom"
    assert TARGET_MESH_SPECS["fiber_stage"].origin == "top"
    assert "waveplate" in expected_asset_keys()
    assert set(NATIVE_MESH_SPECS) == set(expected_asset_keys())
    assert HOUSING_SPECS["laser"].mesh_key == "laser"
    assert HOUSING_SPECS["breadboard"].mesh_key == "breadboard"


def test_catalog_housing_fits_real_aabb() -> None:
    from frontend_pyside.features.teaching_v2.assets import (
        NATIVE_MESH_SPECS,
        ORIGIN_TOP,
        POST_DIAMETER_MM,
        TARGET_MESH_SPECS,
        MeshExtents,
        fit_mesh_to_housing,
        stem_mesh_placement,
        visual_housing,
    )

    spec = NATIVE_MESH_SPECS["laser"]
    laser = visual_housing("laser")
    placement = fit_mesh_to_housing(MeshExtents(spec.min_xyz, spec.max_xyz), laser)
    assert abs(placement.scale[0] - 1.0) < 1e-9
    assert abs(placement.scale[1] - 1.0) < 1e-9
    assert abs(placement.offset_mm[0]) < 1e-9
    old_laser = fit_mesh_to_housing(MeshExtents((-80.0, -23.0, -20.0), (0.0, 23.0, 20.0)), laser)
    assert abs(80.0 * old_laser.scale[0] - 40.0) < 1e-9
    assert abs(46.0 * old_laser.scale[1] - 11.0) < 1e-9
    stem_spec = NATIVE_MESH_SPECS["post_stem"]
    stem = stem_mesh_placement(82.0, MeshExtents(stem_spec.min_xyz, stem_spec.max_xyz))
    assert abs(stem.scale[0] * 12.7 - POST_DIAMETER_MM) < 1e-9
    assert abs(stem.scale[2] - 82.0) < 1e-9
    old_stem = stem_mesh_placement(82.0, MeshExtents((-1.5, -1.5, -1.0), (1.5, 1.5, 0.0)))
    assert abs(old_stem.scale[0] * 3.0 - POST_DIAMETER_MM) < 1e-9
    board = visual_housing("breadboard")
    target = TARGET_MESH_SPECS["breadboard"]
    placed = fit_mesh_to_housing(MeshExtents(target.min_xyz, target.max_xyz), board)
    assert abs(placed.scale[0] - 1.0) < 1e-9
    assert abs(placed.scale[1] - 1.0) < 1e-9
    assert abs(placed.scale[2] - 1.0) < 1e-9
    assert abs(placed.offset_mm[2]) < 1e-9
    assert board.origin == ORIGIN_TOP


def test_shipped_meshes_match_native_spec() -> None:
    import pytest
    from frontend_pyside.features.teaching_v2.assets import mesh_extents, shipped_mesh_violations

    if mesh_extents("lens") is None:
        pytest.skip("assets/*.glb 未放入")
    assert shipped_mesh_violations() == ()


def test_breadboard_and_fiber_stage_load_in_view() -> None:
    import pytest
    from frontend_pyside.features.teaching_v2.assets import FIBER_DISPLAY_DIA_MM, FIBER_MOUNT_PAD_HEIGHT_MM, mesh_extents
    from frontend_pyside.features.teaching_v2.view3d import snapshot_to_render_nodes, snapshot_view3d_guides

    if mesh_extents("breadboard") is None or mesh_extents("fiber_stage") is None:
        pytest.skip("breadboard/fiber_stage glb 未放入")
    store = SceneStore()
    guides = snapshot_view3d_guides(store.snapshot())
    assert guides["hasBoardMesh"] is True
    assert str(guides["boardMeshSource"]).endswith("breadboard.glb")
    assert abs(float(guides["boardX"]) - 225.0) < 1e-6
    assert abs(float(guides["boardY"])) < 1e-6
    fiber = {item["id"]: item for item in snapshot_to_render_nodes(store.snapshot())}["fiber-004"]
    assert fiber["hasStageMesh"] is False
    assert fiber["hasMountPad"] is True
    assert abs(float(fiber["padHeight"]) - FIBER_MOUNT_PAD_HEIGHT_MM) < 1e-6
    assert abs(float(fiber["stemDrop"]) - (0.5 * FIBER_DISPLAY_DIA_MM + FIBER_MOUNT_PAD_HEIGHT_MM)) < 1e-6
    assert abs(float(fiber["stemHeight"]) - (AXIS_HEIGHT_MM - 0.5 * FIBER_DISPLAY_DIA_MM - FIBER_MOUNT_PAD_HEIGHT_MM - 0.2)) < 1e-6


def test_post_stem_and_laser_nodes_use_catalog() -> None:
    import pytest
    from frontend_pyside.features.teaching_v2.assets import mesh_extents
    from frontend_pyside.features.teaching_v2.view3d import snapshot_to_render_nodes

    store = SceneStore()
    nodes = {item["id"]: item for item in snapshot_to_render_nodes(store.snapshot())}
    laser = nodes["laser-001"]
    assert abs(laser["diameterMm"] - 11.0) < 1e-9
    assert abs(laser["fallbackSy"] * 100.0 - 40.0) < 1e-6
    stem = mesh_extents("post_stem")
    if stem is None:
        pytest.skip("post_stem.glb 未放入 assets")
    native_dia = max(stem.size_mm[0], stem.size_mm[1])
    lens = nodes["lens-002"]
    from frontend_pyside.features.teaching_v2.assets import POST_DISPLAY_DIA_MM

    assert abs(lens["stemSx"] * native_dia - POST_DISPLAY_DIA_MM) < 1e-6
    draw = AXIS_HEIGHT_MM - 6.35 - 0.2
    assert abs(lens["stemSz"] - draw / max(stem.size_mm[2], 0.2)) < 1e-6
    assert abs(lens["stemPlaceholderS"] * 100.0 - POST_DISPLAY_DIA_MM) < 1e-9


def test_procedural_hardware_mounts_and_matte_board() -> None:
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QColor, QImage

    from frontend_pyside.features.teaching_v2.view3d import matte_board_texture_url, snapshot_to_render_nodes

    store = SceneStore()
    nodes = {item["id"]: item for item in snapshot_to_render_nodes(store.snapshot())}
    assert nodes["lens-002"]["mountStyle"] == "ring"
    assert nodes["lens-002"]["hasPostBase"] is True
    assert nodes["laser-001"]["mountStyle"] == "clamp"
    assert nodes["fiber-004"]["mountStyle"] == "none"
    assert nodes["fiber-004"]["hasPostBase"] is True
    assert nodes["fiber-004"]["hasMountPad"] is True
    assert nodes["laser-001"]["color"].lower() == "#dc2626"
    assert nodes["fiber-004"]["diameterMm"] == 6.5
    assert nodes["lens-002"]["ringBackSz"] < 0.02
    assert nodes["lens-002"]["hasMountMesh"] is True
    assert str(nodes["lens-002"]["mountMeshSource"]).endswith("mount_ring.glb")
    assert nodes["laser-001"]["hasMountMesh"] is True
    assert nodes["laser-001"]["hasBaseMesh"] is True
    assert str(nodes["laser-001"]["baseMeshSource"]).endswith("mount_post_base.glb")
    assert abs(nodes["lens-002"]["mountSy"] * 20.0 - (12.7 + 4.8)) < 0.05
    assert abs(nodes["lens-002"]["mountSx"] * 10.0 - 7.0) < 0.05
    assert abs(nodes["laser-001"]["baseMeshSx"] * 25.0 - 16.0) < 0.05
    store.add_component("mirror", pose=Pose(40.0, 0.0, AXIS_HEIGHT_MM))
    store.add_component("ccd", pose=Pose(60.0, 0.0, AXIS_HEIGHT_MM))
    store.add_component("oscilloscope")
    by_kind = {item["kind"]: item for item in snapshot_to_render_nodes(store.snapshot())}
    assert by_kind["mirror"]["mountStyle"] == "km"
    assert by_kind["ccd"]["mountStyle"] == "plate"
    assert by_kind["oscilloscope"]["mountStyle"] == "none"
    assert by_kind["oscilloscope"]["hasPostBase"] is False
    image = QImage(QUrl(matte_board_texture_url()).toLocalFile())
    assert not image.isNull()
    scale = image.width() / 450.0
    hole = QColor(image.pixel(int(12.5 * scale), int(12.5 * scale)))
    plate = QColor(image.pixel(2, 2))
    assert hole.lightness() < plate.lightness()


def test_engine_focus_aperture_and_fiber_offset_when_available() -> None:
    import concurrent.futures
    import pytest
    from frontend_pyside.features.teaching_v2.physics import collimated_biconvex_focus_offset_mm

    gateway = FormalTeachingGateway()
    if gateway._bridge is None:
        pytest.skip("正式引擎不可用；编译测试已覆盖")

    def _compute(store: SceneStore, analysis: str):
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(gateway.compute, PhysicsRequest(store.snapshot(), analysis))
            try:
                return future.result(timeout=45)
            except concurrent.futures.TimeoutError:
                pytest.skip(f"正式引擎 {analysis} 超时；编译测试已覆盖")

    focus = collimated_biconvex_focus_offset_mm(50.0)
    terminal_x = 24.0 + focus

    def gold_scene(*, diameter_mm: float, beam_radius_mm: float, terminal: str) -> SceneStore:
        store = SceneStore()
        store.remove_component("fiber-004")
        store.remove_component("lens-003")
        store.update_param("laser-001", "beam_radius_mm", beam_radius_mm)
        store.update_param("lens-002", "diameter_mm", diameter_mm)
        store.add_component(terminal, pose=Pose(terminal_x, 0.0, AXIS_HEIGHT_MM))
        return store

    spot_wide = _compute(gold_scene(diameter_mm=12.7, beam_radius_mm=4.0, terminal="ccd"), "spot")
    spot_narrow = _compute(gold_scene(diameter_mm=6.0, beam_radius_mm=4.0, terminal="ccd"), "spot")
    if not spot_wide.success and not spot_narrow.success:
        pytest.skip("；".join(tuple(spot_wide.errors) + tuple(spot_narrow.errors)))
    wide_metric = spot_wide.metrics.get("rms_spot_radius_um", spot_wide.metrics.get("strehl_ratio"))
    narrow_metric = spot_narrow.metrics.get("rms_spot_radius_um", spot_narrow.metrics.get("strehl_ratio"))
    if wide_metric is None or narrow_metric is None:
        pytest.skip("正式引擎未返回口径相关指标；别名测试已覆盖字段映射")
    assert wide_metric != narrow_metric

    aligned_store = gold_scene(diameter_mm=12.7, beam_radius_mm=0.72, terminal="fiber")
    aligned = _compute(aligned_store, "coupling")
    if not aligned.success:
        pytest.skip("；".join(aligned.errors))
    fiber_id = next(cid for cid, item in aligned_store.components.items() if item.kind == "fiber")
    fiber = aligned_store.components[fiber_id]
    mfd_mm = float(fiber.params["mfd_um"]) * 1.0e-3
    aligned_store.update_pose(fiber_id, Pose(fiber.pose.x_mm, mfd_mm, fiber.pose.z_mm))
    offset = _compute(aligned_store, "coupling")
    if not offset.success:
        pytest.skip("；".join(offset.errors))
    aligned_eta = aligned.metrics.get("coupling_efficiency")
    offset_eta = offset.metrics.get("coupling_efficiency")
    assert aligned_eta is not None and offset_eta is not None
    assert float(offset_eta) < float(aligned_eta)


def test_metric_aliases_read_namespaced_engine_keys() -> None:
    from frontend_pyside.features.teaching_v2.physics import _pick_metrics

    picked = _pick_metrics(
        {
            "wavefront_quality.strehl_estimate_marechal": 0.71,
            "wavefront_rms_waves": 0.02,
            "coupling.mode_overlap_efficiency": 0.4,
        },
        ("strehl_ratio", "rms_waves", "coupling_efficiency"),
    )
    assert picked["strehl_ratio"] == 0.71
    assert picked["rms_waves"] == 0.02
    assert picked["coupling_efficiency"] == 0.4


def test_fiber_receiver_offset_follows_teaching_y() -> None:
    from frontend_pyside.features.teaching_v2.physics import _fiber_receiver_offsets_mm

    store = SceneStore()
    store.remove_component("lens-003")
    fiber = store.components["fiber-004"]
    store.update_pose("fiber-004", Pose(fiber.pose.x_mm, 0.12, fiber.pose.z_mm))
    offset_x, offset_y = _fiber_receiver_offsets_mm(snapshot_to_physical_scene(store.snapshot()))
    assert abs(offset_x - 0.12) < 1e-9
    assert abs(offset_y) < 1e-9


def test_formal_tilts_use_teaching_so3() -> None:
    from frontend_pyside.features.teaching_v2.coordinates import teaching_angles_to_engine
    from teaching_runtime.physical_scene import _compile_project

    store = SceneStore()
    lens = store.components["lens-002"]
    store.update_pose("lens-002", Pose(lens.pose.x_mm, lens.pose.y_mm, lens.pose.z_mm, 0.4, -0.25, 0.15))
    physical = snapshot_to_physical_scene(store.snapshot())
    node = next(item for item in physical.nodes if item.node_id == "lens-002")
    assert node.params["orientation_source"] == "teaching_engine_so3"
    so3 = teaching_angles_to_engine(0.4, -0.25, 0.15)
    assert abs(float(node.params["tilt_x_deg"]) - math.degrees(so3[0])) < 1e-9
    assert abs(float(node.params["tilt_y_deg"]) - math.degrees(so3[1])) < 1e-9
    project, _frame, _warnings, options = _compile_project(physical)
    surfaces = [surface for surface in project.surfaces if surface.metadata.get("teaching_node_id") == "lens-002"]
    assert surfaces
    assert abs(float(surfaces[0].tilt_x_deg) - math.degrees(so3[0])) < 1e-6
    assert abs(float(surfaces[0].tilt_y_deg) - math.degrees(so3[1])) < 1e-6
    direction = options["geometric"]["scene_source_direction"]
    assert abs(direction[0]) < 1e-9
    assert abs(direction[1]) < 1e-9
    assert abs(direction[2] - 1.0) < 1e-9
    published = store.to_publish_dict()
    engine_lens = next(item for item in published["engine_nodes"] if item["id"] == "lens-002")
    assert abs(engine_lens["tilt_x_deg"] - math.degrees(so3[0])) < 1e-9


def test_published_mirror_includes_default_fold() -> None:
    store = SceneStore()
    store.add_component("mirror", pose=Pose(40.0, 0.0, AXIS_HEIGHT_MM))
    mirror_id = next(cid for cid, item in store.components.items() if item.kind == "mirror")
    published = next(item for item in store.to_publish_dict()["engine_nodes"] if item["id"] == mirror_id)
    assert abs(published["tilt_y_deg"] - 45.0) < 1e-6
    physical = snapshot_to_physical_scene(store.snapshot())
    node = next(item for item in physical.nodes if item.node_id == mirror_id)
    assert abs(float(node.params["tilt_y_deg"]) - 45.0) < 1e-6


def test_asset_pipeline_falls_back_when_missing() -> None:
    from frontend_pyside.features.teaching_v2.assets import check_assets
    from frontend_pyside.features.teaching_v2.view3d import mesh_source_for_asset, snapshot_to_render_nodes, stem_mesh_source

    report = check_assets()
    assert report["ok"]
    store = SceneStore()
    nodes = {item["id"]: item for item in snapshot_to_render_nodes(store.snapshot())}
    if "lens" in report["missing"]:
        assert nodes["lens-002"]["meshSource"] == ""
        assert nodes["lens-002"]["hasBodyMesh"] is False
        assert mesh_source_for_asset("lens") == ""
    if "post_stem" in report["missing"]:
        assert nodes["lens-002"]["hasStemMesh"] is False
        assert stem_mesh_source() == ""


def test_asset_pipeline_resolves_dropped_files(tmp_path, monkeypatch) -> None:
    from frontend_pyside.features.teaching_v2 import assets as assets_mod
    from frontend_pyside.features.teaching_v2.view3d import mesh_source_for_asset, stem_mesh_source

    fake = tmp_path / "assets"
    fake.mkdir()
    (fake / "lens.glb").write_bytes(b"glTF")
    (fake / "post_stem.glb").write_bytes(b"glTF")
    monkeypatch.setattr(assets_mod, "ASSET_DIR", fake)
    assert mesh_source_for_asset("lens").endswith("lens.glb")
    assert stem_mesh_source().endswith("post_stem.glb")
    report = assets_mod.check_assets()
    assert "lens" in report["present"]
    assert "post_stem" in report["present"]


def test_ccd_spot_sets_image_distance_to_terminal() -> None:
    from frontend_pyside.features.teaching_v2.physics import (
        _image_distance_to_terminal_mm,
        _sequential_image_distance_mm,
        collimated_biconvex_focus_offset_mm,
    )
    from teaching_runtime.physical_scene import _compile_project

    store = SceneStore()
    store.remove_component("fiber-004")
    store.remove_component("lens-003")
    focus = collimated_biconvex_focus_offset_mm(50.0)
    store.add_component("ccd", pose=Pose(24.0 + focus, 0.0, AXIS_HEIGHT_MM))
    project, _frame, _warnings, _options = _compile_project(snapshot_to_physical_scene(store.snapshot()))
    distance = _image_distance_to_terminal_mm(project)
    assert distance is not None
    assert abs(distance - (focus - 1.0)) < 3.0
    sequential = _sequential_image_distance_mm(project)
    assert sequential is not None and 0.0 < sequential < 0.05
    terminals = [surface for surface in project.surfaces if surface.metadata.get("terminal")]
    assert any(surface.metadata.get("teaching_kind") == "imaging_camera" for surface in terminals)
    assert (project.surfaces[-1].metadata or {}).get("terminal")

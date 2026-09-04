from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import math

from frontend_pyside.features.teaching.experiment_scene import routed_receiver_world_ray
from frontend_pyside.features.teaching.spatial_routing_upgrade import FlexibleSpatialExperimentModel
from frontend_pyside.features.teaching.unified_quick3d import _Unified3DBridge


ROOT = Path(__file__).resolve().parents[1]
QML_ROOT = ROOT / "frontend_pyside" / "resources" / "qml"


def _camera(model: FlexibleSpatialExperimentModel):
    return next(node for node in model.nodes.values() if node.kind == "imaging_camera")


def test_diagnostic_camera_branch_faces_the_camera() -> None:
    model = FlexibleSpatialExperimentModel()
    model.load_layout_preset("dual_mirror_position")
    camera = _camera(model)
    reading = model.instrument_reading(camera.id)
    assert reading.get("valid") is True
    route = routed_receiver_world_ray(model)
    assert route
    assert route[0][0].startswith("laser")
    assert route[-1][0] == camera.id


def test_missed_camera_does_not_get_fake_endpoint() -> None:
    model = FlexibleSpatialExperimentModel()
    model.load_layout_preset("dual_mirror_position")
    camera = _camera(model)
    model.move_node(camera.id, camera.x + 80.0, camera.y, record=False)
    model.rebuild_auto_paths()
    reading = model.instrument_reading(camera.id)
    assert reading.get("valid") is False

    route = routed_receiver_world_ray(model)
    assert route
    assert route[-1][0] == f"miss:{camera.id}"
    camera_world_x = (camera.x - 800.0) * 0.76
    # The ray stays on the physical diagnostic branch instead of bending toward
    # the displaced camera centre.
    assert not math.isclose(route[-1][1][0], camera_world_x, abs_tol=1e-6)


def test_quick3d_bridge_uses_single_receiver_chain_and_camera_gate() -> None:
    model = FlexibleSpatialExperimentModel()
    model.load_layout_preset("dual_mirror_position")
    snapshot = model.scene_snapshot()
    bridge = _Unified3DBridge()
    bridge.set_scene(model, snapshot)
    # Topology alone can no longer light the camera or draw a red path.
    assert bridge.imageReceiverHit is False
    assert bridge.edges == []

    verified = replace(
        snapshot,
        formal_rays_mm=(((0.0, 0.0, 0.0), (0.0, 0.0, 100.0)),),
        physics_source="正式光线追迹",
        physics_status="verified",
    )
    bridge.set_scene(model, verified)
    assert bridge.imageReceiverHit is True
    assert bridge.edges
    assert all(edge["active"] for edge in bridge.edges)
    assert all(edge["id"].startswith("chief:") for edge in bridge.edges)

    camera = _camera(model)
    model.move_node(camera.id, camera.x + 80.0, camera.y, record=False)
    model.rebuild_auto_paths()
    bridge.set_scene(model, model.scene_snapshot())
    assert bridge.imageReceiverHit is False
    assert bridge.edges == []


def test_final_image_spot_uses_red_palette() -> None:
    text = (QML_ROOT / "unified_teaching_scene_3d.qml").read_text(encoding="utf-8")
    for color in ("#FF0000", "#FF4D4F", "#5C0000", "#C40000", "#FF2020", "#FFB3B3"):
        assert color in text


def test_floating_assets_have_continuous_grounded_supports() -> None:
    isolator = (QML_ROOT / "teaching3d" / "assets" / "TeachingIsolator.qml").read_text(encoding="utf-8")
    fiber = (QML_ROOT / "teaching3d" / "assets" / "TeachingFiberStage.qml").read_text(encoding="utf-8")
    # Both bases penetrate the table top by 1 world unit (root y=52; table top y=-9),
    # preventing raster/AA gaps, while the optical centre remains unchanged.
    assert 'position:Qt.vector3d(0,-57.5,0); scale:Qt.vector3d(0.38,0.09,0.30)' in isolator
    assert 'position:Qt.vector3d(-26,-57.5,0); scale:Qt.vector3d(0.52,0.09,0.50)' in fiber
    # The isolator holder reaches the barrel; the five-axis stage has an explicit pedestal.
    assert 'position:Qt.vector3d(0,-24,0); scale:Qt.vector3d(0.36,0.19,0.26)' in isolator
    assert 'position:Qt.vector3d(-26,-33,0); scale:Qt.vector3d(0.22,0.06,0.24)' in fiber

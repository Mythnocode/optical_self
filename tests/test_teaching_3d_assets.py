from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from frontend_pyside.features.teaching.asset_registry import ASSETS, asset_for_kind
from frontend_pyside.features.teaching.component_catalog import DRAWING_SCHEMES
from frontend_pyside.features.teaching.unified_quick3d import _Unified3DBridge
from frontend_pyside.features.teaching.unified_workbench import ExperimentModel

ROOT = Path(__file__).resolve().parents[1]
QML_ROOT = ROOT / "frontend_pyside/resources/qml/teaching3d"


def test_asset_registry_covers_teaching_catalog():
    assert set(DRAWING_SCHEMES) <= set(ASSETS)
    assert asset_for_kind("unknown_kind").asset_id == "generic_device_001"


def test_visual_assets_do_not_reference_physics_or_picking():
    for asset in ASSETS.values():
        path = QML_ROOT / asset.qml
        assert path.is_file(), asset
        text = path.read_text(encoding="utf-8")
        assert "sceneBridge." not in text
        assert "pickable: true" not in text
        assert "PerspectiveCamera" not in text
        assert "DirectionalLight" not in text


def test_optical_asset_node_owns_single_simple_pick_proxy():
    text = (QML_ROOT / "OpticalAssetNode.qml").read_text(encoding="utf-8")
    assert text.count("pickable: true") == 1
    assert "source: \"#Cube\"" in text
    assert "dragOwner" in text
    assert "Loader3D" in text


def test_bridge_adds_visual_metadata_without_changing_metrics():
    model = ExperimentModel()
    before = model.evaluate()
    revision = model.revision
    bridge = _Unified3DBridge()
    bridge.set_scene(model, model.scene_snapshot())
    after = model.evaluate()
    assert model.revision == revision
    assert before == after
    assert len(bridge.nodes) == len(model.nodes)
    assert all(item["assetQml"].startswith("assets/") for item in bridge.nodes)
    assert all(item["pickX"] > 0 and item["pickY"] > 0 and item["pickZ"] > 0 for item in bridge.nodes)
    # A scene without a verified formal raytrace must not invent an optical beam
    # from apparatus topology.  Formal rays are injected separately after the
    # optical engine completes.
    assert len(bridge.envelopeSegments) == 0


def test_detailed_asset_toggle_does_not_touch_model_revision():
    model = ExperimentModel()
    bridge = _Unified3DBridge()
    bridge.set_scene(model, model.scene_snapshot())
    revision = model.revision
    metrics = model.evaluate()
    bridge.setDetailedAssetsEnabled(False)
    bridge.setDetailedAssetsEnabled(True)
    assert model.revision == revision
    assert model.evaluate() == metrics


def test_world_move_mapping_is_visual_to_existing_scene_coordinates_only():
    bridge = _Unified3DBridge()
    captured = []
    bridge.nodeMoveRequested.connect(lambda node_id, x, y: captured.append((node_id, x, y)))
    bridge.moveNodeWorld("lens_1", 76.0, 62.0)
    assert captured
    node_id, scene_x, scene_y = captured[-1]
    assert node_id == "lens_1"
    assert abs(scene_x - 900.0) < 1e-9
    assert abs(scene_y - 550.0) < 1e-9


def test_scene_drag_contract_uses_proxy_owner_and_commits_once_on_release():
    text = (ROOT / "frontend_pyside/resources/qml/unified_teaching_scene_3d.qml").read_text(encoding="utf-8")
    assert "pickResult.objectHit.dragOwner" in text
    assert "root.dragObject.localDragPosition = nextPosition" in text
    assert "sceneBridge.moveNodeWorld(releasedId" in text
    assert "sceneBridge.activate(releasedId)" in text
    assert 'root.dragObject = null; root.dragId = ""; root.draggingDevice = false' in text
    assert "!root.draggingDevice" in text  # expensive Gaussian envelope is suppressed while dragging


def test_teaching_lens_mount_has_continuous_cell_post_and_base():
    text = (QML_ROOT / "assets/TeachingLens.qml").read_text(encoding="utf-8")
    # Four frame bars make a real cell around the optic, rather than the old
    # pair of disconnected clips that visually left the lens floating.
    assert text.count("materials:frameMaterial") >= 5
    assert "position:Qt.vector3d(0, 36,  0)" in text
    assert "position:Qt.vector3d(0,-36,  0)" in text
    assert "position:Qt.vector3d(0,-45,0)" in text
    # The support reaches the shared table datum used by the rest of the teaching
    # assets; there must be no apparent air gap between the cell and its base.
    assert "position:Qt.vector3d(0,-57,0)" in text


def test_qml_toolbar_nudge_is_a_request_not_a_bridge_side_model_edit():
    """Arrow buttons must reach the workbench refresh/recompute chain."""
    model = ExperimentModel()
    model.selected_node_id = "lens_1"
    bridge = _Unified3DBridge()
    bridge.set_scene(model, model.scene_snapshot())
    before_revision = model.revision
    before_x = model.nodes["lens_1"].x
    requested = []
    bridge.nudgeSelectedRequested.connect(lambda dx, dy: requested.append((dx, dy)))
    bridge.nudgeSelected(28.0, 0.0)
    assert requested == [(28.0, 0.0)]
    assert model.revision == before_revision
    assert model.nodes["lens_1"].x == before_x


def test_final_image_preview_uses_persistent_qml_scene_graph_items():
    text = (ROOT / "frontend_pyside/resources/qml/unified_teaching_scene_3d.qml").read_text(encoding="utf-8")
    start = text.index("id: imagingPreview")
    end = text.index("id: sectionPanel", start)
    block = text[start:end]
    assert "id: imageSpotHost" in block
    assert "Canvas {" not in block



def test_quick3d_mount_root_stays_grounded_when_optical_height_state_changes():
    from frontend_pyside.features.teaching.spatial_routing_upgrade import FlexibleSpatialExperimentModel
    from frontend_pyside.features.teaching.experiment_scene import scene_node_world_3d

    model = FlexibleSpatialExperimentModel()
    lens = next(node for node in model.nodes.values() if node.kind == "lens")
    lens.params["z_mm"] = 118.0
    # Engineering/physics transform still retains the optical-height state.
    assert scene_node_world_3d(lens)[1] > 52.0

    bridge = _Unified3DBridge()
    bridge.set_scene(model, model.scene_snapshot())
    rendered = next(item for item in bridge.nodes if item["id"] == lens.id)
    # Mechanical Quick3D root is grounded; procedural feet therefore stay on table.
    assert rendered["y"] == 52.0


def test_final_image_preview_requires_actual_camera_hit():
    from frontend_pyside.features.teaching.spatial_routing_upgrade import FlexibleSpatialExperimentModel

    model = FlexibleSpatialExperimentModel()
    model._replace_with_nodes([
        ("laser", 100, 310, 0, "激光器", {}),
        ("imaging_camera", 700, 310, 180, "相机", {}),
    ], "camera-hit-test")
    camera = next(node for node in model.nodes.values() if node.kind == "imaging_camera")
    bridge = _Unified3DBridge()
    bridge.set_scene(model, model.scene_snapshot())
    assert bridge.imageReceiverAvailable is True
    assert bridge.imageReceiverHit is False
    verified = replace(
        model.scene_snapshot(),
        formal_rays_mm=(((0.0, 0.0, 0.0), (0.0, 0.0, 1.0)),),
        physics_source="正式光线追迹",
        physics_status="verified",
    )
    bridge.set_scene(model, verified)
    assert bridge.imageReceiverHit is True
    assert bridge.imageRadiusXUm > 0

    # Move the camera away from the actual beam.  A Gaussian/fiber state may
    # still exist, but the camera panel must no longer fabricate an image.
    model.move_node(camera.id, camera.x, camera.y + 260.0, record=False)
    model.rebuild_auto_paths()
    bridge.set_scene(model, model.scene_snapshot())
    assert bridge.imageReceiverAvailable is True
    assert bridge.imageReceiverHit is False
    assert "未接收" in bridge.imageStatus or "未命中" in bridge.imageStatus or "路径" in bridge.imageStatus


def test_failed_formal_rays_are_not_rendered_as_physical_teaching_rays(monkeypatch):
    from types import SimpleNamespace
    import frontend_pyside.features.teaching.spatial_routing_upgrade as routing

    model = routing.FlexibleSpatialExperimentModel()
    fake_dataset = SimpleNamespace(rays=(
        SimpleNamespace(failed=False, points_mm=((0.0, 0.0, 0.0), (0.0, 0.0, 10.0))),
        SimpleNamespace(failed=True, points_mm=((0.0, 0.0, 0.0), (99.0, 99.0, 10.0))),
    ))
    monkeypatch.setattr(routing, "formal_ray_dataset_from_result", lambda result, project: fake_dataset)
    accepted = model.set_formal_physics_result({}, {}, model.revision)
    assert accepted is True
    rays = model.scene_snapshot().formal_rays_mm
    assert len(rays) == 1
    assert rays[0][-1] == (0.0, 0.0, 10.0)


def test_final_image_qml_is_gated_by_detector_hit_not_fiber_efficiency():
    text = (ROOT / "frontend_pyside/resources/qml/unified_teaching_scene_3d.qml").read_text(encoding="utf-8")
    start = text.index("id: imagingPreview")
    end = text.index("id: sectionPanel", start)
    block = text[start:end]
    assert "visible: sceneBridge.imageReceiverHit" in block
    assert "未接收到光" in block
    assert "sceneBridge.fiberRadius" not in block
    assert "sceneBridge.receiverEfficiency" not in block

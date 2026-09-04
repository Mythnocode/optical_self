from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from frontend_pyside.app.bootstrap import create_app_context
from frontend_pyside.app.main_window import MainWindow
from frontend_pyside.features.teaching.experiment_scene import (
    project_formal_rays_2d,
    representative_formal_rays,
)
from frontend_pyside.shared.plotting.canvas import PlotCanvas


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _pump(count: int = 12) -> None:
    app = _app()
    for _ in range(count):
        app.processEvents()
        QTest.qWait(8)


def test_embedded_line_plot_reserves_title_and_axis_label_margins():
    _app()
    canvas = PlotCanvas()
    canvas.resize(900, 340)
    canvas.set_plot(
        {
            "kind": "line_multi",
            "x": list(range(1, 10)),
            "series": [{"label": "验证集", "y": [9 - i * 0.6 for i in range(9)]}],
            "title": "真实训练历史",
            "x_label": "训练轮次",
            "y_label": "验证误差",
        }
    )
    try:
        _pump(5)
        params = canvas.figure.subplotpars
        assert params.left >= 0.15
        assert params.bottom >= 0.24
        assert params.top <= 0.86
        assert params.right >= 0.96
    finally:
        canvas.close()


def test_dense_formal_rays_are_reduced_without_inventing_interpolated_paths():
    rays = []
    for index in range(25):
        offset = -2.4 + index * 0.2
        rays.append(((offset, -offset, 0.0), (offset * 0.3, -offset * 0.3, 20.0)))
    reduced = representative_formal_rays(rays, max_rays=9)
    assert 1 <= len(reduced) <= 9
    originals = {tuple(ray) for ray in rays}
    assert all(tuple(ray) in originals for ray in reduced)


def test_side_and_top_are_semantic_projections_of_the_same_formal_ray_set():
    model = SimpleNamespace(
        nodes={
            "l1": SimpleNamespace(kind="lens", x=600.0, y=310.0),
            "l2": SimpleNamespace(kind="lens", x=780.0, y=310.0),
            "fiber": SimpleNamespace(kind="fiber", x=980.0, y=310.0),
        }
    )
    rays = (
        ((-2.5, -1.0, 0.0), (0.2, 0.5, 20.0), (0.0, 0.0, 80.0)),
        ((2.5, 1.0, 0.0), (-0.2, -0.5, 20.0), (0.0, 0.0, 80.0)),
    )
    side = project_formal_rays_2d(model, rays, plane="side")
    top = project_formal_rays_2d(model, rays, plane="top")
    assert len(side) == len(top) == 2
    # Same longitudinal scene x values, different transverse coordinate source.
    assert [point[0] for point in side[0]] == [point[0] for point in top[0]]
    assert [point[1] for point in side[0]] != [point[1] for point in top[0]]
    # Adaptive semantic display scale keeps an ordinary pupil inside the apparatus aperture.
    all_y = [point[1] for ray in side + top for point in ray]
    assert max(all_y) - min(all_y) <= 80.0


def test_simulation_owns_parameter_research_and_tolerance_entry_points():
    app = _app()
    window = MainWindow(create_app_context())
    window.resize(1366, 768)
    window.show()
    try:
        _pump(12)
        QTest.mouseClick(window.command_buttons["simulation"], Qt.LeftButton)
        _pump(15)
        simulation = window._pages["simulation"].loaded_page
        assert simulation is not None
        assert simulation.parameter_research_button.isVisible()
        assert simulation.tolerance_analysis_button.isVisible()

        QTest.mouseClick(simulation.parameter_research_button, Qt.LeftButton)
        _pump(10)
        task = window._optimization_task_window
        assert task is not None and task.target == "optimization.scan"
        assert task.isVisible() and not task.isModal()

        task.hide()
        QTest.mouseClick(simulation.tolerance_analysis_button, Qt.LeftButton)
        _pump(10)
        task = window._optimization_task_window
        assert task.target == "optimization.tolerance"
        assert task.page.tolerance_candidate.currentText() == "当前系统"
        assert task.page.tolerance_template.currentText() == "常用装调"
        assert "当前正式系统" in task.page.tolerance_source_info.text()
    finally:
        try:
            window._optimization_task_window.close()
        except Exception:
            pass
        window.close()
        app.processEvents()


def test_quick3d_physical_rays_do_not_read_experiment_topology_edges():
    root = Path(__file__).resolve().parents[1]
    bridge_source = (root / "frontend_pyside/features/teaching/unified_quick3d.py").read_text(encoding="utf-8")
    start = bridge_source.index("self._edges = []")
    end = bridge_source.index("fiber_node =", start)
    physical_block = bridge_source[start:end]
    assert "formal_rays_world_3d" in physical_block
    assert "model.edges" not in physical_block


def test_teaching_lens_support_reaches_common_table_datum():
    root = Path(__file__).resolve().parents[1]
    source = (root / "frontend_pyside/resources/qml/teaching3d/assets/TeachingLens.qml").read_text(encoding="utf-8")
    normalized = source.replace(" ", "")
    assert "position:Qt.vector3d(0,-57,0)" in normalized
    assert "base" in source.lower()


def test_teaching_supported_assets_reach_common_table_datum():
    root = Path(__file__).resolve().parents[1]
    assets = root / "frontend_pyside/resources/qml/teaching3d/assets"
    for name in (
        "TeachingAperture.qml",
        "TeachingBeamExpander.qml",
        "TeachingMirror.qml",
        "TeachingSplitter.qml",
        "TeachingPowerMeter.qml",
        "TeachingCamera.qml",
        "TeachingWavefrontSensor.qml",
        "TeachingGeneric.qml",
    ):
        source = (assets / name).read_text(encoding="utf-8")
        normalized = source.replace(" ", "")
        assert "-57" in normalized, f"{name} must reach the shared optical-table datum"
        assert "#Cube" in source and "#Cylinder" in source, f"{name} must contain support/pedestal geometry"


def test_teaching_2d_projection_uses_quick3d_light_engineering_palette():
    from frontend_pyside.features.teaching import scene_style
    from frontend_pyside.features.teaching.spatial_routing_upgrade import (
        EngineeringProjectionScene,
        FlexibleSpatialGraphicsView,
    )

    _app()
    view = FlexibleSpatialGraphicsView()
    try:
        assert isinstance(view.scene_obj, EngineeringProjectionScene)
        root = Path(__file__).resolve().parents[1]
        qml = (root / "frontend_pyside/resources/qml/unified_teaching_scene_3d.qml").read_text(encoding="utf-8")
        assert scene_style.SCENE_BACKGROUND in qml
        assert scene_style.TABLE_SURFACE in qml
        assert scene_style.AXIS in qml
        assert scene_style.BEAM in qml
        # Old dark-CAD background must not be the projection scene anymore.
        source = (root / "frontend_pyside/features/teaching/spatial_routing_upgrade.py").read_text(encoding="utf-8")
        block = source[source.index("class EngineeringProjectionScene"):source.index("class ProjectedOpticalNodeItem")]
        assert "#10151a" not in block.lower()
        assert "#343c44" not in block.lower()
    finally:
        view.close()


def test_projection_scene_tracks_actual_experiment_rail_instead_of_legacy_fixed_y():
    from frontend_pyside.features.teaching.spatial_routing_upgrade import (
        FlexibleSpatialExperimentModel,
        FlexibleSpatialGraphicsView,
    )
    from frontend_pyside.features.teaching.experiment_scene import main_rail_y

    _app()
    model = FlexibleSpatialExperimentModel()
    model.mode = "free"
    model.load_layout_preset("straight")
    view = FlexibleSpatialGraphicsView()
    try:
        view.set_model(model, preserve_view=False)
        assert abs(view.scene_obj.reference_rail_y - main_rail_y(model)) < 1e-9
        # This preset intentionally uses y=310 rather than the old workbench's
        # constant 430; a fixed background would visibly detach bases from table.
        assert abs(view.scene_obj.reference_rail_y - 310.0) < 1e-9
    finally:
        view.close()


def test_quick3d_selection_blue_matches_2d_projection_selection_blue():
    from frontend_pyside.features.teaching import scene_style
    root = Path(__file__).resolve().parents[1]
    qml = (root / "frontend_pyside/resources/qml/teaching3d/OpticalAssetNode.qml").read_text(encoding="utf-8")
    assert qml.count(scene_style.SELECTION) >= 2


def test_quick3d_world_projection_uses_one_formal_ray_when_available():
    from frontend_pyside.features.teaching.experiment_scene import formal_rays_world_3d
    from types import SimpleNamespace

    rays = []
    for index in range(25):
        x = (index % 5 - 2) * 0.25
        y = (index // 5 - 2) * 0.25
        rays.append(((x, y, 0.0), (x * 0.2, y * 0.2, 20.0)))
    model = SimpleNamespace(
        nodes={
            "l1": SimpleNamespace(kind="lens", x=600.0, y=310.0),
            "fiber": SimpleNamespace(kind="fiber", x=980.0, y=310.0),
        }
    )
    subset = formal_rays_world_3d(model, rays)
    assert len(subset) == 1


def test_quick3d_bridge_limits_cached_world_rays_to_one():
    from frontend_pyside.features.teaching.unified_quick3d import _Unified3DBridge

    bridge = _Unified3DBridge()
    world_rays = tuple(
        (
            (float(index) * 0.1, 0.0, 0.0),
            (float(index) * 0.1, 0.0, 20.0),
        )
        for index in range(5)
    )
    reduced = bridge._display_formal_rays_world(world_rays)
    assert len(reduced) == 1

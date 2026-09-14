from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel

from frontend_pyside.app.bootstrap import create_app_context
from frontend_pyside.app.main_window import MainWindow
from frontend_pyside.app.workbench_shell import AnalysisTextDocument, TeachingAnalysisPopup, TeachingShell


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_live_teaching_entry_is_teaching_shell() -> None:
    app = _app()
    window = MainWindow(create_app_context())
    window.navigate("teaching")
    try:
        assert isinstance(window.teaching, TeachingShell)
        assert window.mode_stack.currentWidget() is window.teaching
        assert window.findChild(QLabel, "Teaching3DFallback") is not None or window.teaching.view_stack.count() == 2
    finally:
        window.close()
        app.processEvents()


def test_teaching_shell_has_no_legacy_page_tabs() -> None:
    app = _app()
    shell = TeachingShell(create_app_context())
    try:
        assert shell.objectName() == "TeachingShell"
        assert shell.findChild(QLabel, "DocumentTitle") is None
        # A new teaching session must be a blank bench, not a hidden template.
        assert shell.store.selected_component_id is None
        assert not shell.store.components
        assert shell.inspector.objectName() == "teachingV2Inspector"
        assert not shell.inspector.isVisible()
        shell._toolbar_action("inspector")
        assert shell.inspector.isVisible()
        shell._toolbar_action("equipment")
        assert shell.equipment_popup is not None
        shell._add_component("lens")
        assert shell._last_equipment_id
        shell._apply_scheme(4)
        assert len([item for item in shell.store.components.values() if item.kind == "lens"]) == 4
        laser = next(item for item in shell.store.components.values() if item.kind == "laser")
        assert laser.params["wavelength_nm"] == 780.0
        assert any(item.kind == "fiber" for item in shell.store.components.values())
        request = shell._engineering_request_for_current_scene()
        assert request is not None
        assert request["project"]["source"]["wavelength_nm"] == 780.0
        assert request["project"]["surfaces"][0]["coating_layers"]
        shell.canvas_mode.setCurrentText("三维")
        assert shell.view_stack.currentWidget() is shell.view3d
        bridge = getattr(shell.view3d, "bridge", None)
        if bridge is not None:
            assert str(bridge.selectedLabel)
        shell._toolbar_action("calculate")
        assert shell._teaching_result_origin == "近似计算"
        assert (shell.store.results.get("geometry") or {}).get("rays")
        shell._toolbar_action("measure")
        assert "离台" in shell.status.text()
        assert {"imaging", "coupling"}.issubset(shell._tool_buttons)
        shell._toolbar_action("imaging")
        shell._toolbar_action("coupling")
        assert shell.analysis_popups["spot"].isVisible()
        assert shell.analysis_popups["coupling"].isVisible()
        shell._toolbar_action("result")
        shell.store.apply_result(
            "coupling",
            {
                "status": "completed",
                "metrics": {
                    "coupling_efficiency": 0.81,
                    "mode_overlap_efficiency": 0.9,
                },
            },
            source_revision=shell.store.revision,
        )
        assert "模式耦合效率" in shell.result_popup.body.text()
        before = len(shell.store.components)
        shell._drop_component("mirror", 90.0, 4.0, 25.0)
        assert len(shell.store.components) == before + 1
        placed = shell.store.components[shell._last_equipment_id]
        assert placed.kind == "mirror"
        assert abs(placed.pose.x_mm - 90.0) < 1e-6
    finally:
        shell.close()
        app.processEvents()


def test_teaching_sync_writes_only_supported_project_inputs() -> None:
    app = _app()
    context = create_app_context()
    shell = TeachingShell(context)
    try:
        laser_id = shell.store.add_component("laser")
        fiber_id = shell.store.add_component("fiber")
        shell.store.update_param(laser_id, "wavelength_nm", 850.0, reason="测试")
        shell.store.update_param(fiber_id, "mfd_um", 6.2, reason="测试")
        shell._toolbar_action("sync_to_simulation")
        assert context.project.project.wavelength_nm == 850.0
        assert context.project.project.receiver_mfd_um == 6.2
        assert "已同步" in shell.status.text()
        assert context.project.research_profile.get("active_snapshot_source") == "teaching"
    finally:
        shell.close()
        app.processEvents()


def test_top_view_draws_post_mounts_and_mirror_fold() -> None:
    from frontend_pyside.features.teaching_v2.canvas import BenchScene
    from frontend_pyside.features.teaching_v2.coordinates import AXIS_HEIGHT_MM
    from frontend_pyside.features.teaching_v2.model import MIRROR_RUNTIME_FOLD_DEG, Pose, SceneStore

    qml = Path(__file__).resolve().parents[1] / "frontend_pyside/features/teaching_v2/qml/bench_view3d.qml"
    text = qml.read_text(encoding="utf-8")
    assert "bumpView" not in text
    assert "id: lab" not in text
    assert "mountStyle" in text
    assert "#FACC15" in text
    assert "#F97316" not in text
    assert "#EF4444" in text
    assert "#EAB308" not in text
    assert "syncNameTag" in text
    assert "selectedLabel" in text
    # 操作说明移出三维画布，避免与右下角公式和编辑按钮争夺视觉空间。
    assert "左键拖空处转视角" not in text
    assert 'objectName: "gizmo:axis:x"' in text
    app = _app()
    store = SceneStore()
    scene = BenchScene(store)
    try:
        assert abs(scene._items["lens-002"].rotation()) < 1e-6
        store.add_component("mirror", pose=Pose(40.0, 0.0, AXIS_HEIGHT_MM))
        scene.set_snapshot(store.snapshot())
        mirror = next(item for item in scene._items.values() if item.kind == "mirror")
        assert abs(mirror.rotation() + MIRROR_RUNTIME_FOLD_DEG) < 1e-6
    finally:
        scene.clear()
        app.processEvents()


def test_teaching_controls_are_visible_shell_overlays_without_formula_card() -> None:
    app = _app()
    shell = TeachingShell(create_app_context())
    try:
        assert shell.quick_actions.parent() is shell
        assert not hasattr(shell, "formula_card")
        assert [shell._quick_action_buttons[key].text() for key in ("undo", "redo", "delete", "clear")] == [
            "撤销", "下一步", "删除", "清空"
        ]
    finally:
        shell.close()
        app.processEvents()


def test_teaching_equipment_opens_wide_xyz_inspector_and_analysis_has_progress() -> None:
    from frontend_pyside.features.teaching_v2.inspector import POSE_FIELDS

    app = _app()
    shell = TeachingShell(create_app_context())
    popup = TeachingAnalysisPopup("coupling")
    try:
        labels = {name: label for name, label, *_rest in POSE_FIELDS}
        assert labels["x_mm"].startswith("X 坐标")
        assert labels["y_mm"].startswith("Y 坐标")
        assert labels["z_mm"].startswith("Z 坐标")
        assert shell.inspector.minimumWidth() >= 560

        shell._add_component("lens")
        assert shell.inspector.isVisible()
        assert shell.store.selected_component_id == shell._last_equipment_id

        popup.set_busy(True, "正在计算耦合")
        assert not popup.progress.isHidden()
        assert popup.progress.minimum() == 0
        assert popup.progress.maximum() == 0
        assert not popup.run_button.isEnabled()
        popup.set_busy(False, "计算完成")
        assert popup.progress.isHidden()
        assert popup.run_button.isEnabled()
    finally:
        popup.close()
        shell.close()
        app.processEvents()


def test_physical_formula_is_rendered_below_shap_explanation() -> None:
    app = _app()
    document = AnalysisTextDocument("global_contrib", context=create_app_context())
    document.show()
    try:
        document._render_shap({
            "target_name": "总耦合效率",
            "target_unit": "1",
            "top_features": [{
                "feature": "surfaces[0].radius_mm",
                "mean_abs_shap": 0.12,
                "mean_shap": -0.08,
                "relative_importance": 1.0,
            }],
        })
        app.processEvents()
        assert document.analysis_text.isVisible()
        assert document.formula_text.isVisible()
        assert "物理公式：结构参数 · 曲率半径" in document.formula_text.text()
        assert "SHAP 仅用于模型贡献排序" in document.formula_text.text()
    finally:
        document.close()
        app.processEvents()


def test_sync_from_simulation_copies_prescription_and_calculation_contract() -> None:
    app = _app()
    context = create_app_context()
    shell = TeachingShell(context)
    try:
        from frontend_pyside.api.payloads import serialize_project
        from frontend_pyside.features.simulation.form_state import SimulationFormState

        payload = serialize_project(context.project.project, SimulationFormState())
        payload["calculation_contract"] = {"precision": "high", "options": {"hybrid": {"grid_size": 513}}}
        context.project.set_simulation_project_payload(payload)
        shell._toolbar_action("sync_from_simulation")
        lenses = [item for item in shell.store.components.values() if item.kind == "lens"]
        assert len(lenses) == 4
        assert lenses[0].params["radius1_mm"] == context.project.project.surfaces[0].radius_mm
        assert shell._engineering_sync_scene_revision == shell.store.revision
        request = shell._engineering_request_for_current_scene()
        assert request is not None
        assert request["precision"] == "high"
        assert request["options"]["hybrid"]["grid_size"] == 513
        # A formal result is evidence for the same prescription, not a bench
        # edit.  It must not silently fall back to the simplified teaching
        # scene on the next coupling calculation.
        context.project.set_formal_result({"metrics": {"total_coupling_efficiency": 0.94}})
        assert shell._engineering_request_for_current_scene() is not None
        shell.store.update_param(lenses[0].component_id, "radius1_mm", 6.0, reason="测试修改")
        assert shell._engineering_request_for_current_scene() is None
    finally:
        shell.close()
        app.processEvents()


def test_teaching_analysis_popup_uses_one_user_facing_quality_message() -> None:
    app = _app()
    popup = TeachingAnalysisPopup("coupling")
    try:
        from types import SimpleNamespace

        popup.set_result(
            SimpleNamespace(
                success=True,
                status="completed",
                scene_revision=3,
                elapsed_ms=27.0,
                artifacts={
                    "coupling": {
                        "status": "completed",
                        "metrics": {"total_coupling_efficiency": 0.00005083},
                        "warnings": [
                            "Exit-pupil support fill exceeds 5%; inspect sampling/support quality.",
                            "Receiver mode is under-resolved on the propagated field grid.",
                        ],
                        "comparison_note": "与当前仿真工程同处方、同数值配置",
                    }
                },
            )
        )
        assert popup.run_button.text() == "开始正式计算"
        assert "0.005083%" in popup.summary.text()
        assert "建议提高采样精度后复核" in popup.notes.text()
        assert "Exit-pupil" not in popup.notes.text()
        assert "Receiver mode" not in popup.notes.text()
    finally:
        popup.close()
        app.processEvents()

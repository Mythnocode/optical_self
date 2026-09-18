from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel

from frontend_pyside.app.bootstrap import create_app_context
from frontend_pyside.app.main_window import MainWindow
from frontend_pyside.app.workbench_shell import (
    AnalysisTextDocument,
    TeachingImagingCouplingPopup,
    TeachingShell,
)


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _wait(app: QApplication, ms: int = 60) -> None:
    from PySide6.QtTest import QTest

    QTest.qWait(ms)
    app.processEvents()


def _wheel(view, delta: int) -> None:
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent

    center = view.viewport().rect().center()
    event = QWheelEvent(
        QPointF(center), view.viewport().mapToGlobal(center), QPoint(0, 0), QPoint(0, delta),
        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.ScrollUpdate, False,
    )
    QApplication.sendEvent(view.viewport(), event)


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
        # 属性不再占工具栏按钮：选中器件时才弹出来。
        assert "inspector" not in shell._tool_buttons
        shell._toolbar_action("equipment")
        assert shell.equipment_popup is not None
        shell._add_component("lens")
        assert shell._last_equipment_id
        assert shell.inspector.isVisible()
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
        assert "analysis" in shell._tool_buttons
        assert shell._tool_buttons["analysis"].text() == "成像与耦合"
        shell._toolbar_action("analysis")
        assert shell.analysis_popup is not None
        assert shell.analysis_popup.isVisible()
        # 二级栏顺序与标题：方案 / 器材库 / 视角 / 成像与耦合 / 测量 / 计算 /
        # 同步到仿真 / 从仿真更新；"属性"和"结果"都不再占按钮。
        assert [key for key in shell._tool_buttons] == [
            "scheme", "equipment", "display", "analysis",
            "measure", "calculate", "sync_to_simulation", "sync_from_simulation",
        ]
        assert shell._tool_buttons["display"].text() == "视角"
        assert "result" not in shell._tool_buttons
        # 结果窗口已删除，结果只由成像与耦合窗口呈现。
        assert not hasattr(shell, "result_popup")
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
    assert "bridge.selectedPosition" in text
    # 操作说明移出三维画布，避免与右下角公式和编辑按钮争夺视觉空间。
    assert "左键拖空处转视角" not in text
    assert 'objectName: "gizmo:axis:x"' in text
    # 坐标轴是"虚线 + 末端箭头"：虚线段由 Repeater3D 铺开，尖端用内置锥体。
    assert "gizmoDashCenters" in text
    assert 'source: "#Cone"' in text
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


def test_plan_canvas_zooms_and_refits_when_shown() -> None:
    """二维画布：滚轮必须能缩放，从隐藏状态回到前台时按真实尺寸重新适配。

    旧实现把"目标比例要落在 0.22~6.0"当作缩放前提，而视图隐藏时视口只有
    最小尺寸，启动阶段算出的适配比例（≈0.04）正好落在区间外，于是两个方向
    的滚轮都被挡掉，看起来就是"画布不能放大"。
    """
    from PySide6.QtCore import QSize

    app = _app()
    shell = TeachingShell(create_app_context())
    try:
        shell.resize(1200, 760)
        shell.show()
        _wait(app)
        shell._apply_scheme(2)
        shell.canvas_mode.setCurrentText("二维")
        _wait(app)
        view = shell.view

        # 缩放到启动时那种极小比例后，滚轮仍要能继续放大和缩小。
        view.resetTransform()
        view.scale(0.04, 0.04)
        start = float(view.transform().m11())
        for _ in range(6):
            _wheel(view, 120)
        _wait(app)
        zoomed = float(view.transform().m11())
        assert zoomed > start

        for _ in range(6):
            _wheel(view, -120)
        _wait(app)
        assert float(view.transform().m11()) < zoomed

        # 适配比例是按旧视口尺寸算出来的时候，重新显示要补一次适配。
        view._fitted_viewport = QSize(1, 1)
        view._user_scaled = False
        shell.canvas_mode.setCurrentText("三维")
        shell.canvas_mode.setCurrentText("二维")
        _wait(app)
        assert view._fitted_viewport == view.viewport().size()
    finally:
        shell.close()
        app.processEvents()


def test_teaching_analysis_runs_imaging_then_coupling_from_one_button() -> None:
    """成像与耦合：一个按钮按顺序算光斑和耦合，两块数据都进同一个窗口。"""
    from types import SimpleNamespace

    app = _app()
    shell = TeachingShell(create_app_context())
    try:
        requested: list[str] = []
        shell.controller.request_formal = lambda analysis="raytrace": requested.append(str(analysis))
        shell._toolbar_action("analysis")
        popup = shell.analysis_popup
        assert popup.windowTitle() == "成像与耦合"

        popup.run_button.click()
        assert requested == ["spot"]
        assert "成像" in popup.status.text()

        shell._on_formal_result("spot", SimpleNamespace(
            success=True,
            status="completed",
            scene_revision=shell.store.revision,
            artifacts={"spot": {"status": "completed", "metrics": {"rms_spot_radius_um": 8.25}}},
        ))
        # 第一项算完自动接着算耦合。
        assert requested == ["spot", "coupling"]
        assert "8.25" in popup.imaging_summary.text()

        shell._on_formal_result("coupling", SimpleNamespace(
            success=True,
            status="completed",
            scene_revision=shell.store.revision,
            artifacts={
                "coupling": {
                    "status": "completed",
                    "metrics": {
                        "system_efficiency": 0.8,
                        "fiber_interface_efficiency": 0.9,
                        "total_coupling_efficiency": 0.72,
                    },
                }
            },
        ))
        assert popup.coupling_pills["total"].text() == "总耦合效率：72%"
        assert popup.status.text().startswith("正式计算完成")
        assert requested == ["spot", "coupling"]
    finally:
        shell.close()
        app.processEvents()


def test_teaching_toolbar_action_buttons_show_click_feedback() -> None:
    """动作型按钮（计算/测量）要有按下与点亮反馈，不能只靠状态栏文字。"""
    app = _app()
    shell = TeachingShell(create_app_context())
    try:
        button = shell._tool_buttons["calculate"]
        assert button.isCheckable() is False
        assert button.property("flash") in (None, False)
        shell._toolbar_action("calculate")
        assert button.property("flash") is True
        _wait(app, 400)
        assert button.property("flash") is False

        qss = (
            Path(__file__).resolve().parents[1] / "frontend_pyside/resources/qss/light.qss"
        ).read_text(encoding="utf-8")
        assert "QToolButton#TeachingToolButton:pressed" in qss
        assert 'QToolButton#TeachingToolButton[flash="true"]' in qss
    finally:
        shell.close()
        app.processEvents()


def test_engineering_preset_keeps_the_source_on_the_bench() -> None:
    """四非球面方案走工程处方路线，光源同样要留出台面左端余量。

    这条路线直接由仿真工程生成器件位置（不经 apply_optical_scheme），光源
    一旦落在 x=0，管身就会整段悬在台面外。
    """
    from frontend_pyside.features.teaching_v2.assets import (
        BREADBOARD_LENGTH_MM,
        LASER_HOUSING_LENGTH_MM,
        PH_PLATE_MM,
    )

    app = _app()
    shell = TeachingShell(create_app_context())
    try:
        shell._apply_scheme(4)
        laser = next(item for item in shell.store.components.values() if item.kind == "laser")
        assert laser.pose.x_mm - LASER_HOUSING_LENGTH_MM >= 0.0
        assert laser.pose.x_mm - 0.5 * PH_PLATE_MM >= 0.0
        assert shell.store.baseline_x_mm == laser.pose.x_mm
        for item in shell.store.components.values():
            assert 0.0 <= item.pose.x_mm <= BREADBOARD_LENGTH_MM
    finally:
        shell.close()
        app.processEvents()


def test_view3d_name_tag_shows_selected_bench_coordinates() -> None:
    """三维浮标显示选中器件的台面坐标，精度与状态栏测量一致。"""
    from frontend_pyside.features.teaching_v2.model import Pose, SceneStore
    from frontend_pyside.features.teaching_v2.view3d import View3DBridge

    app = _app()
    store = SceneStore()
    store.update_pose("lens-002", Pose(71.4, -2.5, 30.0))
    store.select("lens-002")
    bridge = View3DBridge()
    try:
        bridge.set_snapshot(store.snapshot())
        assert bridge.selectedPosition == "X 71.4 · Y -2.5 · Z 30.0 mm"
        # 名称仍由属性提供，浮标不再显示它。
        assert bridge.selectedLabel == "L1 透镜"
        store.select(None)
        bridge.set_snapshot(store.snapshot())
        assert bridge.selectedPosition == ""
    finally:
        bridge.deleteLater()
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


def test_teaching_equipment_opens_xyz_inspector_and_analysis_has_progress() -> None:
    from frontend_pyside.features.teaching_v2.inspector import POSE_FIELDS

    app = _app()
    shell = TeachingShell(create_app_context())
    popup = TeachingImagingCouplingPopup()
    try:
        labels = {name: label for name, label, *_rest in POSE_FIELDS}
        # 坐标一行三格，标签用最短的轴名，单位另起一块。
        assert [labels[name] for name in ("x_mm", "y_mm", "z_mm")] == ["X", "Y", "Z"]
        assert [labels[name] for name in ("yaw_deg", "pitch_deg", "roll_deg")] == ["绕Z", "绕Y", "绕光轴"]
        # 默认视图只要放得下 X/Y/Z 一行，窗口按内容收紧；"实验设置"整页已删除。
        assert shell.inspector.minimumWidth() <= 520
        assert not hasattr(shell.inspector, "tabs")

        shell._add_component("lens")
        assert shell.inspector.isVisible()
        assert shell.store.selected_component_id == shell._last_equipment_id
        # 默认只摆坐标和倾角，其余参数收在"更多参数"后面。
        assert not shell.inspector._detail.isVisible()
        shell.inspector.detail_button.setChecked(True)
        assert shell.inspector._detail.isVisible()
        assert "focal_length_mm" in shell.inspector._param_editors

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


def test_shap_explanation_has_independent_physical_chain_page() -> None:
    app = _app()
    document = AnalysisTextDocument(
        "param_trend",
        selected="surfaces[0].radius_mm",
        context=create_app_context(),
    )
    document.show()
    try:
        document._render_shap({
            "target_name": "总耦合效率",
            "target_unit": "1",
            "top_features": [
                {
                    "feature": "surfaces[0].radius_mm",
                    "mean_abs_shap": 0.12,
                    "mean_shap": -0.08,
                    "relative_importance": 1.0,
                },
                {
                    "feature": "surfaces[0].thickness_mm",
                    "mean_abs_shap": 0.08,
                    "mean_shap": 0.04,
                    "relative_importance": 0.67,
                },
            ],
            "shap_dependence": {
                "surfaces[0].radius_mm": {
                    "feature_value": [10.0, 11.0],
                    "shap_value": [-0.08, -0.02],
                }
            },
        })
        app.processEvents()
        assert not document.summary_panel.isVisible()
        assert [button.text() for button in document.param_view_buttons] == ["单参数贡献图", "物理链路"]
        assert document.param_view_buttons[0].isChecked()
        assert document.feature_picker.count() == 2
        assert document.workspace.isVisible()
        assert not document.selection_panel.isVisible()
        assert not document.chain_panel.isVisible()

        document.param_view_buttons[1].click()
        app.processEvents()
        assert not document.workspace.isVisible()
        assert document.selection_panel.isVisible()
        assert document.chain_panel.isVisible()
        assert "→" in document.chain_rows.itemAt(0).widget().text()
        assert "Φ<sub>s</sub>" in document.chain_rows.itemAt(0).widget().text()
        chain_text = "\n".join(
            document.chain_rows.itemAt(index).widget().text()
            for index in range(document.chain_rows.count())
            if document.chain_rows.itemAt(index).widget() is not None
        )
        assert chain_text.count("Φ<sub>s</sub>") == 1
        assert chain_text.count("M<sub>t</sub>") == 1
        assert chain_text.count("η<sub>overlap</sub>") == 1

        document.param_view_buttons[0].click()
        app.processEvents()
        assert document.workspace.isVisible()
        assert not document.selection_panel.isVisible()
        assert not document.chain_panel.isVisible()
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
    popup = TeachingImagingCouplingPopup()
    try:
        from types import SimpleNamespace

        popup.set_result(
            "spot",
            SimpleNamespace(
                success=True,
                status="completed",
                scene_revision=3,
                elapsed_ms=12.0,
                artifacts={
                    "spot": {
                        "status": "completed",
                        "metrics": {"rms_spot_radius_um": 12.5, "centroid_x_mm": 0.02},
                    }
                },
            )
        )
        popup.set_result(
            "coupling",
            SimpleNamespace(
                success=True,
                status="completed",
                scene_revision=3,
                elapsed_ms=27.0,
                artifacts={
                    "coupling": {
                        "status": "completed",
                        "metrics": {
                            "coupling_efficiency": 0.00031,
                            "mode_overlap_efficiency": 0.00042,
                            "total_coupling_efficiency": 0.00005083,
                            "coupling_loss_db": 42.9,
                        },
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
        # 成像预览在窗口上半部分，耦合数据用按钮式效率标签排在下面。
        # 窗口这时还没显示，用 isHidden 判断这一块已经放出来。
        assert not popup.imaging_block.isHidden()
        assert "12.5" in popup.imaging_summary.text()
        assert popup.imaging_visual.available
        # 窄窗口里标签不能被裁掉，否则数值读不全。
        popup.resize(popup.minimumSize())
        popup.show()
        _wait(app)
        for label in popup.coupling_pills.values():
            assert label.width() >= label.sizeHint().width() - 2, label.text()
        assert popup.coupling_pills["coupling"].text() == "模式耦合效率：0.031%"
        assert popup.coupling_pills["overlap"].text() == "模式重叠效率：0.042%"
        assert popup.coupling_pills["total"].text() == "总耦合效率：0.005083%"
        assert "耦合损耗 42.9 dB" in popup.coupling_detail.text()
        # 只留图和结果：成功不显示提示语，原始英文告警也不外泄。
        assert not popup.status.isVisible()
        assert "Exit-pupil" not in popup.status.text()
        assert "Receiver mode" not in popup.status.text()
    finally:
        popup.close()
        app.processEvents()


def test_teaching_analysis_popup_hides_placeholders_and_reports_failures() -> None:
    """空态不摆提示文字；算不出来时必须说明原因。"""
    from types import SimpleNamespace

    app = _app()
    popup = TeachingImagingCouplingPopup()
    try:
        popup.show()
        _wait(app)
        # 还没算：没有成像预览块、没有状态文字，只留按钮和效率槽位。
        assert not popup.imaging_block.isVisible()
        assert not popup.status.isVisible()
        assert popup.status.text() == ""
        assert not popup.coupling_detail.isVisible()
        assert popup.coupling_pills["total"].text() == "总耦合效率：—"

        popup.set_result("coupling", SimpleNamespace(
            success=False,
            status="failed",
            scene_revision=1,
            artifacts={"coupling": {"status": "failed", "errors": ["未命中接收端"]}},
        ))
        assert popup.status.isVisible()
        assert "未命中接收端" in popup.status.text()

        # 全部算完也不留提示词，只有结果。
        popup.set_running("", done=True)
        assert popup.status.isHidden()
        assert popup.status.text() == "正式计算完成"

        # 场景改动后旧数字必须清掉，而不是留着当现状。
        popup.set_scene_revision(2)
        assert popup.coupling_pills["total"].text() == "总耦合效率：—"
        assert "重新计算" in popup.status.text()
    finally:
        popup.close()
        app.processEvents()

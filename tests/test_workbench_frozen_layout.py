from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QCheckBox,
    QFormLayout,
    QLabel,
    QPushButton,
    QTabBar,
    QTabWidget,
    QToolButton,
)

from frontend_pyside.app.bootstrap import create_app_context
from frontend_pyside.app.workbench_shell import (
    CombinedSettingsDialog,
    DatasetRailItem,
    EngineeringDialog,
    KIND_TITLES,
    PRIMARY_MODULES,
    PrimaryBar,
    SECONDARY_ITEMS,
    WorkbenchShell,
)
from frontend_pyside.features.simulation.surface_registry import apply_type_defaults
from frontend_pyside.shared.plotting.lazy_workspace import LazyResultWorkspace


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_frozen_secondary_and_accordion_layout():
    app = _app()
    shell = WorkbenchShell(create_app_context())
    shell.resize(1200, 800)
    shell.show()
    try:
        assert shell.context.project.dirty is False
        assert [key for key, _title in PRIMARY_MODULES] == [
            "home",
            "teaching",
            "simulation",
            "model",
            "optimization",
            "explainability",
        ]
        bar = PrimaryBar()
        assert not any(button.toolTip() == "撤销" for button in bar.findChildren(QToolButton))
        assert not any(button.toolTip() == "重做" for button in bar.findChildren(QToolButton))
        bar.deleteLater()
        assert [key for key, _title, _hint in SECONDARY_ITEMS["simulation"]] == [
            "lens_data",
            "materials",
            "layout",
            "image_quality",
            "fiber_coupling",
            "wave_diffraction",
        ]
        assert [title for _key, title, _hint in SECONDARY_ITEMS["simulation"]] == [
            "镜头数据",
            "材料库",
            "光路图",
            "光斑图",
            "光纤耦合",
            "波前与衍射",
        ]
        assert "analysis" not in SECONDARY_ITEMS
        assert [key for key, _title, _hint in SECONDARY_ITEMS["explainability"]] == [
            "global_contrib",
            "param_trend",
            "current_system",
        ]
        assert [title for _key, title, _hint in SECONDARY_ITEMS["explainability"]] == [
            "贡献排序",
            "物理链路",
            "当前系统验证",
        ]
        assert ("explainability", "reason") not in KIND_TITLES
        assert ("analysis", "param_effect") not in KIND_TITLES
        assert ("model", "evaluate") not in KIND_TITLES
        assert KIND_TITLES[("simulation", "coupling")][0] == "光纤耦合"
        assert KIND_TITLES[("optimization", "scan")][0] == "扫描"

        shell.set_module("simulation")
        assert shell.object_rail.source_inspector is not None
        assert shell.object_rail.fiber_inspector is not None
        before_tabs = set(shell._tabs)
        shell.object_rail._sections["source"].set_expanded(True)
        assert "simulation:source_schematic" not in shell._tabs
        assert set(shell._tabs) == before_tabs
        source = shell.object_rail.source_inspector
        pupil_index = source.mode.findData("parallel_pupil")
        source.mode.setCurrentIndex(pupil_index)
        assert source.schematic_mode() == "pupil"

        source.mode.setCurrentIndex(
            source.mode.findData("gaussian")
        )
        source.split_axes.setChecked(False)
        source.waist.setValue(12.5)
        assert source.waist.buttonSymbols() == QAbstractSpinBox.ButtonSymbols.NoButtons
        assert source.waist.alignment() == Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        assert source.wavelength.alignment() == Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        source_state = source.form_state()
        assert source_state.source_type == "gaussian"
        assert source_state.waist_x_um == 12.5
        assert source_state.waist_y_um == 12.5

        shell.object_rail._sections["fiber"].set_expanded(True)
        assert "simulation:fiber_schematic" not in shell._tabs
        fiber = shell.object_rail.fiber_inspector
        fiber.offset_x.setValue(3.5)
        fiber.tilt_x.setValue(120.0)
        receiver_state = fiber.form_state()
        assert receiver_state.offset_x_um == 3.5
        assert receiver_state.tilt_x_urad == 120.0
        assert receiver_state.mode_model == "gaussian"

        collected = shell.collect_simulation_state()
        assert collected.source.waist_x_um == 12.5
        assert collected.receiver.offset_x_um == 3.5
        assert collected.receiver.tilt_x_urad == 120.0
        assert collected.system.pupil_radius_mm > 0
        assert collected.source.power_unit == "mW"
        assert collected.receiver.mode_field_diameter_x_um > 0
        assert collected.receiver.core_refractive_index > 1
        assert "raytrace" in collected.calculation.analyses
        assert "coupling" in collected.calculation.analyses

        assert shell.object_rail.environment_inspector is not None
        assert shell.object_rail.field_inspector is not None
        assert shell.object_rail.detector_inspector is not None
        assert shell.object_rail.lens_sliders is not None
        detector = shell.object_rail.detector_inspector
        assert [detector.placement.itemText(index) for index in range(detector.placement.count())] == [
            "光学面",
            "光纤模场",
            "自定义位置",
        ]
        assert detector.observation()["mode"] == "surface"
        assert not detector.surface.isHidden()
        assert detector.offset.isHidden()
        custom_index = detector.placement.findData("custom")
        detector.placement.setCurrentIndex(custom_index)
        assert detector.surface.isHidden()
        assert not detector.offset.isHidden()
        fiber_index = detector.placement.findData("fiber")
        detector.placement.setCurrentIndex(fiber_index)
        assert detector.surface.isHidden()
        assert detector.offset.isHidden()
        assert detector.pitch.isHidden()
        detector.placement.setCurrentIndex(detector.placement.findData("surface"))
        detector.enabled.setChecked(False)
        assert detector.placement.isHidden()
        detector.enabled.setChecked(True)
        assert not detector.placement.isHidden()
        assert shell.object_rail.lens_sliders.list.minimumHeight() >= 200
        # 高频项在前，环境/视场这两个低频项排在最后；「镜头组」已从左侧栏移除。
        assert list(shell.object_rail._sections) == [
            "source",
            "materials",
            "fiber",
            "detector",
            "environment",
            "field",
        ]
        assert shell.object_rail.materials_inspector is not None
        used_names = [
            shell.object_rail.materials_inspector.names.item(row).text()
            for row in range(shell.object_rail.materials_inspector.names.count())
        ]
        assert used_names
        assert "AIR" not in used_names
        assert "N-BK7" in used_names
        before_material_tabs = set(shell._tabs)
        shell.object_rail._sections["materials"].set_expanded(True)
        assert set(shell._tabs) == before_material_tabs
        shell._secondary_clicked("materials")
        assert "simulation:material_library" in shell._tabs
        library = shell._widgets["simulation:material_library"]
        assert [
            library.table.horizontalHeaderItem(index).text()
            for index in range(library.table.columnCount())
        ] == ["材料名", "折射率", "波长", "更多"]
        assert library.table.rowCount() > 8
        from frontend_pyside.features.simulation.material_library import more_column_width

        more_width = more_column_width(library.table)
        assert library.table.columnWidth(3) == more_width
        assert more_width > library.table.fontMetrics().horizontalAdvance("更多") + 24
        catalog_names = [
            library.table.item(row, 0).text()
            for row in range(library.table.rowCount())
        ]
        assert "N-BK7" in catalog_names
        custom = next(button for button in library.findChildren(QPushButton) if button.text() == "自定义材料")
        assert custom.property("kind") == "primary"
        shell.context.project.upsert_custom_material({"name": "MY-GLASS", "model": "constant", "n": 1.62})
        library.refresh()
        catalog_names = [
            library.table.item(row, 0).text()
            for row in range(library.table.rowCount())
        ]
        assert "MY-GLASS" in catalog_names
        field_labels = [
            child.text()
            for child in shell.object_rail.field_inspector.findChildren(QLabel)
            if child.text()
        ]
        assert "入瞳半径" in field_labels
        assert "视场角 X" in field_labels
        field_forms = shell.object_rail.field_inspector.findChildren(QFormLayout)
        assert field_forms
        assert field_forms[0].rowWrapPolicy() == QFormLayout.RowWrapPolicy.WrapAllRows
        env_inspector = shell.object_rail.environment_inspector
        env_labels = [
            child.text()
            for child in env_inspector.findChildren(QLabel)
            if child.text()
        ]
        assert "大气" in env_labels
        assert "物像共轭" in env_labels
        assert "环境温度" in env_labels
        assert "物距" in env_labels
        env_inspector.temperature.setValue(25.0)
        collected = shell.collect_simulation_state()
        assert collected.system.environment_temperature_c == 25.0
        before_tabs = set(shell._tabs)
        shell.object_rail._sections["environment"].set_expanded(True)
        shell.object_rail._sections["field"].set_expanded(True)
        assert set(shell._tabs) == before_tabs

        source = shell.object_rail.source_inspector
        assert [source.mode.itemText(index) for index in range(source.mode.count())] == [
            "高斯光束",
            "均匀光瞳",
            "点光源",
        ]
        labels = [child.text() for child in source.findChildren(QLabel) if child.text()]
        assert "束腰半径 w₀" in labels
        assert "总功率" in labels
        assert "视场角 X" not in labels
        fiber_labels = [child.text() for child in fiber.findChildren(QLabel) if child.text()]
        assert "模场直径 MFD" in fiber_labels
        assert "纤芯折射率 n_core" in fiber_labels
        assert [fiber.kind.itemText(index) for index in range(fiber.kind.count())] == [
            "单模光纤",
            "多模光纤",
            "用户模式",
        ]

        env = EngineeringDialog("environment", shell.context, system=shell._system_state)
        env_labels = [child.text() for child in env.findChildren(QLabel) if child.text()]
        assert env.windowTitle() == "系统环境"
        assert "环境温度" in env_labels
        assert "物距" in env_labels
        assert "像面位置" in env_labels
        env.close()

        aperture = EngineeringDialog("aperture", shell.context, system=shell._system_state)
        aperture_labels = [child.text() for child in aperture.findChildren(QLabel) if child.text()]
        assert aperture.windowTitle() == "孔径与视场"
        assert "入瞳半径" in aperture_labels
        assert "视场角 X" in aperture_labels
        aperture.close()

        shell.open_document("simulation", "lens_data")
        assert shell._lens_document is not None
        editor = shell._lens_document.editor
        lens_headers = [
            editor.table.horizontalHeaderItem(index).text()
            for index in range(editor.table.columnCount())
        ]
        assert "关键参数" not in lens_headers
        assert "半口径 / mm" in lens_headers
        apply_type_defaults(editor.context.project.surfaces[0], "柱面")
        apply_type_defaults(editor.context.project.surfaces[1], "非球面")
        editor.reload()
        lens_headers = [
            editor.table.horizontalHeaderItem(index).text()
            for index in range(editor.table.columnCount())
        ]
        axis_col = next(index for index, text in enumerate(lens_headers) if "柱轴方位角" in text)
        a4_col = next(index for index, text in enumerate(lens_headers) if "非球面 A4" in text)
        assert editor.table.item(0, axis_col).text() != "未使用"
        assert editor.table.item(1, axis_col).text() == "未使用"
        assert not (editor.table.item(1, axis_col).flags() & Qt.ItemFlag.ItemIsEditable)
        assert editor.table.item(1, a4_col).text() != "未使用"
        assert editor.table.item(0, a4_col).text() == "未使用"
        assert editor.table.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAsNeeded
        apply_type_defaults(editor.context.project.surfaces[0], "球面")
        apply_type_defaults(editor.context.project.surfaces[1], "球面")
        editor.reload()
        assert shell.findChild(QToolButton, "DocumentSplitButton") is None
        assert not any(button.text() == "并排" for button in shell.findChildren(QToolButton))
        pane = shell.workspace.panes[0]
        pin = pane.tabBar().tabButton(pane.currentIndex(), QTabBar.ButtonPosition.LeftSide)
        assert pin is not None and pin.objectName() == "DocumentPinButton"
        assert pin.toolTip() == "固定此页"
        pin.setChecked(True)
        assert pane.is_current_pinned() is True
        assert pin.toolTip() == "取消固定"
        shell.open_document("simulation", "spot")
        assert len(shell.workspace.panes) == 2

        shell._secondary_clicked("fiber_coupling")
        assert "simulation:coupling" in shell._tabs

        shell.set_module("model")
        assert [key for key, _title, _hint in SECONDARY_ITEMS["model"]] == [
            "dataset",
            "train_result",
            "predict_eval",
        ]
        assert [title for _key, title, _hint in SECONDARY_ITEMS["model"]] == [
            "数据集",
            "训练结果",
            "模型预测",
        ]
        rail_texts = [
            shell.object_rail.list.item(index).text()
            for index in range(shell.object_rail.list.count())
        ]
        assert "预测与评估" not in rail_texts
        assert "数据集" not in rail_texts
        assert any("780" in text for text in rail_texts)
        assert not any("结构序列" in text for text in rail_texts)
        shell.open_document("model", "dataset")
        dataset = shell._widgets["model:dataset"]
        assert any(button.text() == "开始训练" for button in dataset.findChildren(QPushButton))
        assert any(button.text() == "选择文件" for button in dataset.findChildren(QPushButton))
        assert any(button.text() == "导入" for button in dataset.findChildren(QPushButton))
        assert any(button.text() == "内置" for button in dataset.findChildren(QPushButton))
        assert dataset.builtin.count() == 1
        assert [
            dataset.data_kind.itemText(index) for index in range(dataset.data_kind.count())
        ] == ["按照镜头", "按照元件"]
        assert "BiLSTM" not in [
            dataset.model_type.itemText(index) for index in range(dataset.model_type.count())
        ]
        dataset_labels = [child.text() for child in dataset.findChildren(QLabel) if child.text()]
        assert "数据来源" in dataset_labels
        assert "采样方式" in dataset_labels
        assert "1. 数据" in dataset_labels
        assert "2. 训练" in dataset_labels
        assert not any(text.startswith("3.") for text in dataset_labels)
        assert "训练模型" not in dataset_labels
        assert "计算精度" in dataset_labels
        assert "树数量" in dataset_labels
        assert "最大深度" in dataset_labels
        assert not hasattr(dataset, "table")
        assert "样本" not in [
            child.text()
            for child in dataset.findChildren(QLabel)
            if child.objectName() == "FieldGroupTitle"
        ]
        assert dataset.lens_count.count() == 4
        assert dataset.variable_scheme.count() == 2
        assert dataset.import_host.isVisible()
        assert dataset.generate_host.isHidden()
        assert dataset.generate_more_host.isHidden()
        assert dataset.sequence_host.isHidden()
        dataset.data_kind.setCurrentIndex(dataset.data_kind.findData("sequence"))
        assert dataset.builtin.count() == 1
        assert [dataset.model_type.itemText(index) for index in range(dataset.model_type.count())] == ["BiLSTM"]
        assert dataset.sequence_host.isHidden()
        dataset.file_path.setText("custom_sequence.csv")
        dataset.import_button.click()
        assert dataset.sequence_host.isVisible()
        assert dataset.training_mode_button.text() == "任意镜头数"
        assert dataset.training_parameters_host.isHidden()
        assert dataset.sequence_training_group.isHidden()
        assert dataset.rf_training_group.isHidden()
        tabs = dataset.findChildren(QTabWidget)
        tab_titles = [tab.tabText(index) for tab in tabs for index in range(tab.count())]
        assert "来源与训练" not in tab_titles
        assert "生成变量" not in tab_titles
        dataset.data_kind.setCurrentIndex(dataset.data_kind.findData("tabular"))
        dataset.trainRequested.emit()
        assert "model:train_result" in shell._tabs
        train_result = shell._widgets["model:train_result"]
        assert train_result._trained is False
        assert [
            train_result.chart.itemText(index) for index in range(train_result.chart.count())
        ] == ["残差图", "实测值与预测值对照", "残差分布", "验证误差曲线"]
        shell.open_document("model", "predict")
        predict = shell._widgets["model:predict"]
        assert predict.predict_model.count() == 0
        assert predict.predict_target.text() == "尚未训练"
        assert predict.input_table.rowCount() > 4
        assert predict.input_table.item(0, 0).text() == "波长"
        assert "光纤模场直径" in [
            predict.input_table.item(row, 0).text() for row in range(predict.input_table.rowCount())
        ]
        assert any(child.text() == "已训练模型" for child in predict.findChildren(QLabel) if child.text())
        assert any(child.text() == "2. 当前镜头" for child in predict.findChildren(QLabel) if child.text())
        assert any(child.text() == "3. 结果" for child in predict.findChildren(QLabel) if child.text())
        assert not any(child.text() == "1. 预测设置" for child in predict.findChildren(QLabel) if child.text())
        assert not any(child.text() == "3. 预测结果" for child in predict.findChildren(QLabel) if child.text())
        predict._run_predict()
        assert predict.metrics.isVisible()
        assert "训练" in predict.metrics.text()
        trained = [{
            "id": "model-test-1",
            "title": "随机森林 · run-1",
            "model_type": "随机森林",
            "target": "耦合损耗(dB)",
            "family": "tabular",
        }]
        shell._trained_models = trained
        shell._sync_rail_document()
        shell.open_document("model", "predict")
        model_rows = [
            shell.object_rail.list.itemWidget(shell.object_rail.list.item(index))
            for index in range(shell.object_rail.list.count())
        ]
        assert any(isinstance(row, DatasetRailItem) for row in model_rows)

        shell.set_module("optimization")
        assert [key for key, _title, _hint in SECONDARY_ITEMS["optimization"]] == [
            "scan",
            "opt_vars",
            "opt_result",
        ]
        assert [title for _key, title, _hint in SECONDARY_ITEMS["optimization"]] == [
            "扫描",
            "优化",
            "优化结果",
        ]
        assert shell.object_rail.goal_inspector is not None
        assert shell.object_rail.list.count() > 3
        shell.open_document("optimization", "opt_goal")
        assert "optimization:opt_vars" in shell._tabs
        assert "optimization:opt_goal" not in shell._tabs
        opt_page = shell._widgets["optimization:opt_vars"]
        assert opt_page.current_metric.parentWidget().height() == opt_page.secondary_objective.height()
        rail = shell.object_rail
        assert [
            rail.optimization_variables_button.text(),
            rail.optimization_more_button.text(),
        ] == ["优化变量", "更多参数"]
        assert rail.optimization_variable_host.isVisible()
        rail.optimization_more_button.click()
        assert rail.optimization_more_scroll.isVisible()
        assert rail.optimization_more_scroll.widgetResizable()
        goal = rail.goal_inspector
        goal.collimation.setChecked(True)
        app.processEvents()
        viewport = rail.optimization_more_scroll.viewport()
        for editor in (
            goal.goal,
            goal.max_length,
            goal.collimation_surface,
            goal.collimation_span,
            goal.collimation_curvature,
            goal.collimation_tilt,
            rail.max_evaluations,
        ):
            editor_right = editor.mapTo(viewport, QPoint(editor.width(), 0)).x()
            assert editor_right <= viewport.width()
        goal.collimation.setChecked(False)
        assert (
            rail.optimization_more_scroll.verticalScrollBarPolicy()
            == Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        assert rail.optimization_variable_host.isHidden()
        assert rail.goal_inspector is opt_page.goal
        assert rail.max_evaluations is opt_page.max_evaluations
        assert opt_page.more_button is None
        assert opt_page.advanced_panel is None
        rail.optimization_variables_button.click()
        assert rail.optimization_variable_host.isVisible()
        assert rail.optimization_more_scroll.isHidden()
        assert opt_page.goal is not None
        goal = opt_page.goal
        opt_labels = [child.text() for child in goal.findChildren(QLabel) if child.text()]
        assert "方式" in opt_labels
        assert "评价方式" not in opt_labels
        assert "算法" not in opt_labels
        assert "工程约束" in opt_labels
        assert "最小厚度" in opt_labels
        assert "最小空气厚度" in opt_labels
        assert "最小中心厚度" not in opt_labels
        assert "最小空气间隔" not in opt_labels
        assert "最大评价次数" in [child.text() for child in opt_page.findChildren(QLabel) if child.text()]
        assert "准直约束" in opt_labels
        assert goal.collimation.text() == "启用"
        assert [
            goal.eval_mode.itemText(index) for index in range(goal.eval_mode.count())
        ] == ["光学仿真", "已训练模型"]
        assert goal.predict_model.isHidden()
        goal.eval_mode.setCurrentIndex(goal.eval_mode.findData("surrogate"))
        assert not goal.predict_model.isHidden()
        assert [
            goal.predict_model.itemText(index) for index in range(goal.predict_model.count())
        ] == ["随机森林 · run-1"]
        goal.eval_mode.setCurrentIndex(goal.eval_mode.findData("formal"))
        assert goal.collimation_surface.isHidden()
        goal.collimation.setChecked(True)
        assert not goal.collimation_surface.isHidden()
        assert not goal.collimation_tilt.isHidden()
        assert getattr(opt_page, "workspace", None) is None
        shell.start_optimization()
        assert "optimization:opt_result" in shell._tabs
        result_page = shell._widgets["optimization:opt_result"]
        assert [
            result_page.chart.itemText(index) for index in range(result_page.chart.count())
        ] == ["过程曲线", "候选对照"]
        rail = shell.object_rail
        assert not rail.shap_button.isVisible()
        assert rail.shap_button.text() == "SHAP"
        assert not rail.shap_button.isEnabled()
        opt_table = opt_page.table
        assert [
            opt_table.horizontalHeaderItem(index).text()
            for index in range(opt_table.columnCount())
        ] == ["参数", "当前值", "最小值", "最大值"]
        shell.open_document("optimization", "scan")
        scan_page = shell._widgets["optimization:scan"]
        assert not hasattr(scan_page, "variable_a")
        assert [
            scan_page.range_table.horizontalHeaderItem(index).text()
            for index in range(scan_page.range_table.columnCount())
        ] == ["参数", "最小", "最大"]
        assert scan_page.run_button.isEnabled() is False

        shell.set_module("explainability")
        shell._secondary_clicked("global_contrib")
        widget = shell._widgets["explainability:global_contrib"]
        plots = widget.findChildren(LazyResultWorkspace)
        assert len(plots) == 1
        global_rail = [
            shell.object_rail.list.item(index).text()
            for index in range(shell.object_rail.list.count())
        ]
        assert any("run-1" in text for text in global_rail)
        assert not any("780" in text for text in global_rail)
        assert widget.compute.isEnabled() is True
        shell._secondary_clicked("param_trend")
        assert shell.object_rail.list.count() > 3
        assert shell._widgets["explainability:param_trend"].compute.isEnabled() is True

        dialog = EngineeringDialog("compute", shell.context, calculation=shell._calculation_state)
        assert dialog.windowTitle() == "采样与运行"
        compute_labels = [child.text() for child in dialog.findChildren(QLabel) if child.text()]
        assert "接收面网格" in compute_labels
        assert "计算窗口" in compute_labels
        assert "最大倾角" in compute_labels
        assert dialog.analysis_boxes["psf"].text() == "点扩散函数 PSF"
        assert dialog.high_precision.text() == "完整复场耦合"
        calc = dialog.calculation_state()
        assert calc.output_grid_size >= 65
        assert "raytrace" in calc.analyses
        dialog.close()

        settings = CombinedSettingsDialog(
            shell.context,
            calculation=shell._calculation_state,
            alignment=shell._alignment_state,
        )
        assert settings.windowTitle() == "计算设置"
        assert settings.findChildren(QTabWidget) == []
        assert "开始正式计算" not in [
            child.text() for child in settings.compute.findChildren(QPushButton)
        ]
        settings.close()
    finally:
        shell.close()
        app.processEvents()

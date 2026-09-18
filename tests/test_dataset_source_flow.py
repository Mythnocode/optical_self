from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel

from frontend_pyside.app.bootstrap import create_app_context
from frontend_pyside.modules.model.dataset import DatasetTab


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_dataset_page_uses_two_numbered_sections_and_collapsible_generation_options() -> None:
    _app()
    widget = DatasetTab(create_app_context())
    widget.show()
    try:
        labels = [child.text() for child in widget.findChildren(QLabel) if child.text()]
        assert "1. 数据" in labels
        assert "2. 训练" in labels
        assert not any(text.startswith("3.") for text in labels)
        assert widget.current_source_mode() == "import"
        assert widget.import_host.isVisible()
        assert widget.generate_host.isHidden()
        assert widget.training_mode_button.text() == "固定镜头数"
        assert widget.training_mode_button.property("trainingMode") == "fixed"
        assert widget.train_button.text() == "开始训练"
        assert widget.training_parameters_host.isHidden()
        assert widget.training_more_button.isVisible()
        widget.training_more_button.click()
        assert widget.training_parameters_host.isVisible()
        assert widget.rf_training_group.isVisible()
        assert widget.xgb_training_group.isVisible()
        assert widget.sequence_training_group.isHidden()
        widget.training_more_button.click()

        widget.training_mode_button.click()
        assert widget.training_mode_button.text() == "任意镜头数"
        assert widget.training_mode_button.property("trainingMode") == "arbitrary"
        assert widget.current_family() == "sequence"
        assert widget.model_type.currentText() == "BiLSTM"
        assert widget.training_parameters_host.isHidden()
        widget.training_more_button.click()
        assert widget.training_parameters_host.isVisible()
        assert widget.rf_training_group.isHidden()
        assert widget.xgb_training_group.isHidden()
        assert widget.sequence_training_group.isVisible()
        widget.training_more_button.click()
        assert widget.training_parameters_host.isHidden()
        widget.training_mode_button.click()
        assert widget.training_mode_button.text() == "固定镜头数"
        assert widget.training_mode_button.property("trainingMode") == "fixed"
        assert widget.current_family() == "tabular"

        widget.source_mode.setCurrentIndex(1)
        assert widget.current_source_mode() == "generate"
        assert widget.import_host.isHidden()
        assert widget.generate_host.isVisible()
        assert widget.samples.isVisible()
        assert widget.target.isVisible()
        assert widget.generation_mode_button.text() == "固定镜头数"
        assert widget.generation_mode_button.property("generationMode") == "fixed"
        assert widget.generate_more_host.isHidden()

        widget.generate_more_button.click()
        assert widget.generate_more_host.isVisible()
        assert widget.lens_count.isVisible()
        assert widget.precision.isVisible()

        widget.generation_mode_button.click()
        assert widget.current_family() == "sequence"
        assert widget.generation_mode_button.text() == "任意镜头数"
        assert widget.generation_mode_button.property("generationMode") == "arbitrary"
        assert widget.fixed_generation_host.isHidden()
        assert widget.sequence_generation_host.isVisible()
        assert widget.generate_button.text() == "生成数据集"
        assert widget.generate_button.isEnabled()
        widget.sequence_variable_button.click()
        first_path, first_check = next(iter(widget.sequence_variable_checks.items()))
        for check in widget.sequence_variable_checks.values():
            check.setChecked(False)
        first_check.setChecked(True)
        assert widget.sequence_variable_host.isVisible()
        assert widget.sequence_variable_paths() == [first_path]
    finally:
        widget.close()


def test_import_and_builtin_actions_keep_the_selected_source_explicit() -> None:
    _app()
    widget = DatasetTab(create_app_context())
    widget.show()
    imported_paths: list[str] = []
    widget.fileImportRequested.connect(imported_paths.append)
    try:
        widget.file_path.setText("custom_samples.csv")
        assert widget.import_button.isEnabled()
        widget.import_button.click()
        assert imported_paths == ["custom_samples.csv"]
        assert widget.current_dataset_source() == "file_pending"
        assert not widget.builtin_button.isEnabled()

        widget.mark_file_imported("external-1")
        assert widget.selected_dataset_id() == "external-1"
        assert widget.current_dataset_source() == "file"
        assert not widget.builtin_button.isEnabled()

        builtin_widget = DatasetTab(create_app_context())
        builtin_widget.show()
        try:
            builtin_widget._select_builtin()
            assert builtin_widget.current_dataset_source() == "builtin"
            assert builtin_widget.selected_dataset_id() == "dataset-880bdde6c292"
            assert not builtin_widget.import_button.isEnabled()
            builtin_widget.source_mode.setCurrentIndex(1)
            assert builtin_widget.current_dataset_source() == ""
            assert builtin_widget.selected_dataset_id() == ""
            builtin_widget.set_active_dataset("generated-1", "generated")
            builtin_widget.source_mode.setCurrentIndex(0)
            assert builtin_widget.current_dataset_source() == ""
            assert builtin_widget.selected_dataset_id() == ""
        finally:
            builtin_widget.close()
    finally:
        widget.close()

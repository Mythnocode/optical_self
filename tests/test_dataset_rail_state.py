from __future__ import annotations

import os
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from frontend_pyside.app.bootstrap import create_app_context
from frontend_pyside.app.workbench_shell import WorkbenchShell


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _rail_item(shell: WorkbenchShell, dataset_id: str):
    key = f"dataset:{dataset_id}"
    for index in range(shell.object_rail.list.count()):
        item = shell.object_rail.list.item(index)
        if item is not None and item.data(Qt.ItemDataRole.UserRole) == key:
            return item, shell.object_rail.list.itemWidget(item)
    raise AssertionError(f"missing rail item: {key}")


def test_dataset_selection_uses_green_check_and_training_id() -> None:
    _app()
    shell = WorkbenchShell(create_app_context())
    shell.show()
    try:
        shell.set_module("model")
        shell.open_document("model", "dataset")
        dataset = shell._widgets["model:dataset"]
        dataset_id = "dataset-880bdde6c292"

        shell._model_object_clicked(f"dataset:{dataset_id}")

        assert shell.object_rail.selected_dataset_id() == dataset_id
        assert dataset.selected_dataset_id() == dataset_id
        _item, row = _rail_item(shell, dataset_id)
        assert row is not None
        assert row.check_label.isVisible()
    finally:
        shell.close()


def test_pending_generation_progress_is_renamed_in_place() -> None:
    _app()
    shell = WorkbenchShell(create_app_context())
    shell.show()
    try:
        shell.set_module("model")
        shell.open_document("model", "dataset")
        pending_id = "pending-dataset-test"
        shell._pending_generated_dataset_id = pending_id
        shell._register_pending_generated_dataset(pending_id)
        shell.object_rail.set_selected_dataset(pending_id)
        _initial_item, initial_row = _rail_item(shell, pending_id)
        with patch.object(
            shell.object_rail,
            "set_catalogs",
            wraps=shell.object_rail.set_catalogs,
        ) as rebuild_catalog:
            shell._update_pending_generated_dataset(0.37, "仿真")
            rebuild_catalog.assert_not_called()

        item, row = _rail_item(shell, pending_id)
        assert item.text() == ""
        assert row is not None
        assert row is initial_row
        assert row.title_label.text() == "数据集生成"
        assert row.progress_bar is not None
        assert row.progress_bar.value() == 37
        assert row.check_label.isVisible()

        name, selected = shell._finalize_pending_generated_dataset(
            "generated-dataset-test", title="数据集1"
        )

        assert name == "数据集1"
        assert selected is True
        assert not any(
            item.get("id") == pending_id for item in shell._datasets
        )
        final = next(
            item for item in shell._datasets
            if item.get("id") == "generated-dataset-test"
        )
        assert final["title"] == "数据集1"
        assert final["kind"] == "generated"
        assert shell.object_rail.selected_dataset_id() == "generated-dataset-test"
    finally:
        shell.close()


def test_failed_generation_stays_in_rail_with_failure_mark() -> None:
    _app()
    shell = WorkbenchShell(create_app_context())
    shell.show()
    try:
        shell.set_module("model")
        shell.open_document("model", "dataset")
        pending_id = "pending-dataset-failed"
        shell._pending_generated_dataset_id = pending_id
        shell._register_pending_generated_dataset(pending_id)
        shell.object_rail.set_selected_dataset(pending_id)
        shell._update_pending_generated_dataset(0.56, "仿真")

        shell._on_workbench_job_failed("dataset", "job timed out after 780.0 s")

        failed = next(item for item in shell._datasets if item.get("id") == pending_id)
        assert failed["kind"] == "generated_failed"
        assert failed["status"] == "生成失败"
        assert failed["error"] == "job timed out after 780.0 s"
        assert shell._pending_generated_dataset_id == ""
        assert shell.object_rail.selected_dataset_id() == ""
        _item, row = _rail_item(shell, pending_id)
        assert row is not None
        assert row.check_label.objectName() == "datasetFailureMark"
        assert row.check_label.isVisible()
        assert row.cancel_button is None
        assert row.progress_bar is not None
        assert row.progress_bar.value() == 56
    finally:
        shell.close()


def test_pending_generation_row_exposes_cancel_entry() -> None:
    _app()
    shell = WorkbenchShell(create_app_context())
    shell.show()
    try:
        shell.set_module("model")
        shell.open_document("model", "dataset")
        pending_id = "pending-dataset-cancel"
        shell._pending_generated_dataset_id = pending_id
        shell._register_pending_generated_dataset(pending_id)
        _item, row = _rail_item(shell, pending_id)

        assert row is not None
        assert row.cancel_button is not None
        requested: list[str] = []
        shell.object_rail.datasetCancelRequested.connect(requested.append)
        row.cancel_button.click()

        assert requested == [pending_id]
        row.set_cancelling(True)
        assert not row.cancel_button.isEnabled()
        assert row.cancel_button.text() == "取消中"
    finally:
        shell.close()

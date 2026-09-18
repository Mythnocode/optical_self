from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

QApplication = pytest.importorskip("PySide6.QtWidgets").QApplication

from frontend_pyside.app.bootstrap import create_app_context
from frontend_pyside.app.workbench_shell import WorkbenchShell


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_generated_dataset_names_are_sequential_and_imports_keep_filename() -> None:
    _app()
    shell = WorkbenchShell(create_app_context())
    try:
        assert shell._next_generated_dataset_name() == "数据集1"
        assert shell._register_generated_dataset("dataset-one") == "数据集1"
        assert shell._register_generated_dataset("dataset-two") == "数据集2"

        shell._register_dataset("实验数据.csv", dataset_id="external-one")

        generated = [item for item in shell._datasets if item.get("kind") == "generated"]
        imported = next(item for item in shell._datasets if item.get("id") == "external-one")
        assert [item["title"] for item in generated] == ["数据集1", "数据集2"]
        assert imported["title"] == "实验数据.csv"
        assert shell._next_generated_dataset_name() == "数据集3"
    finally:
        shell.close()

from __future__ import annotations



from typing import Callable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QVBoxLayout, QWidget

from frontend_pyside.shared.components.basic import SecondaryButton


from backend.optical_ml_app.application.complex_fields import ImportedComplexField, load_complex_field


class ImportedFieldSelector(QWidget):
    fieldChanged = Signal()

    def __init__(self, expected_grid_size: Callable[[], int | None], parent=None):
        super().__init__(parent)
        self._expected_grid_size = expected_grid_size
        self._data: ImportedComplexField | None = None
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        self.path_edit = QLineEdit()
        self.path_edit.setReadOnly(True)
        self.path_edit.setPlaceholderText("尚未选择复场文件")
        self.path_edit.setMinimumWidth(170)
        self.select_button = SecondaryButton("选择…")
        self.select_button.clicked.connect(self.choose_file)
        row.addWidget(self.path_edit, 1)
        row.addWidget(self.select_button, 0)
        root.addLayout(row)
        self.status_label = QLabel("")
        self.status_label.setObjectName("helperText")
        self.status_label.setWordWrap(True)
        self.status_label.setVisible(False)
        root.addWidget(self.status_label)

    @property
    def data(self) -> ImportedComplexField | None:
        return self._data

    def clear(self) -> None:
        self._data = None
        self.path_edit.clear()
        self.status_label.clear()
        self.status_label.setVisible(False)
        self.fieldChanged.emit()

    def choose_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择光纤复场文件",
            "",
            "复场数据 (*.npy *.npz *.csv);;NPY (*.npy);;NPZ (*.npz);;CSV (*.csv)",
        )
        if path:
            self.load_path(path, show_error=True)

    def load_path(self, path: str, *, show_error: bool = False) -> bool:
        try:
            expected = self._expected_grid_size()
            data = load_complex_field(path, expected_grid_size=expected)
        except Exception as exc:
            self._data = None
            self.path_edit.setText(str(path))
            self.status_label.setText(f"导入失败：{exc}")
            self.status_label.setVisible(True)
            if show_error:
                QMessageBox.warning(self, "复场导入失败", str(exc))
            self.fieldChanged.emit()
            return False
        self._data = data
        self.path_edit.setText(data.path)
        wavelength = f"，文件波长 {data.wavelength_nm:g} nm" if data.wavelength_nm is not None else ""
        self.status_label.setText(
            f"已读取 {data.rows}×{data.columns}{wavelength}"
        )
        self.status_label.setVisible(True)
        self.fieldChanged.emit()
        return True


__all__ = ["ImportedComplexField", "ImportedFieldSelector", "load_complex_field"]

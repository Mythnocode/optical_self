from __future__ import annotations



from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QVBoxLayout, QWidget

from frontend_pyside.shared.components.basic import SecondaryButton


@dataclass(frozen=True, slots=True)
class ImportedComplexField:
    path: str
    real: tuple[tuple[float, ...], ...]
    imag: tuple[tuple[float, ...], ...]
    rows: int
    columns: int
    source_format: str
    interpretation: str
    wavelength_nm: float | None = None

    def request_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "real": [list(row) for row in self.real],
            "imag": [list(row) for row in self.imag],
            "shape": [self.rows, self.columns],
            "source_format": self.source_format,
        }
        if self.wavelength_nm is not None:
            payload["wavelength_nm"] = float(self.wavelength_nm)
        return payload


def _field_from_npz(path: Path) -> tuple[np.ndarray, str, float | None]:
    with np.load(path, allow_pickle=False) as data:
        names = set(data.files)
        wavelength = None
        if "wavelength_nm" in names:
            raw = np.asarray(data["wavelength_nm"]).reshape(-1)
            if raw.size:
                wavelength = float(raw[0])
        if "field" in names:
            return np.asarray(data["field"]), "复数复场", wavelength
        if {"real", "imag"}.issubset(names):
            real = np.asarray(data["real"], dtype=float)
            imag = np.asarray(data["imag"], dtype=float)
            if real.shape != imag.shape:
                raise ValueError("NPZ 中 real 与 imag 的尺寸不一致")
            return real + 1j * imag, "实部与虚部", wavelength
        if {"amplitude", "phase_rad"}.issubset(names):
            amplitude = np.asarray(data["amplitude"], dtype=float)
            phase = np.asarray(data["phase_rad"], dtype=float)
            if amplitude.shape != phase.shape:
                raise ValueError("NPZ 中 amplitude 与 phase_rad 的尺寸不一致")
            return amplitude * np.exp(1j * phase), "振幅与相位", wavelength
    raise ValueError("NPZ 文件需包含 field，或 real/imag，或 amplitude/phase_rad")


def _field_from_csv(path: Path) -> tuple[np.ndarray, str, float | None]:
    structured = np.genfromtxt(path, delimiter=",", names=True, encoding="utf-8-sig")
    if structured.dtype.names:
        names = {name.lower(): name for name in structured.dtype.names}
        if "real" not in names or "imag" not in names:
            raise ValueError("CSV 表头至少需要 real、imag 两列")
        real = np.asarray(structured[names["real"]], dtype=float).reshape(-1)
        imag = np.asarray(structured[names["imag"]], dtype=float).reshape(-1)
        if "x_mm" in names and "y_mm" in names:
            x = np.asarray(structured[names["x_mm"]], dtype=float).reshape(-1)
            y = np.asarray(structured[names["y_mm"]], dtype=float).reshape(-1)
            x_unique = np.unique(x)
            y_unique = np.unique(y)
            if x_unique.size * y_unique.size != real.size:
                raise ValueError("CSV 的 x_mm、y_mm 不能组成完整规则网格")
            order = np.lexsort((x, y))
            field = (real[order] + 1j * imag[order]).reshape(y_unique.size, x_unique.size)
            return field, "坐标、实部与虚部", None
        side = int(round(real.size ** 0.5))
        if side * side != real.size:
            raise ValueError("不含坐标的 CSV 行数必须能组成方形网格")
        return (real + 1j * imag).reshape(side, side), "实部与虚部", None
    raise ValueError("CSV 文件需要包含表头")


def load_complex_field(path: str | Path, *, expected_grid_size: int | None = None) -> ImportedComplexField:
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise ValueError("文件不存在")
    suffix = source.suffix.lower()
    wavelength = None
    if suffix == ".npy":
        array = np.load(source, allow_pickle=False)
        interpretation = "复数复场" if np.iscomplexobj(array) else "实数振幅（相位为零）"
    elif suffix == ".npz":
        array, interpretation, wavelength = _field_from_npz(source)
    elif suffix == ".csv":
        array, interpretation, wavelength = _field_from_csv(source)
    else:
        raise ValueError("仅支持 NPY、NPZ 和 CSV 文件")

    values = np.asarray(array, dtype=np.complex128)
    if values.ndim != 2:
        raise ValueError("复场数据必须是二维数组")
    rows, columns = values.shape
    if rows < 17 or columns < 17:
        raise ValueError("复场网格每个方向至少需要 17 个采样点")
    if rows != columns:
        raise ValueError("当前正式耦合求解要求方形复场网格")
    if expected_grid_size is not None and rows != int(expected_grid_size):
        raise ValueError(f"复场尺寸为 {rows}×{columns}，当前接收面网格为 {expected_grid_size}×{expected_grid_size}")
    if not np.all(np.isfinite(values.real)) or not np.all(np.isfinite(values.imag)):
        raise ValueError("复场包含 NaN 或无穷值")
    power = float(np.sum(np.abs(values) ** 2))
    if not np.isfinite(power) or power <= 0.0:
        raise ValueError("复场总功率必须大于零")
    values = values / np.sqrt(power)
    return ImportedComplexField(
        path=str(source),
        real=tuple(tuple(float(value) for value in row) for row in values.real),
        imag=tuple(tuple(float(value) for value in row) for row in values.imag),
        rows=rows,
        columns=columns,
        source_format=suffix.lstrip(".").upper(),
        interpretation=interpretation,
        wavelength_nm=wavelength,
    )


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
        self.status_label = QLabel("支持 NPY、NPZ、CSV；数据将归一化后用于正式耦合。")
        self.status_label.setObjectName("helperText")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

    @property
    def data(self) -> ImportedComplexField | None:
        return self._data

    def clear(self) -> None:
        self._data = None
        self.path_edit.clear()
        self.status_label.setText("支持 NPY、NPZ、CSV；数据将归一化后用于正式耦合。")
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
            if show_error:
                QMessageBox.warning(self, "复场导入失败", str(exc))
            self.fieldChanged.emit()
            return False
        self._data = data
        self.path_edit.setText(data.path)
        wavelength = f"，文件波长 {data.wavelength_nm:g} nm" if data.wavelength_nm is not None else ""
        self.status_label.setText(
            f"已读取 {data.rows}×{data.columns}，{data.interpretation}，已完成归一化{wavelength}。"
        )
        self.fieldChanged.emit()
        return True


__all__ = ["ImportedComplexField", "ImportedFieldSelector", "load_complex_field"]

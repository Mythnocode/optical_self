"""Original complex-field file loader, separated from its Qt selector.

NPY/NPZ/CSV interpretation, validation and normalization are unchanged.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import numpy as np


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


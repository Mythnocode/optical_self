from __future__ import annotations

from dataclasses import dataclass, field
from math import sqrt
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


@dataclass(slots=True)
class ValidationRow:
    case: str
    reference: float | None = None
    reference_uncertainty: float | None = None
    platform: float | None = None
    numerical_uncertainty: float | None = None
    input_uncertainty: float | None = None
    unit: str = ""
    parameter_changes: dict[str, float] = field(default_factory=dict)


_COLUMN_ALIASES = {
    "case": ("工况", "样本", "编号", "case", "beam", "sample", "id", "name"),
    "reference": (
        "参考值", "实验值", "文献值", "理论值", "测量值", "reference", "experiment",
        "experimental", "measured", "theory", "exp", "value",
    ),
    "reference_uncertainty": (
        "参考不确定度", "实验不确定度", "标准差", "sd", "std", "uncertainty", "u_ref",
        "reference_uncertainty", "误差", "error",
    ),
    "platform": ("平台值", "仿真值", "计算值", "platform", "simulation", "simulated", "prediction"),
    "numerical_uncertainty": (
        "数值不确定度", "平台不确定度", "u_num", "numerical_uncertainty", "simulation_uncertainty",
    ),
    "input_uncertainty": (
        "输入参数不确定度", "输入不确定度", "u_input", "input_uncertainty", "parameter_uncertainty",
    ),
    "unit": ("单位", "unit"),
}


def _normalized(text: object) -> str:
    return str(text or "").strip().lower().replace(" ", "").replace("_", "")


def _find_column(columns: Iterable[object], aliases: Iterable[str]) -> object | None:
    lookup = {_normalized(column): column for column in columns}
    for alias in aliases:
        key = _normalized(alias)
        if key in lookup:
            return lookup[key]
    return None


def _number(value) -> float | None:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        text = str(value).strip().replace("%", "")
        try:
            return float(text)
        except ValueError:
            return None



_FRIENDLY_PARAMETER_COLUMNS = {
    "波长nm": ("source.wavelength_nm", 1.0),
    "波长": ("source.wavelength_nm", 1.0),
    "m2": ("source.beam_quality_m2", 1.0),
    "m²": ("source.beam_quality_m2", 1.0),
    "束腰xmm": ("source.waist_x_mm", 1.0),
    "束腰ymm": ("source.waist_y_mm", 1.0),
    "mfdxum": ("receiver.mode_field_diameter_x_um", 1.0),
    "mfdyum": ("receiver.mode_field_diameter_y_um", 1.0),
    "光纤mfdxum": ("receiver.mode_field_diameter_x_um", 1.0),
    "光纤mfdyum": ("receiver.mode_field_diameter_y_um", 1.0),
    "光纤nax": ("receiver.na_x", 1.0),
    "光纤nay": ("receiver.na_y", 1.0),
    "横向偏移xum": ("receiver.offset_x_mm", 0.001),
    "横向偏移yum": ("receiver.offset_y_mm", 0.001),
    "光纤x偏移um": ("receiver.offset_x_mm", 0.001),
    "光纤y偏移um": ("receiver.offset_y_mm", 0.001),
    "轴向位置mm": ("receiver.axial_offset_z_mm", 1.0),
    "轴向偏移mm": ("receiver.axial_offset_z_mm", 1.0),
    "倾角xmrad": ("receiver.tilt_x_deg", 180.0 / (np.pi * 1000.0)),
    "倾角ymrad": ("receiver.tilt_y_deg", 180.0 / (np.pi * 1000.0)),
    "光纤倾角xmrad": ("receiver.tilt_x_deg", 180.0 / (np.pi * 1000.0)),
    "光纤倾角ymrad": ("receiver.tilt_y_deg", 180.0 / (np.pi * 1000.0)),
    "接收面位置mm": ("image_distance_mm", 1.0),
}

def _parameter_columns(frame: pd.DataFrame, mapped_columns: set[object]) -> list[tuple[object, str, float]]:
    result: list[tuple[object, str, float]] = []
    for column in frame.columns:
        if column in mapped_columns:
            continue
        raw = str(column or "").strip()
        norm = _normalized(raw)
        if raw.lower().startswith(("参数:", "param:", "parameter:")):
            path = raw.split(":", 1)[1].strip()
            if path:
                result.append((column, path, 1.0))
            continue
        if norm in _FRIENDLY_PARAMETER_COLUMNS:
            path, scale = _FRIENDLY_PARAMETER_COLUMNS[norm]
            result.append((column, path, scale))
    return result


def load_validation_rows(path: str | Path, *, default_unit: str = "") -> list[ValidationRow]:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xlsm", ".xltx", ".xltm"}:
        frame = pd.read_excel(path)
    elif suffix in {".csv", ".txt"}:
        try:
            frame = pd.read_csv(path, encoding="utf-8-sig")
        except UnicodeDecodeError:
            frame = pd.read_csv(path, encoding="gb18030")
    else:
        raise ValueError("仅支持 XLSX/XLSM/CSV/TXT 实验数据文件")
    if frame.empty:
        return []
    columns = list(frame.columns)
    mapped = {key: _find_column(columns, aliases) for key, aliases in _COLUMN_ALIASES.items()}
    if mapped["reference"] is None:
        numeric_columns = [column for column in columns if pd.api.types.is_numeric_dtype(frame[column])]
        if numeric_columns:
            mapped["reference"] = numeric_columns[0]
    if mapped["reference"] is None:
        raise ValueError("没有识别到参考/实验值列，请将列名改为“参考值”“实验值”或“文献值”。")

    parameter_columns = _parameter_columns(frame, {value for value in mapped.values() if value is not None})

    rows: list[ValidationRow] = []
    for index, record in frame.iterrows():
        reference = _number(record.get(mapped["reference"]))
        if reference is None:
            continue
        case_value = record.get(mapped["case"]) if mapped["case"] is not None else index + 1
        case = str(case_value).strip() if str(case_value).strip() else str(index + 1)
        unit_value = record.get(mapped["unit"]) if mapped["unit"] is not None else default_unit
        parameter_changes: dict[str, float] = {}
        for column, path_name, scale in parameter_columns:
            value = _number(record.get(column))
            if value is not None:
                parameter_changes[path_name] = float(value) * float(scale)
        rows.append(
            ValidationRow(
                case=case,
                reference=reference,
                reference_uncertainty=_number(record.get(mapped["reference_uncertainty"])) if mapped["reference_uncertainty"] is not None else None,
                platform=_number(record.get(mapped["platform"])) if mapped["platform"] is not None else None,
                numerical_uncertainty=_number(record.get(mapped["numerical_uncertainty"])) if mapped["numerical_uncertainty"] is not None else None,
                input_uncertainty=_number(record.get(mapped["input_uncertainty"])) if mapped["input_uncertainty"] is not None else None,
                unit=str(unit_value or default_unit),
                parameter_changes=parameter_changes,
            )
        )
    return rows


def comparison_metrics(rows: Iterable[ValidationRow]) -> dict:
    pairs = [(float(row.reference), float(row.platform)) for row in rows if row.reference is not None and row.platform is not None]
    if not pairs:
        return {"count": 0}
    reference = np.asarray([item[0] for item in pairs], dtype=float)
    platform = np.asarray([item[1] for item in pairs], dtype=float)
    residual = platform - reference
    rmse = float(np.sqrt(np.mean(residual ** 2)))
    mae = float(np.mean(np.abs(residual)))
    mean_abs_ref = float(np.mean(np.abs(reference)))
    relative_rmse = rmse / mean_abs_ref * 100.0 if mean_abs_ref > 0 else float("nan")
    max_abs = float(np.max(np.abs(residual)))
    return {
        "count": len(pairs),
        "rmse": rmse,
        "mae": mae,
        "relative_rmse": relative_rmse,
        "max_abs_error": max_abs,
        "mean_signed_error": float(np.mean(residual)),
    }


def row_diagnostics(row: ValidationRow) -> dict:
    if row.reference is None or row.platform is None:
        return {}
    residual = float(row.platform) - float(row.reference)
    relative = abs(residual) / abs(float(row.reference)) * 100.0 if float(row.reference) != 0 else float("nan")
    components = [
        value
        for value in (row.reference_uncertainty, row.numerical_uncertainty, row.input_uncertainty)
        if value is not None and float(value) >= 0
    ]
    combined = sqrt(sum(float(value) ** 2 for value in components)) if components else None
    normalized = abs(residual) / combined if combined and combined > 0 else None
    return {
        "residual": residual,
        "relative_error": relative,
        "combined_standard_uncertainty": combined,
        "normalized_residual": normalized,
    }


def threshold_interval(x_values: Iterable[float], y_values: Iterable[float], fraction: float = 0.5) -> tuple[float, float] | None:
    pairs = sorted((float(x), float(y)) for x, y in zip(x_values, y_values) if np.isfinite(x) and np.isfinite(y))
    if len(pairs) < 3:
        return None
    x = np.asarray([item[0] for item in pairs], dtype=float)
    y = np.asarray([item[1] for item in pairs], dtype=float)
    peak_index = int(np.nanargmax(y))
    threshold = float(y[peak_index]) * float(fraction)

    def crossing(indices):
        for i, j in indices:
            yi, yj = float(y[i]), float(y[j])
            if (yi - threshold) == 0:
                return float(x[i])
            if (yi - threshold) * (yj - threshold) <= 0 and yi != yj:
                ratio = (threshold - yi) / (yj - yi)
                return float(x[i] + ratio * (x[j] - x[i]))
        return None

    left = crossing((i, i + 1) for i in range(peak_index - 1, -1, -1))
    right = crossing((i, i + 1) for i in range(peak_index, len(x) - 1))
    if left is None or right is None or right < left:
        return None
    return left, right


def three_db_width(x_values: Iterable[float], y_values: Iterable[float]) -> float | None:
    interval = threshold_interval(x_values, y_values, 0.5)
    return None if interval is None else interval[1] - interval[0]

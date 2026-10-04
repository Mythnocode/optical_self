"""Validate portable simulation files without changing or submitting a project."""
from math import isfinite
from typing import Any

from shared_contracts.simulation import SimulationRequest
from shared_contracts.project import SurfaceSnapshot
from .surface_presentation import canonical_surfaces


def validate_project_file(payload: dict[str, Any]) -> None:
    def finite(value: Any, depth: int = 0) -> None:
        if depth > 40:
            raise ValueError("项目数据嵌套过深")
        if isinstance(value, (int, float)) and not isfinite(value):
            raise ValueError("项目包含无效数值")
        if isinstance(value, dict):
            for item in value.values():
                finite(item, depth + 1)
        elif isinstance(value, list):
            for item in value:
                finite(item, depth + 1)

    finite(payload)
    request = SimulationRequest.model_validate(payload)
    if request.schema_version != "1.0" or request.project.schema_version != "2.0" or request.project.receiver is None:
        raise ValueError("项目文件格式不受支持")
    for row in canonical_surfaces(request.project.model_dump(mode="json")):
        SurfaceSnapshot.model_validate(row)
    ui = payload.get("frontend_state") or {}
    if not isinstance(ui, dict):
        raise ValueError("项目界面状态无效")
    field = ui.get("imported_field")
    if field is not None:
        if not isinstance(field, dict) or not isinstance(field.get("shape"), list) or len(field["shape"]) != 2:
            raise ValueError("项目复场数据无效")
        rows, columns = field["shape"]
        if rows != columns or rows not in {65, 129, 257, 513, 1025}:
            raise ValueError("项目复场网格不受支持")
        for key in ("real", "imag"):
            matrix = field.get(key)
            if not isinstance(matrix, list) or len(matrix) != rows or any(
                not isinstance(row, list) or len(row) != columns
                or any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in row)
                for row in matrix
            ):
                raise ValueError("项目复场数组与网格不一致")
        for key in ("path", "source_format", "interpretation"):
            if not isinstance(field.get(key), str):
                raise ValueError("项目复场元数据无效")
        if request.project.receiver.mode_model == "imported" and rows != request.project.analysis_settings.get("calc_grid_size"):
            raise ValueError("项目复场与接收面网格不一致")

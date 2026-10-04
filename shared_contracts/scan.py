

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional
from math import isfinite

from pydantic import BaseModel, Field, field_validator, model_validator

from shared_contracts.errors import ApplicationError


ScanMode = Literal["line_1d", "grid_2d", "lhs", "sobol", "random"]


class ScanParameter(BaseModel):


    path: str = Field(min_length=1)
    label: str = ""
    unit: str = ""
    start: float
    stop: float
    points: int = Field(default=41, ge=2, le=501)

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError("scan parameter path must not be empty")
        return normalized


class ScanRequest(BaseModel):


    schema_version: str = "1.0"
    request_id: str = Field(min_length=1)
    mode: ScanMode = "line_1d"
    parameters: List[ScanParameter] = Field(
        default_factory=list, min_length=1, max_length=8
    )
    response_metrics: List[str] = Field(
        default_factory=lambda: ["coupling_efficiency"]
    )
    analyses: List[str] = Field(default_factory=lambda: ["coupling"])
    nominal_changes: List[Dict[str, Any]] = Field(default_factory=list)
    precision: Literal["preview", "standard", "high"] = "standard"
    random_seed: int = 42
    options: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_scan_shape(self) -> "ScanRequest":
        strategy = self.options.get('sampling_strategy', 'linear')
        if strategy not in {'linear', 'log'}:
            raise ValueError('自适应加密尚未实现，请选择线性采样或对数采样。')
        for parameter in self.parameters:
            if not all(isfinite(v) for v in (parameter.start, parameter.stop)) or parameter.start >= parameter.stop:
                raise ValueError('扫描范围必须是有限数值，且最小值小于最大值。')
            if strategy == 'log' and parameter.start * parameter.stop <= 0:
                raise ValueError('对数采样要求范围两端非零且同号。')
        if not 1 <= int(self.options.get('max_samples', 4096)) <= 50000:
            raise ValueError('采样数量必须在 1～50000 之间。')
        if self.mode == "line_1d" and len(self.parameters) != 1:
            raise ValueError("line_1d scan requires exactly one parameter")
        if self.mode == "grid_2d" and len(self.parameters) != 2:
            raise ValueError("grid_2d scan requires exactly two parameters")
        if self.mode in {"lhs", "sobol", "random"} and len(self.parameters) < 1:
            raise ValueError("multi-parameter sampling requires at least one parameter")
        return self


class ScanResult(BaseModel):


    request_id: str
    status: Literal["completed", "failed", "cancelled"]
    mode: ScanMode
    parameter_paths: List[str] = Field(default_factory=list)
    parameter_labels: List[str] = Field(default_factory=list)
    parameter_units: List[str] = Field(default_factory=list)
    parameter_grid: Optional[List[List[float]]] = None
    response_metrics: List[str] = Field(default_factory=list)
    response_values: Dict[str, List[float]] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)
    errors: List[ApplicationError] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

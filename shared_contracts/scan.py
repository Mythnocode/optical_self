

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator


ScanMode = Literal["line_1d", "grid_2d", "lhs", "sobol", "random"]


class ScanParameter(BaseModel):


    path: str
    label: str = ""
    unit: str = ""
    start: float
    stop: float
    points: int = Field(default=41, ge=2, le=501)


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
    metadata: Dict[str, Any] = Field(default_factory=dict)

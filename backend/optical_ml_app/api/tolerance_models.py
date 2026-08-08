

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from shared_contracts.parameters import ParameterChange
from shared_contracts.project import ProjectSnapshot
from shared_contracts.tolerance import (
    ToleranceAnalysisRequest,
    ToleranceAnalysisResult,
    ToleranceParameter,
)


class ToleranceJobRequest(BaseModel):


    schema_version: str = "1.0"
    request_id: str = Field(min_length=1)
    project: ProjectSnapshot
    analyses: List[str] = Field(default_factory=lambda: ["coupling"])
    parameter_changes: List[ParameterChange] = Field(default_factory=list)
    precision: Literal["preview", "standard", "high"] = "standard"
    random_seed: int = 42
    engine: Optional[str] = None
    options: Dict[str, Any] = Field(default_factory=dict)

    
    tolerance_parameters: List[ToleranceParameter] = Field(default_factory=list)
    tolerance_sampling_method: Literal["random", "lhs", "sobol"] = "lhs"
    tolerance_sample_count: int = Field(default=256, ge=1, le=200000)
    tolerance_threshold_efficiency: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    tolerance_threshold_loss_db: Optional[float] = Field(default=1.0, ge=0.0)
    tolerance_confidence_level: float = Field(default=0.95, gt=0.0, lt=1.0)
    tolerance_correlation_matrix: Optional[List[List[float]]] = None
    tolerance_options: Dict[str, Any] = Field(default_factory=dict)

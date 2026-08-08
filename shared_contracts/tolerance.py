
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator

from shared_contracts.parameters import ParameterChange


ToleranceDistributionName = Literal["fixed", "normal", "uniform", "triangular"]
ToleranceSamplingMethod = Literal["random", "lhs", "sobol"]


class ToleranceDistribution(BaseModel):


    name: ToleranceDistributionName = "normal"
    sigma: Optional[float] = None
    lower: Optional[float] = None
    upper: Optional[float] = None
    mode: Optional[float] = None

    @model_validator(mode="after")
    def validate_distribution(self) -> "ToleranceDistribution":
        if self.name == "normal" and (self.sigma is None or self.sigma < 0.0):
            raise ValueError("normal tolerance distribution requires sigma >= 0")
        if self.name in {"uniform", "triangular"}:
            if self.lower is None or self.upper is None or self.lower > self.upper:
                raise ValueError("uniform/triangular tolerance requires lower <= upper")
        if self.name == "triangular" and self.mode is not None:
            assert self.lower is not None and self.upper is not None
            if not self.lower <= self.mode <= self.upper:
                raise ValueError("triangular mode must lie inside [lower, upper]")
        return self


class ToleranceParameter(BaseModel):


    path: str
    nominal: float
    unit: str = ""
    distribution: ToleranceDistribution = Field(default_factory=ToleranceDistribution)
    enabled: bool = True
    group: Optional[str] = None


class ToleranceAnalysisRequest(BaseModel):


    schema_version: str = "1.0"
    request_id: str
    parameters: List[ToleranceParameter] = Field(default_factory=list)
    analyses: List[str] = Field(default_factory=lambda: ["coupling"])
    nominal_changes: List[ParameterChange] = Field(default_factory=list)
    sampling_method: ToleranceSamplingMethod = "lhs"
    sample_count: int = Field(default=256, ge=1)
    random_seed: int = 42
    precision: Literal["preview", "standard", "high"] = "standard"
    threshold_efficiency: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    threshold_loss_db: Optional[float] = Field(default=1.0, ge=0.0)
    confidence_level: float = Field(default=0.95, gt=0.0, lt=1.0)
    correlation_matrix: Optional[List[List[float]]] = None
    options: Dict[str, Any] = Field(default_factory=dict)


class ToleranceAnalysisResult(BaseModel):
    request_id: str
    status: Literal["completed", "failed", "cancelled"]
    metrics: Dict[str, Any] = Field(default_factory=dict)
    arrays: Dict[str, Any] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)
    errors: List[Dict[str, Any]] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)



from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


OptimizerName = Literal["auto", "differential_evolution", "bayesian"]


class OptimizationVariable(BaseModel):


    path: str
    label: str = ""
    unit: str = ""
    lower_bound: float
    upper_bound: float
    initial_value: float
    enabled: bool = True


class OptimizationObjective(BaseModel):


    metric: str = "coupling_efficiency"
    weight: float = Field(default=1.0, gt=0.0)
    goal: Literal["maximize", "minimize", "target"] = "maximize"
    target_value: Optional[float] = None

    @model_validator(mode="after")
    def validate_target(self) -> "OptimizationObjective":
        if self.goal == "target" and self.target_value is None:
            raise ValueError("target_value is required when goal is 'target'")
        return self


class CollimationConstraint(BaseModel):


    type: Literal["collimation"] = "collimation"
    enabled: bool = True
    after_surface_index: Optional[int] = None
    plane_start_offset_mm: float = Field(default=0.0, ge=0.0)
    evaluation_span_mm: float = Field(default=10.0, gt=0.0)
    max_radius_change_fraction: float = Field(default=0.02, gt=0.0)
    max_normalized_curvature: float = Field(default=0.05, gt=0.0)
    max_centroid_drift_fraction: float = Field(default=0.01, gt=0.0)
    max_axis_tilt_mrad: float = Field(default=1.0, gt=0.0)
    max_edge_power_fraction: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    minimum_score: float = Field(default=0.95, ge=0.0, le=1.0)
    penalty_weight: float = Field(default=100.0, gt=0.0)
    hard: bool = True
    require_clear_span: bool = True


class OptimizationRequest(BaseModel):


    schema_version: str = "1.0"
    request_id: str = Field(min_length=1)
    optimizer: OptimizerName = "auto"
    variables: List[OptimizationVariable] = Field(
        default_factory=list, min_length=1, max_length=64
    )
    objectives: List[OptimizationObjective] = Field(
        default_factory=lambda: [
            OptimizationObjective(metric="coupling_efficiency", goal="maximize")
        ]
    )
    constraints: List[Dict[str, Any]] = Field(default_factory=list)
    analyses: List[str] = Field(default_factory=lambda: ["coupling"])

    @field_validator("constraints", mode="before")
    @classmethod
    def validate_constraints(cls, value):
        normalized: list[dict[str, Any]] = []
        collimation_count = 0
        for item in list(value or []):
            raw = dict(item.model_dump() if hasattr(item, "model_dump") else item)
            if str(raw.get("type", "")).strip().lower() == "collimation":
                collimation_count += 1
                normalized.append(CollimationConstraint.model_validate(raw).model_dump())
            else:
                normalized.append(raw)
        if collimation_count > 1:
            raise ValueError("当前优化请求最多支持一个准直约束")
        return normalized
    nominal_changes: List[Dict[str, Any]] = Field(default_factory=list)
    precision: Literal["preview", "standard", "high"] = "standard"
    random_seed: int = 42
    max_iterations: int = Field(default=100, ge=1, le=5000)
    max_evaluations: Optional[int] = Field(default=None, ge=1)
    convergence_tolerance: float = Field(default=1e-4, gt=0.0)
    options: Dict[str, Any] = Field(default_factory=dict)


class OptimizationIteration(BaseModel):


    iteration: int
    evaluations: int
    variables: List[float]
    metrics: Dict[str, Any] = Field(default_factory=dict)
    merit: float


class OptimizationResult(BaseModel):


    request_id: str
    status: Literal["completed", "failed", "cancelled", "max_iterations"]
    optimizer: OptimizerName
    best_variables: Dict[str, float] = Field(default_factory=dict)
    best_metrics: Dict[str, Any] = Field(default_factory=dict)
    best_merit: float
    # Formally simulated alternatives retained for inverse-design comparison.
    # Additive to the existing contract so older clients can ignore it safely.
    candidates: List[Dict[str, Any]] = Field(default_factory=list)
    history: List[OptimizationIteration] = Field(default_factory=list)
    total_evaluations: int = 0
    total_iterations: int = 0
    warnings: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

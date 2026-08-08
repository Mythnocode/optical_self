from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field
from shared_contracts.errors import ApplicationError
from shared_contracts.parameters import ParameterChange
from shared_contracts.project import ProjectSnapshot


class SimulationRequest(BaseModel):
    schema_version: str = "1.0"
    request_id: str
    project: ProjectSnapshot
    analyses: List[str]
    parameter_changes: List[ParameterChange] = Field(default_factory=list)
    precision: Literal["preview", "standard", "high"] = "standard"
    random_seed: int = 42
    engine: Optional[str] = None
    options: Dict[str, Any] = Field(default_factory=dict)


class SimulationResult(BaseModel):
    request_id: str
    project_fingerprint: str
    engine_name: str
    engine_version: str
    algorithm_version: str
    status: Literal["completed", "failed", "cancelled"]
    metrics: Dict[str, Any] = Field(default_factory=dict)
    arrays: Dict[str, Any] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)
    errors: List[ApplicationError] = Field(default_factory=list)
    elapsed_ms: float = 0.0
    converged: bool = False
    metadata: Dict[str, Any] = Field(default_factory=dict)

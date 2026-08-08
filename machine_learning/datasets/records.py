from typing import Any, Dict
from pydantic import BaseModel, Field


class SampleRecord(BaseModel):
    sample_id: str
    split: str = "unassigned"
    request_id: str
    project_fingerprint: str
    feature_values: Dict[str, float]
    target_values: Dict[str, float] = Field(default_factory=dict)
    valid: bool
    failure_code: str = ""
    failure_message: str = ""
    engine_name: str
    engine_version: str
    elapsed_ms: float
    converged: bool
    metadata: Dict[str, Any] = Field(default_factory=dict)

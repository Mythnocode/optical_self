from typing import Any, Dict, Literal, Optional
from pydantic import BaseModel, Field
from shared_contracts.errors import ApplicationError


class JobStatus(BaseModel):
    job_id: str
    job_type: str
    status: Literal["queued", "running", "completed", "failed", "cancelled"]
    progress: float = 0.0
    stage: str = "queued"
    completed_items: int = 0
    total_items: int = 1
    created_at: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    result_available: bool = False
    error: Optional[ApplicationError] = None
    metrics: Dict[str, Any] = Field(default_factory=dict)
    timings_ms: Dict[str, float] = Field(default_factory=dict)
    result_version: int = 0
    partial_result_available: bool = False

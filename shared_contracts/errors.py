from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class ApplicationError(BaseModel):
    code: str
    stage: str
    message: str
    retryable: bool = False
    trace_id: Optional[str] = None
    context: Dict[str, Any] = Field(default_factory=dict)

from typing import Any, Optional
from pydantic import BaseModel, ConfigDict


class ParameterChange(BaseModel):
    model_config = ConfigDict(frozen=True)
    path: str
    value: Any
    unit: Optional[str] = None

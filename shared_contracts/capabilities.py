from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class EngineCapability(BaseModel):
    name: str
    enabled: bool
    availability: str
    connected: bool = False
    version: Optional[str] = None
    analyses: List[str] = Field(default_factory=list)
    parameter_paths: List[str] = Field(default_factory=list)


class CapabilitiesResponse(BaseModel):
    default_engine: str
    engines: Dict[str, EngineCapability]
    precision_profiles: List[str]
    dataset_sampling_methods: List[str]
    model_types: List[str]
    contract_version: str

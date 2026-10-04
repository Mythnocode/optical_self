"""HTTP contracts for formal Teaching jobs."""
from typing import Literal
from uuid import uuid4
from pydantic import BaseModel, Field
from shared_contracts.simulation import SimulationRequest


class TeachingJobRequest(BaseModel):
    request_id: str = Field(default_factory=lambda: uuid4().hex, min_length=1, max_length=256)
    scene: dict
    scene_revision: int = Field(ge=0)
    analysis: Literal['raytrace', 'spot', 'field', 'wavefront', 'coupling']
    engineering_request: SimulationRequest | None = None

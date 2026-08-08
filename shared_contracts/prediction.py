from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class PredictionRequest(BaseModel):
    model_id: str
    features: Dict[str, float]


class PredictionResult(BaseModel):
    model_id: str
    predictions: Dict[str, float]
    warnings: List[str] = Field(default_factory=list)
    in_training_domain: bool = True


class VerificationResult(BaseModel):
    model_id: str
    dataset_id: str
    simulation_request_id: str
    parameter_values: Dict[str, float]
    predicted_targets: Dict[str, float]
    simulated_targets: Dict[str, float]
    absolute_errors: Dict[str, float]
    relative_errors: Dict[str, Optional[float]]

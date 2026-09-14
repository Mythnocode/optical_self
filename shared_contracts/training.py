from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


class TrainingRequest(BaseModel):
    dataset_id: str
    model_type: Literal["random_forest", "xgboost_physics_residual"] = "random_forest"
    target_names: List[str] = Field(default_factory=list)
    hyperparameters: Dict[str, Any] = Field(default_factory=dict)
    random_seed: int = 42


class TrainingResult(BaseModel):
    model_id: str
    dataset_id: str
    model_type: str
    validation_metrics: Dict[str, float]
    test_metrics: Dict[str, float]
    training_elapsed_ms: float
    warnings: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class JointTrainingRequest(BaseModel):
    dataset_id: str
    random_seed: int = 42
    random_forest_hyperparameters: Dict[str, Any] = Field(default_factory=dict)
    xgboost_hyperparameters: Dict[str, Any] = Field(default_factory=dict)


class JointTrainingResult(BaseModel):
    bundle_id: str
    dataset_id: str
    random_forest: TrainingResult
    xgboost: Optional[TrainingResult] = None
    primary_model_id: str = ""
    status: Literal["completed", "partial"] = "completed"
    warnings: List[str] = Field(default_factory=list)

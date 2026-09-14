from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field
from shared_contracts.project import ProjectSnapshot


class ParameterDefinition(BaseModel):
    name: str
    path: str
    unit: str
    lower_bound: float
    upper_bound: float
    distribution: str = "uniform"


class DatasetGenerationRequest(BaseModel):
    dataset_name: str
    base_project: ProjectSnapshot
    parameters: List[ParameterDefinition]
    targets: List[str]
    sample_count: int = 50
    sampling_method: Literal["latin_hypercube", "sobol"] = "latin_hypercube"
    train_ratio: float = 0.7
    validation_ratio: float = 0.15
    test_ratio: float = 0.15
    random_seed: int = 42
    precision: str = "standard"
    engine: Optional[str] = None
    # Some curated demo/interpretability datasets intentionally train only on
    # user-controlled variables.  Keeping the default True preserves the richer
    # physics-residual feature set for normal research datasets.
    include_derived_physics_features: bool = True
    variable_scheme_id: Optional[str] = None
    lens_count: Optional[int] = None
    design_variable_paths: List[str] = Field(default_factory=list)


class DatasetManifest(BaseModel):
    dataset_id: str
    dataset_name: str
    schema_version: str = "1.0"
    engine_name: str
    engine_version: str
    feature_schema_version: str
    created_at: str
    sample_count: int
    valid_sample_count: int
    failed_sample_count: int
    feature_names: List[str]
    feature_paths: List[str]
    feature_units: List[str]
    target_names: List[str]
    train_ids: List[str]
    validation_ids: List[str]
    test_ids: List[str]
    random_seed: int
    source_project_fingerprint: str
    status: Literal["completed", "partial", "cancelled"] = "completed"
    variable_scheme_id: Optional[str] = None
    lens_count: Optional[int] = None
    design_variable_paths: List[str] = Field(default_factory=list)
    physics_feature_paths: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

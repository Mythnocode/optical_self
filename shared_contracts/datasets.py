from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, model_validator
from shared_contracts.project import ProjectSnapshot


class ParameterDefinition(BaseModel):
    name: str
    path: str
    unit: str
    lower_bound: float
    upper_bound: float
    distribution: str = "uniform"


class ImportedDatasetMode(BaseModel):
    """A sampled receiving mode on the user's fixed physical output window."""

    model_config = ConfigDict(allow_inf_nan=False)
    real: List[List[float]]
    imag: List[List[float]]
    source: str = ""
    output_extent_x_mm: float = Field(default=0.024, gt=0)
    output_extent_y_mm: float = Field(default=0.024, gt=0)

    @model_validator(mode="after")
    def validate_grid(self):
        size = len(self.real)
        if size < 17 or size % 2 == 0 or len(self.imag) != size:
            raise ValueError("导入复场必须是至少 17 点的奇数方形网格")
        if any(len(row) != size for row in self.real + self.imag):
            raise ValueError("导入复场实部与虚部必须是相同尺寸的方形网格")
        if not any(value != 0 for rows in (self.real, self.imag) for row in rows for value in row):
            raise ValueError("导入复场总功率必须大于零")
        return self


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
    imported_mode: Optional[ImportedDatasetMode] = None
    # Some curated demo/interpretability datasets intentionally train only on
    # user-controlled variables.  Keeping the default True preserves the richer
    # physics-residual feature set for normal research datasets.
    include_derived_physics_features: bool = True
    variable_scheme_id: Optional[str] = None
    lens_count: Optional[int] = None
    design_variable_paths: List[str] = Field(default_factory=list)
    # ``tabular`` keeps the established RF/XGBoost flat-feature contract.
    # ``sequence_long`` additionally exports one row per physical lens so the
    # same simulated systems can be trained by the variable-length BiLSTM.
    dataset_layout: Literal["tabular", "sequence_long"] = "tabular"

    @model_validator(mode="after")
    def require_imported_mode(self):
        receiver = self.base_project.receiver
        if receiver is not None and receiver.mode_model == "imported" and self.imported_mode is None:
            raise ValueError("导入复场模式缺少已校验的复场数据")
        if self.imported_mode is not None and (receiver is None or receiver.mode_model != "imported"):
            raise ValueError("当前接收模式不是导入复场")
        return self


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

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from shared_contracts.parameters import ParameterChange
from shared_contracts.project import ProjectSnapshot


CombinationMode = Literal[
    "independent",
    "incoherent_power_sum",
    "coherent_field_sum",
    "ideal_2x2_scalar_combiner",
    "scalar_optical_network",
    "jones_polarization_combiner",
]
PrecisionProfile = Literal["preview", "standard", "high"]
PowerUnit = Literal["W", "mW", "uW", "nW"]


class MultiPathCombination(BaseModel):


    model_config = ConfigDict(extra="allow")

    mode: CombinationMode = "independent"
    summary_metric: str = "coupling_efficiency"
    summary_objective: Literal["auto", "maximize", "minimize"] = "auto"
    default_input_power_value: float = Field(default=1.0, ge=0.0)
    default_input_power_unit: PowerUnit = "mW"


class MultiPathItemRequest(BaseModel):


    model_config = ConfigDict(extra="allow")

    path_id: str = Field(min_length=1)
    label: str | None = None
    enabled: bool = True
    weight: float = Field(default=1.0, ge=0.0)
    input_power_value: float | None = Field(default=None, ge=0.0)
    input_power_unit: PowerUnit | None = None
    project: ProjectSnapshot | None = None
    system: dict[str, Any] | None = None
    source: dict[str, Any] | None = None
    receiver: dict[str, Any] | None = None
    analyses: list[Any] = Field(default_factory=list)
    parameter_changes: list[ParameterChange] = Field(default_factory=list)
    precision: PrecisionProfile | None = None
    random_seed: int | None = None
    engine: str | None = None
    options: dict[str, Any] = Field(default_factory=dict)
    include_large_arrays: bool = False

    @model_validator(mode="after")
    def validate_item(self) -> "MultiPathItemRequest":
        if self.project is None and self.system is None:
            raise ValueError("each multi-path item must define project or system")
        if (self.input_power_value is None) != (self.input_power_unit is None):
            raise ValueError("input_power_value and input_power_unit must be provided together")
        return self


class MultiPathSimulationRequest(BaseModel):


    model_config = ConfigDict(extra="allow")

    schema_version: str = "2.0"
    request_id: str = Field(min_length=1)
    simulation_type: Literal["multi_path", "multipath"] = "multi_path"
    paths: list[MultiPathItemRequest] = Field(min_length=1)
    analyses: list[Any] = Field(default_factory=list)
    combination: MultiPathCombination = Field(default_factory=MultiPathCombination)
    precision: PrecisionProfile = "standard"
    random_seed: int = 42
    engine: str | None = None
    options: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_unique_path_ids(self) -> "MultiPathSimulationRequest":
        path_ids = [path.path_id for path in self.paths]
        if len(set(path_ids)) != len(path_ids):
            raise ValueError("multi-path path_id values must be unique")
        return self

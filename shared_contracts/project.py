from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class CoatingLayerSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    name: str = "layer"
    refractive_index: float = Field(default=1.0, gt=0.0)
    extinction_coefficient: float = Field(default=0.0, ge=0.0)
    thickness_nm: float = Field(default=0.0, ge=0.0)
    dn_dt_per_c: float = 0.0
    dk_dt_per_c: float = 0.0
    cte_per_c: float = 0.0
    reference_temperature_c: float = 20.0


class SurfaceSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    index: int
    surface_type: str = "spherical"
    radius_mm: Optional[float] = None
    distance_to_next_mm: float = 0.0
    material_before: str = "AIR"
    material_after: str = "AIR"
    clear_aperture_mm: Optional[float] = None
    conic: float = 0.0
    asphere_a2: float = 0.0
    asphere_coefficients: List[float] = Field(default_factory=list)
    coating_layers: List[CoatingLayerSnapshot] = Field(default_factory=list)
    surface_absorption_fraction: float = Field(default=0.0, ge=0.0, lt=1.0)
    roughness_rms_nm: float = Field(default=0.0, ge=0.0)
    grating_period_um: Optional[float] = Field(default=None, gt=0.0)
    grating_orders: List[int] = Field(default_factory=list)
    grating_efficiencies: List[float] = Field(default_factory=list)
    aperture_type: str = "circular"
    mechanical_diameter_mm: Optional[float] = Field(default=None, gt=0.0)
    enabled: bool = True
    decenter_x_mm: float = 0.0
    decenter_y_mm: float = 0.0
    tilt_x_deg: float = 0.0
    tilt_y_deg: float = 0.0
    tilt_z_deg: float = 0.0
    # Cylinder/zero-power axis azimuth in the local transverse x-y plane.
    # 0 deg means axis +x (power in y); 90 deg means axis +y (power in x).
    cylinder_axis_deg: float = Field(default=0.0, allow_inf_nan=False)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SourceSnapshot(BaseModel):


    model_config = ConfigDict(frozen=True, extra="forbid")
    wavelength_nm: float = Field(default=1064.0, gt=0.0, allow_inf_nan=False)
    source_type: str = "gaussian"
    object_na_x: float = 0.1
    object_na_y: float = 0.1
    field_x_deg: float = 0.0
    field_y_deg: float = 0.0
    waist_x_mm: float = 0.0
    waist_y_mm: float = 0.0
    beam_quality_m2: float = Field(default=1.0, ge=1.0)
    beam_quality_m2_x: float | None = Field(default=None, ge=1.0)
    beam_quality_m2_y: float | None = Field(default=None, ge=1.0)
    waist_position_x_mm: float = 0.0
    waist_position_y_mm: float = 0.0
    center_x_mm: float = 0.0
    center_y_mm: float = 0.0
    axis_tilt_x_rad: float = 0.0
    axis_tilt_y_rad: float = 0.0
    spectral_wavelengths_nm: List[float] = Field(default_factory=list)
    spectral_power_weights: List[float] = Field(default_factory=list)
    power_value: float | None = None
    power_unit: str | None = None


class ReceiverSnapshot(BaseModel):


    model_config = ConfigDict(frozen=True, extra="forbid")
    na_x: float = 0.12
    na_y: float = 0.12
    mode_field_diameter_x_um: float = 5.0
    mode_field_diameter_y_um: float = 5.0
    offset_x_mm: float = 0.0
    offset_y_mm: float = 0.0
    axial_offset_z_mm: float = 0.0
    tilt_x_deg: float = 0.0
    tilt_y_deg: float = 0.0
    receiver_type: str = "single_mode_fiber"
    mode_model: str = "gaussian"
    core_diameter_um: float | None = Field(default=None, gt=0.0)
    core_refractive_index: float | None = Field(default=None, gt=0.0)
    cladding_refractive_index: float | None = Field(default=None, gt=0.0)
    outside_refractive_index: float = Field(default=1.0, gt=0.0)
    endface_transmission: float = Field(default=1.0, ge=0.0, le=1.0)
    fiber_length_m: float = Field(default=0.0, ge=0.0)
    attenuation_db_per_km: float = Field(default=0.0, ge=0.0)
    connector_loss_db: float = Field(default=0.0, ge=0.0)


class ProjectSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: str = "2.0"
    project_id: str
    surfaces: List[SurfaceSnapshot]
    object_distance_mm: float
    image_distance_mm: float
    pupil_radius_mm: float
    source: SourceSnapshot
    receiver: Optional[ReceiverSnapshot] = None
    aperture: Dict[str, Any] = Field(default_factory=dict)
    analysis_settings: Dict[str, Any] = Field(default_factory=dict)
    fingerprint: str

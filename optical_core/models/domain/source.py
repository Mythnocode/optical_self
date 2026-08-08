# 定义光源参数。

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class OpticalSource:


    wavelength_nm: float
    source_type: str
    object_na_x: float = 0.0
    object_na_y: float = 0.0
    field_x_deg: float = 0.0
    field_y_deg: float = 0.0
    waist_x_mm: float = 0.0
    waist_y_mm: float = 0.0
    beam_quality_m2: float = 1.0
    beam_quality_m2_x: float | None = None
    beam_quality_m2_y: float | None = None
    waist_position_x_mm: float = 0.0
    waist_position_y_mm: float = 0.0
    center_x_mm: float = 0.0
    center_y_mm: float = 0.0
    axis_tilt_x_rad: float = 0.0
    axis_tilt_y_rad: float = 0.0
    power_drift_fraction: float = 0.0
    spectral_fwhm_nm: float = 0.0
    spectral_sample_count: int = 1
    spectral_wavelengths_nm: tuple[float, ...] = ()
    spectral_power_weights: tuple[float, ...] = ()
    coherence_groups: tuple[str | None, ...] = ()
    amplitude_map: object | None = None
    phase_map_rad: object | None = None
    power_value: float | None = None
    power_unit: str | None = None

    def __post_init__(self) -> None:
        if float(self.beam_quality_m2) < 1.0:
            raise ValueError("beam_quality_m2 must be >= 1.0")
        if self.beam_quality_m2_x is not None and float(self.beam_quality_m2_x) < 1.0:
            raise ValueError("beam_quality_m2_x must be >= 1.0")
        if self.beam_quality_m2_y is not None and float(self.beam_quality_m2_y) < 1.0:
            raise ValueError("beam_quality_m2_y must be >= 1.0")
        if float(self.power_drift_fraction) <= -1.0:
            raise ValueError("power_drift_fraction must be > -1")
        if float(self.spectral_fwhm_nm) < 0.0:
            raise ValueError("spectral_fwhm_nm must be non-negative")
        if int(self.spectral_sample_count) < 1:
            raise ValueError("spectral_sample_count must be >= 1")
        if self.spectral_wavelengths_nm and any(float(v) <= 0.0 for v in self.spectral_wavelengths_nm):
            raise ValueError("spectral wavelengths must be positive")
        if self.spectral_power_weights and len(self.spectral_power_weights) != len(self.spectral_wavelengths_nm):
            raise ValueError("spectral_power_weights must match spectral_wavelengths_nm")
        if self.coherence_groups and len(self.coherence_groups) != len(self.spectral_wavelengths_nm):
            raise ValueError("coherence_groups must match spectral_wavelengths_nm")

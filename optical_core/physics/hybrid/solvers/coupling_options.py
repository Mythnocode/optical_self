from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Literal, Mapping


CouplingFieldModel = Literal["cartesian_pupil_propagation", "cartesian_exit_pupil"]
CouplingPropagationModel = Literal["none", "angular_spectrum", "band_limited_angular_spectrum", "scaled_angular_spectrum", "scaled_fresnel", "issc", "fresnel"]
CouplingSamplingModel = Literal["equal_area_pupil"]
CouplingModeModel = Literal["gaussian", "lp01", "he11", "finite_difference", "imported"]
VectorCouplingModel = Literal["paraxial_trace", "vector_debye"]
CouplingPrecisionMode = Literal["preview", "fast", "balanced", "quantitative", "accurate", "reference"]
PupilAmplitudeWeighting = Literal["field", "quadrature", "flux"]
CouplingResultArrayPolicy = Literal["full", "field_only", "none"]


_COUPLING_PRECISION_DEFAULTS: dict[str, dict[str, Any]] = {
    "preview": {
        "grid_size": 65, "pupil_grid_size": 65, "output_grid_size": 129,
        "zero_padding_factor": 1.5, "edge_power_threshold": 5.0e-3,
        "energy_closure_threshold": 1.0e-2, "sampling_convergence_enabled": False,
    },
    "fast": {
        "grid_size": 65, "pupil_grid_size": 129, "output_grid_size": 129,
        "zero_padding_factor": 1.5, "edge_power_threshold": 1.0e-3,
        "energy_closure_threshold": 1.0e-2, "sampling_convergence_enabled": False,
    },
    "balanced": {
        "grid_size": 129, "pupil_grid_size": 257, "output_grid_size": None,
        "zero_padding_factor": 2.0, "edge_power_threshold": 1.0e-4,
        "energy_closure_threshold": 5.0e-3, "sampling_convergence_enabled": False,
    },
    "quantitative": {
        "grid_size": 257, "pupil_grid_size": 257, "output_grid_size": 513,
        "zero_padding_factor": 2.0, "edge_power_threshold": 1.0e-4,
        "energy_closure_threshold": 5.0e-3, "sampling_convergence_enabled": True,
        "sampling_convergence_grid_sizes": (257, 513),
    },
    "accurate": {
        "grid_size": 257, "pupil_grid_size": 513, "output_grid_size": 513,
        "zero_padding_factor": 2.5, "edge_power_threshold": 5.0e-5,
        "energy_closure_threshold": 2.0e-3, "sampling_convergence_enabled": True,
        "sampling_convergence_grid_sizes": (257, 513),
    },
    "reference": {
        "grid_size": 513, "pupil_grid_size": 513, "output_grid_size": 1025,
        "zero_padding_factor": 3.0, "edge_power_threshold": 1.0e-5,
        "energy_closure_threshold": 1.0e-3, "sampling_convergence_enabled": True,
        "sampling_convergence_grid_sizes": (513, 1025),
        "sampling_convergence_tolerance": 1.0e-3,
    },
}


def apply_coupling_precision_defaults(options: Mapping[str, Any] | None) -> dict[str, Any]:


    raw = dict(options or {})
    mode = str(raw.get("precision_mode", "balanced")).strip().lower()
    if mode not in _COUPLING_PRECISION_DEFAULTS:
        raise ValueError(f"unsupported coupling precision_mode: {mode!r}")
    return {**_COUPLING_PRECISION_DEFAULTS[mode], **raw, "precision_mode": mode}




def parse_jones_pair(value: Any, default: tuple[complex, complex] = (1.0 + 0.0j, 0.0 + 0.0j)) -> tuple[complex, complex]:

    if value is None:
        return tuple(complex(item) for item in default)
    if isinstance(value, str):
        alias = value.strip().lower()
        aliases = {
            "x": (1.0 + 0.0j, 0.0 + 0.0j),
            "linear_x": (1.0 + 0.0j, 0.0 + 0.0j),
            "y": (0.0 + 0.0j, 1.0 + 0.0j),
            "linear_y": (0.0 + 0.0j, 1.0 + 0.0j),
            "right_circular": (1.0 / math.sqrt(2.0), -1j / math.sqrt(2.0)),
            "left_circular": (1.0 / math.sqrt(2.0), 1j / math.sqrt(2.0)),
        }
        if alias not in aliases:
            raise ValueError(f"unknown Jones-vector alias: {value!r}")
        return aliases[alias]
    if isinstance(value, Mapping):
        value = (value.get("x", value.get("ex", 0.0)), value.get("y", value.get("ey", 0.0)))
    items = tuple(complex(item) for item in value)
    if len(items) != 2 or sum(abs(item) ** 2 for item in items) <= 0.0:
        raise ValueError("Jones vector must contain two non-zero components")
    norm = math.sqrt(sum(abs(item) ** 2 for item in items))
    return tuple(item / norm for item in items)  


@dataclass(frozen=True, slots=True)
class CouplingOptions:


    wavelength_nm: float = 550.0
    grid_size: int = 129
    field_extent_mm: float | None = None
    mode_field_diameter_x_um: float = 10.0
    mode_field_diameter_y_um: float = 10.0
    mode_model: CouplingModeModel = "gaussian"
    vector_coupling_enabled: bool = False
    vector_coupling_model: VectorCouplingModel = "paraxial_trace"
    polarization_sensitive: bool = False
    incident_jones_vector: tuple[complex, complex] = (1.0 + 0.0j, 0.0 + 0.0j)
    fiber_mode_jones_vector: tuple[complex, complex] = (1.0 + 0.0j, 0.0 + 0.0j)
    receiver_na_x: float | None = None
    receiver_na_y: float | None = None
    receiver_medium_refractive_index: float = 1.0
    offset_x_mm: float = 0.0
    offset_y_mm: float = 0.0
    tilt_x_rad: float = 0.0
    tilt_y_rad: float = 0.0

    field_model: CouplingFieldModel = "cartesian_pupil_propagation"
    propagation_model: CouplingPropagationModel = "angular_spectrum"
    propagation_distance_mm: float | None = None
    receiver_axial_offset_z_mm: float = 0.0
    sampling_model: CouplingSamplingModel = "equal_area_pupil"
    convergence_enabled: bool = True
    precision_mode: CouplingPrecisionMode = "balanced"
    wavefront_fit_order: int = 2
    pupil_amplitude_weighting: PupilAmplitudeWeighting = "quadrature"

    
    
    pupil_grid_size: int = 257
    pupil_extent_scale: float = 1.04
    zero_padding_factor: float = 2.0
    scaled_angular_spectrum_transfer_model: Literal["exact", "fresnel"] = "fresnel"
    edge_power_threshold: float = 1.0e-4
    energy_closure_threshold: float = 5.0e-3
    nyquist_margin_min: float = 1.0
    auto_expand_output: bool = True
    auto_expand_factor: float = 1.5
    auto_expand_max_steps: int = 3
    
    
    
    
    
    auto_expand_max_grid_size: int = 1281
    enforce_numerical_gates: bool = False
    include_diagnostic_arrays: bool = True
    result_array_policy: CouplingResultArrayPolicy = "full"
    output_grid_size: int | None = None
    output_extent_x_mm: float | None = None
    output_extent_y_mm: float | None = None
    sampling_convergence_enabled: bool = False
    sampling_convergence_grid_sizes: tuple[int, ...] = (257, 513)
    sampling_convergence_tolerance: float = 5.0e-3
    issc_oversampling_factor: float = 1.2
    issc_padding_factor: float = 0.1
    issc_max_virtual_grid: int = 2048

    include_breakdown: bool = True
    include_convergence: bool = False
    convergence_grid_sizes: tuple[int, ...] = (65, 129, 257, 513)
    coherent: bool = True

    fiber_core_radius_um: float | None = None
    fiber_n_core: float | None = None
    fiber_n_clad: float | None = None
    fiber_length_m: float = 0.0
    fiber_attenuation_db_per_km: float = 0.0
    fiber_connector_loss_db: float = 0.0
    fiber_facet_transmission_override: float | None = None
    finite_difference_refractive_index_map: Any | None = None
    imported_mode_values: Any | None = None
    fiber_mode_index: int = 0

    def __post_init__(self) -> None:
        positive = {
            "wavelength_nm": self.wavelength_nm,
            "grid_size": self.grid_size,
            "pupil_grid_size": self.pupil_grid_size,
            "mode_field_diameter_x_um": self.mode_field_diameter_x_um,
            "mode_field_diameter_y_um": self.mode_field_diameter_y_um,
            "receiver_medium_refractive_index": self.receiver_medium_refractive_index,
        }
        for name, value in positive.items():
            if not math.isfinite(float(value)) or float(value) <= 0.0:
                raise ValueError(f"{name} must be positive and finite")
        if int(self.grid_size) < 17 or int(self.pupil_grid_size) < 17:
            raise ValueError("coupling grids must contain at least 17 samples per axis")
        if self.output_grid_size is not None and int(self.output_grid_size) < 17:
            raise ValueError("output_grid_size must be at least 17")
        if int(self.auto_expand_max_grid_size) < 17:
            raise ValueError("auto_expand_max_grid_size must be at least 17")
        if str(self.result_array_policy) not in {"full", "field_only", "none"}:
            raise ValueError("result_array_policy must be full, field_only, or none")
        if str(self.scaled_angular_spectrum_transfer_model) not in {"exact", "fresnel"}:
            raise ValueError("scaled_angular_spectrum_transfer_model must be exact or fresnel")
        if not 0.0 <= float(self.edge_power_threshold) < 1.0:
            raise ValueError("edge_power_threshold must be in [0, 1)")
        if not 0.0 <= float(self.energy_closure_threshold) < 1.0:
            raise ValueError("energy_closure_threshold must be in [0, 1)")
        if str(self.mode_model) not in {"gaussian", "lp01", "he11", "finite_difference", "imported"}:
            raise ValueError("mode_model must be gaussian, lp01, he11, finite_difference, or imported")
        if int(self.fiber_mode_index) < 0:
            raise ValueError("fiber_mode_index must be non-negative")
        if str(self.mode_model) == "finite_difference" and self.finite_difference_refractive_index_map is None:
            raise ValueError("finite_difference mode requires finite_difference_refractive_index_map")
        if str(self.mode_model) == "imported" and isinstance(self.imported_mode_values, Mapping):
            import numpy as np

            raw = self.imported_mode_values
            if "real" not in raw or "imag" not in raw:
                raise ValueError("imported mode mapping requires real and imag arrays")
            real = np.asarray(raw["real"], dtype=float)
            imag = np.asarray(raw["imag"], dtype=float)
            if real.shape != imag.shape or real.ndim != 2:
                raise ValueError("imported mode real/imag arrays must be matching 2-D grids")
            object.__setattr__(self, "imported_mode_values", real + 1j * imag)
        if str(self.mode_model) == "imported" and self.imported_mode_values is None:
            raise ValueError("imported mode requires imported_mode_values")
        if str(self.vector_coupling_model) not in {"paraxial_trace", "vector_debye"}:
            raise ValueError("unsupported vector_coupling_model")
        if str(self.field_model) not in {"cartesian_pupil_propagation", "cartesian_exit_pupil"}:
            raise ValueError("unsupported field_model; use cartesian_pupil_propagation")
        if str(self.sampling_model) != "equal_area_pupil":
            raise ValueError("unsupported sampling_model; use equal_area_pupil")
        if str(self.propagation_model) not in {
            "none", "angular_spectrum", "band_limited_angular_spectrum",
            "scaled_angular_spectrum", "scaled_fresnel", "issc", "fresnel",
        }:
            raise ValueError("unsupported propagation_model")
        if str(self.pupil_amplitude_weighting) not in {"field", "quadrature", "flux"}:
            raise ValueError("pupil_amplitude_weighting must be field, quadrature, or flux")
        finite_values = {
            "offset_x_mm": self.offset_x_mm,
            "offset_y_mm": self.offset_y_mm,
            "tilt_x_rad": self.tilt_x_rad,
            "tilt_y_rad": self.tilt_y_rad,
            "receiver_axial_offset_z_mm": self.receiver_axial_offset_z_mm,
            "pupil_extent_scale": self.pupil_extent_scale,
            "zero_padding_factor": self.zero_padding_factor,
            "auto_expand_factor": self.auto_expand_factor,
            "nyquist_margin_min": self.nyquist_margin_min,
            "sampling_convergence_tolerance": self.sampling_convergence_tolerance,
            "issc_oversampling_factor": self.issc_oversampling_factor,
            "issc_padding_factor": self.issc_padding_factor,
        }
        if self.propagation_distance_mm is not None:
            finite_values["propagation_distance_mm"] = self.propagation_distance_mm
        if self.field_extent_mm is not None:
            finite_values["field_extent_mm"] = self.field_extent_mm
        if self.output_extent_x_mm is not None:
            finite_values["output_extent_x_mm"] = self.output_extent_x_mm
        if self.output_extent_y_mm is not None:
            finite_values["output_extent_y_mm"] = self.output_extent_y_mm
        for name, value in finite_values.items():
            if not math.isfinite(float(value)):
                raise ValueError(f"{name} must be finite")
        for name in ("field_extent_mm", "output_extent_x_mm", "output_extent_y_mm"):
            value = getattr(self, name)
            if value is not None and float(value) <= 0.0:
                raise ValueError(f"{name} must be positive when provided")
        if float(self.pupil_extent_scale) <= 0.0:
            raise ValueError("pupil_extent_scale must be positive")
        if float(self.zero_padding_factor) < 1.0:
            raise ValueError("zero_padding_factor must be at least 1")
        if float(self.auto_expand_factor) <= 1.0:
            raise ValueError("auto_expand_factor must be greater than 1")
        if int(self.auto_expand_max_steps) < 0:
            raise ValueError("auto_expand_max_steps must be non-negative")
        if float(self.nyquist_margin_min) < 0.0:
            raise ValueError("nyquist_margin_min must be non-negative")
        if float(self.sampling_convergence_tolerance) <= 0.0:
            raise ValueError("sampling_convergence_tolerance must be positive")
        if int(self.wavefront_fit_order) < 0:
            raise ValueError("wavefront_fit_order must be non-negative")
        if int(self.issc_max_virtual_grid) < 17:
            raise ValueError("issc_max_virtual_grid must be at least 17")
        if float(self.issc_oversampling_factor) < 1.0:
            raise ValueError("issc_oversampling_factor must be at least 1")
        if float(self.issc_padding_factor) < 0.0:
            raise ValueError("issc_padding_factor must be non-negative")
        for name, value in (
            ("fiber_length_m", self.fiber_length_m),
            ("fiber_attenuation_db_per_km", self.fiber_attenuation_db_per_km),
            ("fiber_connector_loss_db", self.fiber_connector_loss_db),
        ):
            if not math.isfinite(float(value)) or float(value) < 0.0:
                raise ValueError(f"{name} must be finite and non-negative")
        if self.fiber_facet_transmission_override is not None:
            value = float(self.fiber_facet_transmission_override)
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise ValueError("fiber_facet_transmission_override must be in [0, 1]")
        for name, value in (
            ("fiber_core_radius_um", self.fiber_core_radius_um),
            ("fiber_n_core", self.fiber_n_core),
            ("fiber_n_clad", self.fiber_n_clad),
        ):
            if value is not None and (not math.isfinite(float(value)) or float(value) <= 0.0):
                raise ValueError(f"{name} must be positive and finite when provided")
        for name, value in (("receiver_na_x", self.receiver_na_x), ("receiver_na_y", self.receiver_na_y)):
            if value is not None:
                value = float(value)
                if not math.isfinite(value) or not 0.0 < value <= float(self.receiver_medium_refractive_index):
                    raise ValueError(f"{name} must satisfy 0 < NA <= receiver_medium_refractive_index")
        for name, value in (
            ("incident_jones_vector", self.incident_jones_vector),
            ("fiber_mode_jones_vector", self.fiber_mode_jones_vector),
        ):
            vector = tuple(complex(item) for item in value)
            if len(vector) != 2 or sum(abs(item) ** 2 for item in vector) <= 0.0:
                raise ValueError(f"{name} must contain two non-zero Jones components")
            object.__setattr__(self, name, vector)

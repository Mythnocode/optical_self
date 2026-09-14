
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from frontend_pyside.presets.demo_780nm_four_lens import (
    DEFAULT_ANALYSES,
    DEFAULT_BEAM_QUALITY_M2,
    DEFAULT_BEAM_QUALITY_M2_X,
    DEFAULT_BEAM_QUALITY_M2_Y,
    DEFAULT_CALCULATION_PRECISION,
    DEFAULT_HIGH_PRECISION_COUPLING,
    DEFAULT_IMAGE_DISTANCE_MM,
    DEFAULT_LAYOUT_PUPIL_SAMPLE_COUNT,
    DEFAULT_OBJECT_DISTANCE_MM,
    DEFAULT_ONLY_VISIBLE_RESULTS,
    DEFAULT_OUTPUT_EXTENT_MM,
    DEFAULT_OUTPUT_GRID_SIZE,
    DEFAULT_PROPAGATION_MODEL,
    DEFAULT_PUPIL_RADIUS_MM,
    DEFAULT_PUPIL_SAMPLE_COUNT,
    DEFAULT_RECEIVER_CORE_DIAMETER_UM,
    DEFAULT_RECEIVER_ENDFACE_TRANSMISSION,
    DEFAULT_RECEIVER_MFD_UM,
    DEFAULT_RECEIVER_NA,
    DEFAULT_RECEIVER_N_CLAD,
    DEFAULT_RECEIVER_N_CORE,
    DEFAULT_RECEIVER_OUTSIDE_INDEX,
    DEFAULT_SOURCE_NA,
    DEFAULT_WAIST_POSITION_MM,
    DEFAULT_WAIST_RADIUS_UM,
    DEFAULT_WAIST_RADIUS_X_UM,
    DEFAULT_WAIST_RADIUS_Y_UM,
    DEFAULT_WAVELENGTH_NM,
    DEFAULT_ZERO_PADDING_FACTOR,
)


@dataclass(frozen=True, slots=True)
class SourceFormState:
    source_type: str = "gaussian"
    wavelength_nm: float = DEFAULT_WAVELENGTH_NM
    waist_x_um: float = DEFAULT_WAIST_RADIUS_X_UM
    waist_y_um: float = DEFAULT_WAIST_RADIUS_Y_UM
    waist_position_mm: float = DEFAULT_WAIST_POSITION_MM
    beam_quality_m2_x: float = DEFAULT_BEAM_QUALITY_M2_X
    beam_quality_m2_y: float = DEFAULT_BEAM_QUALITY_M2_Y
    object_na_x: float = DEFAULT_SOURCE_NA
    object_na_y: float = DEFAULT_SOURCE_NA
    field_x_deg: float = 0.0
    field_y_deg: float = 0.0
    power_value: float = 1.0
    power_unit: str = "mW"
    auxiliary_wavelengths_nm: tuple[float, ...] = ()


@dataclass(frozen=True, slots=True)
class ReceiverFormState:
    receiver_type: str = "single_mode_fiber"
    mode_model: str = "gaussian"
    mode_field_diameter_x_um: float = DEFAULT_RECEIVER_MFD_UM
    mode_field_diameter_y_um: float = DEFAULT_RECEIVER_MFD_UM
    core_diameter_um: float = DEFAULT_RECEIVER_CORE_DIAMETER_UM
    na_x: float = DEFAULT_RECEIVER_NA
    na_y: float = DEFAULT_RECEIVER_NA
    core_refractive_index: float = DEFAULT_RECEIVER_N_CORE
    cladding_refractive_index: float = DEFAULT_RECEIVER_N_CLAD
    outside_refractive_index: float = DEFAULT_RECEIVER_OUTSIDE_INDEX
    offset_x_um: float = 0.0
    offset_y_um: float = 0.0
    axial_offset_z_um: float = 0.0
    tilt_x_urad: float = 0.0
    tilt_y_urad: float = 0.0
    endface_transmission: float = DEFAULT_RECEIVER_ENDFACE_TRANSMISSION
    fiber_length_m: float = 0.0
    attenuation_db_per_km: float = 0.0
    connector_loss_db: float = 0.0
    imported_mode_real: tuple[tuple[float, ...], ...] | None = None
    imported_mode_imag: tuple[tuple[float, ...], ...] | None = None
    imported_mode_source: str = ""


@dataclass(frozen=True, slots=True)
class SystemFormState:
    object_distance_mm: float = DEFAULT_OBJECT_DISTANCE_MM
    pupil_radius_mm: float = DEFAULT_PUPIL_RADIUS_MM
    image_distance_mm: float = DEFAULT_IMAGE_DISTANCE_MM
    field_x_deg: float = 0.0
    field_y_deg: float = 0.0
    auto_best_focus: bool = False
    environment_temperature_c: float = 20.0
    environment_pressure_kpa: float = 101.325
    thermal_compensation: bool = False


@dataclass(frozen=True, slots=True)
class AlignmentFormState:
    enabled: bool = False
    include_dz: bool = True
    max_offset_um: float = 20.0
    max_axial_offset_um: float = 200.0
    max_tilt_urad: float = 5000.0
    max_iterations: int = 40
    max_function_evaluations: int = 300
    timeout_seconds: float = 60.0


@dataclass(frozen=True, slots=True)
class CalculationFormState:
    precision: str = DEFAULT_CALCULATION_PRECISION
    output_grid_size: int = DEFAULT_OUTPUT_GRID_SIZE
    pupil_sample_count: int = DEFAULT_PUPIL_SAMPLE_COUNT
    
    
    layout_pupil_sample_count: int = DEFAULT_LAYOUT_PUPIL_SAMPLE_COUNT
    propagation_model: str = DEFAULT_PROPAGATION_MODEL
    zero_padding_factor: float = DEFAULT_ZERO_PADDING_FACTOR
    output_extent_mm: float = DEFAULT_OUTPUT_EXTENT_MM
    auto_expand_output: bool = True
    analyses: tuple[str, ...] = DEFAULT_ANALYSES
    only_visible_results: bool = DEFAULT_ONLY_VISIBLE_RESULTS
    include_energy_audit: bool = False
    sampling_convergence_enabled: bool = False
    save_large_arrays: bool = False
    high_precision_coupling_enabled: bool = DEFAULT_HIGH_PRECISION_COUPLING


@dataclass(frozen=True, slots=True)
class SimulationFormState:
    source: SourceFormState = field(default_factory=SourceFormState)
    receiver: ReceiverFormState = field(default_factory=ReceiverFormState)
    system: SystemFormState = field(default_factory=SystemFormState)
    calculation: CalculationFormState = field(default_factory=CalculationFormState)
    alignment: AlignmentFormState = field(default_factory=AlignmentFormState)

    def request_options(self) -> dict[str, Any]:
        receiver = self.receiver
        calculation = self.calculation
        analyses = set(calculation.analyses)
        options: dict[str, Any] = {
            "environment_temperature_c": self.system.environment_temperature_c,
            "environment_pressure_kpa": self.system.environment_pressure_kpa,
            "geometric": {
                "pupil_sample_count": calculation.pupil_sample_count,
                "field_x_deg": self.source.field_x_deg,
                "field_y_deg": self.source.field_y_deg,
                "record_surfaces": "raytrace" in analyses,
            },
        }

        
        
        
        if analyses & {"psf", "mtf", "diffraction"}:
            options["wave"] = {
                "grid_size": calculation.output_grid_size,
                "method": WAVE_PROPAGATION_METHOD_MAP.get(
                    calculation.propagation_model, calculation.propagation_model
                ),
                "extent_mm": calculation.output_extent_mm,
                "zero_padding_factor": calculation.zero_padding_factor,
            }

        if analyses & {"coupling", "wavefront_quality", "fiber_alignment", "power_audit"}:
            precision_mode = {
                "preview": "preview",
                "standard": "balanced",
                "high": "reference",
            }.get(calculation.precision, "balanced")
            hybrid = {
                "pupil_sample_count": calculation.pupil_sample_count,
                "grid_size": calculation.output_grid_size,
                "output_grid_size": calculation.output_grid_size,
                "output_extent_x_mm": calculation.output_extent_mm,
                "output_extent_y_mm": calculation.output_extent_mm,
                "propagation_model": calculation.propagation_model,
                "zero_padding_factor": calculation.zero_padding_factor,
                "precision_mode": precision_mode,
                "convergence_enabled": calculation.sampling_convergence_enabled,
                "sampling_convergence_enabled": calculation.sampling_convergence_enabled,
                "auto_expand_output": bool(calculation.auto_expand_output),
                "wavefront_fit_order": 4,
                "include_diagnostic_arrays": calculation.save_large_arrays or "coupling" in analyses,
                "result_array_policy": "full" if calculation.save_large_arrays else "field_only",
                "mode_model": receiver.mode_model,
                # Keep the GUI's native angular unit all the way into the formal
                # coupling options.  The project snapshot remains degree-based for
                # schema compatibility, but the solver no longer has to infer a
                # GUI tilt from that serialized representation.
                "tilt_x_urad": receiver.tilt_x_urad,
                "tilt_y_urad": receiver.tilt_y_urad,
                "high_precision_coupling_enabled": calculation.high_precision_coupling_enabled,
                "fiber_core_radius_um": receiver.core_diameter_um / 2.0,
                "fiber_n_core": receiver.core_refractive_index,
                "fiber_n_clad": receiver.cladding_refractive_index,
                "receiver_medium_refractive_index": receiver.outside_refractive_index,
                "fiber_length_m": receiver.fiber_length_m,
                "fiber_attenuation_db_per_km": receiver.attenuation_db_per_km,
                "fiber_connector_loss_db": receiver.connector_loss_db,
                "fiber_facet_transmission_override": receiver.endface_transmission,
            }
            if receiver.mode_model == "imported":
                if receiver.imported_mode_real is None or receiver.imported_mode_imag is None:
                    raise ValueError("导入复场模式缺少已校验的复场数据")
                hybrid["imported_mode_values"] = {
                    "real": [list(row) for row in receiver.imported_mode_real],
                    "imag": [list(row) for row in receiver.imported_mode_imag],
                }
                hybrid["imported_mode_source"] = receiver.imported_mode_source
            if "power_audit" in analyses:
                hybrid["include_breakdown"] = True
            if self.alignment.enabled and "fiber_alignment" in analyses:
                hybrid.update(
                    {
                        "method": "powell",
                        "include_dz": self.alignment.include_dz,
                        "initial_offset_x_um": receiver.offset_x_um,
                        "initial_offset_y_um": receiver.offset_y_um,
                        "initial_axial_offset_z_um": receiver.axial_offset_z_um,
                        "initial_tilt_x_urad": receiver.tilt_x_urad,
                        "initial_tilt_y_urad": receiver.tilt_y_urad,
                        "max_offset_um": self.alignment.max_offset_um,
                        "max_axial_offset_um": self.alignment.max_axial_offset_um,
                        "max_tilt_urad": self.alignment.max_tilt_urad,
                        "max_iterations": self.alignment.max_iterations,
                        "max_function_evaluations": self.alignment.max_function_evaluations,
                        "timeout_seconds": self.alignment.timeout_seconds,
                        "return_history": False,
                    }
                )
            options["hybrid"] = hybrid
        return options


SOURCE_TYPE_MAP = {
    "高斯模式": "gaussian",
    "Gaussian": "gaussian",
    "均匀光瞳": "parallel_pupil",
    "点光源": "object_space_na",
}
RECEIVER_TYPE_MAP = {
    "单模光纤": "single_mode_fiber",
    "多模光纤": "multimode_fiber",
    "二维探测器": "detector",
    "用户模式": "user_mode",
}
PRECISION_MAP = {"129×129": "preview", "257×257": "standard", "513×513": "high", "1025×1025": "high", "预览": "preview", "标准": "standard", "高精度": "high", "研究级": "high"}
WAVE_PROPAGATION_METHOD_MAP = {
    "scaled_fresnel": "fresnel",
    "scaled_angular_spectrum": "angular_spectrum",
    "issc": "angular_spectrum",
    "matrix_fresnel": "fresnel",
}
PROPAGATION_MAP = {
    "普通角谱": "angular_spectrum",
    "带限角谱": "band_limited_angular_spectrum",
    "缩放角谱": "scaled_angular_spectrum",
    "缩放 Fresnel": "scaled_fresnel",
    "ISSC": "issc",
    "Fresnel": "fresnel",
}


def parse_grid_size(text: str, fallback: int) -> int:
    try:
        return int(str(text).split("×", 1)[0].strip())
    except (TypeError, ValueError):
        return int(fallback)


__all__ = [
    "AlignmentFormState",
    "CalculationFormState",
    "PRECISION_MAP",
    "PROPAGATION_MAP",
    "WAVE_PROPAGATION_METHOD_MAP",
    "RECEIVER_TYPE_MAP",
    "ReceiverFormState",
    "SOURCE_TYPE_MAP",
    "SimulationFormState",
    "SourceFormState",
    "SystemFormState",
    "parse_grid_size",
]

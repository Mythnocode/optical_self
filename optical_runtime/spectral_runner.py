
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Sequence

import numpy as np

from shared_contracts.parameters import ParameterChange
from shared_contracts.simulation import SimulationRequest
from shared_ports.simulation import SimulationPort


@dataclass(frozen=True, slots=True)
class SpectralPoint:
    wavelength_nm: float
    weight: float = 1.0
    temperature_c: float = 20.0


def spectral_points_from_source(source: Any, *, temperature_c: float = 20.0) -> tuple[SpectralPoint, ...]:

    explicit = tuple(float(v) for v in (getattr(source, "spectral_wavelengths_nm", ()) or ()))
    if explicit:
        raw_weights = tuple(float(v) for v in (getattr(source, "spectral_power_weights", ()) or ()))
        weights = raw_weights or tuple(1.0 for _ in explicit)
        if len(weights) != len(explicit):
            raise ValueError("spectral power weights must match explicit wavelengths")
        return tuple(SpectralPoint(wavelength, weight, float(temperature_c)) for wavelength, weight in zip(explicit, weights))
    width = float(getattr(source, "spectral_fwhm_nm", 0.0) or 0.0)
    count = int(getattr(source, "spectral_sample_count", 1) or 1)
    center = float(getattr(source, "wavelength_nm", 550.0))
    if width <= 0.0 or count <= 1:
        return (SpectralPoint(center, 1.0, float(temperature_c)),)
    from optical_core.physics.wave.analyses.spectral_coherence import gaussian_spectral_lines
    wavelengths, weights = gaussian_spectral_lines(center, width, sample_count=count)
    return tuple(
        SpectralPoint(float(wavelength), float(weight), float(temperature_c))
        for wavelength, weight in zip(wavelengths, weights)
    )


class SpectralSimulationRunner:


    algorithm_version = "spectral-thermal-sweep-1.0"

    def __init__(self, simulator: SimulationPort) -> None:
        self.simulator = simulator

    def run(
        self,
        base_request: SimulationRequest,
        points: Iterable[SpectralPoint],
        *,
        response_metric: str = "coupling_efficiency",
        fixed_receiver_axial_offset_z_mm: float | None = None,
    ) -> dict[str, Any]:
        point_list = list(points)
        if not point_list:
            raise ValueError("at least one spectral point is required")
        wavelengths: list[float] = []
        temperatures: list[float] = []
        weights: list[float] = []
        responses: list[float] = []
        warnings: list[str] = []
        statuses: list[str] = []
        for index, point in enumerate(point_list):
            if point.wavelength_nm <= 0.0 or point.weight < 0.0:
                raise ValueError("wavelength must be positive and spectral weight non-negative")
            options = dict(base_request.options)
            options["environment_temperature_c"] = float(point.temperature_c)
            request = base_request.model_copy(
                deep=True,
                update={
                    "request_id": f"{base_request.request_id}:spectral:{index:04d}",
                    "parameter_changes": [
                        *base_request.parameter_changes,
                        ParameterChange(path="source.wavelength_nm", value=float(point.wavelength_nm), unit="nm"),
                        *([] if fixed_receiver_axial_offset_z_mm is None else [
                            ParameterChange(
                                path="receiver.axial_offset_z_mm",
                                value=float(fixed_receiver_axial_offset_z_mm),
                                unit="mm",
                            )
                        ]),
                    ],
                    "options": options,
                },
            )
            result = self.simulator.evaluate(request)
            statuses.append(result.status)
            value = _metric(result.metrics, response_metric)
            if result.status != "completed" or value is None or not np.isfinite(value):
                warnings.append(
                    f"Spectral point {index} at {point.wavelength_nm:g} nm did not provide "
                    f"a finite {response_metric}."
                )
                value = float("nan")
            wavelengths.append(float(point.wavelength_nm))
            temperatures.append(float(point.temperature_c))
            weights.append(float(point.weight))
            responses.append(float(value))

        response_array = np.asarray(responses, dtype=float)
        weight_array = np.asarray(weights, dtype=float)
        valid = np.isfinite(response_array) & (weight_array > 0.0)
        if not np.any(valid):
            weighted_mean = float("nan")
            weighted_std = float("nan")
        else:
            normalized = weight_array[valid] / np.sum(weight_array[valid])
            weighted_mean = float(np.sum(normalized * response_array[valid]))
            weighted_std = float(
                np.sqrt(np.sum(normalized * (response_array[valid] - weighted_mean) ** 2))
            )
        return {
            "metrics": {
                "spectral_weighted_mean": weighted_mean,
                "spectral_weighted_std": weighted_std,
                "spectral_min": float(np.nanmin(response_array)) if np.any(np.isfinite(response_array)) else float("nan"),
                "spectral_max": float(np.nanmax(response_array)) if np.any(np.isfinite(response_array)) else float("nan"),
                "spectral_valid_point_count": int(np.count_nonzero(valid)),
            },
            "arrays": {
                "spectral_wavelength_nm": wavelengths,
                "spectral_temperature_c": temperatures,
                "spectral_weights": weights,
                "spectral_response": responses,
                "spectral_status": statuses,
            },
            "warnings": warnings,
            "metadata": {
                "algorithm_version": self.algorithm_version,
                "response_metric": response_metric,
                "reference_data_used_as_input": False,
                "zemax_data_used_as_input": False,
                "fixed_receiver_axial_offset_z_mm": fixed_receiver_axial_offset_z_mm,
            },
        }


    def run_fixed_plane_broadband(
        self,
        base_request: SimulationRequest,
        points: Iterable[SpectralPoint],
        *,
        fixed_receiver_axial_offset_z_mm: float,
        response_metric: str = "total_coupling_efficiency",
    ) -> dict[str, Any]:

        result = self.run(
            base_request,
            points,
            response_metric=response_metric,
            fixed_receiver_axial_offset_z_mm=float(fixed_receiver_axial_offset_z_mm),
        )
        metrics = result["metrics"]
        metrics["fixed_plane_broadband_mean_total_efficiency"] = metrics["spectral_weighted_mean"]
        metrics["fixed_plane_broadband_efficiency_range"] = (
            metrics["spectral_max"] - metrics["spectral_min"]
            if np.isfinite(metrics["spectral_max"]) and np.isfinite(metrics["spectral_min"])
            else float("nan")
        )
        metrics["fixed_plane_receiver_axial_offset_z_mm"] = float(fixed_receiver_axial_offset_z_mm)
        result["metadata"]["broadband_focus_policy"] = "single_fixed_physical_fiber_plane"
        result["metadata"]["formal_objective_uses_total_efficiency"] = response_metric in {
            "total_coupling_efficiency", "coupling_breakdown_total_estimate"
        }
        return result


def _metric(metrics: dict[str, Any], name: str) -> float | None:
    value = metrics.get(name)
    if isinstance(value, (int, float)):
        return float(value)
    matches = [
        float(item)
        for key, item in metrics.items()
        if key.endswith(f".{name}") and isinstance(item, (int, float))
    ]
    return matches[0] if len(matches) == 1 else None


__all__ = ["SpectralPoint", "spectral_points_from_source", "SpectralSimulationRunner"]

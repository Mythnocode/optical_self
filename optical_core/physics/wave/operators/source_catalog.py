from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np

from optical_core.models.representations.scalar_field import PowerUnit


@dataclass(frozen=True, slots=True)
class PointSource:


    x_mm: float = 0.0
    y_mm: float = 0.0
    start_z_mm: float = 0.0
    wavelength_nm: float = 550.0
    power_value: float = 1.0
    power_unit: PowerUnit | str = PowerUnit.ARBITRARY


@dataclass(frozen=True, slots=True)
class CollimatedSource:


    diameter_mm: float = 1.0
    field_x_deg: float = 0.0
    field_y_deg: float = 0.0
    start_z_mm: float = 0.0
    wavelength_nm: float = 550.0
    power_value: float = 1.0
    power_unit: PowerUnit | str = PowerUnit.ARBITRARY


@dataclass(frozen=True, slots=True)
class FiberSource:


    mode_field_diameter_um: float = 10.0
    wavelength_nm: float = 550.0
    na: float = 0.1
    start_z_mm: float = 0.0
    power_value: float = 1.0
    power_unit: PowerUnit | str = PowerUnit.ARBITRARY


@dataclass(frozen=True, slots=True)
class ExtendedSource:


    width_x_mm: float = 1.0
    height_y_mm: float = 1.0
    angular_width_x_deg: float = 0.0
    angular_height_y_deg: float = 0.0
    start_z_mm: float = 0.0
    wavelength_nm: float = 550.0
    power_value: float = 1.0
    power_unit: PowerUnit | str = PowerUnit.ARBITRARY


@dataclass(frozen=True, slots=True)
class MultiWavelengthSource:
    wavelengths_nm: tuple[float, ...]
    spectral_power_weights: tuple[float, ...]
    source_type: str = "multi_wavelength"


def normalize_power_weights(weights: Sequence[float]) -> list[float]:


    arr = np.asarray(weights, dtype=float).reshape(-1)
    if arr.size == 0:
        return []
    if np.any(~np.isfinite(arr)) or np.any(arr < 0.0):
        raise ValueError("power weights must be finite and non-negative")
    total = float(np.sum(arr))
    if total <= 0.0:
        return (np.ones_like(arr) / arr.size).tolist()
    return (arr / total).tolist()


def _power_metadata(source: Any) -> dict[str, Any]:
    value = float(getattr(source, "power_value", 1.0))
    if not np.isfinite(value) or value < 0.0:
        raise ValueError("source power_value must be finite and non-negative")
    unit = PowerUnit(getattr(source, "power_unit", PowerUnit.ARBITRARY))
    return {
        "source_total_power": value,
        "source_power_unit": unit.value,
    }


def _sample_payload(
    *,
    source: Any,
    positions_mm: list[list[float]],
    directions: list[list[float]],
    wavelength_nm: list[float],
    field_amplitudes: Sequence[float],
    power_weights: Sequence[float],
    quadrature_weights: Sequence[float] | None = None,
    **metadata: Any,
) -> dict[str, Any]:
    n = len(positions_mm)
    if len(directions) != n or len(wavelength_nm) != n:
        raise ValueError("source sample arrays must have the same length")
    field_amplitude_array = np.asarray(field_amplitudes, dtype=float).reshape(-1)
    if field_amplitude_array.shape != (n,) or np.any(~np.isfinite(field_amplitude_array)) or np.any(field_amplitude_array < 0.0):
        raise ValueError("field_amplitudes must be finite non-negative values with one entry per ray")
    fractional_power = normalize_power_weights(power_weights)
    quadrature = np.ones(n, dtype=float) if quadrature_weights is None else np.asarray(quadrature_weights, dtype=float)
    if quadrature.shape != (n,) or np.any(~np.isfinite(quadrature)) or np.any(quadrature < 0.0):
        raise ValueError("quadrature_weights must be finite non-negative values with one entry per ray")
    return {
        "positions_mm": positions_mm,
        "directions": directions,
        "wavelength_nm": wavelength_nm,
        "field_amplitudes": field_amplitude_array.tolist(),
        "power_weights": fractional_power,
        "quadrature_weights": quadrature.tolist(),
        "coordinate_system": "RH_XYZ_Z_OPTICAL_AXIS",
        "optical_axis": "z",
        **_power_metadata(source),
        **metadata,
    }


def sample_point_source(source: PointSource, sample_count: int = 1) -> dict[str, Any]:
    n = max(1, int(sample_count))
    return _sample_payload(
        source=source,
        positions_mm=[[float(source.x_mm), float(source.y_mm), float(source.start_z_mm)] for _ in range(n)],
        directions=[[0.0, 0.0, 1.0] for _ in range(n)],
        wavelength_nm=[float(source.wavelength_nm) for _ in range(n)],
        field_amplitudes=np.ones(n),
        power_weights=np.ones(n),
    )


def sample_collimated_source(source: CollimatedSource, sample_count: int = 5) -> dict[str, Any]:
    coords = _disk_samples(float(source.diameter_mm) / 2.0, sample_count)
    tx = np.tan(np.deg2rad(float(source.field_x_deg)))
    ty = np.tan(np.deg2rad(float(source.field_y_deg)))
    direction = np.array([tx, ty, 1.0], dtype=float)
    direction /= np.linalg.norm(direction)
    n = len(coords)
    return _sample_payload(
        source=source,
        positions_mm=[[x, y, float(source.start_z_mm)] for x, y in coords],
        directions=[direction.tolist() for _ in range(n)],
        wavelength_nm=[float(source.wavelength_nm) for _ in range(n)],
        field_amplitudes=np.ones(n),
        power_weights=np.ones(n),
    )


def sample_fiber_source(source: FiberSource, sample_count: int = 9) -> dict[str, Any]:
    waist_mm = float(source.mode_field_diameter_um) / 2000.0
    coords = _disk_samples(3.0 * waist_mm, sample_count)
    field_amplitudes = np.asarray(
        [np.exp(-(x * x + y * y) / max(waist_mm * waist_mm, 1e-18)) for x, y in coords],
        dtype=float,
    )
    return _sample_payload(
        source=source,
        positions_mm=[[x, y, float(source.start_z_mm)] for x, y in coords],
        directions=[[0.0, 0.0, 1.0] for _ in coords],
        wavelength_nm=[float(source.wavelength_nm) for _ in coords],
        field_amplitudes=field_amplitudes,
        power_weights=np.square(field_amplitudes),
        source_na=float(source.na),
    )


def sample_extended_source(source: ExtendedSource, sample_count: int = 5) -> dict[str, Any]:
    n = max(1, int(sample_count))
    x_values = np.linspace(-source.width_x_mm / 2.0, source.width_x_mm / 2.0, n)
    y_values = np.linspace(-source.height_y_mm / 2.0, source.height_y_mm / 2.0, n)
    xx, yy = np.meshgrid(x_values, y_values, indexing="xy")
    tx = np.tan(np.deg2rad(np.linspace(-source.angular_width_x_deg / 2.0, source.angular_width_x_deg / 2.0, n)))
    ty = np.tan(np.deg2rad(np.linspace(-source.angular_height_y_deg / 2.0, source.angular_height_y_deg / 2.0, n)))
    positions: list[list[float]] = []
    directions: list[list[float]] = []
    for row in range(n):
        for column in range(n):
            positions.append([float(xx[row, column]), float(yy[row, column]), float(source.start_z_mm)])
            direction = np.array([tx[column], ty[row], 1.0], dtype=float)
            direction /= np.linalg.norm(direction)
            directions.append(direction.tolist())
    return _sample_payload(
        source=source,
        positions_mm=positions,
        directions=directions,
        wavelength_nm=[float(source.wavelength_nm) for _ in positions],
        field_amplitudes=np.ones(len(positions)),
        power_weights=np.ones(len(positions)),
    )


def sample_multi_wavelength_source(
    base_source: Any,
    spectral_source: MultiWavelengthSource,
    sample_count: int = 5,
) -> dict[str, Any]:
    if isinstance(base_source, CollimatedSource):
        base = sample_collimated_source(base_source, sample_count)
    elif isinstance(base_source, FiberSource):
        base = sample_fiber_source(base_source, sample_count)
    elif isinstance(base_source, ExtendedSource):
        base = sample_extended_source(base_source, sample_count)
    else:
        base = sample_point_source(base_source if isinstance(base_source, PointSource) else PointSource(), sample_count)

    wavelengths = [float(value) for value in spectral_source.wavelengths_nm]
    spectral_weights = normalize_power_weights(spectral_source.spectral_power_weights)
    if len(wavelengths) != len(spectral_weights) or not wavelengths:
        raise ValueError("wavelengths_nm and spectral_power_weights must be non-empty and have equal length")

    positions: list[list[float]] = []
    directions: list[list[float]] = []
    wl_out: list[float] = []
    field_amplitude_values: list[float] = []
    powers: list[float] = []
    quadrature: list[float] = []
    for pos, direction, amplitude, base_power, base_quad in zip(
        base["positions_mm"],
        base["directions"],
        base["field_amplitudes"],
        base["power_weights"],
        base["quadrature_weights"],
    ):
        for wavelength, spectral_power in zip(wavelengths, spectral_weights):
            positions.append(list(pos))
            directions.append(list(direction))
            wl_out.append(wavelength)
            
            
            field_amplitude_values.append(float(amplitude))
            powers.append(float(base_power) * float(spectral_power))
            quadrature.append(float(base_quad))

    payload = _sample_payload(
        source=base_source,
        positions_mm=positions,
        directions=directions,
        wavelength_nm=wl_out,
        field_amplitudes=field_amplitude_values,
        power_weights=powers,
        quadrature_weights=quadrature,
        spectral_power_weights=spectral_weights,
    )
    return payload


def _disk_samples(radius_mm: float, sample_count: int) -> list[tuple[float, float]]:
    n = max(1, int(sample_count))
    values = np.linspace(-radius_mm, radius_mm, n)
    coords: list[tuple[float, float]] = []
    for x in values:
        for y in values:
            if x * x + y * y <= radius_mm * radius_mm + 1e-15:
                coords.append((float(x), float(y)))
    return coords or [(0.0, 0.0)]




normalize_weights = normalize_power_weights


__all__ = [
    "PointSource",
    "CollimatedSource",
    "FiberSource",
    "ExtendedSource",
    "MultiWavelengthSource",
    "normalize_power_weights",
    "normalize_weights",
    "sample_point_source",
    "sample_collimated_source",
    "sample_fiber_source",
    "sample_extended_source",
    "sample_multi_wavelength_source",
]

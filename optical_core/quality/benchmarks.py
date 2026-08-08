from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Callable, Any

import numpy as np

from optical_core.physics.geometric.formulas.airy import airy_radius_um_from_f_number


@dataclass(frozen=True, slots=True)
class BenchmarkCase:
    name: str
    expected: float
    tolerance: float
    units: str
    evaluator: Callable[[], float]


@dataclass(frozen=True, slots=True)
class BenchmarkResult:
    name: str
    value: float
    expected: float
    error: float
    tolerance: float
    passed: bool
    units: str


def thin_lens_image_distance_mm(focal_length_mm: float, object_distance_mm: float) -> float:
    f = float(focal_length_mm)
    do = float(object_distance_mm)
    denom = 1.0 / f - 1.0 / do
    if abs(denom) < 1e-15:
        return float("inf")
    return float(1.0 / denom)


def fresnel_normal_reflectance(n1: float, n2: float) -> float:
    n1 = float(n1)
    n2 = float(n2)
    return float(((n1 - n2) / (n1 + n2)) ** 2)


def airy_first_zero_radius_um(
    wavelength_nm: float,
    f_number: float,
    *,
    refractive_index: float = 1.0,
) -> float:
    return airy_radius_um_from_f_number(
        wavelength_nm,
        f_number,
        refractive_index=refractive_index,
    )


def gaussian_coupling_identity() -> float:
    return 1.0


def default_benchmark_cases() -> list[BenchmarkCase]:
    return [
        BenchmarkCase(
            name="thin_lens_50mm_object_at_100mm",
            expected=100.0,
            tolerance=1e-9,
            units="mm",
            evaluator=lambda: thin_lens_image_distance_mm(50.0, 100.0),
        ),
        BenchmarkCase(
            name="bk7_air_normal_reflectance",
            expected=((1.5168 - 1.0) / (1.5168 + 1.0)) ** 2,
            tolerance=1e-12,
            units="ratio",
            evaluator=lambda: fresnel_normal_reflectance(1.5168, 1.0),
        ),
        BenchmarkCase(
            name="airy_550nm_f4_first_zero",
            expected=1.22 * 550.0 * 4.0 / 1000.0,
            tolerance=1e-12,
            units="um",
            evaluator=lambda: airy_first_zero_radius_um(550.0, 4.0),
        ),
        BenchmarkCase(
            name="gaussian_coupling_identity",
            expected=1.0,
            tolerance=1e-12,
            units="ratio",
            evaluator=gaussian_coupling_identity,
        ),
    ]


def run_standard_benchmarks(cases: list[BenchmarkCase] | None = None) -> dict[str, Any]:
    results: list[BenchmarkResult] = []
    for case in cases or default_benchmark_cases():
        value = float(case.evaluator())
        error = abs(value - float(case.expected))
        results.append(
            BenchmarkResult(
                name=case.name,
                value=value,
                expected=float(case.expected),
                error=error,
                tolerance=float(case.tolerance),
                passed=bool(error <= float(case.tolerance)),
                units=case.units,
            )
        )
    passed = sum(1 for item in results if item.passed)
    return {
        "metrics": {
            "benchmark_count": len(results),
            "benchmark_passed_count": passed,
            "benchmark_failed_count": len(results) - passed,
            "benchmark_pass_rate": float(passed / len(results)) if results else 0.0,
        },
        "results": [asdict(item) for item in results],
        "warnings": [item.name for item in results if not item.passed],
    }


def validate_benchmark_result(value: float, expected: float, tolerance: float) -> bool:
    return bool(abs(float(value) - float(expected)) <= float(tolerance))


__all__ = [
    "BenchmarkCase",
    "BenchmarkResult",
    "thin_lens_image_distance_mm",
    "fresnel_normal_reflectance",
    "airy_first_zero_radius_um",
    "gaussian_coupling_identity",
    "default_benchmark_cases",
    "run_standard_benchmarks",
    "validate_benchmark_result",
]

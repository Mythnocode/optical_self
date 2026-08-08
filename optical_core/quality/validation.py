from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    code: str
    message: str
    severity: str = "error"


def validate_positive(name: str, value: float, *, allow_zero: bool = False) -> list[ValidationIssue]:
    if value is None:
        return [ValidationIssue("MISSING_VALUE", f"{name} is required")]
    v = float(value)
    if allow_zero:
        ok = v >= 0.0
    else:
        ok = v > 0.0
    return [] if ok else [ValidationIssue("INVALID_POSITIVE", f"{name} must be {'non-negative' if allow_zero else 'positive'}")]


def validate_probability(name: str, value: float) -> list[ValidationIssue]:
    v = float(value)
    return [] if 0.0 <= v <= 1.0 else [ValidationIssue("INVALID_PROBABILITY", f"{name} must be in [0, 1]")]


def validate_grid_size(name: str, value: int, *, require_odd: bool = True, minimum: int = 3) -> list[ValidationIssue]:
    n = int(value)
    issues: list[ValidationIssue] = []
    if n < int(minimum):
        issues.append(ValidationIssue("GRID_TOO_SMALL", f"{name} must be >= {minimum}"))
    if require_odd and n % 2 == 0:
        issues.append(ValidationIssue("GRID_MUST_BE_ODD", f"{name} should be odd for centered sampling", "warning"))
    return issues


def validate_optical_options(options: Mapping[str, Any]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for key in ("wavelength_nm", "grid_size", "pupil_sample_count"):
        if key not in options:
            continue
        if key == "wavelength_nm":
            issues.extend(validate_positive(key, float(options[key])))
        else:
            issues.extend(validate_grid_size(key, int(options[key]), require_odd=True, minimum=3))
    if "transmission" in options:
        issues.extend(validate_probability("transmission", float(options["transmission"])))
    return issues


def issues_to_warnings(issues: list[ValidationIssue]) -> list[str]:
    return [f"{item.code}: {item.message}" for item in issues if item.severity == "warning"]


def issues_to_errors(issues: list[ValidationIssue]) -> list[str]:
    return [f"{item.code}: {item.message}" for item in issues if item.severity == "error"]


__all__ = [
    "ValidationIssue",
    "validate_positive",
    "validate_probability",
    "validate_grid_size",
    "validate_optical_options",
    "issues_to_warnings",
    "issues_to_errors",
]

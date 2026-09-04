from __future__ import annotations

from math import pi
from typing import Any, Literal
from uuid import uuid4

import numpy as np
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from backend.optical_ml_app.api.responses import success
from shared_contracts.parameters import ParameterChange
from shared_contracts.project import ProjectSnapshot
from shared_contracts.simulation import SimulationRequest

router = APIRouter()


class ValidationCaseRequest(BaseModel):
    case: str = "工况"
    parameter_changes: dict[str, float] = Field(default_factory=dict)


class ValidationRunRequest(BaseModel):
    kind: Literal["E003", "E004", "E006"]
    project: ProjectSnapshot
    cases: list[ValidationCaseRequest] = Field(default_factory=list, min_length=1, max_length=128)
    check_numerical_convergence: bool = True
    scan_points: int = Field(default=121, ge=41, le=401)
    scan_half_range_um: float = Field(default=30.0, gt=0.0, le=10000.0)
    scan_half_range_mrad: float = Field(default=150.0, gt=0.0, le=5000.0)


def _three_db_width(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 3 or len(xs) != len(ys):
        return None
    x = np.asarray(xs, dtype=float)
    y = np.asarray(ys, dtype=float)
    finite = np.isfinite(x) & np.isfinite(y)
    x, y = x[finite], y[finite]
    if len(x) < 3:
        return None
    order = np.argsort(x)
    x, y = x[order], y[order]
    peak = int(np.nanargmax(y))
    threshold = float(y[peak]) * 0.5

    def crossing(start: int, stop: int, step: int) -> float | None:
        i = start
        while i != stop:
            j = i + step
            if j < 0 or j >= len(x):
                break
            yi, yj = float(y[i]), float(y[j])
            if yi == threshold:
                return float(x[i])
            if (yi - threshold) * (yj - threshold) <= 0 and yi != yj:
                ratio = (threshold - yi) / (yj - yi)
                return float(x[i] + ratio * (x[j] - x[i]))
            i = j
        return None

    left = crossing(peak, -1, -1)
    right = crossing(peak, len(x), 1)
    if left is None or right is None or right < left:
        return None
    return right - left


def _changes(mapping: dict[str, float]) -> list[ParameterChange]:
    return [ParameterChange(path=str(path), value=float(value)) for path, value in mapping.items()]


def _base_value(project: ProjectSnapshot, path: str, changes: dict[str, float]) -> float:
    if path in changes:
        return float(changes[path])
    if path == "receiver.offset_x_mm":
        return float(project.receiver.offset_x_mm if project.receiver else 0.0)
    if path == "receiver.tilt_x_deg":
        return float(project.receiver.tilt_x_deg if project.receiver else 0.0)
    return 0.0


def _run_e003(engine: Any, project: ProjectSnapshot, case: ValidationCaseRequest, precision: str) -> float:
    request = SimulationRequest(
        request_id=f"validation-e003-{uuid4().hex[:10]}",
        project=project,
        analyses=["coupling"],
        parameter_changes=_changes(case.parameter_changes),
        precision=precision,
        random_seed=42,
    )
    result = engine.evaluate(request)
    value = result.metrics.get("coupling_efficiency")
    if not isinstance(value, (int, float)):
        raise ValueError("平台计算没有返回耦合效率")
    value = float(value)
    return value * 100.0 if abs(value) <= 1.000001 else value


def _run_width(
    engine: Any,
    project: ProjectSnapshot,
    case: ValidationCaseRequest,
    *,
    path: str,
    half_range_native: float,
    points: int,
    precision: str,
    output_scale: float,
) -> tuple[float, int, float]:
    center = _base_value(project, path, case.parameter_changes)
    current_half = float(half_range_native)
    for _attempt in range(4):
        xs = np.linspace(center - current_half, center + current_half, int(points), dtype=float)
        requests: list[SimulationRequest] = []
        for index, x in enumerate(xs):
            mapping = dict(case.parameter_changes)
            mapping[path] = float(x)
            requests.append(SimulationRequest(
                request_id=f"validation-scan-{uuid4().hex[:8]}-{index:04d}",
                project=project,
                analyses=["coupling"],
                parameter_changes=_changes(mapping),
                precision=precision,
                random_seed=42 + index,
            ))
        results = engine.batch_evaluate(requests)
        ys = []
        for result in results:
            value = result.metrics.get("coupling_efficiency")
            ys.append(float(value) if isinstance(value, (int, float)) else float("nan"))
        width = _three_db_width(xs.tolist(), ys)
        if width is not None:
            return float(width) * float(output_scale), int(points), current_half
        current_half *= 2.0
    raise ValueError("自动扫描范围仍未覆盖峰值两侧的 3 dB 交点，请检查当前工况或增大扫描范围")


@router.post("/validation/run")
def run_validation(payload: ValidationRunRequest, request: Request):
    from optical_runtime import create_optical_simulation_engine

    engine = create_optical_simulation_engine()
    rows: list[dict[str, Any]] = []
    for case in payload.cases:
        warnings: list[str] = []
        try:
            if payload.kind == "E003":
                standard = _run_e003(engine, payload.project, case, "standard")
                numerical = None
                if payload.check_numerical_convergence:
                    high = _run_e003(engine, payload.project, case, "high")
                    numerical = abs(high - standard)
                    platform = high
                else:
                    platform = standard
                rows.append({
                    "case": case.case,
                    "platform": platform,
                    "numerical_uncertainty": numerical,
                    "unit": "%",
                    "warnings": warnings,
                })
                continue

            if payload.kind == "E004":
                path = "receiver.offset_x_mm"
                half_native = float(payload.scan_half_range_um) / 1000.0
                scale = 1000.0
                unit = "μm"
            else:
                path = "receiver.tilt_x_deg"
                half_native = float(payload.scan_half_range_mrad) * 180.0 / (pi * 1000.0)
                scale = pi / 180.0 * 1000.0
                unit = "mrad"

            standard, used_points, used_half = _run_width(
                engine, payload.project, case,
                path=path,
                half_range_native=half_native,
                points=payload.scan_points,
                precision="standard",
                output_scale=scale,
            )
            numerical = None
            platform = standard
            if payload.check_numerical_convergence:
                high_points = min(401, max(payload.scan_points + 40, 2 * payload.scan_points - 1))
                high, _, _ = _run_width(
                    engine, payload.project, case,
                    path=path,
                    half_range_native=used_half,
                    points=high_points,
                    precision="high",
                    output_scale=scale,
                )
                numerical = abs(high - standard)
                platform = high
            rows.append({
                "case": case.case,
                "platform": platform,
                "numerical_uncertainty": numerical,
                "unit": unit,
                "scan_points": used_points,
                "warnings": warnings,
            })
        except Exception as exc:
            rows.append({
                "case": case.case,
                "platform": None,
                "numerical_uncertainty": None,
                "unit": "%" if payload.kind == "E003" else ("μm" if payload.kind == "E004" else "mrad"),
                "warnings": [str(exc)],
            })
    return success(request, {"kind": payload.kind, "rows": rows})

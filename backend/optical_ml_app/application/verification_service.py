

from __future__ import annotations

from pathlib import Path
from typing import Any

from shared_contracts.prediction import PredictionRequest
from shared_contracts.project import ProjectSnapshot
from shared_contracts.simulation import SimulationRequest

from backend.optical_ml_app.application.ports import TaskManagerPort


def _extract_features(project: ProjectSnapshot) -> dict[str, float]:

    features: dict[str, float] = {}
    for index, surface in enumerate(project.surfaces):
        prefix = f"surface.{index}"
        features[f"{prefix}.radius_mm"] = surface.radius_mm or 0.0
        features[f"{prefix}.distance_to_next_mm"] = surface.distance_to_next_mm
        features[f"{prefix}.clear_aperture_mm"] = surface.clear_aperture_mm or 0.0
        features[f"{prefix}.conic"] = surface.conic
    features["object_distance_mm"] = project.object_distance_mm
    features["image_distance_mm"] = project.image_distance_mm
    features["pupil_radius_mm"] = project.pupil_radius_mm
    features["wavelength_nm"] = project.source.wavelength_nm
    if project.receiver:
        features["receiver.offset_x_mm"] = project.receiver.offset_x_mm
        features["receiver.offset_y_mm"] = project.receiver.offset_y_mm
        features["receiver.axial_offset_z_mm"] = project.receiver.axial_offset_z_mm
    return features


def _apply_parameter_overrides(
    project: ProjectSnapshot,
    overrides: dict[str, float],
) -> ProjectSnapshot:

    data = project.model_dump(mode="json")

    for path, value in overrides.items():
        parts = path.split(".")
        if len(parts) == 1:
            data[parts[0]] = value
        elif parts[0] == "surface" and len(parts) >= 3:
            idx = int(parts[1])
            key = parts[2]
            while len(data["surfaces"]) <= idx:
                data["surfaces"].append({})
            data["surfaces"][idx][key] = value
        elif parts[0] == "receiver" and len(parts) == 2:
            if data.get("receiver"):
                data["receiver"][parts[1]] = value
        elif parts[0] == "source" and len(parts) == 2:
            if data.get("source"):
                data["source"][parts[1]] = value
        elif parts[0] == "aperture" and len(parts) == 2:
            if data.get("aperture"):
                data["aperture"][parts[1]] = value

    return ProjectSnapshot.model_validate(data)


def _build_simulation_request(
    project: ProjectSnapshot,
    request_id: str,
) -> SimulationRequest:
    return SimulationRequest(
        request_id=request_id,
        project=project,
        analyses=["coupling"],
        precision="standard",
        random_seed=42,
    )


# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------

def _create_engine() -> Any:

    from optical_runtime import create_optical_simulation_engine
    return create_optical_simulation_engine()


def _create_predictor(model_registry_root: str) -> Any:

    from machine_learning.inference.predictor import Predictor
    from machine_learning.registry.model_registry import FileModelRegistry

    registry = FileModelRegistry(Path(model_registry_root))
    return Predictor(registry)


def _run_single_verification(
    model_id: str,
    base_project: ProjectSnapshot,
    overrides: dict[str, float] | None,
    model_registry_root: str,
    request_index: int,
) -> dict[str, Any]:

    engine = _create_engine()
    predictor = _create_predictor(model_registry_root)

    project = (
        _apply_parameter_overrides(base_project, overrides)
        if overrides
        else base_project
    )
    features = _extract_features(project)

    
    pred_request = PredictionRequest(model_id=model_id, features=features)
    pred_result = predictor.predict(pred_request)
    predicted_targets = dict(pred_result.predictions)

    
    sim_request = _build_simulation_request(
        project,
        request_id=f"verify-{model_id[:8]}-{request_index:04d}",
    )
    sim_result = engine.evaluate(sim_request)
    metrics = dict(getattr(sim_result, "metrics", {}) or {})

    
    all_targets = set(predicted_targets) | set(metrics)
    absolute_errors: dict[str, float] = {}
    relative_errors: dict[str, float | None] = {}
    for target in all_targets:
        p = predicted_targets.get(target)
        s = metrics.get(target)
        if p is not None and s is not None:
            absolute_errors[target] = abs(p - s)
            relative_errors[target] = abs(p - s) / max(abs(s), 1e-12)

    return {
        "model_id": model_id,
        "parameter_values": dict(overrides) if overrides else {},
        "predicted_targets": predicted_targets,
        "simulated_targets": {k: float(v) for k, v in metrics.items() if v is not None},
        "absolute_errors": absolute_errors,
        "relative_errors": relative_errors,
    }


def _run_verification_task(
    context: Any,
    model_id: str,
    base_project: ProjectSnapshot,
    parameter_sets: list[dict[str, float]],
    model_registry_root: str,
) -> dict[str, Any]:

    results: list[dict[str, Any]] = []
    for idx, overrides in enumerate(parameter_sets):
        if context.cancellation.is_cancelled:
            break
        result = _run_single_verification(
            model_id=model_id,
            base_project=base_project,
            overrides=overrides,
            model_registry_root=model_registry_root,
            request_index=idx,
        )
        results.append(result)
        if context.progress:
            context.progress.update(
                float(idx + 1) / len(parameter_sets),
                stage=f"verifying sample {idx + 1}/{len(parameter_sets)}",
                completed_items=idx + 1,
                total_items=len(parameter_sets),
            )
    overall_metrics = _aggregate_verification(results)
    return {
        "model_id": model_id,
        "sample_count": len(results),
        "results": results,
        **overall_metrics,
    }


def _aggregate_verification(
    results: list[dict[str, Any]],
) -> dict[str, Any]:

    all_abs: dict[str, list[float]] = {}
    all_rel: dict[str, list[float]] = {}

    for r in results:
        for target, err in r.get("absolute_errors", {}).items():
            all_abs.setdefault(target, []).append(err)
        for target, err in r.get("relative_errors", {}).items():
            if err is not None:
                all_rel.setdefault(target, []).append(err)

    summary: dict[str, Any] = {}
    for target, errors in all_abs.items():
        summary[f"{target}_mae"] = float(sum(errors) / max(len(errors), 1))
        summary[f"{target}_max_abs_error"] = float(max(errors))
    for target, errors in all_rel.items():
        summary[f"{target}_mre"] = float(sum(errors) / max(len(errors), 1))

    return summary


# ==========================================================================

# ==========================================================================

class VerificationApplicationService:


    def __init__(
        self,
        task_manager: TaskManagerPort,
        model_registry: Any,
    ) -> None:
        self.task_manager = task_manager
        self._model_registry_root = str(model_registry.root)

    def submit(
        self,
        model_id: str,
        base_project: ProjectSnapshot,
        parameter_sets: list[dict[str, float]] | None = None,
    ) -> str:

        if not parameter_sets:
            parameter_sets = [{}]

        
        mrr = self._model_registry_root
        ps = list(parameter_sets)

        def _task(context: Any) -> dict[str, Any]:
            return _run_verification_task(
                context=context,
                model_id=model_id,
                base_project=base_project,
                parameter_sets=ps,
                model_registry_root=mrr,
            )

        return self.task_manager.submit("verification", _task)

    def submit_single(
        self,
        model_id: str,
        base_project: ProjectSnapshot,
        overrides: dict[str, float] | None = None,
    ) -> str:

        return self.submit(
            model_id=model_id,
            base_project=base_project,
            parameter_sets=[overrides or {}],
        )

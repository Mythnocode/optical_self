
from __future__ import annotations

from typing import Any

import numpy as np

from backend.optical_ml_app.application.ports import TaskManagerPort
from machine_learning.features.coupling_physics import (
    PHYSICS_RESIDUAL_FEATURE_PATHS,
    coupling_loss_db,
    derive_coupling_physics_features,
)
from machine_learning.features.resolver import FeatureResolver
from machine_learning.optimization import run_hybrid_search
from optical_runtime.analysis.collimation import (
    CollimationConstraintError,
    active_collimation_constraint,
    evaluate_collimation_constraint,
)
from shared_contracts.optimization import (
    CollimationConstraint,
    OptimizationIteration,
    OptimizationRequest,
    OptimizationResult,
)
from shared_contracts.parameters import ParameterChange
from shared_contracts.simulation import SimulationRequest


def _compute_merit(metrics: dict[str, Any], objectives: list[dict]) -> float:
    total = 0.0
    for objective in objectives:
        value = metrics.get(objective["metric"])
        if not isinstance(value, (int, float)) or not np.isfinite(value):
            return float("inf")
        weight = float(objective.get("weight", 1.0))
        if objective.get("goal") == "maximize":
            total += weight * (1.0 - float(value))
        elif objective.get("goal") == "minimize":
            total += weight * float(value)
        else:
            target = float(objective.get("target_value", 0.0))
            total += weight * abs(float(value) - target)
    return total


def _candidate_changes(candidate: np.ndarray, variables: list[dict]) -> list[ParameterChange]:
    return [
        ParameterChange(
            path=variable["path"],
            value=float(
                np.clip(
                    value,
                    float(variable["lower_bound"]),
                    float(variable["upper_bound"]),
                )
            ),
        )
        for variable, value in zip(variables, candidate)
    ]


def _candidate_project(
    candidate: np.ndarray,
    variables: list[dict],
    base_request: SimulationRequest,
):
    from machine_learning.datasets.generator import apply_parameter_changes

    changes = [*base_request.parameter_changes, *_candidate_changes(candidate, variables)]
    return apply_parameter_changes(base_request.project, changes)


def _apply_collimation_constraint(
    project,
    metrics: dict[str, Any],
    constraint: CollimationConstraint | None,
) -> tuple[dict[str, Any], float, bool, list[str]]:

    if constraint is None:
        return metrics, 0.0, True, []
    try:
        assessment = evaluate_collimation_constraint(
            project, constraint, formal_metrics=metrics
        )
    except (CollimationConstraintError, ValueError, ZeroDivisionError) as exc:
        failed = dict(metrics)
        failed.update(
            {
                "collimation_feasible": 0.0,
                "collimation_score": 0.0,
                "collimation_penalty": 1.0e6,
                "collimation_error": str(exc),
            }
        )
        return failed, 1.0e6, False, [str(exc)]
    enriched = dict(metrics)
    enriched.update(assessment.metrics)
    if assessment.violations:
        enriched["collimation_violations"] = dict(assessment.violations)
    return enriched, assessment.penalty, assessment.feasible, list(assessment.warnings)


def _evaluate_candidate(
    candidate: np.ndarray,
    variables: list[dict],
    base_request: SimulationRequest,
    request_id_prefix: str,
    eval_counter: int,
    engine: Any,
    objectives: list[dict],
    collimation_constraint: CollimationConstraint | None = None,
) -> tuple[dict[str, Any], float, bool, list[str]]:
    changes = [*base_request.parameter_changes, *_candidate_changes(candidate, variables)]
    simulation_request = base_request.model_copy(
        deep=True,
        update={
            "request_id": f"{request_id_prefix}:formal:{eval_counter:06d}",
            "parameter_changes": changes,
        },
    )
    simulation_result = engine.evaluate(simulation_request)
    metrics: dict[str, Any] = dict(simulation_result.metrics)
    if "coupling_loss_db" not in metrics:
        loss = coupling_loss_db(metrics)
        if loss is not None:
            metrics["coupling_loss_db"] = loss
    candidate_project = _candidate_project(candidate, variables, base_request)
    metrics, constraint_penalty, feasible, warnings = _apply_collimation_constraint(
        candidate_project, metrics, collimation_constraint
    )
    return (
        metrics,
        float(_compute_merit(metrics, objectives) + constraint_penalty),
        feasible,
        warnings,
    )


def _select_surrogate_model(
    model_registry: Any,
    requested_model_id: str,
    objectives: list[dict],
    project: Any | None = None,
) -> str:
    if model_registry is None:
        return ""

    required_metrics = {str(item["metric"]) for item in objectives}
    resolver = FeatureResolver()

    def features_fit_project(record: dict[str, Any]) -> bool:
        if project is None:
            return True
        feature_paths = [str(path) for path in record.get("feature_paths", [])]
        if not feature_paths:
            return False
        physics_paths = set(PHYSICS_RESIDUAL_FEATURE_PATHS)
        for path in feature_paths:
            if path in physics_paths:
                continue
            try:
                resolver.get_value(project, path)
            except (AttributeError, IndexError, KeyError, TypeError, ValueError):
                return False
        return True

    def compatible(record: dict[str, Any]) -> bool:
        available = set(str(name) for name in record.get("target_names", []))
        if "coupling_loss_db" in available:
            available.add("coupling_efficiency")
        if "coupling_efficiency" in available:
            available.add("coupling_loss_db")
        return (
            record.get("status") == "available"
            and record.get("model_type")
            in {"xgboost_physics_residual", "random_forest"}
            and required_metrics.issubset(available)
            and features_fit_project(record)
        )

    if requested_model_id:
        record = model_registry.describe(requested_model_id)
        if not compatible(record):
            raise ValueError(
                "代理模型不可用、不能预测当前目标，或其镜头/特征结构与当前项目不兼容: "
                f"{requested_model_id}"
            )
        return requested_model_id

    candidates = [
        record for record in model_registry.list_models() if compatible(record)
    ]
    if not candidates:
        return ""
    role_rank = {
        "physics_residual_surrogate": 2,
        "random_forest_baseline": 1,
    }
    candidates.sort(
        key=lambda item: (
            role_rank.get(str(item.get("training_role", "")), 0),
            str(item.get("created_at", "")),
        ),
        reverse=True,
    )
    return str(candidates[0]["model_id"])


def _build_surrogate_predictor(model_registry: Any, model_id: str):
    model, preprocessing, manifest = model_registry.load(model_id)
    feature_paths = list(manifest.get("feature_paths", []))
    target_names = list(manifest.get("target_names", []))
    resolver = FeatureResolver()

    def predict(candidate_project) -> dict[str, float]:
        physics: dict[str, float] = {}
        if set(feature_paths) & set(PHYSICS_RESIDUAL_FEATURE_PATHS):
            physics = derive_coupling_physics_features(candidate_project)
        values: list[float] = []
        for path in feature_paths:
            try:
                if path in physics:
                    values.append(float(physics[path]))
                else:
                    values.append(float(resolver.get_value(candidate_project, path)))
            except (AttributeError, IndexError, KeyError, TypeError, ValueError) as exc:
                raise ValueError(
                    f"代理模型特征与当前光学结构不兼容: {path}"
                ) from exc
        X = np.asarray([values], dtype=float)
        raw = np.asarray(model.predict(preprocessing.transform_features(X)))
        if raw.ndim == 1:
            raw = raw.reshape(1, -1)
        predicted_batch = np.asarray(preprocessing.inverse_targets(raw))
        if predicted_batch.size == 0 or predicted_batch.shape[0] == 0:
            raise ValueError("代理模型没有返回有效预测结果")
        predicted = np.atleast_1d(predicted_batch[0])
        metrics = {
            name: float(value) for name, value in zip(target_names, predicted)
        }
        if "coupling_loss_db" in metrics and "coupling_efficiency" not in metrics:
            metrics["coupling_efficiency"] = float(
                10.0 ** (-metrics["coupling_loss_db"] / 10.0)
            )
        if "coupling_efficiency" in metrics and "coupling_loss_db" not in metrics:
            loss = coupling_loss_db(metrics)
            if loss is not None:
                metrics["coupling_loss_db"] = loss
        return metrics

    return predict, manifest


def _run_optimization_task(
    context: Any,
    base_request: SimulationRequest,
    opt_request: OptimizationRequest,
    dataset_root: str | None = None,
    model_registry: Any | None = None,
) -> OptimizationResult:
    from optical_runtime import create_optical_simulation_engine

    context.progress.update(0.03, "optimization.initializing", 0, 1)
    engine = create_optical_simulation_engine()
    context.progress.update(0.05, "optimization.preparing", 0, 1)
    objectives = [objective.model_dump() for objective in opt_request.objectives]
    active_variables = [
        variable.model_dump() for variable in opt_request.variables if variable.enabled
    ]
    if not active_variables:
        return OptimizationResult(
            request_id=opt_request.request_id,
            status="failed",
            optimizer=opt_request.optimizer,
            best_merit=float("inf"),
            warnings=["No enabled optimization variables"],
        )

    bounds = [
        (float(variable["lower_bound"]), float(variable["upper_bound"]))
        for variable in active_variables
    ]
    initial_x = np.asarray(
        [float(variable["initial_value"]) for variable in active_variables],
        dtype=float,
    )
    
    
    
    
    max_evaluations = int(
        opt_request.max_evaluations
        or max(40, int(opt_request.max_iterations))
    )
    history: list[OptimizationIteration] = []
    evaluated_metrics: dict[tuple[float, ...], dict[str, Any]] = {}
    formal_counter = 0
    surrogate_counter = 0
    collimation_constraint = active_collimation_constraint(opt_request.constraints)
    constraint_warnings: set[str] = set()

    requested_model_id = str(
        opt_request.options.get("surrogate_model_id", "") or ""
    )
    surrogate_model_id = _select_surrogate_model(
        model_registry, requested_model_id, objectives, base_request.project
    )
    surrogate_predict = None
    surrogate_manifest: dict[str, Any] = {}
    if surrogate_model_id:
        surrogate_predict, surrogate_manifest = _build_surrogate_predictor(
            model_registry, surrogate_model_id
        )

    total_progress_items = max_evaluations
    coarse_fraction = float(opt_request.options.get("coarse_fraction", 0.7))
    surrogate_expected = max(
        1,
        int(max(1, max_evaluations - 2) * coarse_fraction),
    )
    formal_expected_with_surrogate = max(
        1, max_evaluations - surrogate_expected
    )

    def formal_objective(candidate: np.ndarray) -> float:
        nonlocal formal_counter
        if context.cancellation.is_cancelled:
            raise StopIteration("cancelled")
        metrics, merit, _feasible, warnings = _evaluate_candidate(
            candidate,
            active_variables,
            base_request,
            opt_request.request_id,
            formal_counter,
            engine,
            objectives,
            collimation_constraint,
        )
        constraint_warnings.update(warnings)
        formal_counter += 1
        key = tuple(np.round(np.asarray(candidate, dtype=float), 12))
        evaluated_metrics[key] = dict(metrics)
        history.append(
            OptimizationIteration(
                iteration=len(history),
                evaluations=formal_counter,
                variables=np.asarray(candidate, dtype=float).tolist(),
                metrics=dict(metrics),
                merit=float(merit),
            )
        )
        if surrogate_predict:
            progress = min(
                0.64
                + 0.34
                * formal_counter
                / formal_expected_with_surrogate,
                0.98,
            )
        else:
            progress = min(
                0.06 + 0.92 * formal_counter / max(max_evaluations, 1),
                0.98,
            )
        context.progress.update(
            progress,
            "optimization.formal_simulation",
            completed_items=surrogate_counter + formal_counter,
            total_items=total_progress_items,
        )
        return float(merit)

    def surrogate_objective(candidate: np.ndarray) -> float:
        nonlocal surrogate_counter
        if context.cancellation.is_cancelled:
            raise StopIteration("cancelled")
        candidate_project = _candidate_project(
            candidate, active_variables, base_request
        )
        metrics = surrogate_predict(candidate_project)
        metrics, constraint_penalty, _feasible, warnings = _apply_collimation_constraint(
            candidate_project, metrics, collimation_constraint
        )
        constraint_warnings.update(warnings)
        surrogate_counter += 1
        context.progress.update(
            min(
                0.06
                + 0.58
                * surrogate_counter
                / surrogate_expected,
                0.64,
            ),
            "optimization.surrogate_coarse_search",
            completed_items=surrogate_counter + formal_counter,
            total_items=total_progress_items,
        )
        return float(_compute_merit(metrics, objectives) + constraint_penalty)

    coarse_objective = surrogate_objective if surrogate_predict else formal_objective
    try:
        search = run_hybrid_search(
            coarse_objective,
            bounds,
            initial_x,
            coarse_method=opt_request.optimizer,
            seed=opt_request.random_seed,
            max_evaluations=max_evaluations,
            tolerance=opt_request.convergence_tolerance,
            coarse_fraction=coarse_fraction,
            refinement_objective=formal_objective if surrogate_predict else None,
            verification_objective=formal_objective if surrogate_predict else None,
        )
    except StopIteration:
        context.progress.update(1.0, "optimization.cancelled")
        return OptimizationResult(
            request_id=opt_request.request_id,
            status="cancelled",
            optimizer=opt_request.optimizer,
            best_merit=float("inf"),
            history=history,
            total_evaluations=surrogate_counter + formal_counter,
            total_iterations=len(history),
        )

    final_key = tuple(np.round(search.final_x, 12))
    best_metrics = evaluated_metrics.get(final_key)
    if best_metrics is None:
        best_metrics, _, _, warnings = _evaluate_candidate(
            search.final_x,
            active_variables,
            base_request,
            opt_request.request_id,
            formal_counter + 1,
            engine,
            objectives,
            collimation_constraint,
        )
        constraint_warnings.update(warnings)

    feedback_sample_id = ""
    feedback_dataset_id = str(
        opt_request.options.get("feedback_dataset_id", "") or ""
    )
    if feedback_dataset_id and dataset_root:
        from machine_learning.workflow.feedback import append_verified_result

        verified_project = _candidate_project(
            search.final_x, active_variables, base_request
        )
        feedback_sample_id = append_verified_result(
            dataset_root,
            feedback_dataset_id,
            request_id=opt_request.request_id,
            project=verified_project,
            feature_values={
                active_variables[index]["path"]: float(search.final_x[index])
                for index in range(len(active_variables))
            },
            target_values=best_metrics,
            engine_name=str(getattr(engine, "name", "optical_runtime")),
            engine_version=str(getattr(engine, "version", "unknown")),
            metadata={
                "optimizer": search.coarse_method,
                "powell_refined": True,
                "surrogate_model_id": surrogate_model_id,
            },
        )

    context.progress.update(1.0, "optimization.verified")
    collimation_feasible = bool(
        not collimation_constraint
        or float(best_metrics.get("collimation_feasible", 0.0)) >= 0.5
    )
    hard_collimation_required = bool(
        collimation_constraint and collimation_constraint.hard
    )
    success = np.isfinite(search.final_value) and (
        not hard_collimation_required or collimation_feasible
    )
    fallback_warning = (
        []
        if surrogate_model_id
        else ["No compatible surrogate model; coarse search used formal simulation"]
    )
    if collimation_constraint and not collimation_feasible:
        constraint_warnings.add(
            "最终候选未满足准直硬约束"
            if collimation_constraint.hard
            else "最终候选存在准直软约束超限"
        )
    return OptimizationResult(
        request_id=opt_request.request_id,
        status="completed" if success else "failed",
        optimizer=opt_request.optimizer,
        best_variables={
            active_variables[index]["path"]: float(search.final_x[index])
            for index in range(len(active_variables))
        },
        best_metrics=best_metrics,
        best_merit=float(search.final_value),
        history=history,
        total_evaluations=surrogate_counter + formal_counter,
        total_iterations=len(history),
        warnings=(
            fallback_warning + sorted(constraint_warnings)
            if success
            else ["Optimisation failed to find a valid solution"]
            + fallback_warning
            + sorted(constraint_warnings)
        ),
        metadata={
            "workflow": [
                "registered_surrogate_coarse_search"
                if surrogate_model_id
                else "formal_coarse_search_fallback",
                "powell_formal_refinement",
                "formal_simulation_verification",
            ],
            "coarse_method": search.coarse_method,
            "coarse_evaluation_source": "surrogate" if surrogate_model_id else "formal",
            "surrogate_model_id": surrogate_model_id,
            "surrogate_model_type": surrogate_manifest.get("model_type", ""),
            "coarse_predicted_merit": search.coarse_value,
            "coarse_formal_merit": search.coarse_verified_value,
            "powell_best_merit": search.refined_value,
            "surrogate_evaluations": surrogate_counter,
            "formal_evaluations": formal_counter,
            "coarse_evaluations": search.coarse_evaluations,
            "powell_evaluations": search.refinement_evaluations,
            "active_variables": [item["path"] for item in active_variables],
            "objectives": [item["metric"] for item in objectives],
            "constraints": list(opt_request.constraints),
            "collimation_constraint_enabled": bool(collimation_constraint),
            "collimation_feasible": collimation_feasible,
            "collimation_score": best_metrics.get("collimation_score"),
            "collimation_violations": best_metrics.get("collimation_violations", {}),
            "feedback_dataset_id": feedback_dataset_id,
            "feedback_sample_id": feedback_sample_id,
        },
    )


class OptimizationApplicationService:
    def __init__(
        self,
        task_manager: TaskManagerPort,
        dataset_root: str | None = None,
        model_registry: Any | None = None,
    ) -> None:
        self.task_manager = task_manager
        self.dataset_root = dataset_root
        self.model_registry = model_registry

    def submit(
        self,
        base_request: SimulationRequest,
        opt_request: OptimizationRequest,
    ) -> str:
        evaluation_budget = int(
            opt_request.max_evaluations
            or max(40, int(opt_request.max_iterations))
        )
        requested_timeout = opt_request.options.get("timeout_seconds")
        if requested_timeout is None:
            
            
            
            timeout_seconds = float(
                max(600, min(3600, evaluation_budget * 15))
            )
        else:
            timeout_seconds = float(
                max(60, min(86400, float(requested_timeout)))
            )
        return self.task_manager.submit(
            "optimization",
            _run_optimization_task,
            base_request,
            opt_request,
            self.dataset_root,
            self.model_registry,
            timeout_seconds=timeout_seconds,
        )

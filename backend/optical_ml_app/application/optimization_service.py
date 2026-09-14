
from __future__ import annotations

from pathlib import Path
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


def _apply_engineering_constraints(project, metrics: dict[str, Any], options: dict[str, Any]) -> tuple[dict[str, Any], float, bool, list[str]]:
    """Evaluate the geometry constraints exposed by the workbench optimiser."""
    cfg = dict(options or {})
    if not cfg:
        return metrics, 0.0, True, []
    surfaces = list(getattr(project, "surfaces", ()) or ())
    violations: dict[str, float] = {}
    length = sum(max(0.0, float(getattr(item, "thickness_mm", getattr(item, "distance_to_next_mm", 0.0)) or 0.0)) for item in surfaces)
    maximum = cfg.get("max_system_length_mm")
    if maximum is not None and length > float(maximum):
        violations["max_system_length_mm"] = length - float(maximum)
    min_center = cfg.get("min_center_thickness_mm")
    if min_center is not None:
        values = [float(getattr(item, "thickness_mm", 0.0) or 0.0) for item in surfaces if str(getattr(item, "material", "")).upper() not in {"", "AIR"}]
        if values and min(values) < float(min_center):
            violations["min_center_thickness_mm"] = float(min_center) - min(values)
    min_air = cfg.get("min_air_gap_mm")
    if min_air is not None:
        values = [float(getattr(item, "thickness_mm", 0.0) or 0.0) for item in surfaces if str(getattr(item, "material", "")).upper() in {"", "AIR"}]
        if values and min(values) < float(min_air):
            violations["min_air_gap_mm"] = float(min_air) - min(values)
    if bool(cfg.get("aperture_within_mechanical", False)):
        for index, item in enumerate(surfaces):
            mechanical = getattr(item, "mechanical_diameter_mm", None)
            aperture = float(getattr(item, "semi_aperture_mm", 0.0) or 0.0)
            if mechanical is not None and aperture > float(mechanical) * 0.5:
                violations[f"aperture_surface_{index + 1}"] = aperture - float(mechanical) * 0.5
    enriched = dict(metrics)
    enriched["engineering_system_length_mm"] = length
    if not violations:
        enriched["engineering_feasible"] = 1.0
        return enriched, 0.0, True, []
    # Edge thickness needs a full surface-sag model.  The current project
    # contract has no reliable lens-pair ownership, so do not fake that check.
    if cfg.get("min_edge_thickness_mm") is not None:
        enriched["engineering_edge_thickness_status"] = "requires_lens_pair_model"
    enriched["engineering_feasible"] = 0.0
    enriched["engineering_violations"] = violations
    return enriched, 1.0e6, False, ["工程约束未满足：" + "、".join(violations)]


def _evaluate_candidate(
    candidate: np.ndarray,
    variables: list[dict],
    base_request: SimulationRequest,
    request_id_prefix: str,
    eval_counter: int,
    engine: Any,
    objectives: list[dict],
    collimation_constraint: CollimationConstraint | None = None,
    engineering_constraints: dict[str, Any] | None = None,
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
    metrics, engineering_penalty, engineering_feasible, engineering_warnings = _apply_engineering_constraints(
        candidate_project, metrics, dict(engineering_constraints or {})
    )
    metrics, constraint_penalty, feasible, warnings = _apply_collimation_constraint(
        candidate_project, metrics, collimation_constraint
    )
    return (
        metrics,
        float(_compute_merit(metrics, objectives) + constraint_penalty + engineering_penalty),
        feasible and engineering_feasible,
        [*engineering_warnings, *warnings],
    )



def _formal_candidate_summary(
    *,
    final_x: np.ndarray,
    best_metrics: dict[str, Any],
    best_merit: float,
    history: list[OptimizationIteration],
    variables: list[dict],
    limit: int = 3,
) -> list[dict[str, Any]]:
    """Return a few *already formally simulated* and meaningfully distinct candidates.

    Inverse design should not show cosmetic A/B/C rows fabricated from the same optimum.
    The optimizer history contains formal simulations, so reuse those verified points and
    suppress near-duplicates in normalized design-variable space.
    """
    rows: list[tuple[np.ndarray, dict[str, Any], float]] = [
        (np.asarray(final_x, dtype=float), dict(best_metrics), float(best_merit))
    ]
    for item in sorted(history, key=lambda record: float(record.merit)):
        vector = np.asarray(item.variables, dtype=float)
        if vector.size != len(variables) or not np.all(np.isfinite(vector)):
            continue
        rows.append((vector, dict(item.metrics), float(item.merit)))

    spans = np.asarray(
        [max(float(v["upper_bound"]) - float(v["lower_bound"]), 1e-12) for v in variables],
        dtype=float,
    )
    chosen: list[tuple[np.ndarray, dict[str, Any], float]] = []
    for vector, metrics, merit in rows:
        if any(np.linalg.norm((vector - other[0]) / spans) < 0.025 for other in chosen):
            continue
        chosen.append((vector, metrics, merit))
        if len(chosen) >= max(1, int(limit)):
            break

    output: list[dict[str, Any]] = []
    for index, (vector, metrics, merit) in enumerate(chosen):
        variables_map = {variables[i]["path"]: float(vector[i]) for i in range(len(variables))}
        efficiency = metrics.get("coupling_efficiency")
        system_efficiency = metrics.get("system_efficiency")
        output.append(
            {
                "label": f"方案{chr(65 + index)}",
                "name": f"方案{chr(65 + index)}",
                "variables": variables_map,
                "metrics": metrics,
                "merit": merit,
                "formal_efficiency": efficiency,
                "coupling_efficiency": efficiency,
                "system_efficiency": system_efficiency,
                "verification_status": "formal_simulation",
            }
        )
    return output

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
        quality = record.get("model_quality")
        if isinstance(quality, dict) and quality.get("prediction_usable") is False:
            return False
        test_metrics = record.get("test_metrics")
        if isinstance(test_metrics, dict) and test_metrics.get("r2") is not None:
            try:
                if not np.isfinite(float(test_metrics["r2"])) or float(test_metrics["r2"]) <= 0.0:
                    return False
            except (TypeError, ValueError):
                return False
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
    model_registry_root: str | None = None,
) -> OptimizationResult:
    from optical_runtime import create_optical_simulation_engine
    # Worker arguments must remain spawn/persistent-worker serializable.
    # FileModelRegistry contains an RLock for its in-process cache, so passing the
    # live registry object through multiprocessing leaves optimization jobs stuck
    # in queued. Reconstruct the lightweight registry inside the worker instead.
    model_registry = None
    if model_registry_root:
        from machine_learning.registry.model_registry import FileModelRegistry
        model_registry = FileModelRegistry(Path(model_registry_root))

    context.progress.update(0.03, "optimization.initializing", 0, 1)
    engine = context.get_or_create_resource(
        "optical_engine", create_optical_simulation_engine
    )
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
    engineering_constraints = dict(opt_request.options.get("engineering_constraints") or {})
    constraint_warnings: set[str] = set()

    requested_model_id = str(
        opt_request.options.get("surrogate_model_id", "") or ""
    )
    surrogate_model_id = _select_surrogate_model(
        model_registry, requested_model_id, objectives, base_request.project
    )
    surrogate_predict = None
    surrogate_manifest: dict[str, Any] = {}
    surrogate_warning = ""
    if surrogate_model_id:
        try:
            surrogate_predict, surrogate_manifest = _build_surrogate_predictor(
                model_registry, surrogate_model_id
            )
            # Validate the persisted artifact against the current project's
            # feature schema before entering the search.  Older XGBoost
            # artifacts can deserialize successfully but reject the DataFrame
            # column names on the first candidate, which used to turn an
            # otherwise valid optimization into an opaque task failure.
            surrogate_predict(_candidate_project(initial_x, active_variables, base_request))
        except Exception as exc:
            if requested_model_id:
                raise ValueError(
                    f"指定代理模型无法用于当前项目：{type(exc).__name__}: {exc}"
                ) from exc
            surrogate_predict = None
            surrogate_model_id = ""
            surrogate_manifest = {}
            surrogate_warning = (
                "自动代理模型与当前特征结构不兼容，已回退到正式仿真："
                f"{type(exc).__name__}: {exc}"
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
            engineering_constraints,
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

    # The current system is a first-class candidate.  Without this formal baseline
    # an inaccurate surrogate can seed refinement in a poor region and return an
    # "optimised" design that is worse than the system the user started from.
    # Count this baseline inside the user's fixed evaluation budget.
    baseline_merit = formal_objective(initial_x)
    remaining_budget = max_evaluations - 1
    if remaining_budget < 8:
        return OptimizationResult(
            request_id=opt_request.request_id,
            status="failed",
            optimizer=opt_request.optimizer,
            best_variables={
                active_variables[index]["path"]: float(initial_x[index])
                for index in range(len(active_variables))
            },
            best_metrics=dict(history[0].metrics) if history else {},
            best_merit=float(baseline_merit),
            history=history,
            total_evaluations=formal_counter,
            total_iterations=len(history),
            warnings=["Optimization budget is too small after formal baseline verification"],
        )

    coarse_objective = surrogate_objective if surrogate_predict else formal_objective
    try:
        search = run_hybrid_search(
            coarse_objective,
            bounds,
            initial_x,
            coarse_method=opt_request.optimizer,
            seed=opt_request.random_seed,
            max_evaluations=remaining_budget,
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
    search_final_metrics = evaluated_metrics.get(final_key)
    if search_final_metrics is None:
        # Defensive fallback only. run_hybrid_search normally verifies final_x via
        # formal_objective, which already records the point in history.
        search_final_metrics, search_final_merit, _feasible, warnings = _evaluate_candidate(
            search.final_x,
            active_variables,
            base_request,
            opt_request.request_id,
            formal_counter + 1,
            engine,
            objectives,
            collimation_constraint,
            engineering_constraints,
        )
        constraint_warnings.update(warnings)
        history.append(
            OptimizationIteration(
                iteration=len(history),
                evaluations=formal_counter + 1,
                variables=np.asarray(search.final_x, dtype=float).tolist(),
                metrics=dict(search_final_metrics),
                merit=float(search_final_merit),
            )
        )

    # Select the best point among *all formally simulated candidates*, including
    # the baseline current system.  Search termination points are not privileged.
    best_iteration = min(history, key=lambda record: float(record.merit))
    best_x = np.asarray(best_iteration.variables, dtype=float)
    best_metrics = dict(best_iteration.metrics)
    best_merit = float(best_iteration.merit)

    feedback_sample_id = ""
    feedback_dataset_id = str(
        opt_request.options.get("feedback_dataset_id", "") or ""
    )
    if feedback_dataset_id and dataset_root:
        from machine_learning.workflow.feedback import append_verified_result

        verified_project = _candidate_project(
            best_x, active_variables, base_request
        )
        feedback_sample_id = append_verified_result(
            dataset_root,
            feedback_dataset_id,
            request_id=opt_request.request_id,
            project=verified_project,
            feature_values={
                active_variables[index]["path"]: float(best_x[index])
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
    success = np.isfinite(best_merit) and (
        not hard_collimation_required or collimation_feasible
    )
    fallback_warning = []
    if surrogate_warning:
        fallback_warning.append(surrogate_warning)
    elif not surrogate_model_id:
        fallback_warning.append("No compatible surrogate model; coarse search used formal simulation")
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
            active_variables[index]["path"]: float(best_x[index])
            for index in range(len(active_variables))
        },
        best_metrics=best_metrics,
        best_merit=best_merit,
        candidates=_formal_candidate_summary(
            final_x=best_x,
            best_metrics=best_metrics,
            best_merit=best_merit,
            history=history,
            variables=active_variables,
            limit=3,
        ),
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
            "baseline_formal_merit": float(baseline_merit),
            # Freeze task-submit baseline/target semantics in the result.  The UI
            # must never reconstruct "before" from a project that the user may
            # already have changed or applied a candidate to.
            "baseline_metrics": dict(history[0].metrics) if history else {},
            "objective_definitions": [dict(item) for item in objectives],
            "search_final_formal_merit": float(search.final_value),
            "selected_best_formal_merit": best_merit,
            "selected_best_is_baseline": bool(np.allclose(best_x, initial_x, rtol=0.0, atol=1e-12)),
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
        # Only a filesystem path may cross the worker boundary. The registry
        # instance itself owns a thread RLock and is intentionally not picklable.
        root = getattr(model_registry, "root", None) if model_registry is not None else None
        self.model_registry_root = str(root) if root is not None else None

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
            self.model_registry_root,
            timeout_seconds=timeout_seconds,
            idempotency_key=f"optimization:{opt_request.request_id}",
        )

from datetime import datetime, timezone
import time
import hashlib
import json
import uuid
from shared_contracts.datasets import DatasetManifest
from shared_contracts.project import ProjectSnapshot
from shared_contracts.simulation import SimulationRequest
from shared_contracts.metrics import analyses_for_metrics, canonical_metric_name, read_metric
from machine_learning.datasets.records import SampleRecord
from machine_learning.datasets.quality import evaluate_simulation_quality
from machine_learning.datasets.sampling import create_sampling_plan
from machine_learning.datasets.splitter import split_ids
from machine_learning.features.resolver import FeatureResolver
from machine_learning.features.coupling_physics import (
    PHYSICS_RESIDUAL_FEATURE_PATHS,
    PHYSICS_RESIDUAL_FEATURE_UNITS,
    coupling_loss_db,
    derive_coupling_physics_features,
    paired_coupling_targets,
)
from shared_contracts.versions import FEATURE_SCHEMA_VERSION
from shared_ports.simulation import SimulationPort


class DatasetGenerator:
    def __init__(self, simulation_port: SimulationPort, store):
        self.simulation_port = simulation_port
        self.store = store
        self.resolver = FeatureResolver()

    def generate(self, request, cancellation=None, progress=None, *, max_workers: int = 1):
        dataset_id = "dataset-" + uuid.uuid4().hex[:12]
        target_valid_count = max(1, int(request.sample_count))
        max_attempts = max(target_valid_count, target_valid_count * 3)
        plan = create_sampling_plan(
            request.parameters,
            target_valid_count,
            request.sampling_method,
            request.random_seed,
        )
        canonical_targets = paired_coupling_targets(request.targets)
        include_coupling_physics = (
            bool(getattr(request, "include_derived_physics_features", True))
            and request.base_project.receiver is not None
            and bool({"coupling_efficiency", "coupling_loss_db"} & set(canonical_targets))
        )
        valid_ids: list[str] = []
        failed = 0
        engine_name = "unknown"
        engine_version = "unknown"

        def prepare_attempts(values, start_index: int):
            prepared_batch: list[
                tuple[str, dict[str, float], ProjectSnapshot, SimulationRequest]
            ] = []
            for local_index, row in enumerate(values):
                if cancellation is not None and cancellation.is_cancelled:
                    break
                index = start_index + local_index
                sample_id = f"sample-{index + 1:06d}"
                feature_values: dict[str, float] = {}
                changes = []
                for parameter, value in zip(request.parameters, row):
                    feature_values[parameter.path] = float(value)
                    changes.append(
                        self.resolver.create_change(
                            parameter.path, float(value), parameter.unit
                        )
                    )
                changed_project = apply_parameter_changes(request.base_project, changes)
                sim_request = SimulationRequest(
                    request_id=f"{dataset_id}-{sample_id}",
                    project=changed_project,
                    analyses=target_to_analyses(canonical_targets),
                    parameter_changes=[],
                    precision=request.precision,
                    random_seed=request.random_seed + index,
                    engine=request.engine,
                    options=dataset_simulation_options(
                        changed_project, precision=request.precision
                    ),
                )
                prepared_batch.append(
                    (sample_id, feature_values, changed_project, sim_request)
                )
            return prepared_batch

        prepared = prepare_attempts(plan.values, 0)

        def run_batch(simulation_requests, *, progress_start: float | None = None,
                      progress_stop: float | None = None):
            results = []
            if not simulation_requests:
                return results
            batch = getattr(self.simulation_port, "batch_evaluate", None)
            batch_error: Exception | None = None
            batch_progress = None
            if progress is not None and progress_start is not None and progress_stop is not None:
                from backend.optical_ml_app.jobs.progress import ScaledProgressReporter

                batch_progress = ScaledProgressReporter(
                    progress,
                    progress_start,
                    progress_stop,
                    stage_prefix="dataset",
                )
            if callable(batch):
                try:
                    try:
                        results = list(
                            batch(
                                simulation_requests,
                                cancellation=cancellation,
                                progress=batch_progress,
                                max_workers=max(1, int(max_workers)),
                            )
                        )
                    except TypeError:
                        # Compatibility with SimulationPort implementations that do
                        # not yet expose max_workers.
                        results = list(
                            batch(
                                simulation_requests,
                                cancellation=cancellation,
                                progress=batch_progress,
                            )
                        )
                except Exception as exc:
                    # Preserve the old dataset contract: one bad simulation must
                    # not destroy the whole dataset.  If a custom/fallback batch
                    # port raises, retry sample-by-sample and record exceptions as
                    # invalid samples exactly as the previous serial path did.
                    batch_error = exc
                    results = []
            if not callable(batch) or batch_error is not None:
                for index, sim_request in enumerate(simulation_requests):
                    try:
                        result = self.simulation_port.evaluate(
                            sim_request, cancellation, None
                        )
                    except Exception as exc:
                        result = exc
                    results.append(result)
                    if batch_progress is not None:
                        batch_progress.update(
                            (index + 1) / max(len(simulation_requests), 1),
                            "dataset.simulation",
                            index + 1,
                            len(simulation_requests),
                        )
            return results

        def quality_decision(result):
            if isinstance(result, Exception):
                return None
            try:
                targets = extract_target_values(result.metrics, canonical_targets)
                return evaluate_simulation_quality(
                    result,
                    targets,
                    canonical_targets,
                    require_converged=True,
                )
            except Exception:
                return None

        def quality_accepts(result) -> bool:
            decision = quality_decision(result)
            return bool(decision is not None and decision.accepted)

        def precision_retry_allowed(result) -> bool:
            """Only retry failures that finer numerical sampling can fix."""

            decision = quality_decision(result)
            if decision is None or decision.accepted:
                return False
            return decision.code in {
                "SIMULATION_NOT_CONVERGED",
                "OPTICAL_NYQUIST_CHECK_FAILED",
            }

        def retry_failed_precision(
            items,
            results,
            *,
            progress_start: float | None = None,
            progress_stop: float | None = None,
        ):
            if str(request.precision).strip().lower() == "high":
                return 0
            retry_indices: list[int] = []
            retry_requests: list[SimulationRequest] = []
            for index, ((sample_id, feature_values, changed_project, sim_request), result) in enumerate(
                zip(items, results)
            ):
                if quality_accepts(result) or not precision_retry_allowed(result):
                    continue
                high_request = sim_request.model_copy(
                    update={
                        "precision": "high",
                        "options": dataset_simulation_options(
                            changed_project, precision="high"
                        ),
                    }
                )
                retry_indices.append(index)
                retry_requests.append(high_request)
            if not retry_requests:
                return 0
            if progress is not None and progress_start is not None:
                progress.update(
                    progress_start,
                    "dataset.precision_retry",
                    0,
                    len(retry_requests),
                )
            retry_results = run_batch(
                retry_requests,
                progress_start=progress_start,
                progress_stop=progress_stop,
            )
            for index, high_request, result in zip(
                retry_indices, retry_requests, retry_results
            ):
                sample_id, feature_values, changed_project, _ = items[index]
                items[index] = (
                    sample_id,
                    feature_values,
                    changed_project,
                    high_request,
                )
                results[index] = result
            if progress is not None and progress_stop is not None:
                progress.update(
                    progress_stop,
                    "dataset.precision_retry.completed",
                    len(retry_results),
                    len(retry_requests),
                )
            return len(retry_results)

        if progress is not None:
            progress.update(0.02, "dataset.preparing", 0, max(1, len(prepared)))

        results = run_batch(
            [item[3] for item in prepared], progress_start=0.02, progress_stop=0.56
        )
        high_precision_retry_count = retry_failed_precision(
            prepared,
            results,
            progress_start=0.56,
            progress_stop=0.70,
        )
        if progress is not None:
            progress.update(
                0.70,
                "dataset.quality_checked",
                len(results),
                len(prepared),
            )
        quality_valid_count = sum(quality_accepts(result) for result in results)

        # A fixed number of attempts can leave too few usable labels when the
        # design space contains numerically invalid combinations.  Supplement the
        # plan until the requested valid count is reached, with a hard 3x cap.
        while (
            quality_valid_count < target_valid_count
            and len(prepared) < max_attempts
            and (cancellation is None or not cancellation.is_cancelled)
        ):
            supplement_count = min(
                max_attempts - len(prepared),
                target_valid_count - quality_valid_count,
            )
            supplement_plan = create_sampling_plan(
                request.parameters,
                supplement_count,
                request.sampling_method,
                request.random_seed + len(prepared),
            )
            supplement = prepare_attempts(supplement_plan.values, len(prepared))
            attempt_start = len(prepared)
            attempt_stop = attempt_start + len(supplement)
            supplement_progress_start = 0.70 + 0.20 * (
                attempt_start / max_attempts
            )
            supplement_progress_stop = 0.70 + 0.20 * (
                attempt_stop / max_attempts
            )
            retry_progress_start = supplement_progress_start + 0.65 * (
                supplement_progress_stop - supplement_progress_start
            )
            supplement_results = run_batch(
                [item[3] for item in supplement],
                progress_start=supplement_progress_start,
                progress_stop=retry_progress_start,
            )
            high_precision_retry_count += retry_failed_precision(
                supplement,
                supplement_results,
                progress_start=retry_progress_start,
                progress_stop=supplement_progress_stop,
            )
            prepared.extend(supplement)
            results.extend(supplement_results)
            if progress is not None:
                progress.update(
                    supplement_progress_stop,
                    "dataset.quality_checked",
                    len(results),
                    len(prepared),
                )
            quality_valid_count = sum(quality_accepts(result) for result in results)

        if progress is not None:
            progress.update(0.90, "dataset.simulation.completed", len(results), len(prepared))

        # Persist records only after the expensive optical batch.  This keeps
        # disk I/O single-threaded and deterministic while the actual simulations
        # run in parallel.
        processed = min(len(prepared), len(results))
        for index, ((sample_id, feature_values, changed_project, sim_request), result) in enumerate(
            zip(prepared, results)
        ):
            if isinstance(result, Exception):
                failed += 1
                message = str(result) or type(result).__name__
                record = SampleRecord(
                    sample_id=sample_id,
                    request_id=sim_request.request_id,
                    project_fingerprint=changed_project.fingerprint,
                    feature_values=feature_values,
                    target_values={},
                    valid=False,
                    failure_code="SIMULATION_EXCEPTION",
                    failure_message=message,
                    engine_name=str(request.engine or "unknown"),
                    engine_version="unknown",
                    elapsed_ms=0.0,
                    converged=False,
                    metadata={
                        "source": "dataset_generation",
                        "algorithm_version": "unknown",
                        "project_fingerprint": changed_project.fingerprint,
                        "random_seed": sim_request.random_seed,
                        "precision": sim_request.precision,
                        "simulation_exception": type(result).__name__,
                    },
                )
                self.store.append_sample(dataset_id, record.model_dump())
                if progress is not None:
                    progress.update(
                        0.90 + 0.09 * (index + 1) / max(processed, 1),
                        "dataset.writing",
                        index + 1,
                        processed,
                    )
                continue
            engine_name = result.engine_name
            engine_version = result.engine_version
            targets = extract_target_values(result.metrics, canonical_targets)
            physics_features: dict[str, float] = {}
            physics_feature_error = ""
            if include_coupling_physics:
                try:
                    physics_features = derive_coupling_physics_features(
                        changed_project, result.metrics
                    )
                    feature_values.update(physics_features)
                except Exception as exc:
                    physics_feature_error = str(exc) or type(exc).__name__
            quality = evaluate_simulation_quality(
                result, targets, canonical_targets, require_converged=True
            )
            valid = quality.accepted and not physics_feature_error
            if valid:
                valid_ids.append(sample_id)
            else:
                failed += 1
            failure_code = (
                "PHYSICS_FEATURE_ERROR"
                if physics_feature_error
                else (result.errors[0].code if result.errors else quality.code)
            )
            failure_message = (
                physics_feature_error
                if physics_feature_error
                else (result.errors[0].message if result.errors else quality.message)
            )
            record = SampleRecord(
                sample_id=sample_id,
                request_id=sim_request.request_id,
                project_fingerprint=changed_project.fingerprint,
                feature_values=feature_values,
                target_values=targets,
                valid=valid,
                failure_code=failure_code,
                failure_message=failure_message,
                engine_name=result.engine_name,
                engine_version=result.engine_version,
                elapsed_ms=result.elapsed_ms,
                converged=result.converged,
                metadata={
                    "source": result.metadata.get("source", "unknown"),
                    "simulation_quality_checks": quality.checks,
                    "algorithm_version": getattr(result, "algorithm_version", "unknown"),
                    "project_fingerprint": getattr(
                        result, "project_fingerprint", changed_project.fingerprint
                    ),
                    "random_seed": sim_request.random_seed,
                    "precision": sim_request.precision,
                    "coupling_physics_features": physics_features,
                },
            )
            self.store.append_sample(dataset_id, record.model_dump())
            if progress is not None:
                progress.update(
                    0.90 + 0.09 * (index + 1) / max(processed, 1),
                    "dataset.writing",
                    index + 1,
                    processed,
                )

        # A cancellation can intentionally stop the batch before every request
        # returns.  Count unprocessed samples as failed only for a non-cancelled
        # run so the manifest remains honest.
        if cancellation is None or not cancellation.is_cancelled:
            failed += max(0, len(prepared) - processed)

        train_ids, validation_ids, test_ids = split_ids(
            valid_ids,
            request.train_ratio,
            request.validation_ratio,
            request.random_seed,
        )
        if cancellation is not None and cancellation.is_cancelled:
            status = "cancelled"
        elif failed:
            status = "partial"
        else:
            status = "completed"
        requested_feature_names = [p.name for p in request.parameters]
        requested_feature_paths = [p.path for p in request.parameters]
        requested_feature_units = [p.unit for p in request.parameters]
        if include_coupling_physics:
            for feature_path in PHYSICS_RESIDUAL_FEATURE_PATHS:
                if feature_path not in requested_feature_paths:
                    requested_feature_names.append(feature_path)
                    requested_feature_paths.append(feature_path)
                    requested_feature_units.append(
                        PHYSICS_RESIDUAL_FEATURE_UNITS[feature_path]
                    )
        manifest = DatasetManifest(
            dataset_id=dataset_id,
            dataset_name=request.dataset_name,
            engine_name=engine_name,
            engine_version=engine_version,
            feature_schema_version=FEATURE_SCHEMA_VERSION,
            created_at=datetime.now(timezone.utc).isoformat(),
            sample_count=len(prepared),
            valid_sample_count=len(valid_ids),
            failed_sample_count=failed,
            feature_names=requested_feature_names,
            feature_paths=requested_feature_paths,
            feature_units=requested_feature_units,
            target_names=canonical_targets,
            train_ids=train_ids,
            validation_ids=validation_ids,
            test_ids=test_ids,
            random_seed=request.random_seed,
            source_project_fingerprint=request.base_project.fingerprint,
            status=status,
            variable_scheme_id=request.variable_scheme_id,
            lens_count=request.lens_count,
            design_variable_paths=list(request.design_variable_paths or requested_feature_paths[:len(request.parameters)]),
            physics_feature_paths=list(PHYSICS_RESIDUAL_FEATURE_PATHS) if include_coupling_physics else [],
            metadata={
                "sampling_method": request.sampling_method,
                "coupling_physics_features": list(PHYSICS_RESIDUAL_FEATURE_PATHS)
                if include_coupling_physics
                else [],
                "analytic_coupling_baseline": bool(include_coupling_physics),
                "source_project": request.base_project.model_dump(),
                "batch_workers": max(1, int(max_workers)),
                "target_valid_sample_count": target_valid_count,
                "max_sample_attempts": max_attempts,
                "high_precision_retry_count": high_precision_retry_count,
                "valid_sample_target_reached": len(valid_ids) >= target_valid_count,
                "variable_scheme_id": request.variable_scheme_id,
                "lens_count": request.lens_count,
                "design_variable_paths": list(request.design_variable_paths or requested_feature_paths[:len(request.parameters)]),
                "physics_feature_paths": list(PHYSICS_RESIDUAL_FEATURE_PATHS) if include_coupling_physics else [],
            },
        )
        self.store.save_manifest(manifest)
        if progress is not None:
            progress.update(1.0, "dataset.completed", processed, max(1, len(prepared)))
        return manifest



def target_to_analyses(targets) -> list[str]:

    return analyses_for_metrics(canonical_metric_name(target) for target in targets)


def extract_target_values(metrics: dict, targets) -> dict[str, float]:
    values: dict[str, float] = {}
    for target in paired_coupling_targets(targets):
        canonical = canonical_metric_name(target)
        value = (
            coupling_loss_db(metrics)
            if canonical == "coupling_loss_db"
            else read_metric(metrics, canonical)
        )
        if value is not None:
            values[canonical] = float(value)
    return values


def apply_parameter_changes(project: ProjectSnapshot, changes) -> ProjectSnapshot:
    data = project.model_dump()

    for change in changes:
        _set_path(data, change.path, change.value)

    data["fingerprint"] = _changed_fingerprint(project.fingerprint, changes)
    return ProjectSnapshot.model_validate(data)


_DATASET_PRECISION_PROFILES: dict[str, dict[str, object]] = {
    # Dataset generation is a repeated-label workload.  Keep the preview
    # profile genuinely cheap; the previous implementation always used the
    # balanced 257 grid and then ran sampling convergence as well.
    "preview": {
        "pupil_sample_count": 9,
        "grid_size": 65,
        "output_grid_size": 129,
        "zero_padding_factor": 1.5,
        "precision_mode": "preview",
        "convergence_enabled": False,
        "sampling_convergence_enabled": False,
        "auto_expand_max_steps": 1,
    },
    "standard": {
        "pupil_sample_count": 25,
        # Use the same propagation grid as the rescue path up front.  The
        # former 129 -> 257 profile caused most otherwise usable samples to
        # fail the conservative Nyquist gate and be recomputed at high
        # precision.  One 257 -> 513 run is cheaper than two runs, while the
        # expensive sampling-convergence repeat remains disabled here.
        "grid_size": 257,
        "output_grid_size": 513,
        "zero_padding_factor": 2.0,
        "precision_mode": "balanced",
        "convergence_enabled": False,
        "sampling_convergence_enabled": False,
        "auto_expand_max_steps": 1,
    },
    "high": {
        "pupil_sample_count": 49,
        "grid_size": 257,
        "output_grid_size": 513,
        "zero_padding_factor": 2.0,
        "precision_mode": "quantitative",
        "convergence_enabled": True,
        "sampling_convergence_enabled": True,
        "sampling_convergence_grid_sizes": (257, 513),
        "auto_expand_max_steps": 3,
    },
}


def dataset_simulation_options(
    project: ProjectSnapshot, precision: str = "standard"
) -> dict:
    options = {"source": "dataset_generation"}

    if project.receiver is not None:
        precision_key = str(precision or "standard").strip().lower()
        if precision_key == "test":
            precision_key = "preview"
        profile = dict(
            _DATASET_PRECISION_PROFILES.get(
                precision_key, _DATASET_PRECISION_PROFILES["standard"]
            )
        )
        options["hybrid"] = {
            "wavelength_nm": project.source.wavelength_nm,
            "pupil_radius_mm": project.pupil_radius_mm,
            "output_extent_x_mm": 0.024,
            "output_extent_y_mm": 0.024,
            "propagation_model": "scaled_fresnel",
            "auto_expand_output": True,
            # Training consumes scalar metrics and derived physics features,
            # not the large propagated-field arrays used by result viewers.
            "include_diagnostic_arrays": False,
            "result_array_policy": "none",
            "high_precision_coupling_enabled": True,
            "mode_field_diameter_x_um": project.receiver.mode_field_diameter_x_um,
            "mode_field_diameter_y_um": project.receiver.mode_field_diameter_y_um,
            "offset_x_mm": project.receiver.offset_x_mm,
            "offset_y_mm": project.receiver.offset_y_mm,
            "axial_offset_z_mm": project.receiver.axial_offset_z_mm,
            "tilt_x_deg": project.receiver.tilt_x_deg,
            "tilt_y_deg": project.receiver.tilt_y_deg,
            "receiver_na_x": project.receiver.na_x,
            "receiver_na_y": project.receiver.na_y,
            "mode_model": project.receiver.mode_model,
            "fiber_core_radius_um": None if project.receiver.core_diameter_um is None else project.receiver.core_diameter_um / 2.0,
            "fiber_n_core": project.receiver.core_refractive_index,
            "fiber_n_clad": project.receiver.cladding_refractive_index,
            "receiver_medium_refractive_index": project.receiver.outside_refractive_index,
            "fiber_facet_transmission_override": project.receiver.endface_transmission,
            "fiber_length_m": project.receiver.fiber_length_m,
            "fiber_attenuation_db_per_km": project.receiver.attenuation_db_per_km,
            "fiber_connector_loss_db": project.receiver.connector_loss_db,
            "include_breakdown": True,
            **profile,
        }

    return options


def _set_path(data: dict, path: str, value) -> None:
    parts = _parse_path(path)
    current = data

    for part in parts[:-1]:
        current = current[part]

    current[parts[-1]] = value


def _parse_path(path: str) -> list:
    parts: list = []

    for chunk in str(path).split("."):
        if "[" in chunk and chunk.endswith("]"):
            name, index = chunk[:-1].split("[", 1)
            parts.append(name)
            parts.append(int(index))
        elif chunk.isdigit():
            parts.append(int(chunk))
        else:
            parts.append(chunk)

    return parts


def _changed_fingerprint(base_fingerprint: str, changes) -> str:
    payload = [
        {"path": change.path, "value": change.value, "unit": change.unit}
        for change in changes
    ]
    digest = hashlib.sha1(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:12]
    return f"{base_fingerprint}:{digest}"

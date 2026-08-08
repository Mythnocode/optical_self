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
)
from shared_contracts.versions import FEATURE_SCHEMA_VERSION
from shared_ports.simulation import SimulationPort


class DatasetGenerator:
    def __init__(self, simulation_port: SimulationPort, store):
        self.simulation_port = simulation_port
        self.store = store
        self.resolver = FeatureResolver()

    def generate(self, request, cancellation=None, progress=None):
        dataset_id = "dataset-" + uuid.uuid4().hex[:12]
        plan = create_sampling_plan(request.parameters, request.sample_count, request.sampling_method, request.random_seed)
        canonical_targets = [canonical_metric_name(target) for target in request.targets]
        include_coupling_physics = (
            request.base_project.receiver is not None
            and bool({"coupling_efficiency", "coupling_loss_db"} & set(canonical_targets))
        )
        valid_ids = []
        failed = 0
        engine_name = "unknown"
        engine_version = "unknown"
        for index, sample_id in enumerate(plan.sample_ids):
            if cancellation is not None and cancellation.is_cancelled:
                break
            feature_values = {}
            changes = []
            for p, value in zip(request.parameters, plan.values[index]):
                feature_values[p.path] = float(value)
                changes.append(self.resolver.create_change(p.path, float(value), p.unit))
            changed_project = apply_parameter_changes(request.base_project, changes)
            sim_request = SimulationRequest(
                request_id="%s-%s" % (dataset_id, sample_id),
                project=changed_project,
                analyses=target_to_analyses(canonical_targets),
                parameter_changes=[],
                precision=request.precision,
                random_seed=request.random_seed + index,
                engine=request.engine,
                options=dataset_simulation_options(changed_project),
            )
            sample_started = time.perf_counter()
            try:
                result = self.simulation_port.evaluate(
                    sim_request, cancellation, progress
                )
            except Exception as exc:
                
                
                
                failed += 1
                message = str(exc) or type(exc).__name__
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
                    elapsed_ms=(time.perf_counter() - sample_started) * 1000.0,
                    converged=False,
                    metadata={
                        "source": "dataset_generation",
                        "algorithm_version": "unknown",
                        "project_fingerprint": changed_project.fingerprint,
                        "random_seed": sim_request.random_seed,
                        "precision": sim_request.precision,
                        "simulation_exception": type(exc).__name__,
                    },
                )
                self.store.append_sample(dataset_id, record.model_dump())
                if progress is not None:
                    progress.update(
                        (index + 1) / len(plan.sample_ids),
                        "dataset.simulation",
                        index + 1,
                        len(plan.sample_ids),
                    )
                continue
            engine_name = result.engine_name
            engine_version = result.engine_version
            targets = extract_target_values(result.metrics, canonical_targets)
            physics_features = {}
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
                    "project_fingerprint": getattr(result, "project_fingerprint", changed_project.fingerprint),
                    "random_seed": sim_request.random_seed,
                    "precision": sim_request.precision,
                    "coupling_physics_features": physics_features,
                },
            )
            self.store.append_sample(dataset_id, record.model_dump())
            if progress is not None:
                progress.update((index + 1) / len(plan.sample_ids), "dataset.simulation", index + 1, len(plan.sample_ids))
        train_ids, validation_ids, test_ids = split_ids(valid_ids, request.train_ratio, request.validation_ratio, request.random_seed)
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
            sample_count=len(plan.sample_ids),
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
            metadata={
                "sampling_method": request.sampling_method,
                "coupling_physics_features": list(PHYSICS_RESIDUAL_FEATURE_PATHS)
                if include_coupling_physics
                else [],
                "analytic_coupling_baseline": bool(include_coupling_physics),
                "source_project": request.base_project.model_dump(),
            },
        )
        self.store.save_manifest(manifest)
        return manifest



def target_to_analyses(targets) -> list[str]:

    return analyses_for_metrics(canonical_metric_name(target) for target in targets)


def extract_target_values(metrics: dict, targets) -> dict[str, float]:
    values: dict[str, float] = {}
    for target in targets:
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


def dataset_simulation_options(project: ProjectSnapshot) -> dict:
    options = {"source": "dataset_generation"}

    if project.receiver is not None:
        options["hybrid"] = {
            "wavelength_nm": project.source.wavelength_nm,
            "pupil_radius_mm": project.pupil_radius_mm,
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

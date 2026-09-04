

from __future__ import annotations

import uuid
import csv
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from datetime import datetime, timezone

from machine_learning.datasets.records import SampleRecord
from machine_learning.datasets.splitter import split_ids
from machine_learning.datasets.storage import FileDatasetStore
from optical_runtime import create_optical_simulation_engine
from shared_contracts.datasets import DatasetManifest
from shared_contracts.versions import FEATURE_SCHEMA_VERSION

from backend.optical_ml_app.application.ports import (
    DatasetRegistryPort,
    EngineResolverPort,
    TaskManagerPort,
)


MAX_SURFACES = 20

MATERIAL_NAME_ALIASES = {
    "AIR": "AIR",
    "VACUUM": "AIR",
    "BK7": "N-BK7",
    "N-BK7": "N-BK7",
    "SF11": "N-SF11",
    "N-SF11": "N-SF11",
}

SUPPORTED_HEADLESS_MATERIALS = {"AIR", "N-BK7", "N-SF11"}


# ==========================================================================


# ==========================================================================

def _float_or_zero(value: Any) -> float:
    if value is None:
        return 0.0
    return float(value)


def _normalize_material_name(name: Any) -> str:
    if name is None:
        return "AIR"

    key = str(name).strip().upper()
    if not key:
        return "AIR"

    normalized = MATERIAL_NAME_ALIASES.get(key, key)

    if normalized not in SUPPORTED_HEADLESS_MATERIALS:
        raise ValueError(
            "Unsupported material for native OpticalSimulationEngine dataset generation: "
            f"{name}. Supported materials are: "
            f"{', '.join(sorted(SUPPORTED_HEADLESS_MATERIALS))}."
        )

    return normalized


def _project_from_sample(sample: dict[str, Any]) -> SimpleNamespace:
    project_data = sample.get("project", sample)

    surfaces_data = project_data.get("surfaces", [])
    surfaces = tuple(_surface_from_dict(item) for item in surfaces_data)

    source_data = project_data.get("source", {})
    receiver_data = project_data.get("receiver", source_data)
    stop_data = project_data.get("stop", {})
    fibre_mfd_mm = float(project_data.get("fibre_mfd_mm", 0.01))

    return SimpleNamespace(
        fingerprint=project_data.get(
            "fingerprint",
            f"headless-dataset-project-{uuid.uuid4().hex[:8]}",
        ),
        surfaces=surfaces,
        object_distance_mm=float(project_data.get("object_distance_mm", 100.0)),
        image_distance_mm=float(project_data.get("image_distance_mm", 150.0)),
        # ProjectSnapshot stores the active wavelength under source.wavelength_nm.
        # Falling back directly to 1550 nm here silently generated a dataset with a
        # different physical wavelength from the simulation page.
        wavelength_nm=float(project_data.get("wavelength_nm", source_data.get("wavelength_nm", 1550.0))),
        wavelength_f_nm=float(project_data.get("wavelength_f_nm", 486.1)),
        wavelength_c_nm=float(project_data.get("wavelength_c_nm", 656.3)),
        pupil_radius_mm=float(project_data.get("pupil_radius_mm", 2.0)),
        fibre_mfd_mm=fibre_mfd_mm,
        stop=SimpleNamespace(
            position_mm=float(stop_data.get("position_mm", 0.0)),
            radius_mm=float(stop_data.get("radius_mm", 2.0)),
        ),
        include_interface_losses=bool(
            project_data.get("include_interface_losses", True)
        ),
        include_internal_absorption=bool(
            project_data.get("include_internal_absorption", True)
        ),
        source=SimpleNamespace(
            wavelength_nm=float(source_data.get("wavelength_nm", project_data.get("wavelength_nm", 1550.0))),
            source_type=str(source_data.get("source_type", "gaussian")),
            object_na=float(source_data.get("object_na", 0.10)),
            object_na_x=float(source_data.get("object_na_x", source_data.get("object_na_y", source_data.get("object_na", 0.10)))),
            object_na_y=float(source_data.get("object_na_y", source_data.get("object_na_z", source_data.get("object_na", 0.10)))),
            field_x_deg=float(source_data.get("field_x_deg", source_data.get("field_y_deg", 0.0))),
            field_y_deg=float(source_data.get("field_y_deg", source_data.get("field_z_deg", 0.0))),
            waist_x_mm=float(source_data.get("waist_x_mm", source_data.get("waist_y_mm", 0.0))),
            waist_y_mm=float(source_data.get("waist_y_mm", source_data.get("waist_z_mm", 0.0))),
            beam_quality_m2=float(source_data.get("beam_quality_m2", source_data.get("m2", 1.0))),
            power_value=source_data.get("power_value"),
            power_unit=source_data.get("power_unit"),
            axial_offset_z_mm=float(source_data.get("axial_offset_z_mm", source_data.get("axial_offset_mm", 0.0))),
            offset_x_mm=float(source_data.get("offset_x_mm", source_data.get("offset_y_mm", 0.0))),
            offset_y_mm=float(source_data.get("offset_y_mm", source_data.get("offset_z_mm", 0.0))),
        ),
        receiver=SimpleNamespace(
            na_x=float(receiver_data.get("na_x", receiver_data.get("na_y", receiver_data.get("receiver_na_x", receiver_data.get("receiver_na_y", receiver_data.get("receiver_na", 0.12)))))),
            na_y=float(receiver_data.get("na_y", receiver_data.get("na_z", receiver_data.get("receiver_na_y", receiver_data.get("receiver_na_z", receiver_data.get("receiver_na", 0.12)))))),
            mode_field_diameter_x_um=float(receiver_data.get("mode_field_diameter_x_um", receiver_data.get("mode_field_diameter_y_um", receiver_data.get("mode_field_diameter_um", fibre_mfd_mm * 1000.0)))),
            mode_field_diameter_y_um=float(receiver_data.get("mode_field_diameter_y_um", receiver_data.get("mode_field_diameter_z_um", receiver_data.get("mode_field_diameter_um", fibre_mfd_mm * 1000.0)))),
            offset_x_mm=float(receiver_data.get("offset_x_mm", receiver_data.get("offset_y_mm", source_data.get("offset_x_mm", source_data.get("offset_y_mm", 0.0))))),
            offset_y_mm=float(receiver_data.get("offset_y_mm", receiver_data.get("offset_z_mm", source_data.get("offset_y_mm", source_data.get("offset_z_mm", 0.0))))),
            axial_offset_z_mm=float(receiver_data.get("axial_offset_z_mm", receiver_data.get("axial_offset_mm", source_data.get("axial_offset_z_mm", source_data.get("axial_offset_mm", 0.0))))),
            tilt_x_deg=float(receiver_data.get("tilt_x_deg", receiver_data.get("tilt_y_deg", 0.0))),
            tilt_y_deg=float(receiver_data.get("tilt_y_deg", receiver_data.get("tilt_z_deg", 0.0))),
        ),
        analysis_settings=project_data.get("analysis_settings", {}),
    )


def _options_from_sample(sample: dict[str, Any], project: Any) -> dict[str, Any]:
    options = dict(sample.get("options", {}) or {})
    hybrid_options = dict(options.get("hybrid", {}) or {})
    receiver = getattr(project, "receiver", SimpleNamespace())

    hybrid_options.setdefault("wavelength_nm", getattr(project, "wavelength_nm", 1550.0))
    hybrid_options.setdefault("pupil_radius_mm", getattr(project, "pupil_radius_mm", 2.0))
    hybrid_options.setdefault("mode_field_diameter_x_um", getattr(receiver, "mode_field_diameter_x_um", 10.0))
    hybrid_options.setdefault("mode_field_diameter_y_um", getattr(receiver, "mode_field_diameter_y_um", 10.0))
    hybrid_options.setdefault("offset_x_mm", getattr(receiver, "offset_x_mm", 0.0))
    hybrid_options.setdefault("offset_y_mm", getattr(receiver, "offset_y_mm", 0.0))
    hybrid_options.setdefault("axial_offset_z_mm", getattr(receiver, "axial_offset_z_mm", 0.0))
    hybrid_options.setdefault("tilt_x_deg", getattr(receiver, "tilt_x_deg", 0.0))
    hybrid_options.setdefault("tilt_y_deg", getattr(receiver, "tilt_y_deg", 0.0))
    hybrid_options.setdefault("include_breakdown", True)

    options["hybrid"] = hybrid_options
    return options


def _surface_from_dict(data: dict[str, Any]) -> SimpleNamespace:
    material_name = _normalize_material_name(
        data.get(
            "after_material_name",
            data.get("material_after", data.get("material", "AIR")),
        )
    )

    return SimpleNamespace(
        radius_mm=data.get("radius_mm"),
        distance_to_next_mm=data.get(
            "distance_to_next_mm",
            data.get("thickness_mm", 0.0),
        ),
        after_material_name=material_name,
        clear_aperture_mm=data.get("clear_aperture_mm", 10.0),
        conic=data.get("conic", 0.0),
        asphere_a2=float(data.get("asphere_a2", data.get("a2", data.get("A2", 0.0))) or 0.0),
        asphere_coefficients=tuple(
            data.get("asphere_coefficients", data.get("asphere_coeffs", ())) or ()
        ),
        user_transmission=data.get("user_transmission", 1.0),
    )


def _validate_project_surfaces(project: Any) -> None:
    surfaces = tuple(getattr(project, "surfaces", ()))
    surface_count = len(surfaces)

    if surface_count == 0:
        raise ValueError("coupling dataset requires at least one real surface")

    if surface_count > MAX_SURFACES:
        raise ValueError(
            f"surface_count exceeds MAX_SURFACES: "
            f"{surface_count} > {MAX_SURFACES}"
        )

    last_surface = surfaces[-1]
    last_distance = getattr(last_surface, "distance_to_next_mm", 0.0)

    if float(last_distance or 0.0) != 0.0:
        raise ValueError(
            "last surface distance_to_next_mm must be 0.0; "
            "use image_distance_mm to set image plane distance"
        )


def _validate_headless_coupling_result(
    result: Any,
    sample_index: int,
) -> None:
    status = getattr(result, "status", "failed")
    converged = bool(getattr(result, "converged", False))
    metrics = getattr(result, "metrics", {}) or {}
    metadata = getattr(result, "metadata", {}) or {}

    coupling_efficiency = metrics.get("coupling_efficiency")

    if status != "completed":
        errors = getattr(result, "errors", []) or []
        raise ValueError(
            f"Headless coupling simulation failed for sample {sample_index}: "
            f"{errors}"
        )

    if not converged:
        raise ValueError(
            f"Headless coupling simulation did not converge for sample "
            f"{sample_index}"
        )

    if metadata.get("not_physical_result") is True:
        raise ValueError(
            f"Headless coupling simulation returned non-physical result "
            f"for sample {sample_index}"
        )

    if coupling_efficiency is None:
        raise ValueError(f"Missing coupling_efficiency for sample {sample_index}")

    coupling_efficiency_float = float(coupling_efficiency)

    if not 0.0 <= coupling_efficiency_float <= 1.0:
        raise ValueError(
            f"Invalid coupling_efficiency for sample {sample_index}: "
            f"{coupling_efficiency_float}"
        )


def _training_feature_values(project: Any) -> dict[str, float]:
    features: dict[str, float] = {}
    surfaces = tuple(getattr(project, "surfaces", ()) or ())
    for index in range(MAX_SURFACES):
        surface = surfaces[index] if index < len(surfaces) else None
        prefix = f"surface.{index}"
        features[f"{prefix}.active"] = 1.0 if surface is not None else 0.0
        features[f"{prefix}.radius_mm"] = _float_or_zero(getattr(surface, "radius_mm", None))
        features[f"{prefix}.distance_to_next_mm"] = _float_or_zero(getattr(surface, "distance_to_next_mm", None))
        features[f"{prefix}.clear_aperture_mm"] = _float_or_zero(getattr(surface, "clear_aperture_mm", None))
        features[f"{prefix}.conic"] = _float_or_zero(getattr(surface, "conic", None))

    receiver = getattr(project, "receiver", SimpleNamespace())
    features["object_distance_mm"] = _float_or_zero(getattr(project, "object_distance_mm", None))
    features["image_distance_mm"] = _float_or_zero(getattr(project, "image_distance_mm", None))
    features["pupil_radius_mm"] = _float_or_zero(getattr(project, "pupil_radius_mm", None))
    features["wavelength_nm"] = _float_or_zero(getattr(project, "wavelength_nm", None))
    features["receiver.offset_x_mm"] = _float_or_zero(getattr(receiver, "offset_x_mm", None))
    features["receiver.offset_y_mm"] = _float_or_zero(getattr(receiver, "offset_y_mm", None))
    features["receiver.axial_offset_z_mm"] = _float_or_zero(getattr(receiver, "axial_offset_z_mm", None))
    return features


def _training_feature_spec() -> list[tuple[str, str, str]]:
    fields = (
        ("active", "1"),
        ("radius_mm", "mm"),
        ("distance_to_next_mm", "mm"),
        ("clear_aperture_mm", "mm"),
        ("conic", "1"),
    )
    spec: list[tuple[str, str, str]] = []
    for index in range(MAX_SURFACES):
        for field, unit in fields:
            path = f"surface.{index}.{field}"
            spec.append((path, path, unit))
    spec.extend(
        [
            ("object_distance_mm", "object_distance_mm", "mm"),
            ("image_distance_mm", "image_distance_mm", "mm"),
            ("pupil_radius_mm", "pupil_radius_mm", "mm"),
            ("wavelength_nm", "wavelength_nm", "nm"),
            ("receiver.offset_x_mm", "receiver.offset_x_mm", "mm"),
            ("receiver.offset_y_mm", "receiver.offset_y_mm", "mm"),
            ("receiver.axial_offset_z_mm", "receiver.axial_offset_z_mm", "mm"),
        ]
    )
    return spec


def _training_sample_record(
    *,
    sample_id: str,
    request_id: str,
    project: Any,
    result: Any,
    valid: bool,
) -> dict[str, Any]:
    errors = list(getattr(result, "errors", []) or [])
    first_error = errors[0] if errors else None
    target_values = {}
    if "coupling_efficiency" in (getattr(result, "metrics", {}) or {}):
        target_values["coupling_efficiency"] = float(result.metrics["coupling_efficiency"])

    record = SampleRecord(
        sample_id=sample_id,
        request_id=request_id,
        project_fingerprint=str(getattr(project, "fingerprint", "")),
        feature_values=_training_feature_values(project),
        target_values=target_values,
        valid=valid,
        failure_code=str(getattr(first_error, "code", "")) if first_error else "",
        failure_message=str(getattr(first_error, "message", "")) if first_error else "",
        engine_name=str(getattr(result, "engine_name", "unknown")),
        engine_version=str(getattr(result, "engine_version", "unknown")),
        elapsed_ms=float(getattr(result, "elapsed_ms", 0.0) or 0.0),
        converged=bool(getattr(result, "converged", False)),
        metadata={"source": "headless_coupling_dataset"},
    )
    return record.model_dump()


def _build_headless_training_manifest(
    *,
    dataset_id: str,
    dataset_name: str,
    random_seed: int,
    source_project_fingerprint: str,
    engine_name: str,
    engine_version: str,
    sample_count: int,
    valid_sample_ids: list[str],
    failed_sample_count: int,
    training_samples: list[dict[str, Any]],
    train_ratio: float,
    validation_ratio: float,
    store: Any,
) -> DatasetManifest:

    if store is None:
        raise RuntimeError("dataset_store is required to publish a headless training dataset")

    training_dir = store.dataset_dir(dataset_id)
    (training_dir / "samples.jsonl").write_text("", encoding="utf-8")

    for sample in training_samples:
        store.append_sample(dataset_id, sample)

    train_ids, validation_ids, test_ids = split_ids(
        valid_sample_ids,
        train_ratio,
        validation_ratio,
        random_seed,
    )
    feature_spec = _training_feature_spec()
    status = "completed" if failed_sample_count == 0 else "partial"
    manifest = DatasetManifest(
        dataset_id=dataset_id,
        dataset_name=dataset_name,
        engine_name=engine_name,
        engine_version=engine_version,
        feature_schema_version=FEATURE_SCHEMA_VERSION,
        created_at=datetime.now(timezone.utc).isoformat(),
        sample_count=sample_count,
        valid_sample_count=len(valid_sample_ids),
        failed_sample_count=failed_sample_count,
        feature_names=[name for _, name, _ in feature_spec],
        feature_paths=[path for path, _, _ in feature_spec],
        feature_units=[unit for _, _, unit in feature_spec],
        target_names=["coupling_efficiency"],
        train_ids=train_ids,
        validation_ids=validation_ids,
        test_ids=test_ids,
        random_seed=random_seed,
        source_project_fingerprint=source_project_fingerprint,
        status=status,
        metadata={"dataset_type": "headless_lens20_coupling"},
    )
    store.save_manifest(manifest)
    return manifest


# ==========================================================================

# ==========================================================================

class NativeCouplingDatasetWriter:
    def __init__(self, output_dir: Path, dataset_id: str):
        self.output_dir = Path(output_dir)
        self.dataset_id = dataset_id
        self.records: list[dict[str, Any]] = []
        self.created_at = datetime.now(timezone.utc).isoformat()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.samples_jsonl_path = self.output_dir / "samples.jsonl"
        self.samples_flat_csv_path = self.output_dir / "samples_flat.csv"
        self.manifest_path = self.output_dir / "manifest.json"
        self.samples_jsonl_path.write_text("", encoding="utf-8")

    def append_sample(self, sample_id: str, project: Any, result: Any) -> None:
        coupling_efficiency = float(result.metrics["coupling_efficiency"])
        record = {
            "sample_id": sample_id,
            "surface_count": len(tuple(getattr(project, "surfaces", ()) or ())),
            "features": self._features(project),
            "target": {"coupling_efficiency": coupling_efficiency},
            "simulation": {
                "status": getattr(result, "status", "unknown"),
                "converged": bool(getattr(result, "converged", False)),
                "not_physical_result": bool((getattr(result, "metadata", {}) or {}).get("not_physical_result", False)),
                "engine_name": getattr(result, "engine_name", "unknown"),
                "engine_version": getattr(result, "engine_version", "unknown"),
                "elapsed_ms": float(getattr(result, "elapsed_ms", 0.0) or 0.0),
                "warnings": list(getattr(result, "warnings", []) or []),
            },
        }
        self.records.append(record)
        with self.samples_jsonl_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def write_manifest(self) -> None:
        manifest = {
            "dataset_id": self.dataset_id,
            "dataset_type": "headless_lens20_coupling",
            "target_column": "coupling_efficiency",
            "target_physical_name": "fiber coupling efficiency",
            "max_surfaces": MAX_SURFACES,
            "sample_count": len(self.records),
            "created_at": self.created_at,
            "samples_jsonl_path": str(self.samples_jsonl_path),
            "samples_flat_csv_path": str(self.samples_flat_csv_path),
        }
        self.manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._write_flat_csv()

    def _write_flat_csv(self) -> None:
        feature_columns: list[str] = []
        for record in self.records:
            for key in record["features"]:
                if key not in feature_columns:
                    feature_columns.append(key)

        columns = ["sample_id"] + feature_columns + ["coupling_efficiency", "status", "converged"]
        with self.samples_flat_csv_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            for record in self.records:
                row = {
                    "sample_id": record["sample_id"],
                    "coupling_efficiency": record["target"]["coupling_efficiency"],
                    "status": record["simulation"]["status"],
                    "converged": record["simulation"]["converged"],
                }
                row.update(record["features"])
                writer.writerow(row)

    def _features(self, project: Any) -> dict[str, float]:
        features: dict[str, float] = {}
        surfaces = tuple(getattr(project, "surfaces", ()) or ())

        for index in range(1, MAX_SURFACES + 1):
            surface = surfaces[index - 1] if index <= len(surfaces) else None
            prefix = f"surface_{index}"
            features[f"{prefix}_active"] = 1.0 if surface is not None else 0.0
            features[f"{prefix}_radius_mm"] = _float_or_zero(getattr(surface, "radius_mm", None))
            features[f"{prefix}_distance_to_next_mm"] = _float_or_zero(getattr(surface, "distance_to_next_mm", None))
            features[f"{prefix}_clear_aperture_mm"] = _float_or_zero(getattr(surface, "clear_aperture_mm", None))
            features[f"{prefix}_conic"] = _float_or_zero(getattr(surface, "conic", None))

        receiver = getattr(project, "receiver", SimpleNamespace())
        features["object_distance_mm"] = _float_or_zero(getattr(project, "object_distance_mm", None))
        features["image_distance_mm"] = _float_or_zero(getattr(project, "image_distance_mm", None))
        features["pupil_radius_mm"] = _float_or_zero(getattr(project, "pupil_radius_mm", None))
        features["wavelength_nm"] = _float_or_zero(getattr(project, "wavelength_nm", None))
        features["receiver_offset_x_mm"] = _float_or_zero(getattr(receiver, "offset_x_mm", None))
        features["receiver_offset_y_mm"] = _float_or_zero(getattr(receiver, "offset_y_mm", None))
        features["receiver_axial_offset_z_mm"] = _float_or_zero(getattr(receiver, "axial_offset_z_mm", None))
        return features


def _run_headless_coupling_dataset_task(
    context: Any,
    payload: dict[str, Any],
    dataset_id: str,
    samples: list[dict[str, Any]],
    output_dir: str,
    dataset_root: str | None,
):
    engine = context.get_or_create_resource(
        "optical_engine", create_optical_simulation_engine
    )
    store = FileDatasetStore(Path(dataset_root)) if dataset_root else None
    output_path = Path(output_dir)
    writer = NativeCouplingDatasetWriter(output_path, dataset_id)

    training_samples: list[dict[str, Any]] = []
    valid_sample_ids: list[str] = []
    failed_sample_count = 0
    engine_name = "unknown"
    engine_version = "unknown"
    source_fingerprint = ""

    for index, sample in enumerate(samples):
        if context.cancellation.is_cancelled:
            break
        project = _project_from_sample(sample)
        _validate_project_surfaces(project)

        sample_id = f"sample_{index:06d}"
        request = SimpleNamespace(
            request_id=f"{dataset_id}-{index:06d}",
            project=project,
            analyses=("coupling",),
            options=_options_from_sample(sample, project),
            precision=payload.get("precision", "standard"),
            random_seed=payload.get("random_seed", 42),
        )

        result = engine.evaluate(request)
        _validate_headless_coupling_result(result, sample_index=index)

        writer.append_sample(sample_id=sample_id, project=project, result=result)
        engine_name = getattr(result, "engine_name", "unknown")
        engine_version = getattr(result, "engine_version", "unknown")
        source_fingerprint = source_fingerprint or str(getattr(project, "fingerprint", ""))
        valid = getattr(result, "status", "failed") == "completed" and bool(getattr(result, "converged", False))
        if valid:
            valid_sample_ids.append(sample_id)
        else:
            failed_sample_count += 1
        training_samples.append(
            _training_sample_record(
                sample_id=sample_id,
                request_id=request.request_id,
                project=project,
                result=result,
                valid=valid,
            )
        )

    writer.write_manifest()
    training_manifest = _build_headless_training_manifest(
        dataset_id=dataset_id,
        dataset_name=payload.get("dataset_name", dataset_id),
        random_seed=int(payload.get("random_seed", 42)),
        source_project_fingerprint=source_fingerprint,
        engine_name=engine_name,
        engine_version=engine_version,
        sample_count=len(samples),
        valid_sample_ids=valid_sample_ids,
        failed_sample_count=failed_sample_count,
        training_samples=training_samples,
        train_ratio=float(payload.get("train_ratio", 0.7)),
        validation_ratio=float(payload.get("validation_ratio", 0.15)),
        store=store,
    )
    training_dir = store.dataset_dir(dataset_id) if store is not None else output_path

    return {
        "dataset_id": dataset_id,
        "training_dataset_id": training_manifest.dataset_id,
        "dataset_type": "headless_lens20_coupling",
        "target_column": "coupling_efficiency",
        "max_surfaces": MAX_SURFACES,
        "sample_count": len(samples),
        "output_dir": str(output_path),
        "manifest_path": str(output_path / "manifest.json"),
        "samples_jsonl_path": str(output_path / "samples.jsonl"),
        "samples_flat_csv_path": str(output_path / "samples_flat.csv"),
        "training_manifest_path": str(training_dir / "manifest.json"),
        "training_samples_jsonl_path": str(training_dir / "samples.jsonl"),
        "training_samples_flat_csv_path": str(training_dir / "samples_flat.csv"),
    }


# ==========================================================================

# ==========================================================================

class HeadlessDatasetApplicationService:
    def __init__(
        self,
        task_manager: TaskManagerPort,
        engine_registry: EngineResolverPort,
        dataset_store: Any | None = None,
        dataset_registry: DatasetRegistryPort | None = None,
    ):
        self.task_manager = task_manager
        self.engine_registry = engine_registry
        self.dataset_store = dataset_store
        self.dataset_registry = dataset_registry

    def submit_coupling_dataset(self, payload: dict[str, Any]) -> str:
        dataset_id = str(
            payload.get("dataset_id")
            or f"headless_lens20_coupling_{uuid.uuid4().hex[:8]}"
        )

        samples = payload.get("samples")
        if samples is None:
            samples = [payload]

        if not isinstance(samples, list) or not samples:
            raise ValueError("samples must be a non-empty list")

        output_dir = Path(
            payload.get(
                "output_dir",
                f"data/datasets/{dataset_id}",
            )
        )

        return self.task_manager.submit(
            "headless_dataset",
            _run_headless_coupling_dataset_task,
            payload,
            dataset_id,
            samples,
            str(output_dir),
            str(self.dataset_store.root) if self.dataset_store is not None else None,
            on_result=lambda result: _apply_headless_registry_side_effect(
                result, self.dataset_registry, self.dataset_store,
            ),
        )

    def _resolve_headless_engine(self) -> Any:
        return self.engine_registry.resolve("headless")


def _apply_headless_registry_side_effect(result, dataset_registry, store):

    if dataset_registry is not None and store is not None:
        manifest = store.load_manifest(result["dataset_id"])
        dataset_registry.register(manifest)

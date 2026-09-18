from __future__ import annotations

from machine_learning.datasets.generator import DatasetGenerator
from frontend_pyside.features.machine_learning.dataset_configuration import (
    build_dataset_parameters,
)
from shared_contracts.datasets import DatasetGenerationRequest, ParameterDefinition
from shared_contracts.project import (
    ProjectSnapshot,
    ReceiverSnapshot,
    SourceSnapshot,
    SurfaceSnapshot,
)
from shared_contracts.simulation import SimulationResult


class _MemoryStore:
    def __init__(self) -> None:
        self.samples: list[dict] = []
        self.manifest = None

    def append_sample(self, dataset_id: str, record: dict) -> None:
        self.samples.append(record)

    def save_manifest(self, manifest) -> None:
        self.manifest = manifest


class _PrecisionAwarePort:
    def __init__(self, *, valid_high_ids: set[str] | None = None) -> None:
        self.calls: list[str] = []
        self.valid_high_ids = valid_high_ids

    def batch_evaluate(self, requests, **kwargs):
        results = []
        for request in requests:
            self.calls.append(request.precision)
            valid = request.precision == "high" and (
                self.valid_high_ids is None
                or request.request_id.rsplit("-", 1)[-1]
                in self.valid_high_ids
            )
            results.append(
                SimulationResult(
                    request_id=request.request_id,
                    project_fingerprint=request.project.fingerprint,
                    engine_name="fake",
                    engine_version="1",
                    algorithm_version="fake",
                    status="completed",
                    metrics={
                        "coupling_efficiency": 0.8,
                        "coupling_loss_db": 0.969,
                        "coupling_propagation_energy_pass": True,
                        "coupling_propagation_edge_pass": True,
                        "coupling_propagation_nyquist_pass": valid,
                    },
                    converged=True,
                )
            )
        return results


class _CaptureProgress:
    def __init__(self) -> None:
        self.values: list[tuple[float, str]] = []

    def update(self, progress, stage, *_args) -> None:
        self.values.append((float(progress), str(stage)))


class _EnergyFailurePort(_PrecisionAwarePort):
    def batch_evaluate(self, requests, **kwargs):
        results = super().batch_evaluate(requests, **kwargs)
        for result in results:
            result.metrics["coupling_propagation_energy_pass"] = False
            result.metrics["coupling_propagation_nyquist_pass"] = True
        return results


def _project() -> ProjectSnapshot:
    return ProjectSnapshot(
        project_id="dataset-fallback-test",
        surfaces=[
            SurfaceSnapshot(
                index=0,
                surface_type="spherical",
                radius_mm=5.0,
                distance_to_next_mm=3.0,
                material_before="AIR",
                material_after="N-BK7",
                clear_aperture_mm=3.0,
            )
        ],
        object_distance_mm=18.0,
        image_distance_mm=9.0,
        pupil_radius_mm=3.0,
        source=SourceSnapshot(wavelength_nm=780.0),
        receiver=ReceiverSnapshot(),
        fingerprint="dataset-fallback-test",
    )


def _request(sample_count: int = 2) -> DatasetGenerationRequest:
    return DatasetGenerationRequest(
        dataset_name="fallback-test",
        base_project=_project(),
        parameters=[
            ParameterDefinition(
                name="radius",
                path="surfaces[0].radius_mm",
                unit="mm",
                lower_bound=4.9,
                upper_bound=5.1,
            )
        ],
        targets=["coupling_efficiency"],
        sample_count=sample_count,
        precision="standard",
        include_derived_physics_features=False,
    )


def test_failed_standard_samples_are_retried_at_high_precision() -> None:
    port = _PrecisionAwarePort()
    store = _MemoryStore()

    manifest = DatasetGenerator(port, store).generate(_request(), max_workers=1)

    assert manifest.sample_count == 2
    assert manifest.valid_sample_count == 2
    assert manifest.failed_sample_count == 0
    assert manifest.metadata["high_precision_retry_count"] == 2
    assert port.calls == ["standard", "standard", "high", "high"]
    assert all(record["valid"] for record in store.samples)
    assert all(record["metadata"]["precision"] == "high" for record in store.samples)


def test_precision_retry_does_not_leave_dataset_progress_at_seventy_percent() -> None:
    port = _PrecisionAwarePort()
    store = _MemoryStore()
    progress = _CaptureProgress()

    DatasetGenerator(port, store).generate(
        _request(), progress=progress, max_workers=1
    )

    values = [value for value, _stage in progress.values]
    stages = [stage for _value, stage in progress.values]
    assert max(values) == 1.0
    assert any(0.56 <= value < 0.70 for value in values)
    assert any(stage == "dataset.precision_retry.completed" for stage in stages)
    assert any(value > 0.70 for value in values)


def test_physical_quality_failures_are_not_retried_at_high_precision() -> None:
    port = _EnergyFailurePort()
    store = _MemoryStore()

    manifest = DatasetGenerator(port, store).generate(_request(), max_workers=1)

    assert manifest.metadata["high_precision_retry_count"] == 0
    assert port.calls == ["standard"] * 6


def test_dataset_supplements_attempts_until_the_three_times_cap() -> None:
    port = _PrecisionAwarePort(valid_high_ids={"000003"})
    store = _MemoryStore()

    manifest = DatasetGenerator(port, store).generate(_request(), max_workers=1)

    assert manifest.sample_count == 6
    assert manifest.valid_sample_count == 1
    assert manifest.failed_sample_count == 5
    assert manifest.metadata["max_sample_attempts"] == 6
    assert manifest.metadata["valid_sample_target_reached"] is False


def test_default_design_parameter_spread_is_five_percent() -> None:
    parameters = build_dataset_parameters(
        {
            "surfaces": [
                {
                    "surface_type": "spherical",
                    "radius_mm": 10.0,
                    "distance_to_next_mm": 3.0,
                    "material_after": "N-BK7",
                    "clear_aperture_mm": 2.0,
                }
            ]
        },
        explicit_paths=[
            "surfaces[0].radius_mm",
            "surfaces[0].distance_to_next_mm",
        ],
    )

    assert (parameters[0]["lower_bound"], parameters[0]["upper_bound"]) == (9.5, 10.5)
    assert (parameters[1]["lower_bound"], parameters[1]["upper_bound"]) == (2.85, 3.15)

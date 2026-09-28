"""End-to-end dataset generation benchmark through the real DatasetGenerator.

Runs the full generation pipeline (sampling -> native ray trace -> wave
propagation -> coupling labels -> quality gates -> manifest/samples on disk)
against a temporary dataset store.

Usage: py -3.12 tools/benchmark_dataset_generation.py [sample_count]
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    import shiboken6  # noqa: F401
except Exception:
    pass
try:
    from frontend_pyside.core.shiboken_guard import harden_shiboken_signature_hook

    harden_shiboken_signature_hook()
except Exception:
    pass

from frontend_pyside.api.payloads import serialize_project
from frontend_pyside.features.simulation.form_state import SimulationFormState
from frontend_pyside.state.project_context import default_project
from machine_learning.datasets.variable_schemes import resolve_variable_scheme
from shared_contracts.datasets import DatasetGenerationRequest, ParameterDefinition
from shared_contracts.project import ProjectSnapshot


def build_request(sample_count: int) -> DatasetGenerationRequest:
    payload = serialize_project(default_project(), SimulationFormState())
    snapshot = ProjectSnapshot.model_validate(payload)
    scheme = resolve_variable_scheme(payload, lens_count=4, include_conic=True)
    parameters = []
    bounds_scale = 0.02
    for path in scheme.design_variable_paths:
        parts = path.replace("]", "").replace("[", ".").split(".")
        value = payload
        for part in parts:
            value = value[int(part)] if part.isdigit() else value.get(part)
        center = float(value)
        if path.endswith(("conic",)):
            lower, upper = center - 0.05, center + 0.05
        else:
            lower = center * (1.0 - bounds_scale)
            upper = center * (1.0 + bounds_scale)
        parameters.append(
            ParameterDefinition(
                name=path,
                path=path,
                unit="mm" if path.endswith("mm") else "-",
                lower_bound=lower,
                upper_bound=upper,
            )
        )
    return DatasetGenerationRequest(
        dataset_name="native_benchmark",
        base_project=snapshot,
        parameters=parameters,
        targets=["coupling_loss_db"],
        sample_count=sample_count,
        sampling_method="latin_hypercube",
        train_ratio=0.7,
        validation_ratio=0.15,
        test_ratio=0.15,
        random_seed=99,
        precision="standard",
        dataset_layout="tabular",
    )


def main() -> None:
    from machine_learning.datasets.generator import DatasetGenerator
    from machine_learning.datasets.storage import FileDatasetStore
    from optical_runtime import create_optical_simulation_engine

    sample_count = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    request = build_request(sample_count)
    store_root = Path(tempfile.mkdtemp(prefix="native_ds_bench_"))
    try:
        generator = DatasetGenerator(create_optical_simulation_engine(), FileDatasetStore(store_root))
        start = time.perf_counter()
        manifest = generator.generate(request)
        elapsed = time.perf_counter() - start
        print(f"样本数目标 {sample_count}，尝试 {manifest.sample_count} 个")
        print(f"有效 {manifest.valid_sample_count}，失败 {manifest.failed_sample_count}，状态 {manifest.status}")
        print(f"总耗时 {elapsed:.2f}s  ({elapsed / max(manifest.sample_count, 1) * 1000.0:.0f} ms/样本)")
        print(f"batch_workers = {manifest.metadata.get('batch_workers')}")
    finally:
        shutil.rmtree(store_root, ignore_errors=True)


if __name__ == "__main__":
    main()

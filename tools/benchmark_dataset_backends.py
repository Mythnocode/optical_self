"""Measure actual dataset labels and trace calls; retain all evidence on disk.

Run each backend in a fresh process, e.g. ... compact 8 / native 8 / python 8.
The trace wrapper is benchmark-only and never changes production settings.
"""
from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.benchmark_dataset_generation import build_request
from machine_learning.datasets.generator import DatasetGenerator
from machine_learning.datasets.storage import FileDatasetStore
from optical_runtime import create_optical_simulation_engine
from optical_core.physics.geometric.solvers import batch_raytrace, native_trace, compact_batch_raytrace


def main():
    mode = sys.argv[1]
    if mode not in {"compact", "native", "python", "production"}:
        raise ValueError("backend must be compact, native, python, or production")
    count = int(sys.argv[2]) if len(sys.argv) > 2 else 8
    uncoated = len(sys.argv) > 3 and sys.argv[3] == "uncoated"
    os.environ["OPTICAL_NATIVE"] = "0" if mode in {"compact", "python"} else "1"
    counters = {"native": 0, "compact": 0, "python": 0}
    timings = {key: 0.0 for key in counters}
    original_trace = batch_raytrace.trace_ray_batch

    def measured_native(*args, **kwargs):
        start = time.perf_counter()
        result = original_native(*args, **kwargs)
        counters["native"] += 1
        timings["native"] += time.perf_counter() - start
        return result

    def measured_compact(*args, **kwargs):
        start = time.perf_counter()
        result = original_compact(*args, **kwargs)
        counters["compact"] += 1
        timings["compact"] += time.perf_counter() - start
        return result

    def measured_trace(system, rays, options, **kwargs):
        if mode != "production":
            options = replace(options, output_level="planes" if mode == "compact" else "full")
        before = sum(counters.values())
        start = time.perf_counter()
        result = original_trace(system, rays, options, **kwargs)
        if sum(counters.values()) == before:
            counters["python"] += 1
            timings["python"] += time.perf_counter() - start
        return result

    original_native = native_trace.trace_ray_batch_native
    original_compact = compact_batch_raytrace.trace_ray_batch_compact
    native_trace.trace_ray_batch_native = measured_native
    compact_batch_raytrace.trace_ray_batch_compact = measured_compact
    batch_raytrace.trace_ray_batch = measured_trace
    output = ROOT / "tests/golden/dataset-backends" / f"{mode}-{count}{'-uncoated' if uncoated else ''}"
    output.mkdir(parents=True, exist_ok=True)
    store = FileDatasetStore(output / "datasets")
    engine = create_optical_simulation_engine()
    generator = DatasetGenerator(engine, store)
    request = build_request(count)
    if uncoated:
        request = request.model_copy(update={"base_project": request.base_project.model_copy(update={
            "surfaces": [surface.model_copy(update={"coating_layers": []}) for surface in request.base_project.surfaces]
        })})
    start = time.perf_counter()
    manifest = generator.generate(request)
    report = {
        "backend": mode, "native_available": native_trace.native_available(),
        "elapsed_seconds": time.perf_counter() - start,
        "trace_calls": counters, "trace_seconds": timings,
        "manifest": manifest.model_dump(mode="json"),
        "samples": list(store.iter_samples(manifest.dataset_id)),
    }
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: report[key] for key in report if key not in {"manifest", "samples"}}), flush=True)
    print(f"valid={manifest.valid_sample_count}, failed={manifest.failed_sample_count}, attempts={manifest.sample_count}", flush=True)


if __name__ == "__main__":
    main()

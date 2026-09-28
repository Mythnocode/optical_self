"""Profile one dataset-style sample simulation to locate hotspots.

Builds the same SimulationRequest the dataset generator produces for a
coupling-loss target (hybrid pipeline, dataset precision profile) and runs it
under cProfile.
"""

from __future__ import annotations

import cProfile
import io
import pstats
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# dateutil→six 导入会触发 shiboken 签名钩子的已知崩溃，先加固（幂等）。
try:
    import shiboken6  # noqa: F401  (激活 shibokensupport)
except Exception:
    shiboken6 = None
try:
    from frontend_pyside.core.shiboken_guard import harden_shiboken_signature_hook

    harden_shiboken_signature_hook()
except Exception:
    pass

from frontend_pyside.api.payloads import serialize_project
from frontend_pyside.features.simulation.form_state import SimulationFormState
from frontend_pyside.state.project_context import default_project
from machine_learning.features.coupling_physics import paired_coupling_targets
from optical_runtime import create_optical_simulation_engine
from shared_contracts.metrics import analyses_for_metrics, canonical_metric_name
from shared_contracts.simulation import SimulationRequest


def _read_path(data: dict, path: str):
    current = data
    for part in str(path).replace("]", "").replace("[", ".").split("."):
        if isinstance(current, list):
            current = current[int(part)]
        else:
            current = current.get(part) if isinstance(current, dict) else getattr(current, part, None)
        if current is None:
            return None
    return current


def build_request(sample_index: int = 0) -> SimulationRequest:
    from machine_learning.datasets.generator import (
        apply_parameter_changes,
        dataset_simulation_options,
    )
    from machine_learning.datasets.variable_schemes import resolve_variable_scheme
    from machine_learning.features.resolver import FeatureResolver
    from shared_contracts.project import ProjectSnapshot

    project = default_project()
    payload = serialize_project(project, SimulationFormState())
    snapshot = ProjectSnapshot.model_validate(payload)
    scheme = resolve_variable_scheme(payload, lens_count=4, include_conic=True)
    targets = paired_coupling_targets(["coupling_loss_db"])
    options = dataset_simulation_options(snapshot, precision="standard")
    # Perturb parameters exactly like a dataset sample would, so caches miss.
    import numpy as np

    resolver = FeatureResolver()
    rng = np.random.default_rng(1000 + sample_index)
    # Gentle radius-only perturbation: keeps the system valid (full trace +
    # wave coupling run) while changing the fingerprint so caches miss.
    changes = []
    for path in scheme.design_variable_paths:
        if path.endswith("radius_mm"):
            current = _read_path(snapshot.model_dump(), path)
            if not current:
                continue
            changes.append(
                resolver.create_change(
                    path, float(current) * (1.0 + 0.001 * float(rng.standard_normal())), "mm"
                )
            )
    if not changes:
        raise SystemExit("no radius variables to perturb")
    perturbed = apply_parameter_changes(snapshot, changes)
    return SimulationRequest(
        request_id=f"profile-sample-{sample_index}",
        project=perturbed,
        analyses=analyses_for_metrics(canonical_metric_name(t) for t in targets),
        parameter_changes=[],
        precision="standard",
        random_seed=1234 + sample_index,
        engine=None,
        options=options,
    )


def main() -> None:
    request = build_request()
    engine = create_optical_simulation_engine()

    # Warm-up (caches, imports) then timed runs.
    result = engine.evaluate(request)
    print("status:", result.status)
    if result.errors:
        print("errors:", result.errors[:3])
    coupling_keys = [k for k in result.metrics if "coupling" in k]
    print("coupling metrics:", {k: result.metrics[k] for k in coupling_keys[:6]})

    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    start = time.perf_counter()
    for index in range(runs):
        request = build_request(index)
        engine.evaluate(request)
    serial = time.perf_counter() - start
    print(f"\n{runs} samples in {serial:.3f}s  ({serial / runs * 1000.0:.1f} ms/sample)")

    profiler = cProfile.Profile()
    profiler.enable()
    engine.evaluate(build_request(100))
    profiler.disable()
    stream = io.StringIO()
    stats = pstats.Stats(profiler, stream=stream)
    stats.sort_stats("cumulative").print_stats(28)
    text = stream.getvalue()
    # Trim the noisy header lines.
    lines = text.splitlines()
    keep = False
    for line in lines:
        if "ncalls" in line:
            keep = True
        if keep:
            print(line)


if __name__ == "__main__":
    main()

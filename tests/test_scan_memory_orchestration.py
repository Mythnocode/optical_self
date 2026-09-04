from __future__ import annotations

from shared_contracts.scan import ScanRequest
from shared_contracts.simulation import SimulationRequest, SimulationResult

from backend.optical_ml_app.application import scan_service


class _Cancellation:
    is_cancelled = False


class _Progress:
    def __init__(self) -> None:
        self.updates = []

    def update(self, *args, **kwargs) -> None:
        self.updates.append((args, kwargs))


class _FakeEngine:
    def __init__(self) -> None:
        self.batch_sizes: list[int] = []
        self.clear_calls = 0

    def batch_evaluate(self, requests, **kwargs):
        items = list(requests)
        self.batch_sizes.append(len(items))
        return [
            SimulationResult.model_construct(
                request_id=str(req.request_id),
                project_fingerprint="test",
                engine_name="fake",
                engine_version="1",
                algorithm_version="1",
                status="completed",
                metrics={"coupling_efficiency": 0.5},
                arrays={},
                warnings=[],
                errors=[],
                elapsed_ms=1.0,
                converged=True,
                metadata={},
            )
            for req in items
        ]

    def clear_prepared_coupling_cache(self) -> None:
        self.clear_calls += 1


class _Context:
    def __init__(self, engine: _FakeEngine) -> None:
        self.engine = engine
        self.cancellation = _Cancellation()
        self.progress = _Progress()

    def get_or_create_resource(self, name, factory):
        assert name == "optical_engine"
        return self.engine


def test_scan_reduces_dense_results_in_bounded_chunks_and_clears_prepared_cache(monkeypatch):
    engine = _FakeEngine()
    context = _Context(engine)
    monkeypatch.setattr(scan_service, "configured_batch_worker_count", lambda: 1)

    base = SimulationRequest.model_construct(
        request_id="base",
        project=None,
        analyses=["coupling"],
        parameter_changes=[],
        precision="standard",
        random_seed=42,
        engine="headless",
        options={},
    )
    scan = ScanRequest.model_construct(
        request_id="scan",
        mode="line_1d",
        parameters=[
            type("P", (), {
                "path": "receiver.offset_x_mm", "label": "X", "unit": "mm",
                "start": -0.01, "stop": 0.01, "points": 5,
            })()
        ],
        response_metrics=["coupling_efficiency"],
        analyses=["coupling"],
        nominal_changes=[],
        precision="standard",
        random_seed=42,
        options={},
    )

    result = scan_service._run_scan_task(context, base, scan)

    assert result.status == "completed"
    assert engine.batch_sizes == [2, 2, 1]
    # Dense prepared modes/evaluations must not survive across scan chunks.
    assert engine.clear_calls == len(engine.batch_sizes)
    assert result.metadata["completed_points"] == 5
    assert result.response_values["coupling_efficiency"] == [0.5] * 5

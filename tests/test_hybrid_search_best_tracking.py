from __future__ import annotations

from types import SimpleNamespace

import numpy as np

import machine_learning.optimization.hybrid_search as hybrid


def test_powell_refine_returns_best_evaluated_point_when_solver_stops_on_worse_point(monkeypatch):
    visited = [
        (np.array([0.0]), 0.8),
        (np.array([1.0]), 0.2),
        (np.array([2.0]), 0.6),
    ]

    def fake_minimize(fun, x0, **kwargs):
        for point, expected in visited:
            assert fun(point) == expected
        # Simulate Powell/maxfev terminating on a point worse than one it has
        # already evaluated.  This is the failure mode seen in the real optical
        # optimization acceptance run.
        return SimpleNamespace(x=np.array([2.0]), fun=0.6)

    monkeypatch.setattr(hybrid, "minimize", fake_minimize)

    def objective(x):
        return {0.0: 0.8, 1.0: 0.2, 2.0: 0.6}[float(x[0])]

    x, value, evaluations = hybrid.powell_refine(
        objective,
        np.array([0.0]),
        [(-3.0, 3.0)],
        max_evaluations=3,
        tolerance=1e-4,
    )

    assert evaluations == 3
    assert value == 0.2
    assert np.allclose(x, [1.0])

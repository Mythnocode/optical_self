from types import SimpleNamespace
from optical_runtime.system_tolerance import _quality_rejection_reason


def _result(**metrics):
    return SimpleNamespace(status="completed", converged=True, metrics=metrics)


def test_tolerance_accepts_conservative_nyquist_warning_when_actual_sampling_converges():
    result = _result(
        coupling_propagation_energy_pass=True,
        coupling_propagation_edge_pass=True,
        coupling_propagation_nyquist_pass=False,
        sampling_convergence_pass=True,
    )
    assert _quality_rejection_reason(result, {}) is None


def test_tolerance_still_rejects_nyquist_failure_without_convergence_evidence():
    result = _result(
        coupling_propagation_energy_pass=True,
        coupling_propagation_edge_pass=True,
        coupling_propagation_nyquist_pass=False,
        sampling_convergence_pass=False,
    )
    assert "nyquist" in (_quality_rejection_reason(result, {}) or "")


def test_tolerance_never_waives_energy_failure():
    result = _result(
        coupling_propagation_energy_pass=False,
        coupling_propagation_edge_pass=True,
        coupling_propagation_nyquist_pass=False,
        sampling_convergence_pass=True,
    )
    assert "energy" in (_quality_rejection_reason(result, {}) or "")

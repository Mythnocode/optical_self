from math import log10

from machine_learning.datasets.generator import extract_target_values
from machine_learning.features.coupling_physics import (
    paired_coupling_targets,
    resolve_stored_target,
)


def test_paired_coupling_targets_keep_efficiency_and_loss_together():
    assert paired_coupling_targets(["coupling_efficiency"]) == [
        "coupling_efficiency",
        "coupling_loss_db",
    ]
    assert paired_coupling_targets(["coupling_loss_db"]) == [
        "coupling_loss_db",
        "coupling_efficiency",
    ]
    assert paired_coupling_targets(["rms_spot_radius_um"]) == ["rms_spot_radius_um"]


def test_extract_target_values_stores_db_loss_when_only_efficiency_is_requested():
    values = extract_target_values({"coupling_efficiency": 0.5}, ["coupling_efficiency"])
    assert values["coupling_efficiency"] == 0.5
    assert abs(values["coupling_loss_db"] - (-10.0 * log10(0.5))) < 1e-12


def test_resolve_stored_target_derives_loss_db_from_efficiency():
    eta = 0.42
    loss = resolve_stored_target({"coupling_efficiency": eta}, "coupling_loss_db")
    assert abs(loss - (-10.0 * log10(eta))) < 1e-12
    recovered = resolve_stored_target({"coupling_loss_db": loss}, "coupling_efficiency")
    assert abs(recovered - eta) < 1e-12


def test_resolve_stored_target_explains_missing_column():
    try:
        resolve_stored_target({"rms_spot_radius_um": 3.1}, "coupling_loss_db")
    except ValueError as exc:
        assert "coupling_loss_db" in str(exc)
        assert "rms_spot_radius_um" in str(exc)
    else:
        raise AssertionError("expected ValueError for missing coupling target")

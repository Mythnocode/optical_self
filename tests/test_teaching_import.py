from __future__ import annotations

import math

import pytest

from frontend_pyside.features.simulation.teaching_import import (
    receiver_payload_from_teaching_snapshot,
    resolve_teaching_snapshot,
    surfaces_from_teaching_lenses,
    teaching_lenses_from_snapshot,
)


def _sample_snapshot() -> dict:
    return {
        "source": "unified_teaching_workbench",
        "wavelength_nm": 780.0,
        "receiver_mode_radius_um": 2.5,
        "receiver_na": 0.13,
        "nodes": [
            {
                "id": "l1",
                "kind": "lens",
                "x": 0.0,
                "params": {"focal_mm": 25.0},
            },
            {
                "id": "l2",
                "kind": "lens",
                "x": 40.0,
                "params": {"focal_mm": 30.0},
            },
            {
                "id": "fiber1",
                "kind": "fiber",
                "x": 120.0,
                "params": {
                    "offset_x_um": 12.0,
                    "offset_y_um": -8.0,
                    "offset_z_um": 5.0,
                    "pitch_mrad": 2.0,
                    "yaw_mrad": -1.5,
                },
            },
        ],
    }


def test_resolve_teaching_snapshot_prefers_profile_teaching_snapshot():
    snapshot = _sample_snapshot()
    profile = {
        "active_snapshot_source": "simulation",
        "teaching_snapshot": snapshot,
    }
    resolved = resolve_teaching_snapshot(profile, "")
    assert resolved is snapshot


def test_receiver_payload_maps_fiber_five_axis():
    payload = receiver_payload_from_teaching_snapshot(_sample_snapshot())
    assert payload["mode_field_diameter_x_um"] == 5.0
    assert payload["offset_x_mm"] == pytest.approx(12.0e-3)
    assert payload["offset_y_mm"] == pytest.approx(-8.0e-3)
    assert payload["axial_offset_z_mm"] == pytest.approx(5.0e-3)
    assert payload["tilt_x_deg"] == pytest.approx(math.degrees(2.0e-3))
    assert payload["tilt_y_deg"] == pytest.approx(math.degrees(-1.5e-3))


def test_surfaces_from_teaching_lenses_builds_lens_pairs():
    lenses = teaching_lenses_from_snapshot(_sample_snapshot())
    surfaces = surfaces_from_teaching_lenses(lenses)
    assert len(surfaces) == 4
    assert surfaces[0].name.endswith("前表面")
    assert surfaces[1].name.endswith("后表面")


def test_simulation_page_auto_imports_pending_teaching_snapshot():
    pytest.importorskip("joblib")
    from PySide6.QtWidgets import QApplication

    from frontend_pyside.app.bootstrap import create_app_context
    from frontend_pyside.features.simulation.page import SimulationPage

    app = QApplication.instance() or QApplication([])
    context = create_app_context()
    snapshot = _sample_snapshot()
    context.project.update_research_profile(
        teaching_snapshot=snapshot,
        shared_snapshot=snapshot,
        active_snapshot_source="teaching",
        pending_teaching_import=True,
    )
    page = SimulationPage(context)
    page.show()
    app.processEvents()

    page.on_activated()
    app.processEvents()

    assert page.context.project.research_profile.get("pending_teaching_import") is False
    assert len(page.context.project.project.surfaces) == 4
    assert page.context.project.project.wavelength_nm == 780.0
    page.close()

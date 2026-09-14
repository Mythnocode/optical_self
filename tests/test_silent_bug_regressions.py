"""Regression coverage for failures that previously looked like success."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.optical_ml_app.application.headless_dataset_service import (
    _options_from_sample,
    _project_from_sample,
)


ROOT = Path(__file__).resolve().parents[1]


def test_dataset_uses_one_canonical_source_wavelength() -> None:
    sample = {
        "project": {
            "wavelength_nm": 1550.0,  # stale legacy field
            "source": {"wavelength_nm": 780.0},
        },
        "options": {"hybrid": {"wavelength_nm": 1550.0}},
    }
    project = _project_from_sample(sample)
    options = _options_from_sample(sample, project)

    assert project.wavelength_nm == 780.0
    assert project.source.wavelength_nm == 780.0
    assert options["hybrid"]["wavelength_nm"] == 780.0


def test_dataset_rejects_missing_or_invalid_wavelength() -> None:
    with pytest.raises(ValueError, match="source.wavelength_nm"):
        _project_from_sample({"project": {"source": {}}})

    with pytest.raises(ValueError, match="finite positive"):
        _project_from_sample({"project": {"source": {"wavelength_nm": 0}}})


def test_canvas_source_text_documents_reconnect_and_incremental_fixes() -> None:
    scene = (ROOT / "frontend_pyside/features/canvas/scene.py").read_text(encoding="utf-8")
    refresh = (ROOT / "frontend_pyside/features/canvas/refresh_controller.py").read_text(encoding="utf-8")

    assert '("source", "view", "tool", "data")' in scene
    assert "self._repair_workflow_edges()" in scene
    assert 'active["rows"], active.get("requested")' in refresh
    assert "status or '返回状态缺失'" in refresh
    assert not (ROOT / "frontend_pyside/app/canvas_shell.py").exists()

from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

from PySide6.QtWidgets import QApplication

from frontend_pyside.shared.plotting.canvas import PlotCanvas
from frontend_pyside.shared.plotting.engineering_views import (
    build_before_after_comparison,
    build_candidate_comparison,
    build_correlation_view,
)
import numpy as np

def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_before_after_uses_frozen_submission_baseline_and_hides_internal_paths():
    result = {
        "best_metrics": {"coupling_efficiency": 0.93, "system_efficiency": 0.82},
        "best_variables": {"surfaces[1].distance_to_next_mm": 12.5},
        "metadata": {
            "baseline_metrics": {"coupling_efficiency": 0.75, "system_efficiency": 0.70}
        },
    }
    # Simulate a mutable current system that has already been changed after the task.
    payload = build_before_after_comparison(
        result, {"coupling_efficiency": 0.93, "system_efficiency": 0.82}
    )
    assert payload["before"]["coupling_efficiency"] == 75.0
    assert payload["after"]["coupling_efficiency"] == 93.0
    assert payload["before"]["label"] == "当前系统"
    assert payload["after"]["label"] == "最佳候选"
    assert all("surfaces[" not in row["name"] for row in payload["parameters"])


def test_legacy_scheme_candidate_labels_are_normalized_to_candidates():
    result = {
        "candidates": [
            {"label": "方案A", "formal_efficiency": 0.91},
            {"label": "方案B", "formal_efficiency": 0.89},
            {"label": "方案C", "formal_efficiency": 0.86},
        ]
    }
    payload = build_candidate_comparison(result, efficiency=True)
    labels = [row["label"] for row in payload["candidates"]]
    assert labels == ["候选1", "候选2", "候选3"]
    assert not any("方案" in label for label in labels)


def test_correlation_heatmap_uses_horizontal_multiline_labels_and_safe_margins():
    _app()
    result = {
        "best_variables": {
            "receiver.axial_offset_z_mm": 0.0,
            "surfaces[1].distance_to_next_mm": 1.0,
            "surfaces[3].distance_to_next_mm": 2.0,
        },
        "history": [
            {
                "variables": {
                    "receiver.axial_offset_z_mm": 0.001 * i,
                    "surfaces[1].distance_to_next_mm": 1.0 + 0.01 * i,
                    "surfaces[3].distance_to_next_mm": 2.0 - 0.005 * i,
                },
                "merit": 0.7 + 0.01 * i,
            }
            for i in range(8)
        ],
    }
    payload = build_correlation_view(result)
    canvas = PlotCanvas()
    canvas.resize(980, 500)
    canvas.set_plot(payload)
    try:
        canvas.draw()
        ax = canvas.figure.axes[0]
        rotations = [float(label.get_rotation()) for label in ax.get_xticklabels()]
        assert rotations and all(abs(value) < 1e-6 for value in rotations)
        assert canvas.figure.subplotpars.bottom >= 0.19
        assert canvas.figure.subplotpars.left >= 0.27
    finally:
        canvas.close()

def test_validation_scatter_keeps_diagnostics_outside_plot_and_uses_available_width():
    _app()
    canvas = PlotCanvas()
    canvas.resize(1000, 430)
    canvas.set_plot({
        "kind": "validation_scatter",
        "actual": [0.55, 0.62, 0.71, 0.79, 0.86, 0.90],
        "predicted": [0.57, 0.61, 0.70, 0.80, 0.84, 0.89],
        "title": "预测值与真实值",
        "x_label": "真实值",
        "y_label": "预测值",
        "simple": False,
    })
    try:
        canvas.draw()
        ax = canvas.figure.axes[0]
        assert str(ax.get_aspect()) == "auto"
        text = " ".join(item.get_text() for item in ax.texts)
        assert "R²" not in text and "MAE" not in text and "P95" not in text
        assert canvas.figure.subplotpars.bottom >= 0.24
    finally:
        canvas.close()


def test_categorical_energy_flow_labels_are_not_diagonal():
    _app()
    canvas = PlotCanvas()
    canvas.resize(900, 430)
    canvas.set_plot({
        "kind": "energy_flow",
        "labels": ["输入功率", "透镜组传输", "端面透射", "模式耦合"],
        "cumulative": [100.0, 92.0, 88.0, 75.0],
        "losses": [0.0, 8.0, 4.0, 13.0],
    })
    try:
        canvas.draw()
        ax = canvas.figure.axes[0]
        assert all(abs(float(label.get_rotation())) < 1e-6 for label in ax.get_xticklabels())
    finally:
        canvas.close()


"""Offscreen check for the explainability physical-chain page layout.

Covers the initial (no data) state, the chain view, the single-parameter plot
view and a short window, dumping geometry + screenshots for each.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="optical-repro-appdata-")
os.environ.setdefault("XDG_CONFIG_HOME", tempfile.mkdtemp(prefix="optical-repro-settings-"))

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from frontend_pyside.app.bootstrap import create_main_window
from frontend_pyside.core.ui_theme import apply_application_theme

OUT = ROOT / "tmp"


def wait(ms: int = 250) -> None:
    QTest.qWait(ms)
    app = QApplication.instance()
    if app is not None:
        app.processEvents()


def box(widget: QWidget | None) -> str:
    if widget is None:
        return "None"
    geo = widget.geometry()
    return f"({geo.x()},{geo.y()},{geo.width()}x{geo.height()}) visible={widget.isVisible()}"


def report(document, tag: str) -> None:
    picker = document.feature_picker
    action_row = document.layout().itemAt(0).widget()
    print(f"=== {tag} ===")
    print(f"  action_row={box(action_row)}")
    print(f"  workspace ={box(document.workspace)}")
    print(f"  chain_view={box(document.chain_view)}")
    print(f"  selection ={box(document.selection_panel)}")
    print(f"  chain_card={box(document.chain_panel)}")
    rows = picker.count()
    visible_rows = picker.viewport().height() // max(picker.sizeHintForRow(0), 1)
    print(
        f"  picker rows={rows} height={picker.height()} visible_rows≈{visible_rows} "
        f"scroll_max={picker.verticalScrollBar().maximum()} "
        f"scroll_mode={picker.verticalScrollMode().name}"
    )
    chain_scroll = document.chain_view.verticalScrollBar()
    print(f"  chain scroll max={chain_scroll.maximum()} page={chain_scroll.pageStep()}")


def shap_payload(count: int = 8) -> dict:
    features = [
        ("surfaces[6].thickness_mm", 4.822e-10),
        ("surfaces[6].radius_mm", 4.169e-10),
        ("surfaces[4].thickness_mm", 1.702e-10),
        ("surfaces[2].radius_mm", 1.527e-10),
        ("surfaces[8].conic", 9.3e-11),
        ("receiver.offset_x_um", 7.1e-11),
        ("source.waist_x_um", 5.2e-11),
        ("surfaces[3].thickness_mm", 3.4e-11),
        ("surfaces[1].conic", 2.2e-11),
        ("surfaces[4].conic", 1.8e-11),
    ][:count]
    top = [
        {"feature": key, "mean_abs_shap": value, "mean_shap": value}
        for key, value in features
    ]
    return {
        "status": "ok",
        "target_name": "coupling_loss_db",
        "target_unit": "dB",
        "top_features": top,
        "shap_dependence": {
            features[0][0]: {
                "feature_value": [0.1, 0.2, 0.3, 0.4, 0.5],
                "shap_value": [-0.2, -0.1, 0.05, 0.2, 0.3],
            }
        },
    }


def prepare(window) -> object:
    window.navigate("explainability")
    window.workbench.open_document("explainability", "param_trend")
    wait(300)
    document = window.workbench._widgets["explainability:param_trend"]
    document.set_trained_models([{
        "id": "model-xgb-001",
        "title": "XGBoost物理残差1",
        "family": "xgboost",
        "target": "coupling_loss_db",
    }])
    return document


def main() -> int:
    app = QApplication.instance() or QApplication([])
    apply_application_theme(app)
    window = create_main_window()
    window.resize(1720, 1050)
    window.show()
    wait(400)

    document = prepare(window)
    window.grab().save(str(OUT / "repro_01_initial.png"))
    report(document, "initial (no SHAP yet)")

    document._render_shap(shap_payload(8))
    document.param_view_buttons[1].click()
    wait(400)
    window.grab().save(str(OUT / "repro_02_chain.png"))
    report(document, "chain view, 8 rows, 1720x1050")

    document.param_view_buttons[0].click()
    wait(300)
    window.grab().save(str(OUT / "repro_03_plot.png"))
    report(document, "plot view")

    document.param_view_buttons[1].click()
    wait(300)
    window.resize(1366, 768)
    wait(500)
    window.grab().save(str(OUT / "repro_04_chain_short.png"))
    report(document, "chain view, 1720x1050 -> 1366x768")

    window.close()
    wait(80)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

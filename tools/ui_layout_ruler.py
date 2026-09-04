"""Developer-only layout ruler for the shared PySide UI system.

It is intentionally not part of the product navigation.  Use it when changing
spacing, typography or common controls so a single screen exposes the standard
header, summary strip, form, actions, progress, table and empty state.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication, QComboBox, QLabel, QProgressBar, QSpinBox, QVBoxLayout, QWidget, QHBoxLayout, QTableWidgetItem

from frontend_pyside.core.ui_theme import apply_application_theme
from frontend_pyside.shared import layout_tokens as ui
from frontend_pyside.shared.components.basic import Card, FormGrid, PrimaryButton, SecondaryButton, SummaryStrip
from frontend_pyside.shared.components.foundation.headers import PageHeader
from frontend_pyside.shared.components.tables import DataTable


def build() -> QWidget:
    page = QWidget()
    page.setWindowTitle("排版标尺")
    root = QVBoxLayout(page)
    root.setContentsMargins(ui.PAGE_MARGIN, ui.PAGE_MARGIN, ui.PAGE_MARGIN, ui.PAGE_MARGIN)
    root.setSpacing(ui.CARD_GAP)

    root.addWidget(PageHeader("排版标尺", "开发验收用：所有普通页面尽量复用同一组尺寸、字体和对齐规则。"))
    root.addWidget(SummaryStrip((("最高效率", "97.3%"), ("最佳位置", "+0.05 mm"), ("3 dB 范围", "−0.18～0.26 mm"))))

    settings = Card("标准表单", compact=True)
    form = FormGrid()
    combo = QComboBox(); combo.addItems(["单参数扫描", "参数优化"])
    points = QSpinBox(); points.setRange(3, 1001); points.setValue(41)
    form.add_row("研究方式", combo, "先研究规律，再决定是否优化")
    form.add_row("采样点数", points, "点数越多，曲线越细")
    settings.body.addWidget(form)
    actions = QHBoxLayout(); actions.addStretch(1); actions.addWidget(SecondaryButton("更多设置")); actions.addWidget(PrimaryButton("开始研究"))
    settings.body.addLayout(actions)
    root.addWidget(settings)

    progress_card = Card("真实任务进度", compact=True)
    hint = QLabel("进度值必须来自后台任务事件；尚未收到可量化进度时使用不确定进度。")
    hint.setObjectName("helperText"); hint.setWordWrap(True)
    bar = QProgressBar(); bar.setRange(0, 100); bar.setValue(57); bar.setFormat("57%")
    progress_card.body.addWidget(hint); progress_card.body.addWidget(bar)
    root.addWidget(progress_card)

    table_card = Card("标准表格", compact=True)
    table = DataTable(2, 4); table.setHorizontalHeaderLabels(["名称", "样本数", "状态", "创建时间"])
    table.setItem(0, 0, QTableWidgetItem("示例数据 A")); table.setItem(0, 1, QTableWidgetItem("300")); table.setItem(0, 2, QTableWidgetItem("可用")); table.setItem(0, 3, QTableWidgetItem("2026-08-15"))
    table.setItem(1, 0, QTableWidgetItem("我的数据 B")); table.setItem(1, 1, QTableWidgetItem("500")); table.setItem(1, 2, QTableWidgetItem("计算中")); table.setItem(1, 3, QTableWidgetItem("2026-08-15"))
    table_card.body.addWidget(table); root.addWidget(table_card)
    root.addStretch(1)
    return page


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--output", default="")
    args = parser.parse_args()
    app = QApplication.instance() or QApplication([])
    apply_application_theme(app)
    page = build(); page.resize(1366, 768); page.show(); app.processEvents()
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True); page.grab().save(args.output)
        print(f"UI_LAYOUT_RULER_OK {args.output}")
    else:
        app.exec()

if __name__ == "__main__":
    main()

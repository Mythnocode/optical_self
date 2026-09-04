
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from frontend_pyside.resources import theme_tokens as theme
from frontend_pyside.shared.components.basic import Card, FeatureCard, InlineMetric, PrimaryButton, SecondaryButton


@dataclass(slots=True)
class TeachingProgressStore:
    progress: dict[str, int] = field(default_factory=lambda: {"principle": 0, "diagnostic": 0, "design": 0})
    records: list[dict[str, str]] = field(default_factory=list)

    def update(self, key: str, value: int, note: str = "") -> None:
        key = str(key)
        value = max(0, min(100, int(value)))
        self.progress[key] = max(value, self.progress.get(key, 0))
        if note:
            self.records.append(
                {
                    "time": datetime.now().strftime("%H:%M:%S"),
                    "module": key,
                    "note": str(note),
                    "progress": str(value),
                }
            )
            self.records = self.records[-80:]

    def overall(self) -> int:
        values = list(self.progress.values())
        return round(sum(values) / max(len(values), 1))


class LearningRouteWidget(QWidget):
    def paintEvent(self, event) -> None:  
        from PySide6.QtCore import QPointF, QRectF
        from PySide6.QtGui import QColor, QPainter, QPen

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), QColor(theme.SURFACE))
        labels = ("理解原理", "识别失配", "使用仪器", "完成装调", "设计系统", "正式验证")
        y = self.height() / 2
        left = 56
        right = max(left + 1, self.width() - 56)
        step = (right - left) / max(len(labels) - 1, 1)
        painter.setPen(QPen(QColor(theme.BORDER), 2))
        painter.drawLine(QPointF(left, y), QPointF(right, y))
        for index, label in enumerate(labels):
            x = left + index * step
            painter.setBrush(QColor(theme.PRIMARY_TINT))
            painter.setPen(QPen(QColor(theme.PRIMARY), 2))
            painter.drawEllipse(QPointF(x, y), 18, 18)
            painter.setPen(QColor(theme.PRIMARY))
            painter.drawText(QRectF(x - 18, y - 18, 36, 36), Qt.AlignmentFlag.AlignCenter, str(index + 1))
            painter.setPen(QColor(theme.TEXT_PRIMARY))
            painter.drawText(QRectF(x - 58, y + 26, 116, 24), Qt.AlignmentFlag.AlignCenter, label)


class TeachingHomePage(QWidget):
    sectionRequested = Signal(str)

    def __init__(self, store: TeachingProgressStore, parent=None) -> None:
        super().__init__(parent)
        self.store = store
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        route_card = Card("学习路线", compact=True)
        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("原理 → 实验诊断 → 系统设计"), 1)
        self.overall_metric = InlineMetric("总体进度", "0", "%")
        top_row.addWidget(self.overall_metric)
        route_card.body.addLayout(top_row)

        route = LearningRouteWidget()
        route.setMinimumHeight(100)
        route_card.body.addWidget(route)

        self.principle_metric = InlineMetric("原理", "0", "%")
        self.diagnostic_metric = InlineMetric("实验诊断", "0", "%")
        self.design_metric = InlineMetric("系统设计", "0", "%")
        modules = (
            ("模场失配原理", self.principle_metric, "principle", "继续"),
            ("实验诊断与装调", self.diagnostic_metric, "diagnostic", "进入"),
            ("单至四透镜系统设计", self.design_metric, "design", "进入"),
        )
        for title, metric, key, action in modules:
            row = QHBoxLayout()
            row.addWidget(QLabel(title), 1)
            metric.value_label.setMinimumWidth(42)
            row.addWidget(metric)
            button = SecondaryButton(action)
            button.clicked.connect(lambda checked=False, k=key: self.sectionRequested.emit(k))
            row.addWidget(button)
            route_card.body.addLayout(row)

        challenge = SecondaryButton("综合挑战")
        challenge.clicked.connect(lambda: self.sectionRequested.emit("diagnostic"))
        route_card.body.addWidget(challenge)
        root.addWidget(route_card)
        root.addStretch(1)
        self.refresh()

    def refresh(self) -> None:
        self.overall_metric.set_value(str(self.store.overall()))
        self.principle_metric.set_value(str(self.store.progress.get("principle", 0)))
        self.diagnostic_metric.set_value(str(self.store.progress.get("diagnostic", 0)))
        self.design_metric.set_value(str(self.store.progress.get("design", 0)))


class TeachingArchivePage(QWidget):
    sectionRequested = Signal(str)

    def __init__(self, store: TeachingProgressStore, parent=None) -> None:
        super().__init__(parent)
        self.store = store
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        summary = QHBoxLayout()
        self.summary_metrics = {
            "principle": InlineMetric("原理掌握", "0", "%"),
            "diagnostic": InlineMetric("实验诊断", "0", "%"),
            "design": InlineMetric("系统设计", "0", "%"),
            "overall": InlineMetric("综合进度", "0", "%"),
        }
        for metric in self.summary_metrics.values():
            metric.value_label.setMinimumWidth(42)
            summary.addWidget(metric)
        root.addLayout(summary)

        body = QHBoxLayout()
        progress_card = Card("能力进度", compact=True)
        self.progress_bars: dict[str, QProgressBar] = {}
        labels = {"principle": "理解模场失配原因", "diagnostic": "选择仪器并完成装调", "design": "完成透镜系统设计决策"}
        for key, label in labels.items():
            row = QHBoxLayout()
            row.addWidget(QLabel(label))
            bar = QProgressBar()
            bar.setRange(0, 100)
            row.addWidget(bar, 1)
            self.progress_bars[key] = bar
            progress_card.body.addLayout(row)
        body.addWidget(progress_card, 1)

        record_card = Card("最近学习记录", compact=True)
        self.record_label = QLabel()
        self.record_label.setWordWrap(True)
        self.record_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        record_card.body.addWidget(self.record_label)
        body.addWidget(record_card, 2)
        root.addLayout(body, 1)

        actions = QHBoxLayout()
        principle = SecondaryButton("继续原理学习")
        principle.clicked.connect(lambda: self.sectionRequested.emit("principle"))
        diagnostic = SecondaryButton("继续实验诊断")
        diagnostic.clicked.connect(lambda: self.sectionRequested.emit("diagnostic"))
        design = PrimaryButton("继续系统设计")
        design.clicked.connect(lambda: self.sectionRequested.emit("design"))
        actions.addWidget(principle)
        actions.addWidget(diagnostic)
        actions.addStretch(1)
        actions.addWidget(design)
        root.addLayout(actions)
        self.refresh()

    def refresh(self) -> None:
        for key, bar in self.progress_bars.items():
            bar.setValue(self.store.progress.get(key, 0))
        self.summary_metrics["principle"].set_value(str(self.store.progress.get("principle", 0)))
        self.summary_metrics["diagnostic"].set_value(str(self.store.progress.get("diagnostic", 0)))
        self.summary_metrics["design"].set_value(str(self.store.progress.get("design", 0)))
        self.summary_metrics["overall"].set_value(str(self.store.overall()))
        if self.store.records:
            text = "\n".join(
                f"{item['time']}　{item['module']}　{item['note']}（{item['progress']}%）"
                for item in reversed(self.store.records[-12:])
            )
        else:
            text = "暂无记录。完成预测、提交实验诊断或完成设计复核后，这里会显示学习轨迹。"
        self.record_label.setText(text)


__all__ = ["TeachingArchivePage", "TeachingHomePage", "TeachingProgressStore"]

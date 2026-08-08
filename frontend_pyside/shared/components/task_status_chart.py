from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from frontend_pyside.resources import theme_tokens as theme


class TaskStatusDonut(QWidget):


    COLORS = {
        "运行中": QColor(theme.PRIMARY),
        "等待中": QColor(theme.CHART_ORANGE),
        "失败": QColor(theme.ERROR),
        "暂停": QColor(theme.TEXT_DISABLED),
    }

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._values = {key: 0 for key in self.COLORS}
        self.setMinimumHeight(220)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_values(
        self,
        *,
        running: int = 0,
        waiting: int = 0,
        failed: int = 0,
        paused: int = 0,
    ) -> None:
        self._values = {
            "运行中": max(0, int(running)),
            "等待中": max(0, int(waiting)),
            "失败": max(0, int(failed)),
            "暂停": max(0, int(paused)),
        }
        self.update()

    def paintEvent(self, event) -> None:  
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(14, 12, -14, -12)
        side = min(rect.width(), rect.height() - 52)
        donut = QRectF(rect.left() + (rect.width() - side) / 2, rect.top(), side, side)
        total = sum(self._values.values())
        pen_width = max(16, int(side * 0.12))
        background = QPen(
            QColor(theme.SURFACE_SECONDARY),
            pen_width,
            Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.FlatCap,
        )
        painter.setPen(background)
        arc_rect = donut.adjusted(
            pen_width / 2,
            pen_width / 2,
            -pen_width / 2,
            -pen_width / 2,
        )
        painter.drawArc(arc_rect, 0, 360 * 16)
        if total:
            start = 90 * 16
            for key, value in self._values.items():
                if value <= 0:
                    continue
                span = -round(360 * 16 * value / total)
                painter.setPen(
                    QPen(
                        self.COLORS[key],
                        pen_width,
                        Qt.PenStyle.SolidLine,
                        Qt.PenCapStyle.FlatCap,
                    )
                )
                painter.drawArc(arc_rect, start, span)
                start += span
        painter.setPen(QColor(theme.TEXT_PRIMARY))
        font = QFont(painter.font())
        font.setBold(True)
        font.setPointSize(max(12, int(side / 13)))
        painter.setFont(font)
        painter.drawText(donut, Qt.AlignmentFlag.AlignCenter, str(total))

        y = donut.bottom() + 18
        font.setBold(False)
        font.setPointSize(9)
        painter.setFont(font)
        x = rect.left()
        segment = rect.width() / max(1, len(self._values))
        for index, (key, value) in enumerate(self._values.items()):
            center = x + segment * index + segment / 2
            painter.setBrush(self.COLORS[key])
            painter.setPen(QPen(Qt.PenStyle.NoPen))
            painter.drawEllipse(QRectF(center - 28, y + 2, 9, 9))
            painter.setPen(QColor(theme.TEXT_SECONDARY))
            painter.drawText(
                QRectF(center - 16, y - 4, 72, 22),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                f"{key} {value}",
            )


class TaskProgressChart(QWidget):


    currentCellChanged = Signal(int, int, int, int)

    STATUS_COLORS = {
        "运行中": QColor(theme.PRIMARY),
        "等待中": QColor(theme.CHART_ORANGE),
        "失败": QColor(theme.ERROR),
        "已暂停": QColor(theme.TEXT_DISABLED),
    }

    ROW_HEIGHT = 62

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._rows: list[list[str]] = []
        self._tooltips: list[list[str]] = []
        self._current_row = -1
        self.setMouseTracking(True)
        self.setMinimumHeight(220)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_rows(
        self,
        rows,
        *,
        tooltips=None,
        align_columns=(),
        eager_rows=None,
    ) -> None:
        del align_columns, eager_rows
        old_row = self._current_row
        old_identity = (
            tuple(self._rows[old_row][:2])
            if 0 <= old_row < len(self._rows)
            else None
        )
        self._rows = [list(map(str, row)) for row in rows]
        self._tooltips = [list(map(str, row)) for row in (tooltips or [])]
        self._current_row = -1
        if old_identity is not None:
            self._current_row = next(
                (
                    index
                    for index, row in enumerate(self._rows)
                    if tuple(row[:2]) == old_identity
                ),
                -1,
            )
        self.setMinimumHeight(max(220, len(self._rows) * self.ROW_HEIGHT + 16))
        self.updateGeometry()
        self.update()

    def currentRow(self) -> int:  
        return self._current_row

    def setCurrentCell(self, row: int, column: int = 0) -> None:  
        del column
        row = int(row)
        if not 0 <= row < len(self._rows):
            return
        old = self._current_row
        self._current_row = row
        self.update()
        if old != row:
            self.currentCellChanged.emit(row, 0, old, 0)

    def sizeHint(self) -> QSize:  
        rows = max(3, min(len(self._rows), 9))
        return QSize(840, rows * self.ROW_HEIGHT + 16)

    def minimumSizeHint(self) -> QSize:  
        return QSize(560, 220)

    @staticmethod
    def _progress(text: str) -> int:
        try:
            return max(0, min(100, int(float(str(text).replace("%", "").strip()))))
        except (TypeError, ValueError):
            return 0

    def _row_at(self, y: float) -> int:
        index = int((float(y) - 8) // self.ROW_HEIGHT)
        return index if 0 <= index < len(self._rows) else -1

    def mousePressEvent(self, event) -> None:  
        row = self._row_at(event.position().y())
        if row >= 0:
            self.setCurrentCell(row, 0)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  
        row = self._row_at(event.position().y())
        if 0 <= row < len(self._tooltips) and self._tooltips[row]:
            self.setToolTip("\n".join(self._tooltips[row]))
        else:
            self.setToolTip("")
        super().mouseMoveEvent(event)

    def paintEvent(self, event) -> None:  
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(theme.SURFACE))
        if not self._rows:
            painter.setPen(QColor(theme.TEXT_MUTED))
            font = QFont(painter.font())
            font.setPointSize(11)
            painter.setFont(font)
            painter.drawText(
                self.rect().adjusted(20, 20, -20, -20),
                Qt.AlignmentFlag.AlignCenter,
                "当前没有未完成任务",
            )
            return

        left = 16.0
        right = float(self.width()) - 18.0
        name_width = max(170.0, min(270.0, self.width() * 0.25))
        status_width = 92.0
        bar_left = left + name_width + status_width
        bar_width = max(160.0, right - bar_left - 58.0)

        normal_font = QFont(painter.font())
        normal_font.setPointSize(10)
        strong_font = QFont(normal_font)
        strong_font.setBold(True)
        small_font = QFont(normal_font)
        small_font.setPointSize(9)

        visible_bottom = self.height()
        for row_index, row in enumerate(self._rows):
            top = 8.0 + row_index * self.ROW_HEIGHT
            if top > visible_bottom:
                break
            name = row[0] if len(row) > 0 else "未命名任务"
            kind = row[1] if len(row) > 1 else ""
            status = row[2] if len(row) > 2 else "未知"
            progress = self._progress(row[3] if len(row) > 3 else "0")
            note = row[4] if len(row) > 4 else ""
            color = self.STATUS_COLORS.get(status, QColor(theme.TEXT_MUTED))

            row_rect = QRectF(7, top, self.width() - 14, self.ROW_HEIGHT - 7)
            if row_index == self._current_row:
                painter.setBrush(QColor(theme.PRIMARY_TINT))
                painter.setPen(QPen(QColor(theme.BORDER), 1.0))
                painter.drawRoundedRect(row_rect, 6, 6)
            elif row_index % 2:
                painter.fillRect(row_rect, QColor(theme.SURFACE_MUTED))

            painter.setFont(strong_font)
            painter.setPen(QColor(theme.TEXT_PRIMARY))
            painter.drawText(
                QRectF(left, top + 8, name_width - 8, 22),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                name,
            )
            painter.setFont(small_font)
            painter.setPen(QColor(theme.TEXT_MUTED))
            painter.drawText(
                QRectF(left, top + 31, name_width - 8, 18),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                kind,
            )

            painter.setFont(normal_font)
            painter.setPen(color)
            painter.drawText(
                QRectF(left + name_width, top + 8, status_width - 8, 22),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                status,
            )

            track = QRectF(bar_left, top + 10, bar_width, 14)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(theme.SURFACE_SECONDARY))
            painter.drawRoundedRect(track, 7, 7)
            if status == "失败":
                fill_ratio = 1.0
            elif status in {"等待中", "已暂停"} and progress <= 0:
                fill_ratio = 0.08
            else:
                fill_ratio = progress / 100.0
            fill = QRectF(track.left(), track.top(), track.width() * fill_ratio, track.height())
            painter.setBrush(color)
            painter.drawRoundedRect(fill, 7, 7)

            painter.setPen(QColor(theme.TEXT_PRIMARY))
            painter.drawText(
                QRectF(bar_left + bar_width + 8, top + 4, 48, 26),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                f"{progress}%",
            )
            painter.setFont(small_font)
            painter.setPen(QColor(theme.TEXT_MUTED))
            painter.drawText(
                QRectF(bar_left, top + 31, bar_width + 56, 18),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                note,
            )


__all__ = ["TaskStatusDonut", "TaskProgressChart"]

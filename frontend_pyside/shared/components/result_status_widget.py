
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton

from frontend_pyside.shared.components.basic import Badge


class ResultStatusWidget(QFrame):
    recomputeRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("resultValidityBar")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 5, 10, 5)
        layout.setSpacing(8)
        self.badge = Badge("待计算", "warning")
        layout.addWidget(self.badge)
        self.summary = QLabel("尚未生成正式结果")
        self.summary.setObjectName("helperText")
        layout.addWidget(self.summary, 1)
        self.recompute_button = QPushButton("重新计算")
        self.recompute_button.setProperty("kind", "secondary")
        self.recompute_button.clicked.connect(self.recomputeRequested.emit)
        layout.addWidget(self.recompute_button)
        self.set_pending("尚未生成正式结果")

    def set_valid(
        self,
        *,
        version: str = "",
        generated_at: str | None = None,
        algorithm: str = "",
        sampling: str = "",
        converged: bool = True,
    ) -> None:
        self.badge.setText("结果有效" if converged else "未收敛")
        self.badge.set_tone("success" if converged else "warning")
        timestamp = generated_at or datetime.now().strftime("%H:%M:%S")
        parts = [f"参数版本 {version}" if version else "", f"{timestamp} 生成"]
        if algorithm:
            parts.append(algorithm)
        if sampling:
            parts.append(sampling)
        self.summary.setText(" · ".join(part for part in parts if part))
        self.recompute_button.setVisible(not converged)

    def set_stale(self, reason: str, *, version: str = "") -> None:
        self.badge.setText("结果已过期")
        self.badge.set_tone("warning")
        suffix = f" · 当前参数 {version}" if version else ""
        self.summary.setText(f"{reason}{suffix}；旧图保留供比较")
        self.recompute_button.setVisible(True)

    def set_running(self, text: str = "后端计算中") -> None:
        self.badge.setText("计算中")
        self.badge.set_tone("warning")
        self.summary.setText(text)
        self.recompute_button.setVisible(False)

    def set_error(self, message: str) -> None:
        self.badge.setText("结果失败")
        self.badge.set_tone("danger")
        self.summary.setText(message)
        self.recompute_button.setVisible(True)

    def set_pending(self, text: str) -> None:
        self.badge.setText("待计算")
        self.badge.set_tone("info")
        self.summary.setText(text)
        self.recompute_button.setVisible(True)


__all__ = ["ResultStatusWidget"]

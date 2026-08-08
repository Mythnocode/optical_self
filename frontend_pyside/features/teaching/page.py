
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QVBoxLayout, QWidget

from .spatial_routing_upgrade import FlexibleSpatialTeachingWorkbench


class TeachingPage(QWidget):


    navigateRequested = Signal(str)

    def __init__(self, context, parent=None):
        super().__init__(parent)
        self.setObjectName("teachingPage")
        self.context = context
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.workbench = FlexibleSpatialTeachingWorkbench(context)
        self.workbench.navigateRequested.connect(self.navigateRequested)
        layout.addWidget(self.workbench)

    def current_profile(self) -> dict:
        return self.workbench.current_profile()


__all__ = ["TeachingPage"]

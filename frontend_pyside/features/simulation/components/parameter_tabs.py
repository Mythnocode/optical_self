from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QCheckBox, QFrame, QScrollArea, QVBoxLayout, QWidget

from frontend_pyside.shared.components.workbench import Accordion, ExpandableSection
from .parameter_parts import ParameterControlMixin, ParameterPageBuilderMixin, ParameterStateMixin


class SimpleParameterTabs(
    ParameterControlMixin,
    ParameterPageBuilderMixin,
    ParameterStateMixin,
    QScrollArea,
):


    changed = Signal()

    def __init__(self, editor: QWidget, parent=None):
        super().__init__(parent)
        self.analysis_boxes: dict[str, QCheckBox] = {}
        self.output_boxes: dict[str, QCheckBox] = {}
        self.editor = editor
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setViewportMargins(0, 0, 0, 0)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setObjectName("simulationParameterAccordion")

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        content_layout.setContentsMargins(0, 0, 0, 64)

        self.section_by_key = {
            "source": ExpandableSection(
                "光源",
                self._source_page(),
                expanded=True,
                header_variant="navigation",
            ),
            "lens": ExpandableSection(
                "镜头",
                self.editor,
                expanded=False,
                header_variant="navigation",
            ),
            "fiber": ExpandableSection(
                "光纤",
                self._receiver_page(),
                expanded=False,
                header_variant="navigation",
            ),
            "calculation": ExpandableSection(
                "设置",
                self._calculation_page(),
                expanded=False,
                header_variant="navigation",
            ),
        }
        self._ordered_keys = ["source", "lens", "fiber", "calculation"]
        self.accordion = Accordion(
            [self.section_by_key[key] for key in self._ordered_keys],
            exclusive=True,
        )
        content_layout.addWidget(self.accordion)
        self.setWidget(content)
        self._connect_change_signals()

    def expand_section(self, key: str) -> None:
        section = self.section_by_key.get(str(key))
        if section is not None:
            section.set_expanded(True)
            self.ensureWidgetVisible(section)

    def attach_result_controls(self, controls: QWidget) -> None:

        host = getattr(self, "result_controls_host_layout", None)
        if host is None or controls is None:
            return
        controls.setParent(self)
        controls.setVisible(True)
        host.addWidget(controls)

    
    
    def count(self) -> int:
        return len(self._ordered_keys)

    def tabText(self, index: int) -> str:
        labels = ["光源", "镜头", "光纤", "设置"]
        return labels[index] if 0 <= index < len(labels) else ""

    def setCurrentIndex(self, index: int) -> None:
        if 0 <= int(index) < len(self._ordered_keys):
            self.expand_section(self._ordered_keys[int(index)])

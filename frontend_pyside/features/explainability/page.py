from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)

from frontend_pyside.features.explainability.actions import ReportContentOptions
from frontend_pyside.infrastructure.api.clients import DatasetClient, TrainingClient
from frontend_pyside.shared.lazy_widgets import LazyStackedWidget
from frontend_pyside.shared.lifecycle import ManagedPageResources
from frontend_pyside.shared.components.basic import SecondaryButton
from frontend_pyside.shared.background import BackgroundPreparer
from frontend_pyside.shared.settings import WorkspaceStateStore
from frontend_pyside.shared.display_names import RegistryAliasStore
from .presentation.api_behavior import ExplainabilityApiMixin
from .presentation.export_behavior import ExplainabilityExportMixin
from .presentation.formula_behavior import ExplainabilityFormulaMixin
from .presentation.shap_behavior import ExplainabilityShapMixin


class ShapClient:


    def __init__(self, api_client):
        self.api_client = api_client

    def explain(self, key: str, model_id: str, payload: dict) -> None:
        self.api_client.post(key, f"/models/{model_id}/shap/explain", payload)


class ExplainabilityPage(
    ExplainabilityApiMixin,
    ExplainabilityShapMixin,
    ExplainabilityFormulaMixin,
    ExplainabilityExportMixin,
    QWidget,
):


    def __init__(self, context, parent=None):
        super().__init__(parent)
        self.context = context
        self.lifecycle = ManagedPageResources(self)
        self.workspace_state = WorkspaceStateStore("explainability")
        self.registry_aliases = RegistryAliasStore()
        self._shap_preparer = BackgroundPreparer(self)
        self._pending_shap_meta: dict[int, str] = {}
        self.api_client = context.api_client
        self.dataset_client = DatasetClient(self.api_client)
        self.training_client = TrainingClient(self.api_client)
        self.shap_client = ShapClient(self.api_client)
        self._shap_data: dict | None = None
        self._shap_available: bool | None = None
        self._report_options = ReportContentOptions()
        self._feature_records: list[dict] = []
        self._local_shap_by_feature: dict[str, float] = {}
        self._selected_feature_name = ""
        self._page_active = False
        self._pending_shap_payload: dict | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 9, 14, 12)
        root.setSpacing(7)

        self.model = QComboBox()
        self.dataset = QComboBox()
        self.output = QComboBox()
        self.lifecycle.connect(self.model.currentIndexChanged, self._sync_model_selection)
        self.lifecycle.connect(self.dataset.currentIndexChanged, self._refresh_context_summary)
        self.lifecycle.connect(self.output.currentIndexChanged, self._refresh_context_summary)


        mode_bar = QHBoxLayout()
        mode_bar.setSpacing(6)
        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)
        self.mode_buttons = []
        for index, label in enumerate(("失配诊断", "解释报告")):
            button = SecondaryButton(label)
            button.setObjectName("workflowStepButton")
            button.setCheckable(True)
            button.clicked.connect(
                lambda checked=False, i=index: self._set_main_step(i)
            )
            self.mode_group.addButton(button, index)
            self.mode_buttons.append(button)
            mode_bar.addWidget(button)
        mode_bar.addStretch(1)
        root.addLayout(mode_bar)

        self.tabs = LazyStackedWidget()
        self.shap_page = None
        self.report_page = None
        self.tabs.add_lazy_widget(self._build_shap_page, "正在准备解释工作区…")
        self.tabs.add_lazy_widget(self._build_report_page, "打开报告时再生成报告视图。")
        root.addWidget(self.tabs, 1)
        self.workspace_state.restore_tab("main", self.tabs, 0)
        self.mode_buttons[self.tabs.currentIndex()].setChecked(True)
        self.tabs.ensure_current_deferred()

        
        
        

        self.lifecycle.connect(self.api_client.completed, self._api_completed)
        self.lifecycle.connect(self.api_client.failed, self._api_failed)
        self.lifecycle.connect(self._shap_preparer.completed, self._shap_prepared)
        self.lifecycle.connect(self._shap_preparer.failed, self._shap_prepare_failed)
        self.lifecycle.connect(context.registry.datasets_changed, self._registry_datasets_changed)
        self.lifecycle.connect(context.registry.models_changed, self._registry_models_changed)
        self.lifecycle.connect(context.registry.current_dataset_changed, self._select_dataset_id)
        self.lifecycle.connect(context.registry.current_model_changed, self._select_model_id)
        self._registry_datasets_changed(context.registry.datasets)
        self._registry_models_changed(context.registry.models)
        QTimer.singleShot(200, self._refresh_selectors)

    def _set_main_step(self, index: int) -> None:
        index = max(0, min(int(index), self.tabs.count() - 1))
        self.tabs.setCurrentIndex(index)
        if 0 <= index < len(self.mode_buttons):
            self.mode_buttons[index].setChecked(True)

    def _build_shap_page(self) -> QWidget:
        self.shap_page = self._shap()
        return self.shap_page

    def _build_report_page(self) -> QWidget:
        self.report_page = self._report()
        return self.report_page

    def on_activated(self) -> None:
        self._page_active = True
        self.lifecycle.activated()
        self._refresh_selectors()
        pending, self._pending_shap_payload = self._pending_shap_payload, None
        if pending is not None:
            self._update_shap_from_api(pending)

    def on_deactivated(self) -> None:
        self._page_active = False
        self.lifecycle.deactivate()

    def resizeEvent(self, event) -> None:  
        super().resizeEvent(event)
        if hasattr(self, "_apply_shap_responsive_layout") and hasattr(self, "shap_linkage_layout"):
            self._apply_shap_responsive_layout(self.width() < 1280)

    def showEvent(self, event) -> None:
        self.on_activated()
        if hasattr(self, "_apply_shap_responsive_layout") and hasattr(self, "shap_linkage_layout"):
            self._apply_shap_responsive_layout(self.width() < 1280)
        super().showEvent(event)

    def hideEvent(self, event) -> None:
        self.on_deactivated()
        super().hideEvent(event)

    def dispose_page(self) -> None:
        self.workspace_state.save_tab("main", self.tabs)
        plot_tabs = getattr(self, "plot_tabs", None)
        if plot_tabs is not None and hasattr(plot_tabs, "dispose"):
            plot_tabs.dispose()
        self.tabs.dispose()
        self.lifecycle.dispose()

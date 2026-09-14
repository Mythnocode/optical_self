from __future__ import annotations

from types import SimpleNamespace

from PySide6.QtCore import QSettings

from frontend_pyside.core.shiboken_guard import harden_shiboken_signature_hook

# 必须先于 main_window（其 assistant 链会拉起 sklearn→pandas→dateutil→six）
harden_shiboken_signature_hook()

from frontend_pyside.app.main_window import MainWindow
from frontend_pyside.infrastructure.api.client import ApiClient
from frontend_pyside.infrastructure.api.clients import (
    DatasetClient,
    HeadlessDatasetClient,
    HealthClient,
    JobClient,
    MultiPathClient,
    OptimizationClient,
    ScanClient,
    SimulationClient,
    ToleranceClient,
    TrainingClient,
)
from frontend_pyside.infrastructure.api.job_monitor import CentralJobMonitor
from frontend_pyside.infrastructure.storage.usage_store import UsageAnalyticsStore
from frontend_pyside.state.app_context import AppContext
from frontend_pyside.state.project_context import ProjectContext
from frontend_pyside.state.registry_context import RegistryContext
from frontend_pyside.state.task_context import TaskContext
from frontend_pyside.shared.settings import UiPreferences
from frontend_pyside.resources.resource_loader import register_resources


class _UnavailableTeachingService:


    def __init__(self, reason: str):
        self.reason = reason

    def catalog(self):
        raise RuntimeError(f"teaching_runtime 不可用：{self.reason}")


class _LazyTeachingService:


    def __init__(self) -> None:
        self._service = None

    def _get(self):
        if self._service is None:
            try:
                from teaching_runtime.service import TeachingModuleService

                self._service = TeachingModuleService()
            except Exception as exc:
                self._service = _UnavailableTeachingService(str(exc))
        return self._service

    def __getattr__(self, name: str):
        return getattr(self._get(), name)


def _create_teaching_service():
    return _LazyTeachingService()


def create_services() -> SimpleNamespace:
    register_resources()
    api = ApiClient()
    usage = UsageAnalyticsStore()
    return SimpleNamespace(
        api=api,
        health=HealthClient(api),
        jobs=JobClient(api),
        simulation=SimulationClient(api),
        multipath=MultiPathClient(api),
        scan=ScanClient(api),
        optimization=OptimizationClient(api),
        tolerance=ToleranceClient(api),
        dataset=DatasetClient(api),
        headless_dataset=HeadlessDatasetClient(api),
        training=TrainingClient(api),
        job_watcher=CentralJobMonitor(api),
        teaching=_create_teaching_service(),
        usage=usage,
        ui_preferences=UiPreferences(),
    )


def create_app_context() -> AppContext:
    services = create_services()
    project = ProjectContext()
    tasks = TaskContext(usage_store=services.usage)
    registry = RegistryContext()
    context = AppContext(
        project=project,
        tasks=tasks,
        registry=registry,
        services=services,
        api_client=services.api,
    )

    # Persist only selections that the user explicitly adopted.  Training a new
    # model still does not make it current.  On restart the saved ID is restored
    # only after the registry confirms the artifact still exists; missing/deleted
    # artifacts clear the saved selection instead of silently choosing another.
    selection_settings = QSettings()
    saved_model_id = str(selection_settings.value("registry/current_model_id", "") or "")
    saved_dataset_id = str(selection_settings.value("registry/current_dataset_id", "") or "")

    def _save_current_model(model_id: str) -> None:
        selection_settings.setValue("registry/current_model_id", str(model_id or ""))

    def _save_current_dataset(dataset_id: str) -> None:
        selection_settings.setValue("registry/current_dataset_id", str(dataset_id or ""))

    def _restore_saved_model(records: list[dict]) -> None:
        nonlocal saved_model_id
        if registry.current_model_id or not saved_model_id:
            return
        ids = {str(item.get("model_id", item.get("id", "")) or "") for item in records if isinstance(item, dict)}
        if saved_model_id in ids:
            registry.set_current_model(saved_model_id)
        else:
            saved_model_id = ""
            selection_settings.setValue("registry/current_model_id", "")

    def _restore_saved_dataset(records: list[dict]) -> None:
        nonlocal saved_dataset_id
        if registry.current_dataset_id or not saved_dataset_id:
            return
        ids = {str(item.get("dataset_id", item.get("id", "")) or "") for item in records if isinstance(item, dict)}
        if saved_dataset_id in ids:
            registry.set_current_dataset(saved_dataset_id)
        else:
            saved_dataset_id = ""
            selection_settings.setValue("registry/current_dataset_id", "")

    registry.current_model_changed.connect(_save_current_model)
    registry.current_dataset_changed.connect(_save_current_dataset)
    registry.models_changed.connect(_restore_saved_model)
    registry.datasets_changed.connect(_restore_saved_dataset)

    # Keep the research journal tied to authoritative state changes instead of
    # reconstructing history from chat text later.  The event payload is kept
    # lightweight; dense result arrays remain in TaskContext/backend artifacts.
    def _record_task_result(task_id: str, result) -> None:
        task = tasks.find(task_id) or {}
        if not task:
            return
        summary = {}
        if isinstance(result, dict):
            for key in ("coupling_efficiency", "system_efficiency", "best_efficiency", "best_value", "yield_rate", "p05", "rmse", "mae", "status"):
                value = result.get(key)
                if value is not None and not isinstance(value, (dict, list, tuple)):
                    summary[key] = value
        project.record_research_event(
            "task_result",
            str(task.get("name") or task.get("kind") or "完成研究任务"),
            {"kind": str(task.get("kind", "")), "result": summary},
            source=str(task.get("kind") or "任务"),
            task_id=str(task_id),
            dedupe_key=f"task:{task_id}",
        )

    def _record_model_change(model_id: str) -> None:
        if not model_id:
            return
        model = registry.model(model_id) or {}
        project.record_research_event(
            "model_adopted",
            "设为当前模型",
            {
                "model_id": str(model_id),
                "model_name": str(model.get("name") or model.get("model_name") or model_id),
                "dataset_id": str(model.get("dataset_id") or ""),
            },
            source="模型分析",
            dedupe_key="current_model",
        )

    tasks.task_result_changed.connect(_record_task_result)
    registry.current_model_changed.connect(_record_model_change)
    return context


def create_main_window() -> MainWindow:
    context = create_app_context()
    window = MainWindow(context)
    window.app_context = context
    
    
    window.destroyed.connect(lambda *_: context.services.usage.close())
    return window

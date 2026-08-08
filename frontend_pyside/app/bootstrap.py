from __future__ import annotations

from types import SimpleNamespace

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
    return AppContext(
        project=ProjectContext(),
        tasks=TaskContext(usage_store=services.usage),
        registry=RegistryContext(),
        services=services,
        api_client=services.api,
    )


def create_main_window() -> MainWindow:
    context = create_app_context()
    window = MainWindow(context)
    window.app_context = context
    
    
    window.destroyed.connect(lambda *_: context.services.usage.close())
    return window

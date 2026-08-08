from __future__ import annotations

from dataclasses import dataclass

from frontend_pyside.state.project_context import ProjectContext
from frontend_pyside.state.registry_context import RegistryContext
from frontend_pyside.state.task_context import TaskContext


@dataclass(slots=True)
class AppContext:


    project: ProjectContext
    tasks: TaskContext
    registry: RegistryContext
    services: object
    api_client: object | None = None

    @property
    def model(self) -> RegistryContext:

        return self.registry


__all__ = ["AppContext"]

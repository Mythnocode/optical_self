
from __future__ import annotations

from dataclasses import dataclass
import importlib
from typing import Any, Callable


@dataclass(frozen=True, slots=True)
class PageSpec:
    key: str
    title: str
    icon_name: str
    group: str
    factory_path: str
    lifetime: str = "cached"
    release_after_s: float = 600.0
    idle_preload_order: int = 0

    def load_factory(self) -> Callable[..., Any]:
        module_name, class_name = self.factory_path.rsplit(":", 1)
        module = importlib.import_module(module_name)
        factory = getattr(module, class_name)
        if not callable(factory):
            raise TypeError(f"{self.factory_path} is not callable")
        return factory


PAGE_SPECS: tuple[PageSpec, ...] = (
    PageSpec(
        "home", "项目总览", "home", "项目",
        "frontend_pyside.features.home.page:HomePage",
        lifetime="resident",
    ),
    # 教学中心紧跟首页，先理解和复盘，再进入正式仿真与研究流程。
    PageSpec(
        "teaching", "教学", "teaching", "项目",
        "frontend_pyside.features.teaching.page:TeachingPage",
        lifetime="cached",
        release_after_s=900.0,
    ),
    PageSpec(
        "simulation", "仿真工作台", "simulation", "项目",
        "frontend_pyside.features.simulation.page:SimulationPage",
        lifetime="resident",
        idle_preload_order=1,
    ),
    PageSpec(
        "optimization", "研究与优化", "optimization", "研究",
        "frontend_pyside.features.optimization.page:OptimizationPage",
        lifetime="cached",
        release_after_s=900.0,
        idle_preload_order=2,
    ),
    PageSpec(
        "machine_learning", "代理模型", "machine_learning", "分析",
        "frontend_pyside.features.machine_learning.page:MachineLearningPage",
        lifetime="cached",
        release_after_s=900.0,
    ),
    PageSpec(
        "explainability", "模型解释", "explainability", "分析",
        "frontend_pyside.features.explainability.page:ExplainabilityPage",
        lifetime="cached",
        release_after_s=900.0,
    ),
    PageSpec(
        "tasks", "任务状态", "tasks", "管理",
        "frontend_pyside.features.tasks.page:TasksPage",
        lifetime="releasable",
        release_after_s=600.0,
    ),
)

PAGE_SPEC_BY_KEY = {spec.key: spec for spec in PAGE_SPECS}
IDLE_PRELOAD_SPECS = tuple(
    sorted(
        (spec for spec in PAGE_SPECS if spec.idle_preload_order > 0),
        key=lambda item: item.idle_preload_order,
    )
)

__all__ = ["IDLE_PRELOAD_SPECS", "PAGE_SPECS", "PAGE_SPEC_BY_KEY", "PageSpec"]

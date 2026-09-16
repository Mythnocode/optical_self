"""Optimization-result tab entry point."""

from .documents import OptimizationDocument
from frontend_pyside.modules.page_spec import PageSpec


PAGE = PageSpec(
    "optimization", "opt_result", "opt_result",
    "优化结果", "候选方案、过程曲线和对照图",
    "优化结果", "候选方案、过程曲线和对照图",
)


class OptimizationResultTab(OptimizationDocument):
    def __init__(self, context, selected, parent=None) -> None:
        super().__init__("opt_result", context, selected, parent)


__all__ = ["OptimizationResultTab"]

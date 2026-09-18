"""Optimization-variable tab entry point."""

from .documents import OptimizationDocument
from frontend_pyside.modules.page_spec import PageSpec


PAGE = PageSpec(
    "optimization", "opt_vars", "opt_vars",
    "优化", "目标、变量范围并开始优化",
    "优化", "目标、工程约束和变量范围",
)


class VariablesTab(OptimizationDocument):
    def __init__(self, context, selected, parent=None, *, goal=None, max_evaluations=None) -> None:
        super().__init__(
            "opt_vars",
            context,
            selected,
            parent,
            goal=goal,
            max_evaluations=max_evaluations,
        )


__all__ = ["VariablesTab"]

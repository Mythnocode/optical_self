"""Parameter-trend tab entry point."""

from .documents import AnalysisTextDocument
from frontend_pyside.modules.page_spec import PageSpec


PAGE = PageSpec(
    "explainability", "param_trend", "param_trend",
    "物理链路", "从排名参数追溯物理公式顺序",
    "物理链路", "参数 → 公式 → 物理量 → 目标输出",
)


class ParameterTrendTab(AnalysisTextDocument):
    def __init__(self, selected, context, parent=None) -> None:
        super().__init__("param_trend", selected, parent=parent, context=context)


__all__ = ["ParameterTrendTab"]

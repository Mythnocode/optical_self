"""Parameter-trend tab entry point."""

from .documents import AnalysisTextDocument
from frontend_pyside.modules.page_spec import PageSpec


PAGE = PageSpec(
    "explainability", "param_trend", "param_trend",
    "单参数规律", "某一个量变大时预测往哪边",
    "单参数规律", "当前选中参数的依赖关系",
)


class ParameterTrendTab(AnalysisTextDocument):
    def __init__(self, selected, context, parent=None) -> None:
        super().__init__("param_trend", selected, parent=parent, context=context)


__all__ = ["ParameterTrendTab"]

"""Global-contribution tab entry point."""

from .documents import AnalysisTextDocument
from frontend_pyside.modules.page_spec import PageSpec


PAGE = PageSpec(
    "explainability", "global_contrib", "global_contrib",
    "贡献排序", "把 SHAP 经物理特征回传到 8 个设计变量",
    "贡献排序", "链式法则贡献与物理解析一致性",
)


class GlobalContributionTab(AnalysisTextDocument):
    def __init__(self, selected, context, parent=None) -> None:
        super().__init__("global_contrib", selected, parent=parent, context=context)


__all__ = ["GlobalContributionTab"]

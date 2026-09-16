"""Global-contribution tab entry point."""

from .documents import AnalysisTextDocument
from frontend_pyside.modules.page_spec import PageSpec


PAGE = PageSpec(
    "explainability", "global_contrib", "global_contrib",
    "全局贡献", "哪些量对模型输出更重要",
    "全局贡献", "数据集上的平均 |SHAP|",
)


class GlobalContributionTab(AnalysisTextDocument):
    def __init__(self, selected, context, parent=None) -> None:
        super().__init__("global_contrib", selected, parent=parent, context=context)


__all__ = ["GlobalContributionTab"]

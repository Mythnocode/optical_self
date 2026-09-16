"""Current-system explanation tab entry point."""

from .documents import AnalysisTextDocument
from frontend_pyside.modules.page_spec import PageSpec


PAGE = PageSpec(
    "explainability", "current_system", "current_system",
    "当前系统", "当前处方这一条样本",
    "当前系统", "本条样本的特征贡献",
)


class CurrentSystemTab(AnalysisTextDocument):
    def __init__(self, selected, context, parent=None) -> None:
        super().__init__("current_system", selected, parent=parent, context=context)


__all__ = ["CurrentSystemTab"]

"""Current-system explanation tab entry point."""

from .documents import AnalysisTextDocument
from frontend_pyside.modules.page_spec import PageSpec


PAGE = PageSpec(
    "explainability", "current_system", "current_system",
    "当前系统验证", "用当前处方和正式仿真复核模型线索",
    "当前系统验证", "当前处方的局部贡献与验证状态",
)


class CurrentSystemTab(AnalysisTextDocument):
    def __init__(self, selected, context, parent=None) -> None:
        super().__init__("current_system", selected, parent=parent, context=context)


__all__ = ["CurrentSystemTab"]

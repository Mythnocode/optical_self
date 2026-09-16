"""Parameter-scan tab entry point."""

from .documents import OptimizationDocument
from frontend_pyside.modules.page_spec import PageSpec


PAGE = PageSpec(
    "optimization", "scan", "scan",
    "扫描", "最多两个已选变量的响应曲线",
    "扫描", "最多两个已选变量",
)


class ScanTab(OptimizationDocument):
    def __init__(self, context, selected, parent=None) -> None:
        super().__init__("scan", context, selected, parent)


__all__ = ["ScanTab"]

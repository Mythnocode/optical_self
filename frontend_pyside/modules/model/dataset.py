"""Dataset tab entry point."""

from .documents import ModelDocument
from frontend_pyside.modules.page_spec import PageSpec


PAGE = PageSpec(
    "model", "dataset", "dataset",
    "数据集", "内置或文件数据集，并在本页训练",
    "数据集", "内置数据集、文件数据集和训练准备",
)


class DatasetTab(ModelDocument):
    def __init__(self, context, parent=None) -> None:
        super().__init__("dataset", context, parent)


__all__ = ["DatasetTab"]

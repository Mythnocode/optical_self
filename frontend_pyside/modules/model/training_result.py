"""Training-result tab entry point."""

from .documents import ModelDocument
from frontend_pyside.modules.page_spec import PageSpec


PAGE = PageSpec(
    "model", "train_result", "train_result",
    "训练结果", "残差图、实测对照和学习曲线",
    "训练结果", "残差图、实测对照和学习曲线",
)


class TrainingResultTab(ModelDocument):
    def __init__(self, context, parent=None) -> None:
        super().__init__("train_result", context, parent)


__all__ = ["TrainingResultTab"]

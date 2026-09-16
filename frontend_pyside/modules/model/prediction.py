"""Prediction tab entry point."""

from .documents import ModelDocument
from frontend_pyside.modules.page_spec import PageSpec


PAGE = PageSpec(
    "model", "predict_eval", "predict",
    "模型预测", "当前系统预测",
    "模型预测", "当前参数的预测结果",
)


class PredictionTab(ModelDocument):
    def __init__(self, context, parent=None) -> None:
        super().__init__("predict", context, parent)


__all__ = ["PredictionTab"]

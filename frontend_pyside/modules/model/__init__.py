"""Model primary entry and its document tabs."""

from .documents import ModelDocument
from .dataset import DatasetTab
from .prediction import PredictionTab
from .training_result import TrainingResultTab

__all__ = ["DatasetTab", "ModelDocument", "PredictionTab", "TrainingResultTab"]

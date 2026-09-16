"""Page registry for the model primary entry."""

from .dataset import PAGE as DATASET_PAGE
from .prediction import PAGE as PREDICTION_PAGE
from .training_result import PAGE as TRAINING_RESULT_PAGE


PAGES = (DATASET_PAGE, TRAINING_RESULT_PAGE, PREDICTION_PAGE)

__all__ = ["PAGES"]

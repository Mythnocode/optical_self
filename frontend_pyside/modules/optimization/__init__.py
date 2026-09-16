"""Optimization primary entry and its document tabs."""

from .documents import OptimizationDocument, QSpinBoxCompat
from .goal import OptimizationGoalInspector
from .result import OptimizationResultTab
from .scan import ScanTab
from .variables import VariablesTab

__all__ = [
    "OptimizationDocument",
    "OptimizationGoalInspector",
    "OptimizationResultTab",
    "QSpinBoxCompat",
    "ScanTab",
    "VariablesTab",
]

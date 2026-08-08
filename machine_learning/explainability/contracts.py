
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class FeatureContribution:
    feature: str
    display_name: str
    symbol_latex: str
    feature_value: float
    shap_value: float
    abs_shap_value: float
    direction: str
    rank: int
    formula_latex: str | None = None
    efficiency_formula_latex: str | None = None
    formula_efficiency: float | None = None
    formula_loss: float | None = None
    formula_centered_contribution: float | None = None
    source_parameters: tuple[str, ...] = ()
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["source_parameters"] = list(self.source_parameters)
        return data


@dataclass(frozen=True)
class FormulaConsistency:
    feature: str
    sample_count: int
    pearson_correlation: float | None
    spearman_correlation: float | None
    calibrated_slope: float | None
    calibrated_intercept: float | None
    normalized_rmse: float | None
    sign_agreement: float | None
    level: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class InteractionContribution:
    feature_a: str
    feature_b: str
    mean_abs_interaction: float
    mean_signed_interaction: float
    rank: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ShapFormulaLinkageReport:
    target_name: str
    target_unit: str
    base_value: float
    prediction: float
    model_prediction: float
    additivity_error: float
    feature_contributions: list[FeatureContribution]
    global_importance: list[dict[str, Any]] = field(default_factory=list)
    formula_consistency: list[FormulaConsistency] = field(default_factory=list)
    interactions: list[InteractionContribution] = field(default_factory=list)
    interaction_matrix: list[list[float]] | None = None
    feature_order: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_name": self.target_name,
            "target_unit": self.target_unit,
            "base_value": self.base_value,
            "prediction": self.prediction,
            "model_prediction": self.model_prediction,
            "additivity_error": self.additivity_error,
            "feature_contributions": [item.to_dict() for item in self.feature_contributions],
            "global_importance": self.global_importance,
            "formula_consistency": [item.to_dict() for item in self.formula_consistency],
            "interactions": [item.to_dict() for item in self.interactions],
            "interaction_matrix": self.interaction_matrix,
            "feature_order": self.feature_order,
            "warnings": self.warnings,
        }

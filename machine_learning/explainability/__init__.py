

from machine_learning.explainability.physics_features import (
    PHYSICS_FEATURES,
    PHYSICS_FEATURE_ORDER,
    PhysicsFeatureDefinition,
    PhysicsFeatureError,
    canonicalize_raw_parameters,
    compute_physics_features,
    evaluate_formula_components,
    formula_registry_metadata,
)
from machine_learning.explainability.physics_residual import (
    FORMULA_FEATURES,
    RESIDUAL_FEATURES,
    PhysicsResidualModel,
    augment_residual_features,
    emphasis_weights,
    formula_baseline_db,
    formula_components_db,
    regression_metrics,
)

from machine_learning.explainability.shap_service import (
    ShapDependencyError,
    ShapFormulaLinkageAnalyzer,
)
from machine_learning.explainability.design_variable_attribution import (
    DESIGN_LABEL,
    DESIGN_SHORT,
    DesignVariableAttribution,
    compute_design_variable_attribution,
    physics_consistency,
)
from machine_learning.explainability.target_transforms import (
    TARGET_TRANSFORMS,
    TargetTransform,
    get_target_transform,
)

__all__ = [
    "PHYSICS_FEATURES",
    "PHYSICS_FEATURE_ORDER",
    "PhysicsFeatureDefinition",
    "PhysicsFeatureError",
    "canonicalize_raw_parameters",
    "compute_physics_features",
    "evaluate_formula_components",
    "formula_registry_metadata",
    "FORMULA_FEATURES",
    "RESIDUAL_FEATURES",
    "PhysicsResidualModel",
    "augment_residual_features",
    "emphasis_weights",
    "formula_baseline_db",
    "formula_components_db",
    "regression_metrics",
    "ShapDependencyError",
    "ShapFormulaLinkageAnalyzer",
    "TARGET_TRANSFORMS",
    "TargetTransform",
    "get_target_transform",
    "DESIGN_SHORT",
    "DESIGN_LABEL",
    "DesignVariableAttribution",
    "compute_design_variable_attribution",
    "physics_consistency",
]

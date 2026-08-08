

from machine_learning.workflow.feedback import append_verified_result

WORKFLOW_STAGES = (
    "formal_optical_simulation",
    "lhs_or_sobol_sampling",
    "quality_gate_and_analytic_coupling",
    "random_forest_baseline",
    "xgboost_physics_residual",
    "shap_parameter_explanation",
    "bilstm_variable_structure_screening",
    "bayesian_or_de_coarse_search",
    "powell_formal_refinement",
    "formal_simulation_verification",
    "feedback_and_iterative_retraining",
)

__all__ = ["WORKFLOW_STAGES", "append_verified_result"]

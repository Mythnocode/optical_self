from __future__ import annotations
from typing import Any, Mapping

from .calculations import calculate
from .contracts import get_catalog
from .experiments import evaluate_prediction, run_parameter_scan, run_numerical_diagnostic, score_experiment, build_report_bundle


class TeachingModuleService:

    def catalog(self) -> dict[str, Any]: return get_catalog()
    def evaluate(self, module: str, inputs: Mapping[str, Any] | None = None) -> dict[str, Any]: return calculate(module, inputs)
    def prediction(self, module: str, payload: Mapping[str, Any]) -> dict[str, Any]: return evaluate_prediction(module, payload)
    def scan(self, module: str, payload: Mapping[str, Any]) -> dict[str, Any]: return run_parameter_scan(module, payload)
    def diagnostics(self, module: str, payload: Mapping[str, Any]) -> dict[str, Any]: return run_numerical_diagnostic(module, payload)
    def score(self, module: str, payload: Mapping[str, Any]) -> dict[str, Any]: return score_experiment(module, payload)
    def report(self, module: str, payload: Mapping[str, Any]) -> dict[str, Any]: return build_report_bundle(module, payload)

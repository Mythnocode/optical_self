from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Mapping

import yaml

from .schemas import DiagnosticFinding, HelpContext

_MISSING = object()


class DiagnosticRuleError(ValueError):
    pass


def _get_path(data: Mapping[str, Any], path: str) -> Any:
    current: Any = data
    for part in path.split("."):
        if isinstance(current, Mapping) and part in current:
            current = current[part]
        else:
            return _MISSING
    return current


def _compare(left: Any, operator: str, right: Any = None) -> bool:
    if left is _MISSING:
        return False
    if operator == "exists":
        return left is not None
    if operator == "not_exists":
        return left is None or left is _MISSING
    if operator == "truthy":
        return bool(left)
    if operator == "falsy":
        return not bool(left)
    if operator == "equals":
        return left == right
    if operator == "not_equals":
        return left != right
    if operator == "contains":
        return str(right).lower() in str(left).lower()
    if operator == "greater_than":
        return float(left) > float(right)
    if operator == "greater_or_equal":
        return float(left) >= float(right)
    if operator == "less_than":
        return float(left) < float(right)
    if operator == "less_or_equal":
        return float(left) <= float(right)
    if operator == "abs_greater_than":
        return abs(float(left)) > float(right)
    if operator == "outside_relative_band":
        tolerance = abs(float(right))
        return float(left) < 1.0 - tolerance or float(left) > 1.0 + tolerance
    raise DiagnosticRuleError(f"Unsupported diagnostic operator: {operator}")


def _condition_matches(condition: Mapping[str, Any], data: Mapping[str, Any]) -> bool:
    if "all" in condition:
        return all(_condition_matches(item, data) for item in condition["all"])
    if "any" in condition:
        return any(_condition_matches(item, data) for item in condition["any"])
    if "not" in condition:
        return not _condition_matches(condition["not"], data)

    path = str(condition.get("path", ""))
    operator = str(condition.get("operator", "equals"))
    left = _get_path(data, path)
    if "value_path" in condition:
        right = _get_path(data, str(condition["value_path"]))
        if right is _MISSING:
            return False
    else:
        right = condition.get("value")
    try:
        return _compare(left, operator, right)
    except (TypeError, ValueError, OverflowError):
        return False


def _flatten_context(context: HelpContext) -> dict[str, Any]:
    payload = context.model_dump(mode="python")
    payload["has_current_result"] = context.has_current_result
    return payload


def _format_value(value: Any, fmt: str | None = None) -> str:
    if value is _MISSING:
        return "未知"
    if fmt is None:
        return str(value)
    if fmt == "percent":
        return f"{float(value) * 100:.4g}%"
    if fmt == "float":
        return f"{float(value):.6g}"
    if fmt == "abs_float":
        return f"{abs(float(value)):.6g}"
    return format(value, fmt)


def _render_template(template: str, data: Mapping[str, Any], fields: Mapping[str, Any]) -> str:
    values: dict[str, str] = {}
    for name, spec in fields.items():
        if isinstance(spec, str):
            path = spec
            fmt = None
        else:
            path = str(spec.get("path", ""))
            fmt = spec.get("format")
        values[name] = _format_value(_get_path(data, path), fmt)
    try:
        return template.format(**values)
    except KeyError as exc:
        raise DiagnosticRuleError(f"Unknown template field {exc} in {template!r}") from exc


class DiagnosticRuleEngine:
    def __init__(self, rules_path: str | Path) -> None:
        payload = yaml.safe_load(Path(rules_path).read_text(encoding="utf-8")) or {}
        self.rules = payload.get("rules", payload if isinstance(payload, list) else [])
        if not isinstance(self.rules, list):
            raise DiagnosticRuleError("Diagnostic rules must be a list")

    def evaluate(self, context: HelpContext) -> list[DiagnosticFinding]:
        data = _flatten_context(context)
        findings: list[DiagnosticFinding] = []
        for rule in self.rules:
            if not isinstance(rule, Mapping):
                continue
            applies_to = [str(item) for item in rule.get("applies_to", [])]
            if applies_to and context.analysis_type and context.analysis_type not in applies_to:
                continue
            condition = rule.get("condition", {})
            if not isinstance(condition, Mapping) or not _condition_matches(condition, data):
                continue
            finding = rule.get("finding", {})
            fields = rule.get("fields", {})
            explanation = _render_template(str(finding.get("text", "")), data, fields)
            source_ids = [str(item) for item in rule.get("sources", [])]
            if context.has_current_result and "context.current_report" not in source_ids:
                source_ids.append("context.current_report")
            findings.append(
                DiagnosticFinding(
                    rule_id=str(rule.get("id", "unknown_rule")),
                    title=str(finding.get("title", rule.get("id", "诊断发现"))),
                    explanation=explanation,
                    source_ids=source_ids,
                    action_ids=[str(item) for item in rule.get("actions", [])],
                    evidence_paths=[str(item) for item in rule.get("evidence_paths", [])],
                    severity=str(rule.get("severity", "warning")),
                )
            )
        severity_order = {"critical": 0, "warning": 1, "info": 2}
        findings.sort(key=lambda item: severity_order.get(item.severity, 9))
        return findings

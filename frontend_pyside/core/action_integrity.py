
from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

BUTTON_CONSTRUCTORS = {
    "QPushButton",
    "QToolButton",
    "PrimaryButton",
    "SecondaryButton",
}
ACTION_SIGNALS = {"clicked", "pressed", "released", "toggled", "triggered"}


@dataclass(frozen=True, slots=True)
class UnboundAction:
    path: Path
    line: int
    variable: str
    constructor: str


def audit_button_actions(paths: Iterable[str | Path]) -> list[UnboundAction]:
    issues: list[UnboundAction] = []
    for raw_path in paths:
        path = Path(raw_path)
        if path.is_dir():
            candidates = path.rglob("*.py")
        elif path.suffix == ".py":
            candidates = (path,)
        else:
            continue
        for candidate in candidates:
            issues.extend(_audit_file(candidate))
    return sorted(issues, key=lambda item: (str(item.path), item.line, item.variable))


def _audit_file(path: Path) -> list[UnboundAction]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    except (OSError, SyntaxError, UnicodeError):
        return []

    created: dict[str, tuple[int, str]] = {}
    connected: set[str] = set()
    menu_bound: set[str] = set()
    exported: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            constructor = _call_name(node.value.func)
            if constructor in BUTTON_CONSTRUCTORS:
                for target in node.targets:
                    name = _target_name(target)
                    if name:
                        created[name] = (node.lineno, constructor)

        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "connect" and isinstance(node.func.value, ast.Attribute):
                signal = node.func.value
                if signal.attr in ACTION_SIGNALS:
                    name = _target_name(signal.value)
                    if name:
                        connected.add(name)
            elif node.func.attr == "setMenu":
                name = _target_name(node.func.value)
                if name:
                    menu_bound.add(name)

        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Name):
            
            
            if any(isinstance(target, (ast.Subscript, ast.List, ast.Tuple)) for target in node.targets):
                exported.add(node.value.id)

        if isinstance(node, ast.Return):
            exported.update(_names_in_expression(node.value))

    issues = []
    for name, (line, constructor) in created.items():
        if name in connected or name in menu_bound or name in exported:
            continue
        issues.append(UnboundAction(path, line, name, constructor))
    return issues


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _target_name(node: ast.AST | None) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _names_in_expression(node: ast.AST | None) -> set[str]:
    if node is None:
        return set()
    names: set[str] = set()
    for child in ast.walk(node):
        name = _target_name(child)
        if name:
            names.add(name)
    return names


__all__ = ["UnboundAction", "audit_button_actions"]

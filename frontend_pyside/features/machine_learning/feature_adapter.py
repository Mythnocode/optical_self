

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

_PATH_TOKEN = re.compile(r"([^\.\[\]]+)|\[(\d+)\]")


class FeaturePathError(ValueError):
    pass


def _tokens(path: str) -> list[str | int]:
    if not path or not isinstance(path, str):
        raise FeaturePathError("feature path must be a non-empty string")
    tokens: list[str | int] = []
    for name, index in _PATH_TOKEN.findall(path):
        tokens.append(int(index) if index else name)
    if not tokens:
        raise FeaturePathError(f"invalid feature path: {path!r}")
    return tokens


def resolve_feature_path(payload: Any, path: str) -> float:


    current = payload
    for token in _tokens(path):
        if isinstance(token, int):
            if not isinstance(current, Sequence) or isinstance(current, (str, bytes, bytearray)):
                raise FeaturePathError(f"{path}: expected a sequence before [{token}]")
            if token >= len(current):
                raise FeaturePathError(f"{path}: index {token} is out of range")
            current = current[token]
        else:
            if isinstance(current, Mapping):
                if token not in current:
                    raise FeaturePathError(f"{path}: missing field {token!r}")
                current = current[token]
            elif hasattr(current, token):
                current = getattr(current, token)
            else:
                raise FeaturePathError(f"{path}: missing attribute {token!r}")

    if isinstance(current, bool):
        return float(current)
    try:
        value = float(current)
    except (TypeError, ValueError) as exc:
        raise FeaturePathError(f"{path}: value {current!r} is not numeric") from exc
    if value != value or value in (float("inf"), float("-inf")):
        raise FeaturePathError(f"{path}: value must be finite")
    return value


def features_from_project(payload: Any, feature_paths: Sequence[str]) -> dict[str, float]:
    """Build exactly the feature vector declared by a trained-model manifest.

    Plain project paths are resolved directly.  Physics-residual features are not
    ordinary JSON fields, so they must be derived from the *current* optical
    project using the same physics feature builder used during dataset creation.
    Missing fields are never replaced with zero or another cosmetic default.
    """
    if not feature_paths:
        raise FeaturePathError("the selected model manifest does not declare feature_paths")

    from machine_learning.features.coupling_physics import (
        PHYSICS_RESIDUAL_FEATURE_PATHS,
        derive_coupling_physics_features,
    )
    from machine_learning.explainability.physics_features import PhysicsFeatureError
    from shared_contracts.project import ProjectSnapshot

    physics_paths = set(PHYSICS_RESIDUAL_FEATURE_PATHS)
    requested_physics = [path for path in feature_paths if path in physics_paths]
    physics: dict[str, float] = {}
    if requested_physics:
        try:
            project = payload if isinstance(payload, ProjectSnapshot) else ProjectSnapshot.model_validate(payload)
            physics = derive_coupling_physics_features(project)
        except (PhysicsFeatureError, TypeError, ValueError) as exc:
            raise FeaturePathError(f"cannot derive coupling physics features: {exc}") from exc

    values: dict[str, float] = {}
    for path in feature_paths:
        if path in physics:
            values[path] = float(physics[path])
        else:
            values[path] = resolve_feature_path(payload, path)
    return values



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


    if not feature_paths:
        raise FeaturePathError("the selected model manifest does not declare feature_paths")
    return {path: resolve_feature_path(payload, path) for path in feature_paths}



from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

_PATH_TOKEN = re.compile(r"([^\.\[\]]+)|\[(\d+)\]")
_LEGACY_SURFACE_PATH = re.compile(r"^surface\.(\d+)\.(.+)$")


def _canonical_feature_path(path: str) -> str:
    text = str(path or "").strip()
    match = _LEGACY_SURFACE_PATH.fullmatch(text)
    if match:
        field = "distance_to_next_mm" if match.group(2) == "thickness_mm" else match.group(2)
        return f"surfaces[{int(match.group(1))}].{field}"
    if text == "wavelength_nm":
        return "source.wavelength_nm"
    return text


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


def _shared_project(payload: Any):
    """Normalize the two project representations used by the desktop app.

    The workbench keeps an editable dataclass, while the backend contracts use
    a pydantic ``ProjectSnapshot``.  Treating the dataclass as if it were the
    pydantic model makes physics feature derivation fail and used to be hidden
    by a broad UI exception, leaving prediction/SHAP with incomplete inputs.
    """
    from shared_contracts.project import ProjectSnapshot

    if isinstance(payload, ProjectSnapshot):
        return payload
    if isinstance(payload, Mapping):
        return ProjectSnapshot.model_validate(payload)
    model_dump = getattr(payload, "model_dump", None)
    if callable(model_dump):
        return ProjectSnapshot.model_validate(model_dump())

    # The editable PySide project is a dataclass and must go through the same
    # serializer used for formal simulation requests.  This preserves canonical
    # paths such as source.wavelength_nm and surfaces[i].distance_to_next_mm.
    if hasattr(payload, "surfaces") and hasattr(payload, "wavelength_nm"):
        from frontend_pyside.api.payloads import serialize_project

        return ProjectSnapshot.model_validate(serialize_project(payload))
    raise TypeError("payload is not a supported optical project")


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

    physics_paths = set(PHYSICS_RESIDUAL_FEATURE_PATHS)
    requested_physics = [path for path in feature_paths if path in physics_paths]
    physics: dict[str, float] = {}
    canonical_project = None
    try:
        canonical_project = _shared_project(payload)
    except (TypeError, ValueError) as exc:
        if requested_physics:
            raise FeaturePathError(f"cannot read optical project: {exc}") from exc
    if requested_physics:
        try:
            physics = derive_coupling_physics_features(canonical_project)
        except (PhysicsFeatureError, TypeError, ValueError) as exc:
            raise FeaturePathError(f"cannot derive coupling physics features: {exc}") from exc

    resolution_payload = canonical_project if canonical_project is not None else payload
    values: dict[str, float] = {}
    for path in feature_paths:
        original_path = str(path)
        canonical_path = _canonical_feature_path(original_path)
        if canonical_path in physics:
            values[original_path] = float(physics[canonical_path])
        elif canonical_path.startswith("surfaces[") and canonical_path.endswith("].active"):
            # Legacy headless datasets exported an ``active`` flag for every
            # surface. It is not a field on SurfaceSnapshot, but it can be
            # reconstructed deterministically for prediction.
            try:
                index = int(canonical_path[len("surfaces[") : canonical_path.index("]")])
                surfaces = list(getattr(resolution_payload, "surfaces", ()) or ())
                values[original_path] = float(
                    index < len(surfaces)
                    and bool(getattr(surfaces[index], "enabled", True))
                )
            except (ValueError, TypeError):
                raise FeaturePathError(f"{original_path}: invalid surface index")
        else:
            values[original_path] = resolve_feature_path(resolution_payload, canonical_path)
    return values

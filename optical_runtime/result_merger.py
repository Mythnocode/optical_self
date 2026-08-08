from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np


class ResultKeyCollisionError(KeyError):
    pass


def _equal(left: Any, right: Any) -> bool:
    try:
        if isinstance(left, np.ndarray) or isinstance(right, np.ndarray):
            return bool(np.array_equal(np.asarray(left), np.asarray(right), equal_nan=True))
        return bool(left == right)
    except Exception:
        return False


@dataclass
class EnginePartialResult:
    metrics: dict[str, Any] = field(default_factory=dict)
    arrays: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[Any] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    converged: bool = True

    @classmethod
    def empty(cls) -> "EnginePartialResult":
        return cls()

    def _protected_merge(
        self,
        target: dict[str, Any],
        incoming: dict[str, Any],
        *,
        collection: str,
        namespace: str | None,
        on_conflict: str,
    ) -> None:
        for key, value in incoming.items():
            if key not in target:
                target[key] = value
                continue
            if _equal(target[key], value):
                continue
            message = f"result key collision in {collection}: {key!r}"
            if on_conflict == "raise":
                raise ResultKeyCollisionError(message)
            if on_conflict == "keep_first":
                self.warnings.append(message + "; kept first value")
                continue
            if on_conflict == "replace":
                self.warnings.append(message + "; replaced explicitly")
                target[key] = value
                continue
            
            
            prefix = namespace or "collision"
            candidate = f"{prefix}.{key}"
            suffix = 2
            while candidate in target:
                candidate = f"{prefix}.{suffix}.{key}"
                suffix += 1
            target[candidate] = value
            self.warnings.append(message + f"; second value stored as {candidate!r}")

    def merge(
        self,
        other: "EnginePartialResult",
        *,
        namespace: str | None = None,
        on_conflict: str = "namespace",
    ) -> "EnginePartialResult":
        self._protected_merge(self.metrics, other.metrics, collection="metrics", namespace=namespace, on_conflict=on_conflict)
        self._protected_merge(self.arrays, other.arrays, collection="arrays", namespace=namespace, on_conflict=on_conflict)
        self.warnings.extend(other.warnings)
        self.errors.extend(other.errors)
        self._protected_merge(self.metadata, other.metadata, collection="metadata", namespace=namespace, on_conflict=on_conflict)
        self.converged = self.converged and other.converged
        return self

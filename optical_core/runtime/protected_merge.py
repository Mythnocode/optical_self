
from __future__ import annotations

from typing import Any, Iterable, Mapping

import numpy as np


class ArtifactKeyCollisionError(KeyError):
    pass


def _equivalent(left: Any, right: Any) -> bool:
    try:
        if isinstance(left, np.ndarray) or isinstance(right, np.ndarray):
            return bool(np.array_equal(np.asarray(left), np.asarray(right), equal_nan=True))
        return bool(left == right)
    except Exception:
        return False


def merge_unique_mappings(
    *mappings: Mapping[str, Any],
    collection: str = "artifact",
) -> dict[str, Any]:


    result: dict[str, Any] = {}
    for mapping in mappings:
        for key, value in mapping.items():
            if key not in result:
                result[key] = value
                continue
            if _equivalent(result[key], value):
                continue
            raise ArtifactKeyCollisionError(
                f"{collection} key collision: {key!r}; use an explicit namespace"
            )
    return result


def merge_unique_pairs(
    pairs: Iterable[tuple[str, Any]],
    *,
    collection: str = "artifact",
) -> dict[str, Any]:
    return merge_unique_mappings(dict(pairs), collection=collection)


__all__ = ["ArtifactKeyCollisionError", "merge_unique_mappings", "merge_unique_pairs"]

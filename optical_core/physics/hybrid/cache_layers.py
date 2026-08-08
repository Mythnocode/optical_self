
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generic, Hashable, TypeVar

K = TypeVar("K", bound=Hashable)
V = TypeVar("V")


@dataclass(slots=True)
class MemoryCache(Generic[K, V]):
    values: dict[K, V] = field(default_factory=dict)
    hits: int = 0
    misses: int = 0

    def get(self, key: K) -> V | None:
        if key in self.values:
            self.hits += 1
            return self.values[key]
        self.misses += 1
        return None

    def put(self, key: K, value: V) -> V:
        self.values[key] = value
        return value

    def clear(self) -> None:
        self.values.clear()
        self.hits = 0
        self.misses = 0

    def metrics(self) -> dict[str, int]:
        return {"size": len(self.values), "hits": self.hits, "misses": self.misses}


class RayTraceCache(MemoryCache[K, V]):
    pass


class PupilFieldCache(MemoryCache[K, V]):
    pass


class PropagationSpectrumCache(MemoryCache[K, V]):
    pass


class FiberModeCache(MemoryCache[K, V]):
    pass


class ToleranceOperatorCache(MemoryCache[K, V]):
    pass


__all__ = [
    "MemoryCache",
    "RayTraceCache",
    "PupilFieldCache",
    "PropagationSpectrumCache",
    "FiberModeCache",
    "ToleranceOperatorCache",
]

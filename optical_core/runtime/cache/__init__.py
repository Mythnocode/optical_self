from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import hashlib
import json
import pickle
import sys
from typing import Any, Callable, Generic, TypeVar

T = TypeVar("T")


def stable_fingerprint(value: Any) -> str:

    try:
        payload = json.dumps(value, sort_keys=True, default=_json_default).encode("utf-8")
    except TypeError:
        payload = pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True, slots=True)
class CacheStats:
    item_count: int
    total_bytes: int
    hit_count: int
    miss_count: int
    eviction_count: int

    @property
    def hit_rate(self) -> float:
        total = self.hit_count + self.miss_count
        return float(self.hit_count / total) if total else 0.0


class LRUCache(Generic[T]):
    def __init__(
        self,
        *,
        max_items: int = 128,
        max_bytes: int | None = None,
        sizer: Callable[[T], int] | None = None,
    ):
        self.max_items = max(1, int(max_items))
        self.max_bytes = max_bytes if max_bytes is None else max(1, int(max_bytes))
        self._sizer = sizer or approximate_size_bytes
        self._items: OrderedDict[str, tuple[T, int]] = OrderedDict()
        self._bytes = 0
        self._hits = 0
        self._misses = 0
        self._evictions = 0

    def get(self, key: str, default: T | None = None) -> T | None:
        if key not in self._items:
            self._misses += 1
            return default

        value, size = self._items.pop(key)
        self._items[key] = (value, size)
        self._hits += 1
        return value

    def put(self, key: str, value: T) -> None:
        size = int(max(0, self._sizer(value)))

        if key in self._items:
            _, old_size = self._items.pop(key)
            self._bytes -= old_size

        self._items[key] = (value, size)
        self._bytes += size
        self._trim()

    def get_or_compute(self, key: str, factory: Callable[[], T]) -> T:
        existing = self.get(key)
        if existing is not None:
            return existing

        value = factory()
        self.put(key, value)
        return value

    def clear(self) -> None:
        self._items.clear()
        self._bytes = 0

    def keys(self) -> tuple[str, ...]:
        return tuple(self._items.keys())

    def stats(self) -> CacheStats:
        return CacheStats(
            item_count=len(self._items),
            total_bytes=self._bytes,
            hit_count=self._hits,
            miss_count=self._misses,
            eviction_count=self._evictions,
        )

    def _trim(self) -> None:
        while len(self._items) > self.max_items:
            _, (_, size) = self._items.popitem(last=False)
            self._bytes -= size
            self._evictions += 1

        if self.max_bytes is not None:
            while self._items and self._bytes > self.max_bytes:
                _, (_, size) = self._items.popitem(last=False)
                self._bytes -= size
                self._evictions += 1


class TraceCache(LRUCache[Any]):
    pass


class FieldCache(LRUCache[Any]):
    pass


def approximate_size_bytes(value: Any) -> int:
    nbytes = getattr(value, "nbytes", None)
    if nbytes is not None:
        return int(nbytes)

    if isinstance(value, dict):
        return sum(
            approximate_size_bytes(k) + approximate_size_bytes(v)
            for k, v in value.items()
        )

    if isinstance(value, (list, tuple, set, frozenset)):
        return sum(approximate_size_bytes(v) for v in value) + sys.getsizeof(value)

    return sys.getsizeof(value)


def _json_default(value: Any) -> Any:
    if hasattr(value, "tolist"):
        return value.tolist()

    if hasattr(value, "__dict__"):
        return dict(value.__dict__)

    return repr(value)


__all__ = [
    "stable_fingerprint",
    "CacheStats",
    "LRUCache",
    "TraceCache",
    "FieldCache",
    "approximate_size_bytes",
]
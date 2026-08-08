from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import time
from typing import Iterator


@dataclass(frozen=True, slots=True)
class ProfileRecord:
    name: str
    elapsed_ms: float
    metadata: dict[str, object]


class RuntimeProfiler:
    def __init__(self) -> None:
        self.records: list[ProfileRecord] = []

    @contextmanager
    def span(self, name: str, **metadata: object) -> Iterator[None]:
        start = time.perf_counter()
        try:
            yield
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            self.records.append(ProfileRecord(name=name, elapsed_ms=elapsed_ms, metadata=dict(metadata)))

    def add_record(self, name: str, elapsed_ms: float, **metadata: object) -> None:
        self.records.append(ProfileRecord(name=name, elapsed_ms=float(elapsed_ms), metadata=dict(metadata)))

    def summary(self) -> dict[str, object]:
        total = sum(record.elapsed_ms for record in self.records)
        by_name: dict[str, float] = {}
        for record in self.records:
            by_name[record.name] = by_name.get(record.name, 0.0) + record.elapsed_ms
        return {
            "profile_total_ms": total,
            "profile_record_count": len(self.records),
            "profile_by_name_ms": by_name,
            "profile_records": [
                {"name": r.name, "elapsed_ms": r.elapsed_ms, "metadata": r.metadata}
                for r in self.records
            ],
        }


def time_call(name: str, func, *args, profiler: RuntimeProfiler | None = None, **kwargs):
    local_profiler = profiler or RuntimeProfiler()
    with local_profiler.span(name):
        return func(*args, **kwargs)

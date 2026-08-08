
from __future__ import annotations

from collections import defaultdict, deque
from contextlib import contextmanager
from dataclasses import dataclass
from threading import RLock
from typing import Iterator

import numpy as np
from scipy import fft as scipy_fft


@dataclass(slots=True)
class PropagationWorkspace:
    shape: tuple[int, int]
    spectrum: np.ndarray
    spectral_product: np.ndarray
    output: np.ndarray | None
    intensity: np.ndarray

    @classmethod
    def allocate(cls, shape: tuple[int, int]) -> "PropagationWorkspace":
        shape = (int(shape[0]), int(shape[1]))
        return cls(
            shape=shape,
            spectrum=np.empty(shape, dtype=np.complex128),
            spectral_product=np.empty(shape, dtype=np.complex128),
            output=None,
            intensity=np.empty(shape, dtype=np.float64),
        )

    @property
    def nbytes(self) -> int:
        return int(
            self.spectrum.nbytes
            + self.spectral_product.nbytes
            + (0 if self.output is None else self.output.nbytes)
            + self.intensity.nbytes
        )

    def fft2(self, values: np.ndarray) -> np.ndarray:
        source = np.asarray(values, dtype=np.complex128)
        try:
            transformed = np.fft.fft2(source, out=self.spectrum)
            if transformed is not self.spectrum:
                np.copyto(self.spectrum, transformed)
        except TypeError:  
            np.copyto(self.spectrum, np.fft.fft2(source))
        return self.spectrum

    def propagate_spectrum(self, transfer: np.ndarray) -> np.ndarray:
        np.multiply(self.spectrum, transfer, out=self.spectral_product)
        
        
        transformed = scipy_fft.ifft2(self.spectral_product, overwrite_x=True)
        if not np.shares_memory(transformed, self.spectral_product):
            if self.output is None:
                self.output = np.empty(self.shape, dtype=np.complex128)
            np.copyto(self.output, transformed)
            return self.output
        return transformed

    def update_intensity(self, values: np.ndarray | None = None) -> np.ndarray:
        source = self.output if values is None else np.asarray(values)
        np.abs(source, out=self.intensity)
        np.square(self.intensity, out=self.intensity)
        return self.intensity


class PropagationWorkspacePool:


    def __init__(self, max_bytes: int = 768 * 1024**2) -> None:
        self.max_bytes = max(0, int(max_bytes))
        self._available: dict[tuple[int, int], deque[PropagationWorkspace]] = defaultdict(deque)
        self._available_bytes = 0
        self._created = 0
        self._reused = 0
        self._leased = 0
        self._lock = RLock()

    @contextmanager
    def acquire(self, shape: tuple[int, int]) -> Iterator[PropagationWorkspace]:
        key = (int(shape[0]), int(shape[1]))
        workspace: PropagationWorkspace | None = None
        with self._lock:
            bucket = self._available.get(key)
            if bucket:
                workspace = bucket.pop()
                self._available_bytes -= workspace.nbytes
                self._reused += 1
            self._leased += 1
        if workspace is None:
            workspace = PropagationWorkspace.allocate(key)
            with self._lock:
                self._created += 1
        try:
            yield workspace
        finally:
            with self._lock:
                self._leased -= 1
                if workspace.nbytes <= self.max_bytes:
                    self._available[key].append(workspace)
                    self._available_bytes += workspace.nbytes
                    self._trim_unlocked()

    def _trim_unlocked(self) -> None:
        if self._available_bytes <= self.max_bytes:
            return
        
        for key in sorted(self._available, key=lambda item: item[0] * item[1], reverse=True):
            bucket = self._available[key]
            while bucket and self._available_bytes > self.max_bytes:
                self._available_bytes -= bucket.popleft().nbytes
            if not bucket:
                self._available.pop(key, None)
            if self._available_bytes <= self.max_bytes:
                break

    def clear(self) -> None:
        with self._lock:
            self._available.clear()
            self._available_bytes = 0

    def info(self) -> dict[str, int]:
        with self._lock:
            return {
                "created": int(self._created),
                "reused": int(self._reused),
                "leased": int(self._leased),
                "available_count": int(sum(len(v) for v in self._available.values())),
                "available_bytes": int(self._available_bytes),
                "max_bytes": int(self.max_bytes),
            }


_GLOBAL_PROPAGATION_WORKSPACE_POOL = PropagationWorkspacePool()


def global_propagation_workspace_pool() -> PropagationWorkspacePool:
    return _GLOBAL_PROPAGATION_WORKSPACE_POOL


def clear_global_propagation_workspaces() -> None:
    _GLOBAL_PROPAGATION_WORKSPACE_POOL.clear()


def global_propagation_workspace_info() -> dict[str, int]:
    return _GLOBAL_PROPAGATION_WORKSPACE_POOL.info()


__all__ = [
    "PropagationWorkspace",
    "PropagationWorkspacePool",
    "global_propagation_workspace_pool",
    "clear_global_propagation_workspaces",
    "global_propagation_workspace_info",
]

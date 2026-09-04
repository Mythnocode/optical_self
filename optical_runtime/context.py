
from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
import hashlib
import json
import struct
from typing import Any, Callable

import numpy as np

from optical_core.coordinates import DEFAULT_COORDINATE_CONVENTION
from optical_core.models.domain.aperture import CircularApertureDefinition
from optical_core.models.domain.receiver import FiberReceiver
from optical_core.models.domain.source import OpticalSource
from optical_core.models.domain.system import SequentialOpticalSystem
from optical_core.models.representations.trace import TraceBundle


TRACE_AFFECTING_OPTION_KEYS = frozenset({
    "wavelength_nm", "pupil_sample_count", "pupil_radius_mm",
    "explicit_pupil_samples", "source_model", "object_distance_mm",
    "object_space_na", "field_x_deg", "field_y_deg", "start_z_mm",
    "beam_quality_m2",
    "apodization_type", "apodization_factor",
    "apodization_factor_x", "apodization_factor_y",
    "source_wavefront_radius_x_mm", "source_wavefront_radius_y_mm",
    "source_waist_position_mm",
    "include_source_to_pupil_opl", "record_surfaces",
    "propagate_to_image", "evaluate_apertures",
    "max_intersection_iterations", "sampling_role", "trace_output_level",
    "polarization_sensitive", "vector_coupling_enabled",
})


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def _hash_update(hasher: Any, value: Any) -> None:

    if is_dataclass(value):
        _hash_update(hasher, asdict(value))
        return
    if isinstance(value, np.ndarray):
        array = np.ascontiguousarray(value)
        hasher.update(b"A")
        hasher.update(array.dtype.str.encode("ascii"))
        hasher.update(repr(tuple(array.shape)).encode("ascii"))
        hasher.update(memoryview(array).cast("B"))
        return
    if isinstance(value, np.generic):
        _hash_update(hasher, value.item())
        return
    if isinstance(value, dict):
        hasher.update(b"{")
        for key in sorted(value, key=lambda item: str(item)):
            _hash_update(hasher, str(key))
            _hash_update(hasher, value[key])
        hasher.update(b"}")
        return
    if isinstance(value, tuple):
        hasher.update(b"(")
        for item in value:
            _hash_update(hasher, item)
        hasher.update(b")")
        return
    if isinstance(value, list):
        hasher.update(b"[")
        for item in value:
            _hash_update(hasher, item)
        hasher.update(b"]")
        return
    if value is None:
        hasher.update(b"N")
    elif isinstance(value, bool):
        hasher.update(b"T" if value else b"F")
    elif isinstance(value, int):
        hasher.update(b"I" + str(value).encode("ascii"))
    elif isinstance(value, float):
        hasher.update(b"D" + struct.pack("!d", float(value)))
    elif isinstance(value, str):
        encoded = value.encode("utf-8")
        hasher.update(b"S" + str(len(encoded)).encode("ascii") + b":" + encoded)
    else:
        _hash_update(hasher, repr(value))


@dataclass(frozen=True, slots=True)
class ExecutionProfile:
    precision: str
    pupil_sample_count: int
    wave_grid_size: int
    max_intersection_iterations: int
    record_surfaces: bool
    random_seed: int


@dataclass(frozen=True, slots=True)
class SimulationScene:
    system: SequentialOpticalSystem
    source: OpticalSource
    receiver: FiberReceiver | None
    aperture: CircularApertureDefinition
    execution_profile: ExecutionProfile
    options: dict[str, Any]
    project_data: dict[str, Any]


@dataclass(frozen=True, slots=True)
class TraceKey:


    options_digest: str

    def token(self) -> str:
        return self.options_digest[:16]


@dataclass(slots=True)
class SimulationContext:
    scene: SimulationScene
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    artifacts: dict[str, Any] = field(default_factory=dict)
    _trace_cache: dict[TraceKey, TraceBundle] = field(default_factory=dict)
    shared_trace_cache: Any | None = None
    trace_build_count: int = 0
    trace_progress_callback: Any | None = None

    def __post_init__(self) -> None:
        self.metadata.update(
            {
                "coordinate_system": DEFAULT_COORDINATE_CONVENTION.coordinate_system_id,
                "coordinate_handedness": DEFAULT_COORDINATE_CONVENTION.handedness,
                "optical_axis": DEFAULT_COORDINATE_CONVENTION.optical_axis,
                "propagation_direction": "+z",
                "zemax_data_used_as_input": False,
                "reference_data_used_as_input": False,
            }
        )

    def canonical_trace_options(self, options: dict[str, Any] | None = None) -> dict[str, Any]:
        raw = dict(options or {})
        opts = {key: raw[key] for key in TRACE_AFFECTING_OPTION_KEYS if key in raw}
        profile = self.scene.execution_profile
        source = self.scene.source
        opts.setdefault("wavelength_nm", source.wavelength_nm)
        opts.setdefault("pupil_sample_count", profile.pupil_sample_count)
        opts.setdefault("pupil_radius_mm", self.scene.aperture.radius_mm)
        opts.setdefault("source_model", source.source_type or "parallel_pupil")
        opts.setdefault("object_distance_mm", self.scene.system.object_distance_mm)
        opts.setdefault("object_space_na", max(source.object_na_x, source.object_na_y))
        opts.setdefault("field_x_deg", source.field_x_deg)
        opts.setdefault("field_y_deg", source.field_y_deg)
        opts.setdefault("beam_quality_m2", source.beam_quality_m2)
        opts.setdefault("start_z_mm", -1.0e-6)
        opts.setdefault("max_intersection_iterations", profile.max_intersection_iterations)
        opts["record_surfaces"] = bool(opts.get("record_surfaces", False) or profile.record_surfaces)
        opts.setdefault("propagate_to_image", True)
        opts.setdefault("evaluate_apertures", True)
        opts.setdefault("sampling_role", "geometric_analysis")
        opts.setdefault("trace_output_level", "planes" if opts["record_surfaces"] else "final")
        if "gaussian" in str(source.source_type).lower() or source.waist_x_mm > 0.0 or source.waist_y_mm > 0.0:
            opts.setdefault("apodization_type", "gaussian_elliptical")
            radius = float(opts["pupil_radius_mm"])
            waist_x = source.waist_x_mm if source.waist_x_mm > 0.0 else source.waist_y_mm
            waist_y = source.waist_y_mm if source.waist_y_mm > 0.0 else source.waist_x_mm
            if waist_x > 0.0:
                opts.setdefault("apodization_factor_x", (radius / waist_x) ** 2)
            if waist_y > 0.0:
                opts.setdefault("apodization_factor_y", (radius / waist_y) ** 2)
        return opts

    def trace_key(self, options: dict[str, Any] | None = None) -> TraceKey:
        opts = self.canonical_trace_options(options)
        
        
        payload_object = {
            "system": self.scene.system,
            "source": self.scene.source,
            "aperture": self.scene.aperture,
            "options": opts,
        }
        digest = hashlib.sha256()
        _hash_update(digest, payload_object)
        return TraceKey(digest.hexdigest())

    def get_or_create_trace(self, options: dict[str, Any] | None = None) -> TraceBundle:
        opts = self.canonical_trace_options(options)
        key = self.trace_key(opts)
        if key in self._trace_cache:
            self.metadata["shared_trace_cache_hits"] = int(self.metadata.get("shared_trace_cache_hits", 0)) + 1
            return self._trace_cache[key]
        if self.shared_trace_cache is not None:
            shared = self.shared_trace_cache.get(key.options_digest)
            if shared is not None:
                self._trace_cache[key] = shared
                self.metadata["engine_trace_cache_hits"] = int(self.metadata.get("engine_trace_cache_hits", 0)) + 1
                return shared
            lock_factory = getattr(self.shared_trace_cache, "key_lock", None)
            if callable(lock_factory):
                with lock_factory(key.options_digest):
                    shared = self.shared_trace_cache.get(key.options_digest)
                    if shared is not None:
                        self._trace_cache[key] = shared
                        self.metadata["engine_trace_cache_hits"] = int(self.metadata.get("engine_trace_cache_hits", 0)) + 1
                        return shared
                    return self._build_trace_and_cache(opts, key)

        return self._build_trace_and_cache(opts, key)

    def _build_trace_and_cache(self, opts: dict[str, Any], key: TraceKey) -> TraceBundle:
        from optical_core.physics.geometric.operators.pupil_sampling import (
            sample_explicit_pupil_rays,
            sample_pupil_grid,
        )
        from optical_core.physics.geometric.solvers.batch_raytrace import trace_ray_batch
        from optical_core.physics.geometric.solvers.trace_options import TraceOptions

        common = {
            "pupil_radius_mm": float(opts["pupil_radius_mm"]),
            "wavelength_nm": float(opts["wavelength_nm"]),
            "start_z_mm": float(opts.get("start_z_mm", -1.0e-6)),
            "source_model": str(opts.get("source_model", "parallel_pupil")),
            "beam_quality_m2": float(opts.get("beam_quality_m2", 1.0)),
            "object_distance_mm": float(opts.get("object_distance_mm", 0.0) or 0.0),
            "object_space_na": None if opts.get("object_space_na") is None else float(opts["object_space_na"]),
            "field_x_deg": float(opts.get("field_x_deg", 0.0)),
            "field_y_deg": float(opts.get("field_y_deg", 0.0)),
            "apodization_type": opts.get("apodization_type"),
            "apodization_factor": None if opts.get("apodization_factor") is None else float(opts["apodization_factor"]),
            "apodization_factor_x": None if opts.get("apodization_factor_x") is None else float(opts["apodization_factor_x"]),
            "apodization_factor_y": None if opts.get("apodization_factor_y") is None else float(opts["apodization_factor_y"]),
            "source_wavefront_radius_x_mm": (
                None if opts.get("source_wavefront_radius_x_mm") is None
                else float(opts["source_wavefront_radius_x_mm"])
            ),
            "source_wavefront_radius_y_mm": (
                None if opts.get("source_wavefront_radius_y_mm") is None
                else float(opts["source_wavefront_radius_y_mm"])
            ),
            "include_source_to_pupil_opl": bool(opts.get("include_source_to_pupil_opl", False)),
        }
        explicit = opts.get("explicit_pupil_samples")
        if explicit is None:
            rays = sample_pupil_grid(sample_count=int(opts["pupil_sample_count"]), **common)
        else:
            rays = sample_explicit_pupil_rays(samples=explicit, **common)
        trace = trace_ray_batch(
            self.scene.system,
            rays,
            TraceOptions(
                wavelength_nm=float(opts["wavelength_nm"]),
                pupil_sample_count=int(rays.valid_mask.size),
                record_surfaces=bool(opts["record_surfaces"]),
                propagate_to_image=bool(opts.get("propagate_to_image", True)),
                evaluate_apertures=bool(opts.get("evaluate_apertures", True)),
                max_intersection_iterations=int(opts["max_intersection_iterations"]),
                output_level=str(opts.get("trace_output_level", "planes")),
                polarization_sensitive=bool(opts.get("polarization_sensitive", False) or opts.get("vector_coupling_enabled", False)),
            ),
            progress_callback=self.trace_progress_callback,
        )
        self._trace_cache[key] = trace
        if self.shared_trace_cache is not None:
            self.shared_trace_cache.put(key.options_digest, trace)
        self.trace_build_count += 1
        self.metadata["shared_trace_build_count"] = self.trace_build_count
        self.metadata["shared_trace_keys"] = [item.token() for item in self._trace_cache]
        self.metadata["source_field_sampling"] = {
            "source_model": str(opts.get("source_model", "parallel_pupil")),
            "apodization_type": opts.get("apodization_type"),
            "apodization_factor_x": opts.get("apodization_factor_x", opts.get("apodization_factor")),
            "apodization_factor_y": opts.get("apodization_factor_y", opts.get("apodization_factor")),
        }
        return trace

    def get_or_create_artifact(self, key: str, factory: Callable[[], Any]) -> Any:
        if key not in self.artifacts:
            self.artifacts[key] = factory()
        return self.artifacts[key]

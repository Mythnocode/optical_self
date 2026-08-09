
from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Iterable


class AnalysisCategory(str, Enum):
    GEOMETRIC = "geometric"
    WAVE = "wave"
    HYBRID = "hybrid"


@dataclass(frozen=True, slots=True)
class AnalysisDefinition:
    name: str
    category: AnalysisCategory
    aliases: tuple[str, ...] = ()
    requires_trace: bool = False
    requires_complex_field: bool = False
    production: bool = True
    executor: str = "default"


class AnalysisRegistry:
    def __init__(self, definitions: Iterable[AnalysisDefinition]) -> None:
        self._definitions: dict[str, AnalysisDefinition] = {}
        self._aliases: dict[str, str] = {}
        for definition in definitions:
            name = self._normalize(definition.name)
            if name in self._definitions:
                raise KeyError(f"duplicate analysis: {name}")
            self._definitions[name] = definition
            for alias in definition.aliases:
                key = self._normalize(alias)
                if key in self._definitions and key != name:
                    raise KeyError(f"duplicate analysis alias: {key}")
                existing = self._aliases.get(key)
                if existing is not None and existing != name:
                    raise KeyError(f"duplicate analysis alias: {key}")
                self._aliases[key] = name

    @staticmethod
    def _normalize(name: str) -> str:
        return str(name or "").strip().lower().replace(" ", "_").replace("-", "_")

    def canonical_name(self, name: str) -> str:
        key = self._normalize(name)
        return self._aliases.get(key, key)

    def resolve(self, name: str) -> AnalysisDefinition:
        canonical = self.canonical_name(name)
        try:
            return self._definitions[canonical]
        except KeyError as exc:
            raise KeyError(f"unsupported optical analysis: {name!r}") from exc

    def get(self, name: str) -> AnalysisDefinition | None:
        return self._definitions.get(self.canonical_name(name))

    def definitions(self) -> tuple[AnalysisDefinition, ...]:
        return tuple(self._definitions[name] for name in sorted(self._definitions))

    def names(self, category: AnalysisCategory | None = None) -> set[str]:
        return {
            name for name, definition in self._definitions.items()
            if category is None or definition.category is category
        }

    def public_names(
        self,
        category: AnalysisCategory | None = None,
        *,
        include_aliases: bool = True,
    ) -> tuple[str, ...]:


        canonical = self.names(category)
        names = set(canonical)
        if include_aliases:
            names.update(
                alias
                for alias, target in self._aliases.items()
                if target in canonical
            )
        return tuple(sorted(names))


def _definitions() -> list[AnalysisDefinition]:
    g = AnalysisCategory.GEOMETRIC
    w = AnalysisCategory.WAVE
    h = AnalysisCategory.HYBRID
    items: list[AnalysisDefinition] = [
        AnalysisDefinition("raytrace", g, aliases=("ray_trace",), requires_trace=True),
        AnalysisDefinition("scene_raytrace", g, aliases=("teaching_scene_raytrace", "free_scene_raytrace")),
        AnalysisDefinition("spot", g, aliases=("spot_diagram", "spot_analysis"), requires_trace=True),
        AnalysisDefinition("throughput", g, requires_trace=True),
        AnalysisDefinition("power_audit", g, aliases=("throughput_audit",), requires_trace=True),
        AnalysisDefinition("focus_search", g, aliases=("best_focus", "strehl_focus"), requires_trace=True),
        AnalysisDefinition("material_transmission", g, aliases=("transmission_budget",)),
        AnalysisDefinition("ghost_stray_light", g, aliases=("ghost", "stray_light", "ray_tree")),
        AnalysisDefinition("ray_fan", g),
        AnalysisDefinition("distortion", g),
        AnalysisDefinition("field_curvature", g),
        AnalysisDefinition("chromatic", g),
        AnalysisDefinition("first_order", g),
        AnalysisDefinition("seidel", g),
        AnalysisDefinition("diffraction", w, aliases=("scalar_diffraction", "wave_optics", "wave-optics")),
        AnalysisDefinition("interference", w),
        AnalysisDefinition("coherence", w),
        AnalysisDefinition("psf", w),
        AnalysisDefinition("mtf", w),
        AnalysisDefinition("wavefront", w),
        AnalysisDefinition("polarization", w),
        AnalysisDefinition("grating", w, aliases=("grating_diffraction",)),
        AnalysisDefinition("material_index", w),
        AnalysisDefinition("fresnel_interface", w, aliases=("polarized_interface", "polarized_interfaces", "polarized_fresnel", "fresnel_jones")),
        AnalysisDefinition("thin_film", w, aliases=("thinfilm",)),
        AnalysisDefinition("fabry_perot", w, aliases=("fabryperot",)),
        AnalysisDefinition("fourier_optics", w),
        AnalysisDefinition("fourier_transform", w),
        AnalysisDefinition("fraunhofer_diffraction", w),
        AnalysisDefinition("fresnel_propagation", w),
        AnalysisDefinition("angular_spectrum", w),
        AnalysisDefinition("coherent_imaging", w),
        AnalysisDefinition("spatial_filtering", w),
        AnalysisDefinition("fourier_psf_mtf", w),
        AnalysisDefinition("birefringence", w),
        AnalysisDefinition("uniaxial_crystal", w),
        AnalysisDefinition("crystal_retardance", w),
        AnalysisDefinition("waveplate_from_crystal", w),
        AnalysisDefinition("effective_extraordinary_index", w),
        AnalysisDefinition("ordinary_extraordinary_split", w),
        AnalysisDefinition("crystal_summary", w),
        AnalysisDefinition("polarization_diagnostics", w),
        AnalysisDefinition("analyzer_scan_diagnostics", w),
        AnalysisDefinition("malus_fit", w),
        AnalysisDefinition("stokes_from_scan", w),
        AnalysisDefinition("polarization_state_compare", w),
        AnalysisDefinition("stokes_error", w),
        AnalysisDefinition("polarization_ellipse_diagnostics", w),
        AnalysisDefinition("polarization_interference", w),
        AnalysisDefinition("two_beam_polarization_interference", w),
        AnalysisDefinition("polarization_phase_scan", w),
        AnalysisDefinition("young_polarization_interference", w),
        AnalysisDefinition("analyzer_restored_interference", w),
        AnalysisDefinition("polarization_complementarity", w),
        AnalysisDefinition("coupling", h, aliases=("fiber_coupling", "fibre_coupling"), requires_trace=True, requires_complex_field=True),
        AnalysisDefinition("detector", h, requires_trace=True, requires_complex_field=True),
        AnalysisDefinition("exit_pupil", h, requires_trace=True, requires_complex_field=True),
        AnalysisDefinition("wavefront_quality", h, requires_trace=True),
        AnalysisDefinition("psf_mtf", h, aliases=("hybrid_psf_mtf",), requires_trace=True, requires_complex_field=True),
        AnalysisDefinition("na_stop_fiber", h, aliases=("fiber_mode", "fibre_mode", "stop_radius")),
        AnalysisDefinition("wavefront_tools", h, aliases=("zernike_tools", "wavefront_map")),
        AnalysisDefinition("quality_audit", h, aliases=("audit_suite", "standard_benchmarks")),
        AnalysisDefinition("fiber_tolerance", h, aliases=("fibre_tolerance", "coupling_tolerance", "fiber_offset_tolerance"), requires_trace=True, requires_complex_field=True),
        AnalysisDefinition(
            "fiber_alignment",
            h,
            aliases=("fibre_alignment", "fiber_auto_alignment", "auto_fiber_alignment"),
            requires_trace=True,
            requires_complex_field=True,
        ),
        AnalysisDefinition("coupling_research", h, aliases=("coupling_study", "coupling_mechanism"), requires_trace=True, requires_complex_field=True),
    ]
    geometric_trace = {"raytrace", "spot", "throughput", "power_audit", "focus_search"}
    wave_propagation = {"diffraction", "psf", "mtf", "wavefront"}
    wave_option_dataclass = {"interference", "coherence", "polarization"}
    routed: list[AnalysisDefinition] = []
    for item in items:
        if item.category is g:
            if item.name == "ghost_stray_light":
                executor = "geometric_ghost_stray_light"
            elif item.name == "scene_raytrace":
                executor = "geometric_scene_raytrace"
            else:
                executor = f"geometric_{item.name}" if item.name in geometric_trace else "geometric_native"
        elif item.category is w:
            if item.name in wave_propagation:
                executor = "wave_propagation"
            elif item.name in wave_option_dataclass:
                executor = "wave_option_dataclass"
            else:
                executor = "wave_formula"
        else:
            executor = f"hybrid_{item.name}"
        routed.append(replace(item, executor=executor))
    return routed


DEFAULT_ANALYSIS_REGISTRY = AnalysisRegistry(_definitions())

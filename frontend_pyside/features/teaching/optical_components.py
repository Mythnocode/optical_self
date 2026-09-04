from __future__ import annotations

"""Unified optical-component model for the teaching workbench.

Visual placement (scene x/y, Quick3D asset) and optical prescription stay on the
same component object, but live in separate nested models so display code never
invents a second Lens type and solvers never read QML transforms.
"""

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping


@dataclass(slots=True)
class VisualModel:
    """Screen / Quick3D placement only — never fed to the raytrace engine."""

    scene_x: float = 0.0
    scene_y: float = 0.0
    rotation_deg: float = 0.0
    height_mm: float = 82.0
    asset_kind: str = ""


@dataclass(slots=True)
class OpticalModel:
    """Prescription / source / detector fields consumed by formal optics."""

    params: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class OpticalComponent:
    """Parent of every teaching optical device that can enter OpticalSystem."""

    component_id: str
    kind: str
    label: str
    visual: VisualModel = field(default_factory=VisualModel)
    optical: OpticalModel = field(default_factory=OpticalModel)
    enabled: bool = True

    @property
    def params(self) -> dict[str, Any]:
        return self.optical.params

    def to_node_dict(self) -> dict[str, Any]:
        return {
            "id": self.component_id,
            "kind": self.kind,
            "label": self.label,
            "x": float(self.visual.scene_x),
            "y": float(self.visual.scene_y),
            "rotation_deg": float(self.visual.rotation_deg),
            "params": dict(self.optical.params),
            "enabled": bool(self.enabled),
        }


@dataclass(slots=True)
class LaserComponent(OpticalComponent):
    """Laser source component."""


@dataclass(slots=True)
class LensComponent(OpticalComponent):
    """Refractive lens component."""


@dataclass(slots=True)
class MirrorComponent(OpticalComponent):
    """Mirror / fold component."""


@dataclass(slots=True)
class CCDComponent(OpticalComponent):
    """CCD / area detector — tray label ``ccd``; may store kind ``ccd``."""


@dataclass(slots=True)
class FiberComponent(OpticalComponent):
    """Fiber coupler / five-axis stage."""



# Map tray / MIME kinds onto concrete component classes.
_KIND_CLASS: dict[str, type[OpticalComponent]] = {
    "laser": LaserComponent,
    "lens": LensComponent,
    "mirror": MirrorComponent,
    "ccd": CCDComponent,
    "imaging_camera": CCDComponent,
    "camera": CCDComponent,
    "fiber": FiberComponent,
}

# Kinds that participate in formal OpticalSystem.components (sources, lenses, detectors).
OPTICAL_SYSTEM_KINDS = frozenset({
    "laser", "lens", "mirror", "ccd", "imaging_camera", "camera", "fiber",
    "beam_analyzer", "focus_scan_module",
})


class DeviceFactory:
    """Create one OpticalComponent from a teaching tray drop or preset spec."""

    _counters: dict[str, int] = {}

    @classmethod
    def reset_counters(cls) -> None:
        cls._counters.clear()

    @classmethod
    def _next_label(cls, kind: str, label: str | None) -> str:
        if label:
            return str(label)
        base = {
            "laser": "Laser",
            "lens": "Lens",
            "mirror": "Mirror",
            "ccd": "CCD",
            "imaging_camera": "CCD",
            "camera": "CCD",
            "fiber": "Fiber",
        }.get(kind, kind.title())
        count = cls._counters.get(kind, 0) + 1
        cls._counters[kind] = count
        if kind == "lens":
            return f"Lens{count:03d}"
        return base if count == 1 else f"{base}{count:03d}"

    @classmethod
    def create(
        cls,
        kind: str,
        *,
        component_id: str,
        scene_x: float = 0.0,
        scene_y: float = 0.0,
        rotation_deg: float = 0.0,
        label: str | None = None,
        params: Mapping[str, Any] | None = None,
        enabled: bool = True,
    ) -> OpticalComponent:
        kind = str(kind or "").strip()
        # Normalize CCD aliases onto the CCDComponent class while preserving
        # imaging_camera for receivers that already expect that kind string.
        class_kind = "ccd" if kind in {"ccd", "imaging_camera", "camera"} else kind
        component_cls = _KIND_CLASS.get(class_kind, OpticalComponent)
        stored_kind = "ccd" if class_kind == "ccd" and kind == "ccd" else (
            "imaging_camera" if class_kind == "ccd" else kind
        )
        if kind == "ccd":
            stored_kind = "ccd"
        visual = VisualModel(
            scene_x=float(scene_x),
            scene_y=float(scene_y),
            rotation_deg=float(rotation_deg),
            asset_kind=stored_kind if stored_kind != "ccd" else "imaging_camera",
        )
        optical = OpticalModel(params=dict(params or {}))
        return component_cls(
            component_id=str(component_id),
            kind=stored_kind,
            label=cls._next_label(class_kind, label),
            visual=visual,
            optical=optical,
            enabled=bool(enabled),
        )


@dataclass(slots=True)
class TeachingOpticalSystem:
    """Teaching-side OpticalSystem: ordered components feeding formal raytrace."""

    components: list[OpticalComponent] = field(default_factory=list)

    def clear(self) -> None:
        self.components.clear()

    def upsert(self, component: OpticalComponent) -> None:
        for index, existing in enumerate(self.components):
            if existing.component_id == component.component_id:
                self.components[index] = component
                return
        self.components.append(component)

    def remove(self, component_id: str) -> None:
        self.components = [c for c in self.components if c.component_id != component_id]

    def sync_from_nodes(self, nodes: Mapping[str, Any]) -> None:
        """Rebuild components from ExperimentNode map (drag / preset / load)."""
        DeviceFactory.reset_counters()
        ordered = sorted(
            (
                node for node in nodes.values()
                if str(getattr(node, "kind", "")) in OPTICAL_SYSTEM_KINDS
            ),
            key=lambda node: float(getattr(node, "x", 0.0)),
        )
        self.components = [
            DeviceFactory.create(
                str(getattr(node, "kind", "")),
                component_id=str(getattr(node, "id", "")),
                scene_x=float(getattr(node, "x", 0.0)),
                scene_y=float(getattr(node, "y", 0.0)),
                rotation_deg=float(getattr(node, "rotation_deg", 0.0)),
                label=str(getattr(node, "label", "") or None) or None,
                params=dict(getattr(node, "params", {}) or {}),
                enabled=bool(dict(getattr(node, "params", {}) or {}).get("enabled", True)),
            )
            for node in ordered
        ]

    def kinds(self) -> list[str]:
        return [c.kind for c in self.components]

    def labels(self) -> list[str]:
        return [c.label for c in self.components]

    def find(self, kind: str) -> list[OpticalComponent]:
        return [c for c in self.components if c.kind == kind or (kind == "ccd" and c.kind in {"ccd", "imaging_camera", "camera"})]


def component_summary(system: TeachingOpticalSystem | Iterable[OpticalComponent]) -> list[str]:
    components = system.components if isinstance(system, TeachingOpticalSystem) else list(system)
    return [f"{c.label}({c.kind})" for c in components]


__all__ = [
    "CCDComponent",
    "DeviceFactory",
    "FiberComponent",
    "LaserComponent",
    "LensComponent",
    "MirrorComponent",
    "OPTICAL_SYSTEM_KINDS",
    "OpticalComponent",
    "OpticalModel",
    "TeachingOpticalSystem",
    "VisualModel",
    "component_summary",
]

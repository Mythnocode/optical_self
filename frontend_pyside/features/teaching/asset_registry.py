from __future__ import annotations

"""Visual-only asset registry for the teaching 3D workbench.

The registry deliberately contains no optical parameters.  Optical positions and
physics remain owned by ExperimentModel/sceneBridge; entries here only select a
visual representation and a cheap picking proxy.
"""

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True, slots=True)
class Teaching3DAsset:
    asset_id: str
    qml: str
    tier: str
    pick_scale: tuple[float, float, float]
    estimated_models: int
    transparent_materials: int = 0
    source: str = "Chen built-in procedural asset"
    license: str = "project-owned"


_ASSET: Final = {
    "laser": ("laser_lab_001", "assets/TeachingLaser.qml", "B", (0.90, 0.48, 0.52), 7, 0),
    "isolator": ("isolator_001", "assets/TeachingIsolator.qml", "A", (0.40, 0.48, 0.40), 6, 0),
    "half_wave_plate": ("waveplate_mount_001", "assets/TeachingWavePlate.qml", "A", (0.42, 0.54, 0.42), 5, 1),
    "pbs": ("pbs_mount_001", "assets/TeachingSplitter.qml", "A", (0.48, 0.50, 0.38), 5, 2),
    "beam_sampler": ("sampler_mount_001", "assets/TeachingSplitter.qml", "A", (0.48, 0.50, 0.38), 5, 2),
    "splitter": ("splitter_mount_001", "assets/TeachingSplitter.qml", "A", (0.48, 0.50, 0.38), 5, 2),
    "mirror": ("mirror_mount_001", "assets/TeachingMirror.qml", "A", (0.44, 0.58, 0.46), 8, 0),
    "aperture": ("aperture_mount_001", "assets/TeachingAperture.qml", "A", (0.42, 0.56, 0.42), 5, 1),
    "lens": ("lens_mount_001", "assets/TeachingLens.qml", "A", (0.48, 0.58, 0.48), 5, 1),
    "beam_expander": ("beam_expander_001", "assets/TeachingBeamExpander.qml", "B", (0.90, 0.52, 0.48), 7, 4),
    "cylindrical_lens": ("cyl_lens_mount_001", "assets/TeachingCylindricalLens.qml", "A", (0.50, 0.58, 0.38), 5, 1),
    "fiber": ("fiber_stage_001", "assets/TeachingFiberStage.qml", "B", (0.58, 0.62, 0.55), 9, 0),
    "power_meter": ("power_sensor_001", "assets/TeachingPowerMeter.qml", "A", (0.52, 0.55, 0.52), 5, 0),
    "photodetector": ("photodetector_001", "assets/TeachingPowerMeter.qml", "A", (0.52, 0.55, 0.52), 5, 0),
    "beam_analyzer": ("beam_analyzer_001", "assets/TeachingCamera.qml", "A", (0.54, 0.54, 0.55), 5, 0),
    "imaging_camera": ("imaging_camera_001", "assets/TeachingCamera.qml", "A", (0.54, 0.54, 0.55), 5, 0),
    "ccd": ("ccd_001", "assets/TeachingCamera.qml", "A", (0.54, 0.54, 0.55), 5, 0),
    "focus_scan_module": ("focus_scan_001", "assets/TeachingCamera.qml", "A", (0.66, 0.54, 0.55), 5, 0),
    "camera": ("camera_001", "assets/TeachingCamera.qml", "A", (0.54, 0.54, 0.55), 5, 0),
    "wavefront_sensor": ("wavefront_sensor_001", "assets/TeachingWavefrontSensor.qml", "A", (0.58, 0.54, 0.58), 5, 0),
    "oscilloscope": ("oscilloscope_001", "assets/TeachingInstrumentBox.qml", "A", (0.62, 0.55, 0.62), 4, 0),
}

ASSETS: Final[dict[str, Teaching3DAsset]] = {
    kind: Teaching3DAsset(asset_id, qml, tier, pick_scale, model_count, transparent)
    for kind, (asset_id, qml, tier, pick_scale, model_count, transparent) in _ASSET.items()
}

FALLBACK_ASSET: Final = Teaching3DAsset(
    "generic_device_001", "assets/TeachingGeneric.qml", "A", (0.44, 0.44, 0.44), 3
)


def asset_for_kind(kind: str) -> Teaching3DAsset:
    return ASSETS.get(str(kind or ""), FALLBACK_ASSET)


def asset_manifest_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for kind, asset in sorted(ASSETS.items()):
        rows.append(
            {
                "kind": kind,
                "asset_id": asset.asset_id,
                "qml": asset.qml,
                "tier": asset.tier,
                "pick_scale": list(asset.pick_scale),
                "estimated_models": asset.estimated_models,
                "transparent_materials": asset.transparent_materials,
                "source": asset.source,
                "license": asset.license,
                "physics_role": "visual_only",
            }
        )
    return rows


__all__ = ["ASSETS", "FALLBACK_ASSET", "Teaching3DAsset", "asset_for_kind", "asset_manifest_rows"]

from __future__ import annotations

import json
import math
from typing import Any

from frontend_pyside.core.types import LensSurface


def resolve_teaching_snapshot(profile: dict[str, Any] | None, settings_json: str = "") -> dict[str, Any] | None:
    """Return the newest teaching workbench snapshot if one exists."""
    profile = dict(profile or {})
    candidates: list[dict[str, Any]] = []
    if str(profile.get("active_snapshot_source", "")) == "teaching":
        item = profile.get("teaching_snapshot")
        if isinstance(item, dict):
            candidates.append(item)
    shared = profile.get("shared_snapshot")
    if isinstance(shared, dict) and str(shared.get("source", "")) == "unified_teaching_workbench":
        candidates.append(shared)
    teaching = profile.get("teaching_snapshot")
    if isinstance(teaching, dict):
        candidates.append(teaching)
    raw = str(settings_json or "").strip()
    if raw:
        try:
            item = json.loads(raw)
            if isinstance(item, dict):
                candidates.append(item)
        except json.JSONDecodeError:
            pass
    for snapshot in candidates:
        nodes = list(snapshot.get("nodes") or [])
        if nodes:
            return snapshot
    return None


def teaching_lenses_from_snapshot(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    nodes = list(snapshot.get("nodes", []) or [])
    lenses = [dict(node) for node in nodes if str(node.get("kind")) == "lens"]
    lenses.sort(key=lambda item: float(item.get("x", 0.0)))
    return lenses


def surfaces_from_teaching_lenses(lenses: list[dict[str, Any]]) -> list[LensSurface]:
    surfaces: list[LensSurface] = []
    for index, lens in enumerate(lenses):
        params = dict(lens.get("params", {}) or {})
        focal = max(1.0, float(params.get("focal_mm", 25.0)))
        radius = max(2.0, 1.04 * focal)
        next_x = (
            float(lenses[index + 1].get("x", lens.get("x", 0.0) + 20.0))
            if index + 1 < len(lenses)
            else float(lens.get("x", 0.0)) + 100.0
        )
        gap_mm = max(0.5, min(40.0, (next_x - float(lens.get("x", 0.0))) / 20.0))
        group_id = str(lens.get("id") or f"L{index + 1}")
        surfaces.extend(
            [
                LensSurface(f"L{index + 1} 前表面", radius, 2.0, "N-BK7", 3.0, group_id=group_id),
                LensSurface(f"L{index + 1} 后表面", -radius, gap_mm, "AIR", 3.0, group_id=group_id),
            ]
        )
    return surfaces


def receiver_payload_from_teaching_snapshot(snapshot: dict[str, Any]) -> dict[str, float]:
    """Map teaching fiber five-axis params into simulation receiver payload units."""
    mode_radius_um = float(snapshot.get("receiver_mode_radius_um", 2.5) or 2.5)
    mfd_um = max(0.4, 2.0 * mode_radius_um)
    payload = {
        "mode_field_diameter_x_um": mfd_um,
        "mode_field_diameter_y_um": mfd_um,
        "na_x": float(snapshot.get("receiver_na", 0.13) or 0.13),
        "na_y": float(snapshot.get("receiver_na", 0.13) or 0.13),
    }
    for node in list(snapshot.get("nodes") or []):
        if str(node.get("kind")) != "fiber":
            continue
        params = dict(node.get("params") or {})
        payload.update(
            {
                "offset_x_mm": float(params.get("offset_x_um", 0.0) or 0.0) * 1.0e-3,
                "offset_y_mm": float(params.get("offset_y_um", 0.0) or 0.0) * 1.0e-3,
                "axial_offset_z_mm": float(params.get("offset_z_um", 0.0) or 0.0) * 1.0e-3,
                "tilt_x_deg": math.degrees(float(params.get("pitch_mrad", 0.0) or 0.0) * 1.0e-3),
                "tilt_y_deg": math.degrees(float(params.get("yaw_mrad", 0.0) or 0.0) * 1.0e-3),
            }
        )
        break
    return payload


def source_payload_from_teaching_snapshot(snapshot: dict[str, Any]) -> dict[str, float]:
    return {"wavelength_nm": float(snapshot.get("wavelength_nm", 780.0) or 780.0)}


__all__ = [
    "receiver_payload_from_teaching_snapshot",
    "resolve_teaching_snapshot",
    "source_payload_from_teaching_snapshot",
    "surfaces_from_teaching_lenses",
    "teaching_lenses_from_snapshot",
]

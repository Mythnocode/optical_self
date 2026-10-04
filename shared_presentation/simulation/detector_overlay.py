"""Original detector display overlay, without widget lookup."""
from typing import Any

def _plot_surface_z(payload: dict[str, Any], index: int | None = None) -> float:
    surfaces = [item for item in payload.get("surfaces") or [] if isinstance(item, dict)]
    if not surfaces:
        return 0.0
    if index is None:
        return float(surfaces[-1].get("z", 0.0) or 0.0)
    wanted = int(index)
    for item in surfaces:
        try:
            if int(item.get("surface_index", -1)) == wanted:
                return float(item.get("z", 0.0) or 0.0)
        except (TypeError, ValueError):
            continue
    if 0 <= wanted < len(surfaces):
        return float(surfaces[wanted].get("z", 0.0) or 0.0)
    return float(surfaces[-1].get("z", 0.0) or 0.0)

def detector_object(payload: dict[str, Any], observation: dict[str, Any], mfd_um: float = 5.0) -> dict[str, Any] | None:
    if not observation.get("enabled"):
        return None
    mode = str(observation.get("mode") or "surface")
    surfaces = [item for item in payload.get("surfaces") or [] if isinstance(item, dict)]
    if mode == "custom":
        z = _plot_surface_z(payload, None) + float(observation.get("offset_mm") or 0.0)
    elif mode == "fiber":
        z = _plot_surface_z(payload, None)
        for item in payload.get("objects") or []:
            if isinstance(item, dict) and str(item.get("kind", "")) == "fiber":
                z = float(item.get("z", z) or z)
                break
    else:
        z = _plot_surface_z(payload, int(observation.get("surface_index") or 0))
    if mode == "fiber":
        radius = max(float(mfd_um) / 2000.0, 1e-4)
        return {
            "kind": "fiber",
            "name": "探测器",
            "z": z,
            "center_x": 0.0,
            "center_y": 0.0,
            "radius": radius,
            "width": 0.0,
            "height": 0.0,
            "metadata": {"user_detector": True, "mode": "fiber"},
        }
    width = float(observation.get("pixels_x") or 0) * float(observation.get("pitch_um") or 0.0) / 1000.0
    height = float(observation.get("pixels_y") or 0) * float(observation.get("pitch_um") or 0.0) / 1000.0
    if width <= 0.0:
        width = max((float(surfaces[-1].get("aperture", 0.0) or 0.0) * 2.0) if surfaces else 1.0, 0.2)
    if height <= 0.0:
        height = width
    return {
        "kind": "detector",
        "name": "探测器",
        "z": z,
        "center_x": 0.0,
        "center_y": 0.0,
        "radius": 0.0,
        "width": width,
        "height": height,
        "metadata": {"user_detector": True, "mode": mode},
    }

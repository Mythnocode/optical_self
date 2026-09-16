
"""画布视角和缩放操作。

这里集中处理 2D 坐标轴范围、3D 相机视角以及以鼠标位置为中心的缩放，
使交互策略与具体图表类型解耦。
"""

from __future__ import annotations

import numpy as np


def _surface_bounds(surface: dict) -> np.ndarray:

    z = float(surface.get("z", 0.0) or 0.0)
    aperture = max(float(surface.get("aperture", 0.0) or 0.0), 0.0)
    cx = float(surface.get("decenter_x", 0.0) or 0.0)
    cy = float(surface.get("decenter_y", 0.0) or 0.0)
    radius = float(surface.get("radius", float("inf")) or float("inf"))
    conic = float(surface.get("conic", 0.0) or 0.0)

    sag = 0.0
    if aperture > 0.0 and np.isfinite(radius) and 1.0e-12 < abs(radius) < 1.0e12:
        inside = max(0.0, 1.0 - (1.0 + conic) * (aperture / radius) ** 2)
        denominator = radius * (1.0 + np.sqrt(inside))
        if abs(denominator) > 1.0e-12:
            sag = abs(aperture * aperture / denominator)

    tx = np.deg2rad(float(surface.get("tilt_x_deg", 0.0) or 0.0))
    ty = np.deg2rad(float(surface.get("tilt_y_deg", 0.0) or 0.0))
    tilt_axial = aperture * (abs(np.sin(tx)) + abs(np.sin(ty)))
    axial_half = max(sag + tilt_axial, 1.0e-6)
    return np.asarray(
        [
            [z - axial_half, cx - aperture, cy - aperture],
            [z + axial_half, cx + aperture, cy + aperture],
        ],
        dtype=float,
    )


def fit_optical_scene_3d(ax, data: dict, *, zoom: float = 1.0) -> None:

    points: list[np.ndarray] = []

    for ray in data.get("rays", []):
        values = np.asarray(ray.get("points", []), dtype=float)
        if values.ndim == 2 and values.shape[1] == 3:
            points.append(np.column_stack((values[:, 2], values[:, 0], values[:, 1])))

    for surface in data.get("surfaces", []):
        if surface.get("visible", True) is False:
            continue
        vertices = np.asarray(surface.get("vertices", []), dtype=float)
        if vertices.ndim == 2 and vertices.shape[1] == 3 and len(vertices):
            points.append(vertices)
        else:
            points.append(_surface_bounds(surface))

    for item in data.get("objects", []):
        if item.get("visible", True) is False:
            continue
        z = float(item.get("z", 0.0) or 0.0)
        width = max(
            float(item.get("width", 0.0) or 0.0),
            float(item.get("radius", 0.0) or 0.0) * 2,
        )
        height = max(
            float(item.get("height", 0.0) or 0.0),
            float(item.get("radius", 0.0) or 0.0) * 2,
        )
        cx = float(item.get("center_x", 0.0) or 0.0)
        cy = float(item.get("center_y", 0.0) or 0.0)
        depth = max(0.018 * max(width, height, 1.0), 1.0e-3)
        points.append(
            np.asarray(
                [
                    [z - depth, cx - width / 2, cy - height / 2],
                    [z + depth, cx + width / 2, cy + height / 2],
                ]
            )
        )

    envelope = [dict(item) for item in data.get("beam_envelope", []) or []]
    if envelope:
        for item in envelope:
            z = float(item.get("z", 0.0) or 0.0)
            cx = float(item.get("center_x", 0.0) or 0.0)
            cy = float(item.get("center_y", 0.0) or 0.0)
            rx = max(float(item.get("radius_x", 0.0) or 0.0), 0.0)
            ry = max(float(item.get("radius_y", 0.0) or 0.0), 0.0)
            points.append(
                np.asarray(
                    [
                        [z, cx - rx, cy - ry],
                        [z, cx + rx, cy + ry],
                    ],
                    dtype=float,
                )
            )

    if bool(data.get("show_section_plane", False)):
        vertices = np.asarray(
            data.get("section_plane", {}).get("vertices", []), dtype=float
        )
        if vertices.shape == (4, 3):
            points.append(vertices)

    if not points:
        ax.set_xlim(0.0, 1.0)
        ax.set_ylim(-0.5, 0.5)
        ax.set_zlim(-0.5, 0.5)
        return

    stacked = np.vstack(points)
    finite = stacked[np.all(np.isfinite(stacked), axis=1)]
    if not len(finite):
        return

    low = np.min(finite, axis=0)
    high = np.max(finite, axis=0)
    spans = np.maximum(high - low, 1.0e-6)
    centre = 0.5 * (low + high)

    
    margin = np.asarray([0.10, 0.13, 0.13])
    half = 0.5 * spans * (1.0 + 2.0 * margin)
    
    
    transverse_floor = max(0.035 * spans[0], 0.25)
    half[1] = max(half[1], transverse_floor)
    half[2] = max(half[2], transverse_floor)

    ax.set_xlim(centre[0] - half[0], centre[0] + half[0])
    ax.set_ylim(centre[1] - half[1], centre[1] + half[1])
    ax.set_zlim(centre[2] - half[2], centre[2] + half[2])

    transverse = max(2.0 * half[1], 2.0 * half[2], 1.0e-6)
    axial = max(2.0 * half[0], 1.0e-6)
    
    # Long optical trains need more axial visual room than ordinary 3D plots.
    # Keep a moderate cap so lenses remain legible without compressing a four-lens
    # train into the small 5.4:1 box used by the older implementation.
    visual_axial = min(max(axial, 3.2 * transverse), 10.0 * transverse)
    display_zoom = max(0.62, min(1.18, 0.94 * float(zoom)))
    try:
        ax.set_box_aspect((visual_axial, transverse, transverse), zoom=display_zoom)
    except TypeError:
        ax.set_box_aspect((visual_axial, transverse, transverse))


def apply_optical_scene_3d_zoom(ax, *, zoom: float = 1.0) -> None:
    """Change 3D display scale without cropping the physical data limits."""
    try:
        x0, x1 = ax.get_xlim(); y0, y1 = ax.get_ylim(); z0, z1 = ax.get_zlim()
        axial = max(abs(float(x1 - x0)), 1e-6)
        transverse = max(abs(float(y1 - y0)), abs(float(z1 - z0)), 1e-6)
        visual_axial = min(max(axial, 3.2 * transverse), 10.0 * transverse)
        display_zoom = max(0.62, min(1.18, 0.94 * float(zoom)))
        try:
            ax.set_box_aspect((visual_axial, transverse, transverse), zoom=display_zoom)
        except TypeError:
            ax.set_box_aspect((visual_axial, transverse, transverse))
    except Exception:
        return


def fit_optical_section_2d(ax, data: dict) -> None:
    x_values: list[float] = []
    y_values: list[float] = []
    for ray in data.get("rays", []):
        z = np.asarray(ray.get("z", []), dtype=float)
        transverse = np.asarray(ray.get("t", ray.get("y", [])), dtype=float)
        count = min(len(z), len(transverse))
        if count:
            x_values.extend(z[:count].tolist())
            y_values.extend(transverse[:count].tolist())
    for surface in data.get("surfaces", []):
        z = float(surface.get("z", 0.0) or 0.0)
        x_values.append(z)
        y_values.extend([float(surface.get("t_min", 0.0)), float(surface.get("t_max", 0.0))])
    if not x_values:
        return
    x_low, x_high = min(x_values), max(x_values)
    y_limit = max(max(abs(value) for value in y_values), 1.0e-6)
    x_margin = 0.08 * max(x_high - x_low, 1.0)
    ax.set_xlim(x_low - x_margin, x_high + x_margin)
    ax.set_ylim(-1.16 * y_limit, 1.16 * y_limit)


def zoom_axes_at_event(ax, event, *, base_scale: float = 1.18) -> bool:
    if event.inaxes is not ax or event.xdata is None or event.ydata is None:
        return False
    factor = 1.0 / base_scale if event.button == "up" else base_scale
    x_left, x_right = ax.get_xlim()
    y_bottom, y_top = ax.get_ylim()
    x = float(event.xdata)
    y = float(event.ydata)
    ax.set_xlim(x - (x - x_left) * factor, x + (x_right - x) * factor)
    ax.set_ylim(y - (y - y_bottom) * factor, y + (y_top - y) * factor)
    return True


__all__ = ["apply_optical_scene_3d_zoom", "fit_optical_scene_3d", "fit_optical_section_2d", "zoom_axes_at_event"]

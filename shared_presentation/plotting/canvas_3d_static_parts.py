
"""静态 3D 光学元件渲染器。

本模块绘制镜片、平面、光阑、探测面等不会随每帧结果变化的几何对象，供 3D
画布初始化或场景结构变化时调用。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from matplotlib.colors import to_rgba
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

from shared_presentation import theme_tokens as theme
from shared_presentation.plotting.optical_scene_geometry import infer_lens_groups


@dataclass(slots=True)
class StaticSceneArtists:
    high_quality: list = field(default_factory=list)
    persistent: list = field(default_factory=list)
    surface_pick_artists: dict[object, int] = field(default_factory=dict)


def render_static_scene(ax, data: dict) -> StaticSceneArtists:
    artists = StaticSceneArtists()
    quality = str(data.get("render_quality", "high") or "high").lower()
    interactive = quality in {"interactive", "preview", "low"}
    surfaces = [
        dict(item)
        for item in data.get("surfaces", [])
        if bool(item.get("enabled", True))
    ]

    z_axis = data.get("optical_axis", [0.0, 1.0])
    if len(z_axis) == 2:
        axis_artist, = ax.plot(
            [float(z_axis[0]), float(z_axis[1])],
            [0.0, 0.0],
            [0.0, 0.0],
            color=theme.OPTICAL_AXIS,
            linewidth=0.95,
            linestyle=(0, (5, 4)),
            alpha=0.82,
            zorder=1,
        )
        artists.persistent.append(axis_artist)

    by_index = {
        int(surface.get("surface_index", -1)): surface
        for surface in surfaces
    }
    groups = list(data.get("lens_groups", []) or infer_lens_groups(surfaces))

    
    
    for group in groups:
        _render_lens_group_body(
            ax,
            group,
            by_index,
            artists,
            interactive=interactive,
        )

    for surface in surfaces:
        _render_surface(ax, surface, artists, interactive=interactive)

    for group_index, group in enumerate(groups, start=1):
        _render_lens_group_label(
            ax,
            group,
            by_index,
            artists,
            fallback_label=f"L{group_index}",
        )
    return artists


def _render_surface(
    ax, surface: dict, artists: StaticSceneArtists, *, interactive: bool
) -> None:
    aperture = max(float(surface.get("aperture", 0.0) or 0.0), 0.0)
    if aperture <= 0.0:
        return

    fill = theme.SURFACE_FILL
    edge = theme.SURFACE_EDGE
    radial_count = 7 if interactive else 13
    angular_count = 28 if interactive else 56
    axial, x, y = _surface_mesh(
        surface, radial_count=radial_count, angular_count=angular_count
    )
    face = ax.plot_surface(
        axial,
        x,
        y,
        color=fill,
        alpha=0.24 if interactive else 0.30,
        linewidth=0.0,
        antialiased=not interactive,
        shade=False,
        zorder=4,
    )
    artists.high_quality.append(face)

    
    
    quarter = angular_count // 4
    half = angular_count // 2
    for angle_index in (0, quarter):
        for offset in (0, half):
            curve = np.column_stack(
                (
                    axial[:, angle_index + offset],
                    x[:, angle_index + offset],
                    y[:, angle_index + offset],
                )
            )
            line, = ax.plot(
                curve[:, 0],
                curve[:, 1],
                curve[:, 2],
                color=edge,
                linewidth=0.72,
                alpha=0.72,
                zorder=7,
            )
            artists.persistent.append(line)

    rim = np.column_stack((axial[-1], x[-1], y[-1]))
    rim_line, = ax.plot(
        rim[:, 0],
        rim[:, 1],
        rim[:, 2],
        color=edge,
        linewidth=1.18,
        alpha=0.98,
        picker=7,
        zorder=8,
    )
    surface_index = int(surface.get("surface_index", -1))
    rim_line.set_gid(f"surface:{surface_index}")
    artists.persistent.append(rim_line)
    artists.surface_pick_artists[rim_line] = surface_index


def _render_lens_group_body(
    ax,
    group: dict,
    by_index: dict[int, dict],
    artists: StaticSceneArtists,
    *,
    interactive: bool,
) -> None:
    indices = [
        int(value)
        for value in group.get("surface_indices", [])
        if int(value) in by_index
    ]
    if len(indices) < 2:
        return
    ordered = sorted(
        (by_index[index] for index in indices),
        key=lambda item: float(item.get("z", 0.0) or 0.0),
    )
    first, second = ordered[0], ordered[-1]
    aperture = max(
        min(
            float(first.get("aperture", 0.0) or 0.0),
            float(second.get("aperture", 0.0) or 0.0),
        ),
        0.0,
    )
    if aperture <= 0.0:
        return

    z_gap = abs(
        float(second.get("z", 0.0) or 0.0)
        - float(first.get("z", 0.0) or 0.0)
    )
    
    
    if z_gap > max(8.0 * aperture, 40.0):
        return

    count = 28 if interactive else 64
    rim_first = _outer_rim(first, count=count)
    rim_second = _outer_rim(second, count=count)
    if rim_first.shape != rim_second.shape or len(rim_first) < 4:
        return

    faces = []
    for index in range(len(rim_first)):
        nxt = (index + 1) % len(rim_first)
        faces.append(
            [
                rim_first[index],
                rim_first[nxt],
                rim_second[nxt],
                rim_second[index],
            ]
        )
    body = Poly3DCollection(
        faces,
        facecolors=to_rgba(theme.LENS_BODY_FILL, 0.13 if interactive else 0.17),
        edgecolors=to_rgba(theme.LENS_BODY_EDGE, 0.18),
        linewidths=0.24,
        zorder=2,
    )
    ax.add_collection3d(body)
    artists.high_quality.append(body)


def _render_lens_group_label(
    ax,
    group: dict,
    by_index: dict[int, dict],
    artists: StaticSceneArtists,
    *,
    fallback_label: str,
) -> None:
    indices = [
        int(value)
        for value in group.get("surface_indices", [])
        if int(value) in by_index
    ]
    if not indices:
        return
    group_surfaces = [by_index[index] for index in indices]
    z_values = [float(item.get("z", 0.0) or 0.0) for item in group_surfaces]
    aperture = max(
        (float(item.get("aperture", 0.0) or 0.0) for item in group_surfaces),
        default=0.0,
    )
    if aperture <= 0.0:
        return
    center_x = float(
        np.mean([float(item.get("decenter_x", 0.0) or 0.0) for item in group_surfaces])
    )
    center_y = float(
        np.mean([float(item.get("decenter_y", 0.0) or 0.0) for item in group_surfaces])
    )
    label = str(group.get("label", "") or fallback_label)
    text = ax.text(
        float(np.mean(z_values)),
        center_x + aperture * 1.18,
        center_y + aperture * 0.06,
        label,
        color=theme.TEXT_PRIMARY,
        fontsize=9.5,
        fontweight="semibold",
        ha="center",
        va="bottom",
        zorder=11,
    )
    artists.persistent.append(text)


def _outer_rim(surface: dict, *, count: int) -> np.ndarray:
    axial, x, y = _surface_mesh(surface, radial_count=2, angular_count=count)
    return np.column_stack((axial[-1], x[-1], y[-1]))


def _surface_mesh(surface: dict, *, radial_count: int, angular_count: int):
    aperture = max(float(surface.get("aperture", 0.0) or 0.0), 1.0e-9)
    radius = float(surface.get("radius", float("inf")) or float("inf"))
    conic = float(surface.get("conic", 0.0) or 0.0)
    z0 = float(surface.get("z", 0.0) or 0.0)
    cx = float(surface.get("decenter_x", 0.0) or 0.0)
    cy = float(surface.get("decenter_y", 0.0) or 0.0)

    rho = np.linspace(0.0, aperture, radial_count)[:, None]
    theta = np.linspace(
        0.0, 2.0 * np.pi, angular_count, endpoint=False
    )[None, :]
    lateral_x = cx + rho * np.cos(theta)
    lateral_y = cy + rho * np.sin(theta)
    sag = _conic_sag(rho, radius, conic)
    axial = z0 + np.repeat(sag, angular_count, axis=1)

    points = np.stack((axial, lateral_x, lateral_y), axis=-1)
    points = _apply_tilt(points, surface, centre=(z0, cx, cy))
    return points[..., 0], points[..., 1], points[..., 2]


def _conic_sag(rho: np.ndarray, radius: float, conic: float) -> np.ndarray:
    if (
        not np.isfinite(radius)
        or abs(radius) < 1.0e-12
        or abs(radius) > 1.0e12
    ):
        return np.zeros_like(rho)
    inside = 1.0 - (1.0 + conic) * np.square(rho / radius)
    root = np.sqrt(np.maximum(inside, 0.0))
    denominator = radius * (1.0 + root)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.divide(
            np.square(rho),
            denominator,
            out=np.zeros_like(rho),
            where=np.abs(denominator) > 1.0e-12,
        )


def _apply_tilt(
    points: np.ndarray,
    surface: dict,
    centre: tuple[float, float, float],
) -> np.ndarray:
    tx = np.deg2rad(float(surface.get("tilt_x_deg", 0.0) or 0.0))
    ty = np.deg2rad(float(surface.get("tilt_y_deg", 0.0) or 0.0))
    tz = np.deg2rad(float(surface.get("tilt_z_deg", 0.0) or 0.0))
    if max(abs(tx), abs(ty), abs(tz)) < 1.0e-12:
        return points
    cz, cx, cy = centre
    translated = points - np.asarray([cz, cx, cy])
    rx = np.asarray(
        [[1, 0, 0], [0, np.cos(tx), -np.sin(tx)], [0, np.sin(tx), np.cos(tx)]]
    )
    ry = np.asarray(
        [[np.cos(ty), 0, np.sin(ty)], [0, 1, 0], [-np.sin(ty), 0, np.cos(ty)]]
    )
    rz = np.asarray(
        [[np.cos(tz), -np.sin(tz), 0], [np.sin(tz), np.cos(tz), 0], [0, 0, 1]]
    )
    return translated @ (rz @ ry @ rx).T + np.asarray([cz, cx, cy])


__all__ = ["StaticSceneArtists", "render_static_scene"]


from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from matplotlib.colors import to_rgba
from mpl_toolkits.mplot3d.art3d import Line3DCollection, Poly3DCollection

from frontend_pyside.resources import theme_tokens as theme


@dataclass(slots=True)
class DynamicSceneArtists:
    ray_collections: list = field(default_factory=list)
    ray_group_keys: list[tuple[str, float | None]] = field(default_factory=list)
    high_quality: list = field(default_factory=list)
    persistent: list = field(default_factory=list)


def render_dynamic_scene(
    ax,
    data: dict,
    *,
    reuse_ray_collections: list | None = None,
    reuse_ray_group_keys: list[tuple[str, float | None]] | None = None,
) -> DynamicSceneArtists:
    artists = DynamicSceneArtists()
    quality = str(data.get("render_quality", "high") or "high").lower()
    interactive = quality in {"interactive", "preview", "low"}
    _render_beam_envelope(
        ax,
        data.get("beam_envelope", []),
        artists,
        interactive=interactive,
        focus=data.get("focus"),
    )
    _render_rays(
        ax,
        data.get("rays", []),
        artists,
        interactive=interactive,
        reuse_collections=reuse_ray_collections,
        reuse_group_keys=reuse_ray_group_keys,
    )
    for item in data.get("objects", []):
        kind = str(item.get("kind", ""))
        if kind == "fiber":
            _render_fiber(ax, item, artists, interactive=interactive)
        elif kind == "aperture":
            _render_aperture(ax, item, artists, interactive=interactive)
    if bool(data.get("show_section_plane", False)):
        _render_section_plane(
            ax, data.get("section_plane", {}), artists, interactive=interactive
        )
    _render_selected_surface_marker(ax, data, artists)
    _render_orientation_marker(ax, artists)
    return artists


def _sample_evenly(items: list, limit: int) -> list:
    if len(items) <= limit:
        return items
    indices = sorted({round(index * (len(items) - 1) / max(1, limit - 1)) for index in range(limit)})
    return [items[index] for index in indices]


def _ray_points(ray: dict, *, interactive: bool) -> np.ndarray | None:
    points = np.asarray(ray.get("points", []), dtype=float)
    if points.ndim != 2 or points.shape[0] < 2 or points.shape[1] != 3:
        z = np.asarray(ray.get("z", []), dtype=float)
        x = np.asarray(ray.get("x", []), dtype=float)
        y = np.asarray(ray.get("y", []), dtype=float)
        count = min(len(z), len(x), len(y))
        if count < 2:
            return None
        points = np.column_stack((x[:count], y[:count], z[:count]))
    if interactive and len(points) > 160:
        indices = np.linspace(0, len(points) - 1, 160, dtype=int)
        points = points[indices]
    return points


def _remove_artist(artist) -> None:
    try:
        artist.remove()
    except (AttributeError, ValueError, RuntimeError):
        pass


def _render_beam_envelope(
    ax,
    envelope: list[dict],
    artists: DynamicSceneArtists,
    *,
    interactive: bool,
    focus: dict | None,
) -> None:
    rows = [dict(item) for item in envelope or []]
    if len(rows) < 3:
        return

    z = np.asarray([float(item.get("z", 0.0)) for item in rows], dtype=float)
    cx = np.asarray([float(item.get("center_x", 0.0)) for item in rows], dtype=float)
    cy = np.asarray([float(item.get("center_y", 0.0)) for item in rows], dtype=float)
    rx = np.asarray([max(float(item.get("radius_x", 0.0)), 1.0e-6) for item in rows], dtype=float)
    ry = np.asarray([max(float(item.get("radius_y", 0.0)), 1.0e-6) for item in rows], dtype=float)
    finite = np.isfinite(z) & np.isfinite(cx) & np.isfinite(cy) & np.isfinite(rx) & np.isfinite(ry)
    if np.count_nonzero(finite) < 3:
        return
    z, cx, cy, rx, ry = z[finite], cx[finite], cy[finite], rx[finite], ry[finite]

    angle_count = 18 if interactive else 40
    theta = np.linspace(0.0, 2.0 * np.pi, angle_count, endpoint=True)
    axial = np.repeat(z[:, None], len(theta), axis=1)
    x = cx[:, None] + rx[:, None] * np.cos(theta)[None, :]
    y = cy[:, None] + ry[:, None] * np.sin(theta)[None, :]
    shell = ax.plot_surface(
        axial,
        x,
        y,
        color=theme.BEAM_ENVELOPE_FILL,
        alpha=0.055 if interactive else 0.085,
        linewidth=0.0,
        antialiased=not interactive,
        shade=False,
        zorder=1,
    )
    artists.high_quality.append(shell)

    ring_count = 5 if interactive else 8
    indices = np.linspace(0, len(z) - 1, min(ring_count, len(z)), dtype=int)
    for index in sorted(set(indices.tolist())):
        ring, = ax.plot(
            np.full_like(theta, z[index]),
            x[index],
            y[index],
            color=theme.BEAM_ENVELOPE_EDGE,
            linewidth=0.56,
            alpha=0.34,
            zorder=3,
        )
        artists.persistent.append(ring)

    if isinstance(focus, dict):
        fz = float(focus.get("z", 0.0) or 0.0)
        nearest = int(np.argmin(np.abs(z - fz)))
        waist, = ax.plot(
            np.full_like(theta, z[nearest]),
            x[nearest],
            y[nearest],
            color=theme.BEAM_WAIST,
            linewidth=1.35,
            alpha=0.95,
            zorder=10,
        )
        artists.persistent.append(waist)
        focus_label = str(focus.get("label", "束腰") or "")
        if focus_label:
            label = ax.text(
                z[nearest],
                cx[nearest] + rx[nearest] * 1.18,
                cy[nearest],
                focus_label,
                color=theme.BEAM_WAIST,
                fontsize=9,
                fontweight="semibold",
                zorder=11,
            )
            artists.persistent.append(label)


def _render_rays(
    ax,
    rays: list[dict],
    artists: DynamicSceneArtists,
    *,
    interactive: bool,
    reuse_collections: list | None = None,
    reuse_group_keys: list[tuple[str, float | None]] | None = None,
) -> None:
    display_rays = _sample_evenly(list(rays or []), 96) if interactive else list(rays or [])
    grouped: dict[tuple[str, float | None], list[np.ndarray]] = {}
    point_rows: list[np.ndarray] = []
    for ray in display_rays:
        points = _ray_points(ray, interactive=interactive)
        if points is None:
            continue
        point_rows.append(points)
        segment = np.column_stack((points[:, 2], points[:, 0], points[:, 1]))
        role = str(ray.get("role", "regular"))
        wavelength = ray.get("wavelength_nm")
        key = (role, float(wavelength) if wavelength else None)
        grouped.setdefault(key, []).append(segment)

    style = {
        "chief": (theme.RAY_CHIEF, 2.05, 0.98, "solid"),
        "marginal": (theme.RAY_MARGINAL, 1.22, 0.88, "solid"),
        "regular": (theme.RAY_REGULAR, 0.66, 0.42, "solid"),
        "failed": (theme.RAY_FAILED, 1.15, 0.95, "dashed"),
    }
    keys = sorted(grouped, key=lambda item: (item[0], item[1] if item[1] is not None else -1.0))
    can_reuse = bool(reuse_collections is not None and reuse_group_keys == keys and len(reuse_collections) == len(keys))
    if reuse_collections and not can_reuse:
        for collection in reuse_collections:
            _remove_artist(collection)

    for index, key in enumerate(keys):
        role, wavelength = key
        segments = grouped[key]
        color, width, alpha, linestyle = style.get(role, style["regular"])
        if wavelength is not None:
            color = _wavelength_color(wavelength, fallback=color)
        if can_reuse:
            collection = reuse_collections[index]
            collection.set_segments(segments)
            collection.set_color([to_rgba(color, alpha)])
            collection.set_linewidth(width)
            collection.set_linestyle(linestyle)
            collection.set_visible(True)
        else:
            collection = Line3DCollection(
                segments,
                colors=[to_rgba(color, alpha)],
                linewidths=width,
                linestyles=linestyle,
                zorder=8 if role in {"chief", "failed"} else 5,
            )
            ax.add_collection3d(collection)
        artists.ray_collections.append(collection)
        artists.ray_group_keys.append(key)



def _render_aperture(
    ax, item: dict, artists: DynamicSceneArtists, *, interactive: bool
) -> None:
    radius = float(item.get("radius", 0.0) or 0.0)
    if radius <= 0.0:
        return
    theta = np.linspace(0.0, 2.0 * np.pi, 36 if interactive else 72)
    z = float(item.get("z", 0.0) or 0.0)
    cx = float(item.get("center_x", 0.0) or 0.0)
    cy = float(item.get("center_y", 0.0) or 0.0)
    line, = ax.plot(
        np.full_like(theta, z),
        cx + radius * np.cos(theta),
        cy + radius * np.sin(theta),
        color=theme.APERTURE_COLOR,
        linewidth=1.55,
        alpha=0.92,
        zorder=10,
    )
    artists.persistent.append(line)


def _render_fiber(
    ax, item: dict, artists: DynamicSceneArtists, *, interactive: bool
) -> None:
    z0 = float(item.get("z", 0.0) or 0.0)
    cx = float(item.get("center_x", 0.0) or 0.0)
    cy = float(item.get("center_y", 0.0) or 0.0)
    radius = max(float(item.get("radius", 0.2) or 0.2), 0.03)
    length = max(
        float(item.get("metadata", {}).get("length_display", radius * 2.8)),
        0.2,
    )
    angular_count = 20 if interactive else 42
    axial_count = 4 if interactive else 7
    theta = np.linspace(0.0, 2.0 * np.pi, angular_count)
    z = np.linspace(z0, z0 + length, axial_count)[:, None]
    x = cx + radius * np.cos(theta)[None, :]
    y = cy + radius * np.sin(theta)[None, :]
    x = np.repeat(x, len(z), axis=0)
    y = np.repeat(y, len(z), axis=0)
    cylinder = ax.plot_surface(
        np.repeat(z, len(theta), axis=1),
        x,
        y,
        color=theme.FIBER_CLADDING,
        alpha=0.42 if interactive else 0.50,
        linewidth=0.0,
        shade=False,
        antialiased=not interactive,
        zorder=4,
    )
    artists.high_quality.append(cylinder)
    core_radius = radius * 0.34
    ring, = ax.plot(
        np.full_like(theta, z0),
        cx + core_radius * np.cos(theta),
        cy + core_radius * np.sin(theta),
        color=theme.FIBER_CORE,
        linewidth=1.3,
        alpha=0.95,
        zorder=10,
    )
    artists.persistent.append(ring)
    name = str(item.get("name", "") or "")
    if name:
        label = ax.text(
            z0 - 0.12 * length,
            cx + radius * 1.3,
            cy,
            name,
            color=theme.FIBER_CLADDING,
            fontsize=9,
            fontweight="semibold",
            ha="right",
            zorder=11,
        )
        artists.persistent.append(label)


def _render_section_plane(
    ax, section: dict, artists: DynamicSceneArtists, *, interactive: bool
) -> None:
    vertices = np.asarray(section.get("vertices", []), dtype=float)
    if vertices.shape != (4, 3) or interactive:
        return
    face = Poly3DCollection(
        [vertices],
        facecolors=to_rgba(theme.SECTION_PLANE, 0.065),
        edgecolors=to_rgba(theme.SECTION_PLANE, 0.36),
        linewidths=0.65,
        zorder=1,
    )
    ax.add_collection3d(face)
    artists.high_quality.append(face)


def _render_selected_surface_marker(ax, data: dict, artists: DynamicSceneArtists) -> None:
    selected = data.get("selected_surface")
    if not isinstance(selected, dict):
        selected = next(
            (dict(item) for item in data.get("surfaces", []) if bool(item.get("selected", False))),
            None,
        )
    if not isinstance(selected, dict):
        return
    z = float(selected.get("z", 0.0) or 0.0)
    cx = float(selected.get("decenter_x", selected.get("center_x", 0.0)) or 0.0)
    cy = float(selected.get("decenter_y", selected.get("center_y", 0.0)) or 0.0)
    aperture = max(float(selected.get("aperture", selected.get("radius", 0.0)) or 0.0), 0.05)
    theta = np.linspace(0.0, 2.0 * np.pi, 72)
    ring, = ax.plot(
        np.full_like(theta, z),
        cx + aperture * 1.035 * np.cos(theta),
        cy + aperture * 1.035 * np.sin(theta),
        color=theme.SURFACE_SELECTED_EDGE,
        linewidth=1.8,
        alpha=0.98,
        zorder=12,
    )
    artists.persistent.append(ring)
    index = selected.get("surface_index", data.get("selected_surface_index", ""))
    label = ax.text(
        z, cx + aperture * 1.10, cy, f"S{index}",
        color=theme.SURFACE_SELECTED_EDGE, fontsize=9, fontweight="bold", zorder=13,
    )
    artists.persistent.append(label)


def _render_orientation_marker(ax, artists: DynamicSceneArtists) -> None:
    marker = ax.text2D(
        0.025,
        0.035,
        "Z→  X↗  Y↑",
        transform=ax.transAxes,
        fontsize=9,
        color=theme.TEXT_SECONDARY,
    )
    artists.persistent.append(marker)


def _wavelength_color(wavelength_nm: float, *, fallback: str) -> str:
    if wavelength_nm < 450:
        return "#7C3AED"
    if wavelength_nm < 510:
        return "#2563EB"
    if wavelength_nm < 570:
        return "#059669"
    if wavelength_nm < 600:
        return "#D97706"
    if wavelength_nm < 750:
        return "#DC2626"
    return fallback


__all__ = ["DynamicSceneArtists", "render_dynamic_scene"]

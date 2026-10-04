"""Export the original Matplotlib scene's primitives for a browser renderer.

Geometry and camera fitting stay in the shared Python presentation layer. No
Qt canvas, pyplot state, optical engine or raster screenshot is used here.
"""
from __future__ import annotations

import numpy as np
from matplotlib.colors import to_rgba
from matplotlib.figure import Figure
from mpl_toolkits.mplot3d.art3d import Line3D, Line3DCollection, Poly3DCollection, Text3D

from .canvas_3d_static_parts import render_static_scene
from .canvas_3d_rendering import render_dynamic_scene
from .canvas_view import fit_optical_scene_3d
from .surface_tooltip import surface_tooltip


def _rgba(value, alpha=None):
    return list(to_rgba(value, alpha))


def scene_3d_model(data: dict) -> dict:
    figure = Figure(figsize=(1, 1), dpi=100)
    ax = figure.add_subplot(111, projection="3d")
    ax.set_proj_type("ortho")
    ax.set_axis_off()
    ax.set_position([0, 0, 1, 1])
    static = render_static_scene(ax, data)
    dynamic = render_dynamic_scene(ax, data)
    high_quality = [*static.high_quality, *dynamic.high_quality]
    fit_optical_scene_3d(ax, data)
    ax.view_init(elev=17, azim=-72)
    matrix = ax.get_proj()
    ax.M = matrix

    primitives = []
    surface_by_id = {f"surface:{int(surface.get('surface_index', -1))}": surface for surface in data.get("surfaces", [])}
    for order, artist in enumerate(ax.get_children()):
        common = {"order": order, "z_order": float(artist.get_zorder()), "interactive_hide": artist in high_quality}
        if isinstance(artist, Line3D):
            coordinates = artist.get_data_3d()
            points = np.column_stack(coordinates)
            if not np.all(np.isfinite(points)):
                continue
            primitives.append({**common, "kind": "line", "paths": [points.tolist()],
                "color": _rgba(artist.get_color(), artist.get_alpha()),
                "width": float(artist.get_linewidth()),
                "dash": list(artist._dash_pattern[1] or []), "surface_id": artist.get_gid(),
                "hover_text": surface_tooltip(surface_by_id[artist.get_gid()]) if artist.get_gid() in surface_by_id else None})
        elif isinstance(artist, Line3DCollection):
            primitives.append({**common, "kind": "line_collection", "paths": [np.asarray(row).tolist() for row in artist._segments3d],
                "color": artist.get_colors()[0].tolist(), "width": float(artist.get_linewidths()[0]),
                "dash": list(artist.get_linestyles()[0][1] or [])})
        elif isinstance(artist, Poly3DCollection):
            # _vec/_segslices are Matplotlib's original plot_surface/collection
            # polygons, including its rcount/ccount sampling and body quads.
            if hasattr(artist, "_faces"):
                invalid = np.broadcast_to(artist._invalid_vertices, artist._faces.shape[:2])
                faces = [face[~mask].tolist() for face, mask in zip(artist._faces, invalid)]
            else:
                faces = [artist._vec[:3, part].T.tolist() for part in artist._segslices]
            fill = _rgba(artist._facecolor3d[0], artist.get_alpha())
            edge = _rgba(artist._edgecolor3d[0], artist.get_alpha()) if len(artist._edgecolor3d) else [0, 0, 0, 0]
            primitives.append({**common, "kind": "polygons", "faces": faces,
                "color": fill, "edge_color": edge, "width": float(artist.get_linewidths()[0])})
        elif isinstance(artist, Text3D):
            x, y = artist.get_position()
            primitives.append({**common, "kind": "text", "point": [float(x), float(y), float(artist._z)],
                "text": artist.get_text(), "color": _rgba(artist.get_color(), artist.get_alpha()),
                "size": float(artist.get_fontsize()), "weight": artist.get_fontweight(),
                "horizontal": artist.get_ha(), "vertical": artist.get_va()})
        elif artist in ax.texts:
            primitives.append({**common, "kind": "text_2d", "point": list(artist.get_position()),
                "text": artist.get_text(), "color": _rgba(artist.get_color(), artist.get_alpha()),
                "size": float(artist.get_fontsize()), "weight": artist.get_fontweight(),
                "horizontal": artist.get_ha(), "vertical": artist.get_va()})

    return {"version": 1, "projection": matrix.tolist(), "data_view": [-0.095, 0.09],
        "limits": [list(ax.get_xlim()), list(ax.get_ylim()), list(ax.get_zlim())],
        "box_aspect": ax._box_aspect.tolist(), "elevation": 17, "azimuth": -72,
        "primitives": primitives}

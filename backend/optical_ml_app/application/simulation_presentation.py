"""Adapt completed simulation results using the original Python presentation data."""
from shared_presentation.display_profile import use_display_profile
from shared_presentation.simulation.adapters.formal_results import formal_result_diagnostics, formal_result_to_plots
from shared_presentation.simulation.detector_overlay import detector_object
from shared_presentation.simulation.result_metrics import ResultMetrics
from shared_presentation.plotting.ray_section import RaySection
from shared_presentation.plotting.scene_3d_model import scene_3d_model
import numpy as np

PLOT_KEYS = {
    "ray_layout": ("光路",), "layout_3d": ("3D光路",), "spot": ("点列图",),
    "coupling": ("端面匹配", "模式重叠", "耦合图", "能量分解"), "wavefront": ("波前", "PSF"),
}

def build_presentation(result: dict, project: dict, kind: str, observation: dict | None = None, profile: dict | None = None) -> dict:
    keys = PLOT_KEYS[kind]
    if kind in {"ray_layout", "layout_3d"}:
        # ResultDocument calls serialize_project without a form state. Preserve
        # that display convention: final table thickness supplies the image gap.
        # This changes layout coordinates only, never the submitted calculation.
        project = dict(project)
        surfaces = project.get("surfaces") or []
        project["image_distance_mm"] = max(float(surfaces[-1].get("distance_to_next_mm", 0)) if surfaces else 0, 1e-6)
        project["object_distance_mm"] = 1000000.0
    with use_display_profile(profile):
        plots = formal_result_to_plots(result, project, requested_keys=set(keys))
    plot = next((plots[key] for key in keys if key in plots and plots[key].get("kind", "empty") != "empty"), None)
    diagnostics = formal_result_diagnostics(result)
    if plot is None:
        plot = {"kind": "empty", "message": "正式结果已返回，但当前页暂未找到可绘制的数据。\n" + diagnostics}
    elif kind in {"ray_layout", "layout_3d"}:
        plot = dict(plot)
        objects = [dict(item) for item in plot.get("objects", []) if not item.get("metadata", {}).get("user_detector")]
        overlay = detector_object(plot, dict(observation or {}), project.get("receiver", {}).get("mode_field_diameter_x_um", 5.0))
        if overlay is not None:
            objects.append(overlay)
        plot["objects"] = objects
        if kind == "ray_layout":
            model = RaySection._raytrace_artist_model(plot)
            plot["section_artists"] = {
                key: model[key] for key in ("surface_segments", "surface_colors", "surface_widths", "rim_segments", "grouped_rays", "scale_visible")
            }
        else:
            plot["scene_artists"] = scene_3d_model(plot)
    if plot.get("kind") == "beam_match":
        # QPainter's contour rows use numpy linspace(dtype=int). Keep its exact
        # sampling and float32 threshold so boundary pixels agree with Qt.
        plot = dict(plot)
        contour = np.asarray(plot.get("contour", []), dtype=np.float32)
        paths = [[], []]
        if contour.ndim == 2 and contour.size and contour.shape == np.asarray(plot.get("z", [])).shape:
            threshold = float(np.nanmax(contour)) * float(plot.get("contour_fraction", np.exp(-2.0)))
            if threshold > 0:
                mask = contour >= threshold
                for row in np.linspace(0, mask.shape[0]-1, min(mask.shape[0], 180), dtype=int):
                    columns = np.flatnonzero(mask[row])
                    if columns.size:
                        for path, column in zip(paths, (columns[0], columns[-1])):
                            path.append([float(column / max(mask.shape[1]-1, 1)), float(row / max(mask.shape[0]-1, 1))])
        plot["contour_paths"] = paths
    return {
        "kind": kind, "plot": plot,
        "labels": ResultMetrics(kind).labels(dict(result.get("metrics") or {}), arrays=dict(result.get("arrays") or {})),
        "details": "\n".join([f"结果来源：{result.get('source', '正式计算')}", f"状态：{result.get('status', '—')}", diagnostics]),
    }

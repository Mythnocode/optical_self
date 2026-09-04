from __future__ import annotations

import math

import numpy as np

from frontend_pyside.features.simulation.surface_registry import ensure_surface_defaults


class SimulationPreviewWorkflow:


    def __init__(self, project_context):
        self.context = project_context

    def run(self, *, project=None, quality: str = "high", parameter_changes: dict | None = None):
        project = project if project is not None else self.context.project
        quality = str(quality or "high").lower()
        if quality not in {"section", "interactive", "high"}:
            quality = "high"
        ray_count = {"section": 7, "interactive": 11, "high": 21}[quality]
        sample_count = {"section": 0, "interactive": 240, "high": 600}[quality]

        surfaces = []
        z_position = 0.0
        active_surfaces = []
        for index, surface in enumerate(project.surfaces):
            ensure_surface_defaults(surface, fallback_group=f"L{index // 2 + 1}")
            surfaces.append(
                {
                    "surface_index": index,
                    "surface_id": str(getattr(surface, "surface_id", "")),
                    "group_id": str(getattr(surface, "element_id", surface.group_id or "")),
                    "z": z_position,
                    "radius": surface.radius_mm,
                    "conic": surface.conic,
                    "aperture": surface.semi_aperture_mm,
                    "type": surface.surface_type,
                    "name": surface.name,
                    "enabled": surface.enabled,
                }
            )
            active_surfaces.append(surface)
            z_position += surface.thickness_mm

        rays = []
        wavelength_mm = project.wavelength_nm * 1.0e-6
        offsets = np.linspace(-2.5, 2.5, ray_count)
        centre = (ray_count - 1) / 2
        for ray_index, y0 in enumerate(offsets):
            z_values = [0.0]
            y_values = [float(y0)]
            x_values = [float((ray_index - centre) * 0.10)]
            y_value = float(y0)
            slope = -0.018 * y0
            current_z = 0.0
            for surface in active_surfaces:
                current_z += surface.thickness_mm
                y_value += slope * surface.thickness_mm
                if surface.enabled:
                    parameters = surface.type_parameters
                    if surface.surface_type == "坐标断点":
                        y_value -= float(parameters.get("decenter_y_mm", 0.0))
                        slope += math.tan(
                            math.radians(float(parameters.get("tilt_y_deg", 0.0)))
                        )
                    elif surface.surface_type == "衍射光栅":
                        density = float(parameters.get("groove_density_lpm", 600.0))
                        order = int(parameters.get("diffraction_order", 1))
                        argument = float(
                            np.clip(order * wavelength_mm * density, -0.98, 0.98)
                        )
                        slope += 0.08 * math.asin(argument)
                    elif surface.surface_type == "反射镜":
                        slope = -slope
                    elif surface.surface_type not in {"光阑", "探测器/像面"}:
                        sign = 1 if surface.radius_mm >= 0 else -1
                        slope += -0.0009 * y_value * sign
                z_values.append(current_z)
                y_values.append(y_value)
                x_values.append(x_values[-1])
            rays.append({"z": z_values, "x": x_values, "y": y_values})

        changes = {str(k): float(v) for k, v in dict(parameter_changes or {}).items() if isinstance(v, (int, float))}
        receiver_dx_mm = float(changes.get("receiver.offset_x_mm", 0.0))
        receiver_dy_mm = float(changes.get("receiver.offset_y_mm", 0.0))
        receiver_dz_mm = float(changes.get("receiver.axial_offset_z_mm", 0.0))
        tilt_x_rad = math.radians(float(changes.get("receiver.tilt_x_deg", 0.0)))
        tilt_y_rad = math.radians(float(changes.get("receiver.tilt_y_deg", 0.0)))
        mfd_um = max(0.1, float(changes.get("receiver.mode_field_diameter_x_um", getattr(project, "receiver_mfd_um", 5.0))))
        mode_radius_mm = 0.5 * mfd_um * 1.0e-3

        enabled_count = sum(1 for surface in active_surfaces if surface.enabled)
        grating_count = sum(
            1 for surface in active_surfaces if surface.surface_type == "衍射光栅"
        )
        base_efficiency = float(
            np.clip(
                0.84
                - 0.006 * enabled_count
                - 0.01 * sum(abs(surface.conic) for surface in active_surfaces)
                - 0.015 * grating_count,
                0.05,
                0.93,
            )
        )
        # Candidate mode is still a *quick preview*, never a formal result.  Use
        # standard Gaussian-overlap factors so lateral/angle/axial fibre changes
        # produce meaningful visual feedback without touching the shared system.
        lateral_factor = math.exp(-2.0 * (receiver_dx_mm**2 + receiver_dy_mm**2) / max(mode_radius_mm**2, 1e-15))
        k_mm = 2.0 * math.pi / max(wavelength_mm, 1e-12)
        tilt_factor = math.exp(-0.5 * (k_mm * mode_radius_mm) ** 2 * (tilt_x_rad**2 + tilt_y_rad**2))
        rayleigh_mm = math.pi * mode_radius_mm**2 / max(wavelength_mm, 1e-12)
        axial_factor = 1.0 / (1.0 + (receiver_dz_mm / max(2.0 * rayleigh_mm, 1e-12)) ** 2)
        efficiency = float(np.clip(base_efficiency * lateral_factor * tilt_factor * axial_factor, 0.0, 0.93))
        metrics = {
            "coupling_efficiency": efficiency,
            "strehl": 0.90,
            "rms_spot_um": 1.27,
            "edge_power": 0.0018,
        }
        source = "候选快速预览（待正式验证）" if changes else "快速近似预览"
        plots = {
            "光路": {
                "kind": "raytrace",
                "surfaces": surfaces,
                "rays": rays,
                "title": "二维光路预览",
                "x_label": "z / mm",
                "y_label": "y / mm",
                "source": source,
                "render_quality": "interactive" if quality != "high" else "high",
                "description": "编辑期间优先更新二维截面；正式结果仍需后端求解器验证。",
            }
        }
        if quality == "section":
            plots["__metrics__"] = metrics
            plots["__quality__"] = quality
            return plots

        plots["3D光路"] = {
            "kind": "raytrace3d",
            "surfaces": surfaces,
            "rays": rays,
            "optical_axis": [0.0, z_position],
            "title": "三维光路预览",
            "x_label": "z / mm",
            "y_label": "x / mm",
            "z_label": "y / mm",
            "source": source,
            "render_quality": "interactive" if quality == "interactive" else "high",
            "description": "简化三维用于编辑反馈；高质量三维在停止操作后更新。",
        }
        if quality == "interactive":
            plots["__metrics__"] = metrics
            plots["__quality__"] = quality
            return plots

        rng = np.random.default_rng(7)
        spot = rng.normal(0, 1.0, sample_count)
        spot_y = rng.normal(0, 0.78, sample_count)
        axis = np.linspace(-8, 8, 151)
        xx, yy = np.meshgrid(axis, axis)
        psf = np.exp(-2 * (xx**2 + yy**2) / (1.7**2))
        freq = np.linspace(0, 1, 161)
        mtf = np.exp(-2.4 * freq**2)
        plots.update(
            {
                "点列图": {
                    "kind": "scatter",
                    "x": spot,
                    "y": spot_y,
                    "title": "几何点列图",
                    "x_label": "x / μm",
                    "y_label": "y / μm",
                    "source": source,
                },
                "PSF": {
                    "kind": "heatmap",
                    "x": axis.tolist(),
                    "y": axis.tolist(),
                    "z": psf.tolist(),
                    "title": "归一化 PSF",
                    "x_label": "x / μm",
                    "y_label": "y / μm",
                    "source": source,
                },
                "MTF": {
                    "kind": "line",
                    "x": freq.tolist(),
                    "y": mtf.tolist(),
                    "title": "MTF",
                    "x_label": "归一化频率",
                    "y_label": "调制度",
                    "source": source,
                },
                "耦合场": {
                    "kind": "heatmap_pair",
                    "x": axis.tolist(),
                    "y": axis.tolist(),
                    "z1": np.exp(
                        -2 * ((xx - 0.25) ** 2 + (yy + 0.1) ** 2) / (2.1**2)
                    ).tolist(),
                    "z2": np.exp(-2 * (xx**2 + yy**2) / (2.0**2)).tolist(),
                    "title": "接收面场与光纤模式（近似）",
                    "source": source,
                },
                "诊断": {
                    "kind": "bar",
                    "labels": ["边缘功率", "闭合误差", "采样误差"],
                    "values": [0.0018, 0.0012, 0.0024],
                    "title": "数值质量诊断",
                    "source": source,
                },
            }
        )
        plots["__metrics__"] = metrics
        plots["__quality__"] = quality
        return plots


__all__ = ["SimulationPreviewWorkflow"]

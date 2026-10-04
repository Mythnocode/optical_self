"""Original optical section artist geometry, independent of GUI widgets."""
import numpy as np
from shared_presentation import theme_tokens as theme
RAY_LINEWIDTH_2D=.85
RAY_ALPHA_2D=.58
SURFACE_LINEWIDTH_2D=1.35

class RaySection:
    @staticmethod
    def _raytrace_artist_model(data: dict) -> dict:
            """把光路载荷转换为可复用的镜面、边框和射线 artist 模型。"""
    
            surfaces = list(data.get("surfaces", []) or [])
            rays = list(data.get("rays", []) or [])
            selected = data.get("selected_surface_index")
    
            surface_segments: list[np.ndarray] = []
            surface_colors: list[str] = []
            surface_widths: list[float] = []
            group_rims: dict[str, list[tuple[float, float, float, float]]] = {}
            for surface in surfaces:
                z = float(surface.get("z", 0.0) or 0.0)
                aperture = float(surface.get("aperture", 0.0) or 0.0)
                low = float(surface.get("t_min", -aperture))
                high = float(surface.get("t_max", aperture))
                transverse = np.linspace(low, high, 72)
                centre = 0.5 * (low + high)
                radius = float(surface.get("radius", float("inf")) or float("inf"))
                conic = float(surface.get("conic", 0.0) or 0.0)
                rho = np.abs(transverse - centre)
                if np.isfinite(radius) and 1.0e-12 < abs(radius) < 1.0e12:
                    inside = np.maximum(1.0 - (1.0 + conic) * np.square(rho / radius), 0.0)
                    denominator = radius * (1.0 + np.sqrt(inside))
                    sag = np.divide(
                        np.square(rho),
                        denominator,
                        out=np.zeros_like(rho),
                        where=np.abs(denominator) > 1.0e-12,
                    )
                else:
                    sag = np.zeros_like(rho)
                segment = np.column_stack((z + sag, transverse))
                surface_segments.append(segment)
                is_selected = int(surface.get("surface_index", -1)) == selected or bool(
                    surface.get("selected")
                )
                surface_colors.append(
                    theme.SURFACE_SELECTED_EDGE if is_selected else theme.SURFACE_EDGE
                )
                surface_widths.append(2.0 if is_selected else SURFACE_LINEWIDTH_2D)
                group = str(surface.get("group_id", "") or "")
                if group:
                    group_rims.setdefault(group, []).append(
                        (float(segment[0, 0]), low, float(segment[-1, 0]), high)
                    )
    
            rim_segments: list[np.ndarray] = []
            for group_surfaces in group_rims.values():
                if len(group_surfaces) < 2:
                    continue
                first, second = group_surfaces[0], group_surfaces[-1]
                rim_segments.extend(
                    [
                        np.asarray([[first[0], first[1]], [second[0], second[1]]], dtype=float),
                        np.asarray([[first[2], first[3]], [second[2], second[3]]], dtype=float),
                    ]
                )
    
            grouped: dict[str, list[np.ndarray]] = {}
            for ray in rays:
                z_values = np.asarray(ray.get("z", []), dtype=float)
                transverse = np.asarray(ray.get("t", ray.get("y", [])), dtype=float)
                count = min(len(z_values), len(transverse))
                if count >= 2:
                    grouped.setdefault(str(ray.get("role", "regular")), []).append(
                        np.column_stack((z_values[:count], transverse[:count]))
                    )
    
            scale_visible = bool(data.get("scale_label")) and data.get("scale_mode") != "physical"
            objects = tuple(
                (
                    str(item.get("kind", "")),
                    float(item.get("z", 0.0) or 0.0),
                    float(item.get("center_y", item.get("center_x", 0.0)) or 0.0),
                    float(item.get("radius", 0.0) or 0.0),
                    float(item.get("width", 0.0) or 0.0),
                    float(item.get("height", 0.0) or 0.0),
                )
                for item in data.get("objects") or []
                if isinstance(item, dict)
            )
            signature = (
                len(surface_segments),
                len(rim_segments),
                tuple(sorted(grouped)),
                scale_visible,
                objects,
            )
            return {
                "surface_segments": surface_segments,
                "surface_colors": surface_colors,
                "surface_widths": surface_widths,
                "rim_segments": rim_segments,
                "grouped_rays": grouped,
                "scale_visible": scale_visible,
                "signature": signature,
            }

    @staticmethod
    def _ray_role_style(role: str) -> tuple[str, float, float, str]:
            """返回不同射线角色对应的颜色、线宽、透明度和线型。"""
            styles = {
                "chief": (theme.RAY_CHIEF, 1.45, 0.92, "solid"),
                "marginal": (theme.RAY_MARGINAL, 1.0, 0.76, "solid"),
                "regular": (theme.RAY_REGULAR, RAY_LINEWIDTH_2D, RAY_ALPHA_2D, "solid"),
                "failed": (theme.RAY_FAILED, 1.05, 0.95, "dashed"),
            }
            return styles.get(role, styles["regular"])


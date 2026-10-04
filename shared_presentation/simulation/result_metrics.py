"""Original result-header formatting and array-derived display positions."""
from typing import Any
import math
import numpy as np
from shared_presentation.plotting.optical_scene_geometry import build_beam_envelope, focus_from_envelope

class ResultMetrics:
    def __init__(self, kind: str):
        self.kind = kind

    @staticmethod
    def _format_efficiency(value: Any) -> str:
        try:
            return f"{float(value) * 100:.2f}%"
        except (TypeError, ValueError):
            return "—"


    @staticmethod
    def _format_number(value: Any, *, suffix: str = "", digits: int = 2) -> str:
        """Format optional result metrics without applying numeric formatting to placeholders."""
        try:
            number = float(value)
        except (TypeError, ValueError):
            return "—"
        if not math.isfinite(number):
            return "—"
        return f"{number:.{digits}f}{suffix}"


    @staticmethod
    def _metric_value(metrics: dict[str, Any], *names: str) -> Any:
        """Read a metric from both flat and analysis-namespaced result payloads."""
        for name in names:
            if name in metrics and metrics[name] is not None:
                return metrics[name]
            suffix = f".{name}"
            matches = [
                value
                for key, value in metrics.items()
                if str(key).endswith(suffix) and value is not None
            ]
            if len(matches) == 1:
                return matches[0]
        return None


    @staticmethod
    def _numeric_array(value: Any, *, ndim: int | None = None) -> np.ndarray | None:
        """Return a numeric array while treating lazy descriptors as unavailable."""
        if value is None or isinstance(value, dict):
            return None
        try:
            array = np.asarray(value, dtype=float)
        except (TypeError, ValueError):
            return None
        if not array.size or (ndim is not None and array.ndim != ndim):
            return None
        return array


    @classmethod
    def _peak_position_text(cls, metrics: dict[str, Any], arrays: dict[str, Any]) -> str:
        """Read or derive the PSF peak coordinate for the spot header."""
        direct = cls._metric_value(metrics, "peak_position", "psf_peak_position")
        if isinstance(direct, dict):
            x_value = direct.get("x_um", direct.get("x_mm"))
            y_value = direct.get("y_um", direct.get("y_mm"))
            try:
                x = float(x_value)
                y = float(y_value)
                if "x_mm" in direct:
                    x *= 1000.0
                if "y_mm" in direct:
                    y *= 1000.0
                if math.isfinite(x) and math.isfinite(y):
                    return f"x={x:.2f} μm, y={y:.2f} μm"
            except (TypeError, ValueError):
                pass
        elif direct is not None:
            text = str(direct).strip()
            if text:
                return text

        peak_x = cls._metric_value(metrics, "psf_peak_x_um", "peak_x_um")
        peak_y = cls._metric_value(metrics, "psf_peak_y_um", "peak_y_um")
        try:
            x = float(peak_x)
            y = float(peak_y)
            if math.isfinite(x) and math.isfinite(y):
                return f"x={x:.2f} μm, y={y:.2f} μm"
        except (TypeError, ValueError):
            pass

        intensity = None
        for name in ("hybrid_psf_intensity", "psf_intensity", "diffraction_intensity"):
            candidate = cls._numeric_array(arrays.get(name), ndim=2)
            if candidate is not None:
                intensity = candidate
                break
        if intensity is None:
            # Spot-only results may not contain a PSF grid. Estimate the
            # densest spot cell so the header remains useful in that mode.
            points = cls._numeric_array(arrays.get("spot_points_um"), ndim=2)
            if points is None:
                x_points = cls._numeric_array(arrays.get("spot_x_um"), ndim=1)
                y_points = cls._numeric_array(arrays.get("spot_y_um"), ndim=1)
                if x_points is not None and y_points is not None and len(x_points) == len(y_points):
                    points = np.column_stack((x_points, y_points))
            if points is None or points.shape[1] != 2:
                return "—"
            points = points[np.all(np.isfinite(points), axis=1)]
            if not len(points):
                return "—"
            if len(points) == 1:
                x, y = (float(value) for value in points[0])
                return f"x={x:.2f} μm, y={y:.2f} μm"
            bins = max(8, min(32, int(np.sqrt(len(points)) * 2.0)))
            weights = cls._numeric_array(arrays.get("spot_integration_weights"), ndim=1)
            if weights is not None and len(weights) == len(points):
                weights = np.maximum(np.nan_to_num(weights, nan=0.0), 0.0)
            else:
                weights = None
            try:
                histogram, x_edges, y_edges = np.histogram2d(
                    points[:, 0], points[:, 1], bins=bins, weights=weights
                )
                cell_x, cell_y = np.unravel_index(int(np.argmax(histogram)), histogram.shape)
                in_cell = (
                    (points[:, 0] >= x_edges[cell_x])
                    & (points[:, 0] <= x_edges[cell_x + 1])
                    & (points[:, 1] >= y_edges[cell_y])
                    & (points[:, 1] <= y_edges[cell_y + 1])
                )
                selected = points[in_cell]
                if not len(selected):
                    selected = points
                x = float(np.mean(selected[:, 0]))
                y = float(np.mean(selected[:, 1]))
                return f"x={x:.2f} μm, y={y:.2f} μm"
            except (TypeError, ValueError):
                return "—"

        x_candidates = [
            cls._numeric_array(arrays.get(name), ndim=1)
            for name in ("detector_grid_x_mm", "coupling_grid_x_mm", "psf_x_mm")
        ]
        y_candidates = [
            cls._numeric_array(arrays.get(name), ndim=1)
            for name in ("detector_grid_y_mm", "coupling_grid_y_mm", "psf_y_mm")
        ]
        axis_x = next(
            (axis for axis in x_candidates if axis is not None and len(axis) == intensity.shape[1]),
            None,
        )
        axis_y = next(
            (axis for axis in y_candidates if axis is not None and len(axis) == intensity.shape[0]),
            None,
        )
        if axis_x is None or axis_y is None:
            return "—"

        finite = np.isfinite(intensity)
        if not np.any(finite):
            return "—"
        safe_intensity = np.where(finite, intensity, -np.inf)
        row, column = np.unravel_index(int(np.argmax(safe_intensity)), intensity.shape)
        x = float(axis_x[column]) * 1000.0
        y = float(axis_y[row]) * 1000.0
        if not (math.isfinite(x) and math.isfinite(y)):
            return "—"
        return f"x={x:.2f} μm, y={y:.2f} μm"


    @classmethod
    def _focus_position_text(cls, metrics: dict[str, Any], arrays: dict[str, Any]) -> str:
        """Read a focus-search result or derive focus from ray data."""
        direct = cls._metric_value(
            metrics,
            "best_focus_z_mm",
            "focus_position_z_mm",
            "focus_z_mm",
            "focus_position",
        )
        if isinstance(direct, dict):
            direct = direct.get("z_mm", direct.get("z"))
        try:
            z = float(direct)
            if math.isfinite(z):
                return f"z={z:.2f} mm"
        except (TypeError, ValueError):
            if direct is not None and str(direct).strip():
                return str(direct).strip()

        path_points = cls._numeric_array(arrays.get("raytrace_path_points_mm"), ndim=2)
        offsets = cls._numeric_array(arrays.get("raytrace_path_offsets"), ndim=1)
        if (
            path_points is not None
            and path_points.shape[1] == 3
            and offsets is not None
            and len(offsets) >= 3
        ):
            statuses = cls._numeric_array(arrays.get("raytrace_status_codes"), ndim=1)
            rays: list[dict[str, Any]] = []
            integer_offsets = offsets.astype(int)
            for index, (start, end) in enumerate(zip(integer_offsets[:-1], integer_offsets[1:])):
                if not (0 <= start < end <= len(path_points)):
                    continue
                status = int(statuses[index]) if statuses is not None and index < len(statuses) else 0
                rays.append({"points": path_points[start:end], "role": "failed" if status else ""})
            focus = focus_from_envelope(build_beam_envelope(rays))
            if isinstance(focus, dict):
                try:
                    z = float(focus.get("z"))
                    if math.isfinite(z):
                        return f"z={z:.2f} mm"
                except (TypeError, ValueError):
                    pass

        # Reduced result policies may omit full paths but retain final ray lines.
        positions = cls._numeric_array(arrays.get("raytrace_final_positions_mm"), ndim=2)
        directions = cls._numeric_array(arrays.get("raytrace_final_directions"), ndim=2)
        if (
            positions is None
            or directions is None
            or positions.shape != directions.shape
            or positions.shape[1] != 3
        ):
            return "—"
        valid_mask = cls._numeric_array(arrays.get("raytrace_valid_mask"), ndim=1)
        matrix = np.zeros((3, 3), dtype=float)
        vector = np.zeros(3, dtype=float)
        valid_count = 0
        for index, (position, direction) in enumerate(zip(positions, directions)):
            if valid_mask is not None and (index >= len(valid_mask) or valid_mask[index] <= 0.5):
                continue
            if not np.all(np.isfinite(position)) or not np.all(np.isfinite(direction)):
                continue
            norm = float(np.linalg.norm(direction))
            if norm <= 1.0e-12:
                continue
            unit = direction / norm
            projection = np.eye(3) - np.outer(unit, unit)
            matrix += projection
            vector += projection @ position
            valid_count += 1
        if valid_count < 2:
            return "—"
        try:
            focus = np.linalg.lstsq(matrix, vector, rcond=None)[0]
            z = float(focus[2])
        except (np.linalg.LinAlgError, TypeError, ValueError):
            return "—"
        return f"z={z:.2f} mm" if math.isfinite(z) else "—"


    def labels(
        self,
        metrics: dict[str, Any],
        *,
        arrays: dict[str, Any] | None = None,
    ) -> list[str]:
        """Update the compact metric header, including array-derived positions."""
        arrays = dict(arrays or {})
        if self.kind == "coupling":
            system_value = metrics.get("system_efficiency")
            if system_value is None:
                system_value = metrics.get("transmission_efficiency")
            receiver_value = metrics.get("receiver_efficiency")
            if receiver_value is None:
                receiver_value = metrics.get("receiving_efficiency")
            if receiver_value is None:
                receiver_value = metrics.get("fiber_interface_efficiency")
            total_value = metrics.get("total_coupling_efficiency")
            if total_value is None:
                total_value = metrics.get("total_efficiency")
            if total_value is None:
                total_value = metrics.get("coupling_efficiency")
            values = (
                f"系统效率：{self._format_efficiency(system_value)}",
                f"端面接收效率：{self._format_efficiency(receiver_value)}",
                f"总耦合效率：{self._format_efficiency(total_value)}",
            )
        elif self.kind == "spot":
            values = (
                f"光斑半径：{self._format_number(metrics.get('rms_spot_radius_um', metrics.get('rms_um')), suffix=' μm')}",
                f"峰值位置：{self._peak_position_text(metrics, arrays)}",
                None,
            )
        elif self.kind == "ray_layout":
            values = (
                f"光线数量：{metrics.get('ray_count', '—')}",
                f"聚焦位置：{self._focus_position_text(metrics, arrays)}",
                None,
            )
        elif self.kind == "wavefront":
            values = (
                f"波前 RMS：{self._format_number(self._metric_value(metrics, 'wavefront_rms_nm', 'wavefront_rms'), suffix=' nm')}",
                f"斯特列尔：{self._format_number(self._metric_value(metrics, 'strehl_estimate_marechal', 'strehl', 'strehl_ratio', 'wavefront_strehl'))}",
                None,
            )
        elif self.kind == "layout_3d":
            values = ("三维视图", None, None)
        else:
            values = ("—", None, None)

        return [value for value in values if value is not None]

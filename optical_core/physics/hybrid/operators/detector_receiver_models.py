# 定义像素探测器、接收器位置和姿态、噪声、饱和及光线到像素的沉积模型。
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np


@dataclass(frozen=True, slots=True)
class PixelArrayDetector:


    pixel_count_x: int = 128
    pixel_count_y: int = 128
    pixel_pitch_um: float = 5.0
    saturation_electrons: float = 50_000.0
    read_noise_electrons: float = 3.0
    dark_current_electrons_per_s: float = 0.0
    exposure_s: float = 1.0

    @property
    def width_x_mm(self) -> float:
        return self.pixel_count_x * self.pixel_pitch_um / 1000.0

    @property
    def height_y_mm(self) -> float:
        return self.pixel_count_y * self.pixel_pitch_um / 1000.0


@dataclass(frozen=True, slots=True)
class ReceiverPose:


    offset_x_mm: float = 0.0
    offset_y_mm: float = 0.0
    axial_offset_z_mm: float = 0.0
    tilt_x_deg: float = 0.0
    tilt_y_deg: float = 0.0


@dataclass(frozen=True, slots=True)
class DetectorNoiseModel:
    read_noise_electrons: float = 3.0
    dark_current_electrons_per_s: float = 0.0
    shot_noise: bool = True
    seed: int = 42


@dataclass(frozen=True, slots=True)
class DetectorSaturationModel:
    saturation_electrons: float = 50_000.0
    full_well_electrons: float = 50_000.0
    clip: bool = True


def apply_receiver_pose(points_xy_mm: Any, pose: ReceiverPose) -> np.ndarray:


    pts = np.asarray(points_xy_mm, dtype=float)
    if pts.ndim == 1:
        pts = pts.reshape(1, -1)
    if pts.ndim != 2 or pts.shape[1] not in {2, 3}:
        raise ValueError("points_xy_mm must have shape (N,2) or (N,3) in XYZ order")
    xy = pts[:, :2].copy()
    xy[:, 0] -= float(pose.offset_x_mm)
    xy[:, 1] -= float(pose.offset_y_mm)
    
    xy[:, 0] -= float(pose.axial_offset_z_mm) * np.tan(np.deg2rad(float(pose.tilt_x_deg)))
    xy[:, 1] -= float(pose.axial_offset_z_mm) * np.tan(np.deg2rad(float(pose.tilt_y_deg)))
    return xy


def detector_coordinates(detector: PixelArrayDetector) -> tuple[np.ndarray, np.ndarray]:
    x = (np.arange(detector.pixel_count_x) - (detector.pixel_count_x - 1) / 2.0) * detector.pixel_pitch_um / 1000.0
    y = (np.arange(detector.pixel_count_y) - (detector.pixel_count_y - 1) / 2.0) * detector.pixel_pitch_um / 1000.0
    return np.meshgrid(x, y, indexing="xy")


def deposit_points_to_pixels(
    detector: PixelArrayDetector,
    points_xy_mm: Any,
    signal_weights: Any | None = None,
    *,
    pose: ReceiverPose | None = None,
) -> np.ndarray:


    pts = np.asarray(points_xy_mm, dtype=float)
    if pts.ndim == 1:
        pts = pts.reshape(1, -1)
    xy = apply_receiver_pose(pts, pose) if pose is not None else pts[:, :2]
    signal = np.ones(xy.shape[0], dtype=float) if signal_weights is None else np.asarray(signal_weights, dtype=float).reshape(-1)
    if signal.shape != (xy.shape[0],):
        raise ValueError("signal_weights must contain one value per point")
    if np.any(~np.isfinite(signal)) or np.any(signal < 0.0):
        raise ValueError("signal_weights must be finite and non-negative")

    image = np.zeros((detector.pixel_count_y, detector.pixel_count_x), dtype=float)
    pitch = detector.pixel_pitch_um / 1000.0
    px = xy[:, 0] / pitch + (detector.pixel_count_x - 1) / 2.0
    py = xy[:, 1] / pitch + (detector.pixel_count_y - 1) / 2.0
    for x_pixel, y_pixel, value in zip(px, py, signal):
        x0 = int(np.floor(x_pixel))
        y0 = int(np.floor(y_pixel))
        dx = x_pixel - x0
        dy = y_pixel - y0
        for ix, wx in ((x0, 1.0 - dx), (x0 + 1, dx)):
            if ix < 0 or ix >= detector.pixel_count_x:
                continue
            for iy, wy in ((y0, 1.0 - dy), (y0 + 1, dy)):
                if iy < 0 or iy >= detector.pixel_count_y:
                    continue
                image[iy, ix] += float(value) * float(wx) * float(wy)
    return image


def add_detector_noise(image: Any, model: DetectorNoiseModel) -> np.ndarray:
    arr = np.asarray(image, dtype=float)
    rng = np.random.default_rng(int(model.seed))
    out = arr.copy()
    if model.shot_noise:
        out = rng.poisson(np.maximum(out, 0.0)).astype(float)
    dark = float(model.dark_current_electrons_per_s)
    if dark > 0.0:
        out += rng.poisson(dark, size=out.shape)
    if model.read_noise_electrons > 0.0:
        out += rng.normal(0.0, float(model.read_noise_electrons), size=out.shape)
    return out


def apply_saturation(image: Any, model: DetectorSaturationModel) -> np.ndarray:
    arr = np.asarray(image, dtype=float)
    if not model.clip:
        return arr
    return np.clip(arr, 0.0, float(model.saturation_electrons))


def detector_dynamic_range_db(detector: PixelArrayDetector) -> float:
    noise = max(float(detector.read_noise_electrons), 1e-12)
    return float(20.0 * np.log10(max(float(detector.saturation_electrons), noise) / noise))


def detector_summary(image: Any) -> dict[str, float]:
    arr = np.asarray(image, dtype=float)
    total = float(np.sum(arr))
    peak = float(np.max(arr)) if arr.size else 0.0
    saturated_fraction = float(np.count_nonzero(arr >= peak) / arr.size) if arr.size and peak > 0.0 else 0.0
    return {
        "detector_total_signal": total,
        "detector_peak_signal": peak,
        "detector_saturated_peak_fraction": saturated_fraction,
    }


__all__ = [
    "PixelArrayDetector",
    "ReceiverPose",
    "DetectorNoiseModel",
    "DetectorSaturationModel",
    "apply_receiver_pose",
    "detector_coordinates",
    "deposit_points_to_pixels",
    "add_detector_noise",
    "apply_saturation",
    "detector_dynamic_range_db",
    "detector_summary",
]

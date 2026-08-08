from __future__ import annotations

import math
from typing import Any, Mapping
import numpy as np

from .contracts import get_module


def _read(inputs: Mapping[str, Any], key: str, spec: Mapping[str, Any]) -> float:
    try:
        value = float(inputs.get(key, spec["default"]))
    except (TypeError, ValueError):
        value = float(spec["default"])
    if not math.isfinite(value):
        value = float(spec["default"])
    return float(np.clip(value, float(spec["minimum"]), float(spec["maximum"])))


def _params(module: str, inputs: Mapping[str, Any] | None) -> dict[str, float]:
    contract = get_module(module)
    raw = inputs or {}
    return {k: _read(raw, k, spec) for k, spec in contract["parameters"].items()}


def _list(a, digits=8):
    return np.round(np.asarray(a, dtype=float), digits).tolist()


def calculate_gaussian(inputs=None) -> dict[str, Any]:
    p = _params("gaussian", inputs)
    wavelength_um = p["wavelength_nm"] * 1e-3
    w0 = p["waist_um"]
    m2 = p["beam_quality_m2"]
    z_um = p["observation_distance_mm"] * 1e3
    zr_um = math.pi * w0 * w0 / max(m2 * wavelength_um, 1e-15)
    radius = w0 * math.sqrt(1.0 + (z_um / max(zr_um, 1e-15)) ** 2)
    divergence = m2 * wavelength_um / (math.pi * max(w0, 1e-15))
    extent_mm = max(4 * zr_um / 1e3, abs(p["observation_distance_mm"]) * 1.25, 1.0)
    z_mm = np.linspace(-extent_mm, extent_mm, 241)
    radius_curve = w0 * np.sqrt(1.0 + ((z_mm * 1e3) / max(zr_um, 1e-15)) ** 2)
    x = np.linspace(-3 * radius, 3 * radius, 181)
    intensity = np.exp(-2 * (x / max(radius, 1e-15)) ** 2)
    passed = radius <= 50.0
    region = "束腰附近" if abs(z_um) <= zr_um else "明显发散区"
    return {
        "module": "gaussian", "inputs": p, "model_kind": "teaching_approximation",
        "metrics": {"rayleigh_range_mm": zr_um / 1e3, "observation_radius_um": radius,
                    "divergence_half_angle_mrad": divergence * 1e3},
        "plots": {"primary": {"kind": "line_multi", "x": _list(z_mm, 6),
                              "series": [{"label": "+w(z)", "y": _list(radius_curve, 6)},
                                         {"label": "-w(z)", "y": _list(-radius_curve, 6)}],
                              "x_label": "传播位置 z / mm", "y_label": "光束半径 / μm", "title": "Gaussian 光束包络"},
                  "secondary": {"kind": "line", "x": _list(x, 6), "y": _list(intensity, 8),
                                "x_label": "观察面横向位置 / μm", "y_label": "归一化强度", "title": "观察面光强截面"}},
        "observation": f"观察面位于{region}；M² 越大，瑞利长度越短、发散越强。",
        "task_status": {"passed": passed, "label": "达到任务目标" if passed else "继续调整参数"},
    }


def _marcuse_mode_radius(a: float, v: float) -> float:
    v = max(v, 0.5)
    return a * (0.65 + 1.619 / v**1.5 + 2.879 / v**6)


def calculate_fiber(inputs=None) -> dict[str, Any]:
    p = _params("fiber", inputs)
    if p["n_clad"] >= p["n_core"]:
        p["n_clad"] = p["n_core"] - 1e-4
    na = math.sqrt(max(p["n_core"]**2 - p["n_clad"]**2, 0.0))
    wavelength_um = p["wavelength_nm"] * 1e-3
    v = 2 * math.pi * p["core_radius_um"] * na / max(wavelength_um, 1e-15)
    acceptance = math.degrees(math.asin(min(max(na, 0.0), 1.0)))
    single = v <= 2.405
    guided = p["launch_angle_deg"] <= acceptance
    mode_radius = _marcuse_mode_radius(p["core_radius_um"], v)
    axis = np.linspace(-3.2 * p["core_radius_um"], 3.2 * p["core_radius_um"], 121)
    xx, yy = np.meshgrid(axis, axis)
    lp01 = np.exp(-2 * (xx**2 + yy**2) / max(mode_radius**2, 1e-15))
    r = np.sqrt(xx**2 + yy**2)
    theta = np.arctan2(yy, xx)
    lp11 = ((r / max(p["core_radius_um"], 1e-15)) * np.cos(theta) * np.exp(-(r / max(mode_radius, 1e-15))**2))**2
    lp11 = lp11 / max(float(lp11.max()), 1e-15)
    return {
        "module": "fiber", "inputs": p, "model_kind": "teaching_approximation",
        "metrics": {"numerical_aperture": na, "v_number": v, "acceptance_half_angle_deg": acceptance,
                    "mfd_um": 2 * mode_radius},
        "plots": {"primary": {"kind": "heatmap", "x": _list(axis, 5), "y": _list(axis, 5), "z": _list(lp01, 6),
                              "x_label": "x / μm", "y_label": "y / μm", "title": "LP01 近似强度"},
                  "secondary": {"kind": "line", "x": _list(np.linspace(0, 4, 161), 4),
                                "y": _list(np.where(np.linspace(0,4,161) <= 2.405, 1.0, 0.0), 3),
                                "x_label": "V 数", "y_label": "单模判定", "title": "V 数截止示意"}},
        "observation": f"当前 V={v:.3f}，{'满足' if single else '不满足'}单模条件；入射角{'位于' if guided else '超出'}接受锥。",
        "task_status": {"passed": single and guided, "label": "单模且入射角合格" if single and guided else "继续调整光纤参数"},
        "flags": {"single_mode": single, "guided": guided, "lp11_visible": not single},
    }


def calculate_coupling(inputs=None) -> dict[str, Any]:
    p = _params("coupling", inputs)
    wb = p["beam_radius_um"]
    wf = p["mfd_um"] / 2.0
    wavelength_um = p["wavelength_nm"] * 1e-3
    dr = math.hypot(p["offset_x_um"], p["offset_y_um"])
    tilt = math.hypot(p["tilt_x_mrad"], p["tilt_y_mrad"]) * 1e-3
    size_factor = (2 * wb * wf / max(wb*wb + wf*wf, 1e-15)) ** 2
    effective_w = math.sqrt(2 * wb*wb * wf*wf / max(wb*wb + wf*wf, 1e-15))
    lateral = math.exp(-2 * dr*dr / max(wb*wb + wf*wf, 1e-15))
    angular = math.exp(-(math.pi * effective_w * tilt / max(wavelength_um, 1e-15)) ** 2)
    zr = math.pi * wb * wb / max(wavelength_um, 1e-15)
    axial = 1.0 / math.sqrt(1.0 + (p["axial_offset_um"] / max(zr, 1e-15)) ** 2)
    field = float(np.clip(size_factor * lateral * angular * axial, 0.0, 1.0))
    total = field * p["facet_transmission"]
    extent = max(3.0 * max(wb, wf), dr + 2.5 * wf, 10.0)
    axis = np.linspace(-extent, extent, 121)
    xx, yy = np.meshgrid(axis, axis)
    incident = np.exp(-2 * (xx**2 + yy**2) / max(wb**2, 1e-15))
    fiber = np.exp(-2 * ((xx-p["offset_x_um"])**2 + (yy-p["offset_y_um"])**2) / max(wf**2, 1e-15))
    scan = np.linspace(-3*effective_w, 3*effective_w, 201)
    scan_eta = size_factor * np.exp(-2 * scan**2 / max(wb*wb + wf*wf, 1e-15)) * p["facet_transmission"]
    passed = total >= 0.8
    factors = {"尺寸匹配": size_factor, "横向对准": lateral, "角度对准": angular, "轴向对准": axial, "端面透射": p["facet_transmission"]}
    weakest = min(factors, key=factors.get)
    return {
        "module": "coupling", "inputs": p, "model_kind": "teaching_approximation",
        "metrics": {"field_efficiency": field, "total_efficiency": total,
                    "lateral_factor": lateral, "angular_factor": angular},
        "plots": {"primary": {"kind": "heatmap_pair", "x": _list(axis,5), "y": _list(axis,5),
                              "z1": _list(incident,6), "z2": _list(fiber,6),
                              "title": "入射场与光纤模式强度"},
                  "secondary": {"kind": "line", "x": _list(scan,5), "y": _list(scan_eta,8),
                                "x_label": "X 偏移 / μm", "y_label": "总效率", "title": "横向偏移容差近似"},
                  "factors": {"kind": "bar", "labels": list(factors), "values": list(factors.values()), "title": "效率因子分解"}},
        "observation": f"当前最弱因素是“{weakest}”。强度重合不代表相位一定匹配。",
        "task_status": {"passed": passed, "label": "总效率达到 80%" if passed else "继续完成五轴对准"},
    }


def calculate_psf(inputs=None) -> dict[str, Any]:
    p = _params("psf", inputs)
    wavelength_um = p["wavelength_nm"] * 1e-3
    f_number = p["focal_length_mm"] / max(p["aperture_diameter_mm"], 1e-15)
    airy = 1.22 * wavelength_um * f_number
    w_rms = math.sqrt((p["defocus_waves"] / math.sqrt(12))**2 + (p["spherical_aberration_waves"] / math.sqrt(20))**2)
    strehl = math.exp(-(2 * math.pi * w_rms)**2)
    psf_rms = airy * (0.42 + 1.8 * w_rms + 0.9*w_rms*w_rms)
    geometric = airy * (0.15 + 2.4 * abs(p["defocus_waves"]) + 1.8 * abs(p["spherical_aberration_waves"]))
    n = 151
    extent = max(5 * airy, 3 * psf_rms, 2.0)
    axis = np.linspace(-extent, extent, n)
    xx, yy = np.meshgrid(axis, axis)
    rr = np.sqrt(xx**2 + yy**2)
    sigma_core = max(psf_rms / 1.177, airy * 0.25, 1e-6)
    core = np.exp(-0.5 * (rr/sigma_core)**2)
    ring_r = airy * (1.0 + 0.7*abs(p["spherical_aberration_waves"]))
    ring = 0.13 * (1-strehl) * np.exp(-0.5*((rr-ring_r)/max(0.25*airy,1e-6))**2)
    psf = core + ring
    psf /= max(float(psf.max()), 1e-15)
    freq = np.linspace(0, 1, 201)
    mtf = np.exp(-2.2 * (freq / max(strehl**0.25, 0.15))**2)
    return {
        "module": "psf", "inputs": p, "model_kind": "teaching_approximation",
        "metrics": {"airy_radius_um": airy, "strehl_ratio": strehl,
                    "psf_rms_radius_um": psf_rms, "geometric_rms_radius_um": geometric},
        "plots": {"primary": {"kind": "heatmap", "x": _list(axis,5), "y": _list(axis,5), "z": _list(psf,6),
                              "x_label": "像面 x / μm", "y_label": "像面 y / μm", "title": "近似 PSF"},
                  "secondary": {"kind": "line_multi", "x": _list(freq,5),
                                "series": [{"label": "当前 MTF", "y": _list(mtf,8)},
                                           {"label": "理想参考", "y": _list(np.exp(-2.2*freq**2),8)}],
                                "x_label": "归一化空间频率", "y_label": "MTF", "title": "MTF 近似对比"}},
        "observation": "像差增大时中心峰值下降、PSF 展宽，MTF 高频部分先受损。",
        "task_status": {"passed": strehl >= 0.8, "label": "接近衍射极限" if strehl >= 0.8 else "继续校正像差"},
    }


_CALCULATORS = {"gaussian": calculate_gaussian, "fiber": calculate_fiber, "coupling": calculate_coupling, "psf": calculate_psf}


def calculate(module: str, inputs=None) -> dict[str, Any]:
    try:
        result = _CALCULATORS[module](inputs)
    except KeyError as exc:
        raise ValueError(f"unknown teaching module: {module}") from exc
    contract = get_module(module)
    result.update({"title": contract["title"], "formula": contract["formula"],
                   "assumptions": contract["assumptions"], "theory": contract["theory"]})
    return result

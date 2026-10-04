
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping, Sequence

import numpy as np
from scipy.stats import pearsonr, spearmanr

from machine_learning.explainability.physics_features import PHYSICS_FEATURES


_STREHL_FORMULA = r"S\approx\exp[-(2\pi\sigma_W/\lambda)^2]"
_PSF_FORMULA = r"\mathrm{PSF}=|\mathcal{F}\{P\exp(i2\pi W/\lambda)\}|^2"
_MTF_FORMULA = r"\mathrm{MTF}=|\mathcal{F}\{\mathrm{PSF}\}|"
_SURFACE_PATH = re.compile(
    r"(?:surfaces?|surface)(?:\[(\d+)\]|\.(\d+))\.(.+)", re.IGNORECASE
)


@dataclass(frozen=True, slots=True)
class FormulaLinkageMetadata:
    feature: str
    physical_category: str
    formula_category: str
    formula_item: str
    mapping_level: str
    mapping_note: str
    formula_latex: str
    efficiency_formula_latex: str = ""
    source_parameters: tuple[str, ...] = ()
    description: str = ""
    formula_steps: tuple[tuple[str, str], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "physical_category": self.physical_category,
            "formula_category": self.formula_category,
            "formula_item": self.formula_item,
            "mapping_level": self.mapping_level,
            "mapping_note": self.mapping_note,
            "formula_latex": self.formula_latex,
            "efficiency_formula_latex": self.efficiency_formula_latex,
            "source_parameters": list(self.source_parameters),
            "description": self.description,
            "formula_steps": [
                {"stage": stage, "latex": latex}
                for stage, latex in self.formula_steps
            ],
        }


def _surface_formula_steps(feature: str) -> tuple[tuple[str, str], ...] | None:
    match = _SURFACE_PATH.fullmatch(str(feature).strip())
    if match is None:
        return None
    index = int(match.group(1) if match.group(1) is not None else match.group(2)) + 1
    field = match.group(3).lower()
    surface = rf"S_{{{index}}}"
    if field in {"radius_mm", "radius", "curvature_radius_mm"}:
        power = rf"\Phi_{{{surface}}}=\frac{{n_{{{surface}}}^+-n_{{{surface}}}^-}}{{R_{{{surface}}}}}"
        refraction = rf"(n\theta)_{{{surface}}}^+=(n\theta)_{{{surface}}}^--\Phi_{{{surface}}}y_{{{surface}}}"
        return (("表面光焦度", power), ("近轴折射", refraction))
    if field in {"distance_to_next_mm", "thickness_mm", "thickness", "air_gap_mm"}:
        distance = rf"y_{{{surface},\mathrm{{out}}}}=y_{{{surface},\mathrm{{in}}}}+t_{{{surface}}}\theta_{{{surface}}}"
        path = rf"\mathrm{{OPL}}_{{{surface}}}=n_{{{surface}}}t_{{{surface}}},\quad\Delta\phi_{{{surface}}}=\frac{{2\pi n_{{{surface}}}t_{{{surface}}}}}{{\lambda_0}}"
        return (("介质内传播", distance), ("光程与相位", path))
    if field == "conic":
        sag = rf"z_{{{surface}}}(r)=\frac{{c_{{{surface}}}r^2}}{{1+\sqrt{{1-(1+K_{{{surface}}})c_{{{surface}}}^2r^2}}}},\quad c_{{{surface}}}=\frac{{1}}{{R_{{{surface}}}}}"
        wavefront = rf"\Delta W_{{{surface}}}(r)=(n_{{{surface}}}^--n_{{{surface}}}^+)z_{{{surface}}}(r)"
        return (("非球面矢高", sag), ("波前光程差", wavefront))
    if field in {"semi_aperture_mm", "semi_diameter_mm", "aperture_mm"}:
        pupil = rf"P_{{{surface}}}(r)=\Theta(a_{{{surface}}}-r)"
        clipped = rf"E_{{{surface}}}^+(r)=P_{{{surface}}}(r)E_{{{surface}}}^-(r)"
        return (("表面孔径", pupil), ("孔径截断", clipped))
    if field in {"material", "material_after", "glass"}:
        dispersion = rf"n_{{m_{{{surface}}}}}^2(\lambda)=1+\sum_j\frac{{B_{{m_{{{surface}}},j}}\lambda^2}}{{\lambda^2-C_{{m_{{{surface}}},j}}}}"
        power = rf"\Phi_{{{surface}}}(\lambda)=\frac{{n_{{m_{{{surface}}}}}(\lambda)-n_{{{surface}}}^-(\lambda)}}{{R_{{{surface}}}}}"
        return (("材料色散", dispersion), ("波长相关光焦度", power))
    return None


def formula_linkage_for_feature(feature_name: str) -> FormulaLinkageMetadata:

    feature = str(feature_name)
    low = feature.lower().replace(" ", "")

    definition = PHYSICS_FEATURES.get(feature)
    if definition is not None:
        category_map = {
            "size_ratio": ("尺寸失配", "模式失配", "尺寸失配"),
            "lateral_mismatch": ("中心位置失配", "对准误差", "横向偏移"),
            "angular_mismatch": ("角度与波前失配", "对准误差", "角度偏移"),
            "axial_mismatch": ("焦面与曲率失配", "对准误差", "轴向离焦"),
            "curvature_mismatch": ("焦面与曲率失配", "模式失配", "曲率失配"),
        }
        physical_category, formula_category, formula_item = category_map[feature]
        return FormulaLinkageMetadata(
            feature=feature,
            physical_category=physical_category,
            formula_category=formula_category,
            formula_item=formula_item,
            mapping_level="直接",
            mapping_note="该特征就是解析公式使用的无量纲物理量",
            formula_latex=definition.formula_latex,
            efficiency_formula_latex=definition.efficiency_formula_latex,
            source_parameters=tuple(definition.source_parameters),
            description=definition.description,
            formula_steps=(
                ("无量纲物理量", definition.formula_latex),
                ("相对耦合效率", definition.efficiency_formula_latex),
            ),
        )

    surface_steps = _surface_formula_steps(feature)
    if surface_steps:
        field = _SURFACE_PATH.fullmatch(feature)
        assert field is not None
        surface_number = int(field.group(1) if field.group(1) is not None else field.group(2)) + 1
        property_name = field.group(3).lower()
        labels = {
            "radius_mm": ("结构参数", "曲率半径", "焦面与曲率失配", "曲率半径改变该表面的折射光焦度"),
            "radius": ("结构参数", "曲率半径", "焦面与曲率失配", "曲率半径改变该表面的折射光焦度"),
            "curvature_radius_mm": ("结构参数", "曲率半径", "焦面与曲率失配", "曲率半径改变该表面的折射光焦度"),
            "distance_to_next_mm": ("结构参数", "厚度与间隔", "焦面与曲率失配", "该面后的介质厚度决定传播矩阵与光程"),
            "thickness_mm": ("结构参数", "厚度与间隔", "焦面与曲率失配", "该面后的介质厚度决定传播矩阵与光程"),
            "thickness": ("结构参数", "厚度与间隔", "焦面与曲率失配", "该面后的介质厚度决定传播矩阵与光程"),
            "air_gap_mm": ("结构参数", "厚度与间隔", "焦面与曲率失配", "该空气间隔决定传播矩阵与光程"),
            "conic": ("结构参数", "圆锥系数", "光束结构与像差", "圆锥系数改变该表面的非球面矢高和波前"),
            "semi_aperture_mm": ("结构参数", "半口径", "光束结构与像差", "半口径定义该表面的瞳面截断范围"),
            "semi_diameter_mm": ("结构参数", "半口径", "光束结构与像差", "半口径定义该表面的瞳面截断范围"),
            "aperture_mm": ("结构参数", "半口径", "光束结构与像差", "半口径定义该表面的瞳面截断范围"),
            "material": ("结构参数", "材料色散", "焦面与曲率失配", "该表面后的材料折射率随波长变化"),
            "material_after": ("结构参数", "材料色散", "焦面与曲率失配", "该表面后的材料折射率随波长变化"),
            "glass": ("结构参数", "材料色散", "焦面与曲率失配", "该表面后的材料折射率随波长变化"),
        }
        category, item, physical_category, description = labels.get(
            property_name,
            ("结构参数", "表面参数", "焦面与曲率失配", "该表面参数会改变光线传播或瞳面场"),
        )
        return FormulaLinkageMetadata(
            feature=feature,
            physical_category=physical_category,
            formula_category=category,
            formula_item=item,
            mapping_level="间接",
            mapping_note=f"第{surface_number}表面的参数通过专属公式影响后续焦面场",
            formula_latex=surface_steps[0][1],
            efficiency_formula_latex="",
            source_parameters=(feature,),
            description=description,
            formula_steps=surface_steps,
        )

    axis_match = re.search(r"(?:offset|tilt|angle)_([xy])", low)
    if axis_match and any(token in low for token in ("offset", "tilt", "angle", "pitch", "yaw")):
        axis = axis_match.group(1)
        if "offset" in low:
            steps = (
                ("单轴归一化偏移", rf"u_{{{axis}}}=\frac{{\Delta {axis}}}{{w_{{f,{axis}}}}}"),
                ("单轴重叠因子", rf"\frac{{\eta_{{{axis}}}}}{{\eta_{{{axis},0}}}}=\exp(-u_{{{axis}}}^2)"),
            )
            category, item, physical = "对准误差", "横向偏移", "中心位置失配"
            note = f"{axis.upper()} 方向偏移按该轴光纤模场半径归一化"
        else:
            steps = (
                ("单轴归一化倾角", rf"u_{{\theta,{axis}}}=\frac{{\pi w_{{f,{axis}}}\theta_{axis}}}{{\lambda}}"),
                ("单轴重叠因子", rf"\frac{{\eta_{{\theta,{axis}}}}}{{\eta_{{\theta,{axis},0}}}}=\exp(-u_{{\theta,{axis}}}^2)"),
            )
            category, item, physical = "对准误差", "角度偏移", "角度与波前失配"
            note = f"{axis.upper()} 方向倾角按该轴模场半径与波长归一化"
        return FormulaLinkageMetadata(
            feature, physical, category, item, "组合", note,
            steps[0][1], steps[1][1], (), note, steps,
        )

    if any(token in low for token in ("axial_offset", "offset_z", "defocus", "axial", "接收面位置", "离焦")):
        steps = (
            ("瑞利长度", r"z_R=\frac{\pi w_f^2}{\lambda}"),
            ("离焦后的复光束参数", r"q(\Delta z)=\Delta z+i z_R"),
        )
        return FormulaLinkageMetadata(
            feature, "焦面与曲率失配", "对准误差", "轴向离焦", "组合",
            "轴向位置先改变高斯光束参数，再改变接收面复场重叠",
            steps[0][1], "", (), "轴向离焦通过接收面复场影响耦合", steps,
        )

    if "mode_curvature_radius" in low:
        definition = PHYSICS_FEATURES["curvature_mismatch"]
        steps = (
            ("曲率失配量", definition.formula_latex),
            ("相对耦合效率", definition.efficiency_formula_latex),
        )
        return FormulaLinkageMetadata(
            feature, "焦面与曲率失配", "模式失配", "曲率失配", "组合",
            "目标模式曲率与接收面入射波前曲率共同决定该参数",
            steps[0][1], steps[1][1], tuple(definition.source_parameters),
            definition.description, steps,
        )

    size_axis = re.search(r"size_ratio_([xy])", low)
    if size_axis:
        axis = size_axis.group(1)
        steps = (
            ("单轴尺寸比", rf"\rho_{axis}=\frac{{w_{{b,{axis}}}}}{{w_{{f,{axis}}}}}"),
            ("单轴尺寸失配效率", rf"\eta_{{\mathrm{{size}},{axis}}}=\left(\frac{{2\rho_{axis}}}{{1+\rho_{axis}^2}}\right)^2"),
        )
        return FormulaLinkageMetadata(
            feature, "尺寸失配", "模式失配", "尺寸失配", "组合",
            f"{axis.upper()} 方向的尺寸比单独决定该轴的高斯模重叠",
            steps[0][1], steps[1][1], (), "采用理想高斯模、波前匹配时的单轴尺寸因子", steps,
        )

    if any(token in low for token in ("waist", "beam_radius", "mode_radius", "mode_field", "mfd", "模场")):
        axis_match = re.search(r"(?:waist|radius|diameter)_([xy])", low)
        axis = axis_match.group(1) if axis_match else ""
        axis_name = f"_{axis}" if axis else ""
        if "mfd" in low or "mode_field" in low or "mode_field_diameter" in low:
            steps = (
                ("模场半径", rf"w_{{f{axis_name}}}=\frac{{D_{{f{axis_name}}}}}{{2}}"),
                ("尺寸失配效率", rf"\eta_{{\mathrm{{size}}{axis_name}}}=\left(\frac{{2\rho{axis_name}}}{{1+\rho{axis_name}^2}}\right)^2,\quad\rho{axis_name}=\frac{{w_{{b{axis_name}}}}}{{w_{{f{axis_name}}}}}"),
            )
        elif "waist" in low and "beam_radius_at_receiver" not in low:
            steps = (
                ("源束腰半径", rf"w_{{b{axis_name}}}=w_{{s{axis_name}}}"),
                ("光束与模场尺寸比", rf"\rho{axis_name}=\frac{{w_{{b{axis_name}}}}}{{w_{{f{axis_name}}}}}"),
                ("尺寸失配效率", rf"\eta_{{\mathrm{{size}}{axis_name}}}=\left(\frac{{2\rho{axis_name}}}{{1+\rho{axis_name}^2}}\right)^2"),
            )
        else:
            steps = (
                ("光束与模场尺寸比", rf"\rho{axis_name}=\frac{{w_{{b{axis_name}}}}}{{w_{{f{axis_name}}}}}"),
                ("尺寸失配效率", rf"\eta_{{\mathrm{{size}}{axis_name}}}=\left(\frac{{2\rho{axis_name}}}{{1+\rho{axis_name}^2}}\right)^2"),
            )
        return FormulaLinkageMetadata(
            feature, "尺寸失配", "模式失配", "尺寸失配", "组合",
            f"{axis.upper() + ' 方向' if axis else ''}束腰或模场半径决定尺寸匹配",
            steps[0][1], steps[-1][1], (), "采用理想高斯模、波前匹配时的尺寸重叠因子", steps,
        )

    if "wavelength" in low or "波长" in low:
        steps = (
            ("真空波数", r"k_0=\frac{2\pi}{\lambda_0}"),
            ("介质波数", r"k(\lambda_0)=n(\lambda_0)k_0"),
        )
        return FormulaLinkageMetadata(
            feature, "角度与波前失配", "传播相位", "波数", "直接",
            "波长决定波数、衍射尺度和材料色散的工作点",
            steps[0][1], "", (), "波长会进入传播相位与衍射计算", steps,
        )

    if any(token in low for token in ("offset_x", "offset_y", "decenter", "centroid", "横向偏移")):
        definition = PHYSICS_FEATURES["lateral_mismatch"]
        return FormulaLinkageMetadata(
            feature, "中心位置失配", "对准误差", "横向偏移", "组合",
            "需要与另一横向分量和光纤模场半径组合后才能计算公式值",
            definition.formula_latex, definition.efficiency_formula_latex,
            tuple(definition.source_parameters), definition.description,
        )
    if any(token in low for token in ("tilt", "angle", "pitch", "yaw", "倾角", "角度")):
        definition = PHYSICS_FEATURES["angular_mismatch"]
        return FormulaLinkageMetadata(
            feature, "角度与波前失配", "对准误差", "角度偏移", "组合",
            "需要与另一角度分量、波长和模场半径组合后才能计算公式值",
            definition.formula_latex, definition.efficiency_formula_latex,
            tuple(definition.source_parameters), definition.description,
        )
    if any(token in low for token in ("axial", "defocus", "offset_z", "离焦", "接收面位置")):
        definition = PHYSICS_FEATURES["axial_mismatch"]
        return FormulaLinkageMetadata(
            feature, "焦面与曲率失配", "对准误差", "轴向离焦", "组合",
            "需要波长与模场半径计算瑞利长度后才能形成归一化离焦量",
            definition.formula_latex, definition.efficiency_formula_latex,
            tuple(definition.source_parameters), definition.description,
        )
    if any(token in low for token in ("size_ratio", "waist", "mode_field", "mfd", "beam_radius", "束腰", "模场")):
        definition = PHYSICS_FEATURES["size_ratio"]
        return FormulaLinkageMetadata(
            feature, "尺寸失配", "模式失配", "尺寸失配", "组合",
            "需要入射光斑半径和光纤模场半径共同形成尺寸比",
            definition.formula_latex, definition.efficiency_formula_latex,
            tuple(definition.source_parameters), definition.description,
        )
    if any(token in low for token in ("curvature_mismatch", "wavefront_curvature")):
        definition = PHYSICS_FEATURES["curvature_mismatch"]
        steps = (("曲率失配量", definition.formula_latex), ("相对耦合效率", definition.efficiency_formula_latex))
        return FormulaLinkageMetadata(
            feature, "焦面与曲率失配", "模式失配", "曲率失配", "组合",
            "需要入射场和目标模式的波前曲率共同形成归一化曲率失配量",
            definition.formula_latex, definition.efficiency_formula_latex,
            tuple(definition.source_parameters), definition.description, steps,
        )
    if any(token in low for token in ("radius_mm", ".radius", "curvature", "thickness", "distance_to_next", "air_gap", "spacing", "material", "glass", "conic")):
        return FormulaLinkageMetadata(
            feature, "焦面与曲率失配", "", "", "未映射",
            "该结构参数尚未建立独立公式链路；不复用其他变量的公式",
            "", "", (), "请补充该字段的专属物理关系后再显示公式",
        )
    if any(token in low for token in ("strehl", "wavefront", "opd", "zernike", "波前")):
        return FormulaLinkageMetadata(
            feature, "角度与波前失配", "波前质量", "Strehl", "指标",
            "该参数属于波前质量指标，公式用于解释趋势而非独立损失分解",
            _STREHL_FORMULA, "", (), "波前误差增大会降低焦面主峰能量",
        )
    if any(token in low for token in ("psf", "spot", "点列")):
        return FormulaLinkageMetadata(
            feature, "光束结构与像差", "成像质量", "PSF", "指标",
            "该参数属于焦面成像质量指标",
            _PSF_FORMULA, "", (), "PSF反映孔径、像差和传播对焦面场的共同作用",
        )
    if "mtf" in low:
        return FormulaLinkageMetadata(
            feature, "光束结构与像差", "成像质量", "MTF", "指标",
            "该参数属于调制传递指标",
            _MTF_FORMULA, "", (), "MTF描述系统对不同空间频率调制的传递能力",
        )
    return FormulaLinkageMetadata(
        feature, "光束结构与像差", "", "", "未映射",
        "当前特征尚无可靠公式映射", "", "", (), "",
    )


def infer_target_unit(target_name: str, manifest: Mapping[str, Any]) -> str:
    target = str(target_name)
    units = manifest.get("target_units") or {}
    if isinstance(units, Mapping) and units.get(target):
        return str(units[target])
    transform = str(manifest.get("target_transform") or "")
    if target in {"coupling_loss_db", "insertion_loss_db"} or transform == "coupling_loss_db":
        return "dB"
    if target in {"coupling_efficiency", "system_efficiency", "transmission_efficiency"}:
        return "比例"
    return ""


def target_supports_additive_formula_comparison(target_name: str, target_unit: str) -> bool:
    return str(target_name) in {"coupling_loss_db", "coupling_loss_db_pred", "insertion_loss_db"} and str(target_unit).lower() == "db"


def enrich_local_formula_values(
    metadata: FormulaLinkageMetadata,
    *,
    feature_value: float,
    background_values: Sequence[float],
    shap_value: float,
    comparison_enabled: bool,
) -> dict[str, Any]:

    result = metadata.to_dict()
    definition = PHYSICS_FEATURES.get(metadata.feature)
    if definition is None:
        result["formula_comparison_status"] = {
            "间接": "indirect_parameter",
            "组合": "requires_derived_feature",
            "指标": "trend_only",
        }.get(metadata.mapping_level, "unavailable")
        return result

    efficiency = float(definition.relative_efficiency(float(feature_value)))
    loss = float(definition.loss_db(float(feature_value)))
    result.update(
        {
            "formula_efficiency": efficiency,
            "formula_loss": loss,
        }
    )
    if not comparison_enabled:
        result["formula_comparison_status"] = "target_domain_mismatch"
        return result

    background = np.asarray(background_values, dtype=float).reshape(-1)
    finite = background[np.isfinite(background)]
    if finite.size == 0:
        result["formula_comparison_status"] = "background_unavailable"
        return result
    background_mean = float(np.mean([definition.loss_db(float(value)) for value in finite]))
    centered = loss - background_mean
    result.update(
        {
            "formula_background_mean": background_mean,
            "formula_centered_contribution": centered,
            "shap_minus_formula": float(shap_value) - centered,
            "formula_comparison_status": "available",
        }
    )
    return result


def formula_consistency_record(
    feature_name: str,
    feature_values: Sequence[float],
    shap_values: Sequence[float],
) -> dict[str, Any] | None:
    definition = PHYSICS_FEATURES.get(str(feature_name))
    if definition is None:
        return None
    feature_array = np.asarray(feature_values, dtype=float).reshape(-1)
    shap_array = np.asarray(shap_values, dtype=float).reshape(-1)
    finite = np.isfinite(feature_array) & np.isfinite(shap_array)
    feature_array = feature_array[finite]
    shap_array = shap_array[finite]
    if feature_array.size == 0:
        return None
    formula = np.asarray([definition.loss_db(float(value)) for value in feature_array], dtype=float)
    formula_centered = formula - float(np.mean(formula))

    pearson = spearman = slope = intercept = nrmse = sign_agreement = None
    if feature_array.size >= 3 and np.std(formula_centered) > 1.0e-12 and np.std(shap_array) > 1.0e-12:
        pearson = float(pearsonr(formula_centered, shap_array).statistic)
        spearman = float(spearmanr(formula_centered, shap_array).statistic)
        slope, intercept = [float(value) for value in np.polyfit(formula_centered, shap_array, deg=1)]
        fitted = slope * formula_centered + intercept
        rmse = float(np.sqrt(np.mean((shap_array - fitted) ** 2)))
        nrmse = rmse / max(float(np.std(shap_array)), 1.0e-12)
        active = (np.abs(formula_centered) > 1.0e-9) | (np.abs(shap_array) > 1.0e-9)
        if np.any(active):
            sign_agreement = float(np.mean(np.sign(formula_centered[active]) == np.sign(shap_array[active])))

    score = abs(pearson) if pearson is not None else 0.0
    level = "high" if score >= 0.85 else ("medium" if score >= 0.60 else "low")
    return {
        "feature": str(feature_name),
        "sample_count": int(feature_array.size),
        "pearson_correlation": pearson,
        "spearman_correlation": spearman,
        "calibrated_slope": slope,
        "calibrated_intercept": intercept,
        "normalized_rmse": nrmse,
        "sign_agreement": sign_agreement,
        "level": level,
    }


__all__ = [
    "FormulaLinkageMetadata",
    "enrich_local_formula_values",
    "formula_consistency_record",
    "formula_linkage_for_feature",
    "infer_target_unit",
    "target_supports_additive_formula_comparison",
]


from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np
from scipy.stats import pearsonr, spearmanr

from machine_learning.explainability.physics_features import PHYSICS_FEATURES


_OVERLAP_FORMULA = (
    r"\eta_{\mathrm{overlap}}="
    r"\frac{|\iint E_sE_f^*\,dA|^2}"
    r"{\iint|E_s|^2dA\;\iint|E_f|^2dA}"
)
_TOTAL_FORMULA = (
    r"\eta_{\mathrm{total}}="
    r"\eta_{\mathrm{transmission}}\eta_{\mathrm{overlap}}"
    r"\eta_{\mathrm{facet}}\eta_{\mathrm{propagation}}"
)
_STREHL_FORMULA = r"S\approx\exp[-(2\pi\sigma_W/\lambda)^2]"
_PSF_FORMULA = r"\mathrm{PSF}=|\mathcal{F}\{P\exp(i2\pi W/\lambda)\}|^2"
_MTF_FORMULA = r"\mathrm{MTF}=|\mathcal{F}\{\mathrm{PSF}\}|"


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
        }


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
        return FormulaLinkageMetadata(
            feature, "焦面与曲率失配", "模式失配", "曲率失配", "组合",
            "需要入射场和目标模式的波前曲率共同形成归一化曲率失配量",
            definition.formula_latex, definition.efficiency_formula_latex,
            tuple(definition.source_parameters), definition.description,
        )
    if any(token in low for token in ("surfaces[", "radius_mm", ".radius", "curvature", "thickness", "air_gap", "spacing", "material", "glass", "conic")):
        return FormulaLinkageMetadata(
            feature, "焦面与曲率失配", "总耦合效率", "复场重叠", "间接",
            "镜片结构参数先改变焦面振幅与相位，再通过完整复场重叠影响耦合",
            _OVERLAP_FORMULA, _TOTAL_FORMULA,
            (), "结构参数没有可独立分离的闭式耦合损失项",
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

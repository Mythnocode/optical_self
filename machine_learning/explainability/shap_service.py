
from __future__ import annotations

from dataclasses import replace
from typing import Callable, Mapping, Sequence
import warnings

import numpy as np
import pandas as pd
from scipy.stats import pearsonr, spearmanr

from machine_learning.explainability.contracts import (
    FeatureContribution,
    FormulaConsistency,
    InteractionContribution,
    ShapFormulaLinkageReport,
)
from machine_learning.explainability.physics_features import (
    PHYSICS_FEATURES,
    PHYSICS_FEATURE_ORDER,
    compute_physics_features,
)


class ShapDependencyError(RuntimeError):
    pass


def _load_shap():
    try:
        import shap
    except ImportError as exc:  
        raise ShapDependencyError(
            "SHAP 未安装。请执行: pip install -r requirements/requirements.txt"
        ) from exc
    return shap


def _as_dataframe(
    data: pd.DataFrame | np.ndarray | Sequence[Sequence[float]],
    feature_names: Sequence[str],
) -> pd.DataFrame:
    if isinstance(data, pd.DataFrame):
        missing = [name for name in feature_names if name not in data.columns]
        if missing:
            raise ValueError(f"缺少特征列: {missing}")
        return data.loc[:, list(feature_names)].astype(float).reset_index(drop=True)
    array = np.asarray(data, dtype=float)
    if array.ndim == 1:
        array = array.reshape(1, -1)
    if array.ndim != 2 or array.shape[1] != len(feature_names):
        raise ValueError(
            f"特征矩阵应为 (n, {len(feature_names)})，实际为 {array.shape}"
        )
    return pd.DataFrame(array, columns=list(feature_names))


def _extract_explanation_values(explanation, target_index: int) -> tuple[np.ndarray, np.ndarray]:
    values = np.asarray(explanation.values, dtype=float)
    base = np.asarray(explanation.base_values, dtype=float)

    if values.ndim == 2:
        selected_values = values
    elif values.ndim == 3:
        if target_index >= values.shape[2]:
            raise ValueError(f"target_index={target_index} 超出模型输出范围")
        selected_values = values[:, :, target_index]
    else:
        raise ValueError(f"不支持的 SHAP values 形状: {values.shape}")

    if base.ndim == 0:
        selected_base = np.full(selected_values.shape[0], float(base))
    elif base.ndim == 1:
        if base.shape[0] == selected_values.shape[0]:
            selected_base = base
        elif base.shape[0] > target_index:
            selected_base = np.full(selected_values.shape[0], float(base[target_index]))
        else:
            raise ValueError(f"不支持的 base_values 形状: {base.shape}")
    elif base.ndim == 2:
        selected_base = base[:, target_index]
    else:
        raise ValueError(f"不支持的 base_values 形状: {base.shape}")

    return selected_values, np.asarray(selected_base, dtype=float)


class ShapFormulaLinkageAnalyzer:


    def __init__(
        self,
        model,
        background_features: pd.DataFrame | np.ndarray,
        feature_names: Sequence[str] = PHYSICS_FEATURE_ORDER,
        *,
        feature_transform: Callable[[np.ndarray], np.ndarray] | None = None,
        target_name: str = "coupling_loss_db",
        target_unit: str = "dB",
        target_index: int = 0,
        output_scale: float = 1.0,
        output_offset: float = 0.0,
        explainer=None,
    ) -> None:
        self.model = model
        self.feature_names = tuple(feature_names)
        if not self.feature_names:
            raise ValueError("feature_names 不能为空")
        self.background_features = _as_dataframe(background_features, self.feature_names)
        self.feature_transform = feature_transform or (lambda x: np.asarray(x, dtype=float))
        self.background_model_input = np.asarray(
            self.feature_transform(self.background_features.to_numpy(dtype=float)),
            dtype=float,
        )
        if self.background_model_input.shape != self.background_features.shape:
            raise ValueError(
                "feature_transform 必须保持二维特征矩阵形状，"
                f"输入 {self.background_features.shape}，输出 {self.background_model_input.shape}"
            )
        self.target_name = target_name
        self.target_unit = target_unit
        self.target_index = int(target_index)
        self.output_scale = float(output_scale)
        self.output_offset = float(output_offset)
        self.formula_comparison_enabled = target_name in {
            "coupling_loss_db",
            "coupling_loss_db_pred",
        } and target_unit.lower() == "db"

        shap = _load_shap()
        if explainer is not None:
            self.explainer = explainer
        else:
            
            
            
            try:
                self.explainer = shap.TreeExplainer(
                    model,
                    feature_names=list(self.feature_names),
                    feature_perturbation="tree_path_dependent",
                )
            except Exception:
                self.explainer = shap.Explainer(
                    model,
                    self.background_model_input,
                    feature_names=list(self.feature_names),
                )
        self._background_formula_mean = self._compute_background_formula_means()

    @classmethod
    def from_registered_model(
        cls,
        registry,
        model_id: str,
        background_features: pd.DataFrame | np.ndarray,
        *,
        target_index: int = 0,
    ) -> "ShapFormulaLinkageAnalyzer":

        model, preprocessing, manifest = registry.load(model_id)
        feature_names = manifest["feature_paths"]
        target_names = manifest.get("target_names", ["target"])
        if target_index >= len(target_names):
            raise ValueError("target_index 超出 manifest.target_names")

        output_scale = 1.0
        output_offset = 0.0
        y_scaler = getattr(preprocessing, "y_scaler", None)
        if y_scaler is not None and hasattr(y_scaler, "scale_"):
            output_scale = float(np.asarray(y_scaler.scale_).reshape(-1)[target_index])
            output_offset = float(np.asarray(y_scaler.mean_).reshape(-1)[target_index])

        target_name = str(target_names[target_index])
        target_unit = str(manifest.get("target_units", {}).get(target_name, "target_unit"))
        target_transform = manifest.get("target_transform")
        if target_transform == "coupling_loss_db":
            target_name = "coupling_loss_db"
            target_unit = "dB"

        return cls(
            model,
            background_features,
            feature_names,
            feature_transform=preprocessing.transform_features,
            target_name=target_name,
            target_unit=target_unit,
            target_index=target_index,
            output_scale=output_scale,
            output_offset=output_offset,
        )

    def _compute_background_formula_means(self) -> dict[str, float]:
        output: dict[str, float] = {}
        for feature in self.feature_names:
            definition = PHYSICS_FEATURES.get(feature)
            if definition is None:
                continue
            losses = [definition.loss_db(v) for v in self.background_features[feature]]
            output[feature] = float(np.mean(losses))
        return output

    def _model_input(self, features: pd.DataFrame) -> np.ndarray:
        transformed = np.asarray(
            self.feature_transform(features.to_numpy(dtype=float)), dtype=float
        )
        if transformed.shape != features.shape:
            raise ValueError("feature_transform 改变了特征矩阵形状")
        return transformed

    def _explain_matrix(self, features: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message="X does not have valid feature names.*",
                category=UserWarning,
            )
            explanation = self.explainer(self._model_input(features))
        values, base = _extract_explanation_values(explanation, self.target_index)
        values = values * self.output_scale
        base = base * self.output_scale + self.output_offset
        return values, base

    def _model_predict(self, features: pd.DataFrame) -> np.ndarray:
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message="X does not have valid feature names.*",
                category=UserWarning,
            )
            prediction = np.asarray(
                self.model.predict(self._model_input(features)), dtype=float
            )
        if prediction.ndim == 1:
            selected = prediction
        elif prediction.ndim == 2:
            selected = prediction[:, self.target_index]
        else:
            raise ValueError(f"不支持的模型预测形状: {prediction.shape}")
        return selected * self.output_scale + self.output_offset

    def explain_raw(
        self,
        raw_parameters: Mapping[str, float],
        *,
        top_k: int | None = None,
    ) -> ShapFormulaLinkageReport:
        feature_values = compute_physics_features(raw_parameters, self.feature_names)
        return self.explain_one(feature_values, top_k=top_k)

    def explain_one(
        self,
        feature_values: Mapping[str, float],
        *,
        top_k: int | None = None,
    ) -> ShapFormulaLinkageReport:
        missing = [name for name in self.feature_names if name not in feature_values]
        if missing:
            raise ValueError(f"缺少模型特征: {missing}")
        row = pd.DataFrame(
            [[float(feature_values[name]) for name in self.feature_names]],
            columns=list(self.feature_names),
        )
        shap_values, base_values = self._explain_matrix(row)
        model_prediction = float(self._model_predict(row)[0])
        base_value = float(base_values[0])
        prediction = float(base_value + np.sum(shap_values[0]))

        ranked = sorted(
            zip(self.feature_names, row.iloc[0].to_numpy(), shap_values[0], strict=True),
            key=lambda item: abs(float(item[2])),
            reverse=True,
        )
        if top_k is not None:
            ranked = ranked[: max(0, int(top_k))]

        contributions: list[FeatureContribution] = []
        for rank, (name, feature_value, shap_value) in enumerate(ranked, start=1):
            definition = PHYSICS_FEATURES.get(name)
            if definition is None:
                contributions.append(
                    FeatureContribution(
                        feature=name,
                        display_name=name,
                        symbol_latex=name,
                        feature_value=float(feature_value),
                        shap_value=float(shap_value),
                        abs_shap_value=abs(float(shap_value)),
                        direction="increase_target" if shap_value >= 0 else "decrease_target",
                        rank=rank,
                    )
                )
                continue

            formula_efficiency = definition.relative_efficiency(float(feature_value))
            formula_loss = definition.loss_db(float(feature_value))
            centered = None
            if self.formula_comparison_enabled:
                centered = formula_loss - self._background_formula_mean[name]
            contributions.append(
                FeatureContribution(
                    feature=name,
                    display_name=definition.display_name,
                    symbol_latex=definition.symbol_latex,
                    feature_value=float(feature_value),
                    shap_value=float(shap_value),
                    abs_shap_value=abs(float(shap_value)),
                    direction="increase_loss" if shap_value >= 0 else "decrease_loss",
                    rank=rank,
                    formula_latex=definition.formula_latex,
                    efficiency_formula_latex=definition.efficiency_formula_latex,
                    formula_efficiency=formula_efficiency,
                    formula_loss=formula_loss,
                    formula_centered_contribution=centered,
                    source_parameters=definition.source_parameters,
                    description=definition.description,
                )
            )

        warnings: list[str] = []
        if not self.formula_comparison_enabled:
            warnings.append(
                "当前模型目标不是 dB 耦合损失；解析公式仍展示，但不与 SHAP 值直接作加性比较。"
            )

        return ShapFormulaLinkageReport(
            target_name=self.target_name,
            target_unit=self.target_unit,
            base_value=base_value,
            prediction=prediction,
            model_prediction=model_prediction,
            additivity_error=prediction - model_prediction,
            feature_contributions=contributions,
            feature_order=list(self.feature_names),
            warnings=warnings,
        )


    def shap_distribution(
        self,
        features: pd.DataFrame | np.ndarray,
        *,
        max_samples: int | None = 1000,
    ) -> pd.DataFrame:

        frame = _as_dataframe(features, self.feature_names)
        if max_samples is not None and len(frame) > max_samples:
            frame = frame.sample(max_samples, random_state=0).reset_index(drop=True)
        values, _ = self._explain_matrix(frame)
        rows: list[dict[str, object]] = []
        for sample_index in range(len(frame)):
            for feature_index, name in enumerate(self.feature_names):
                definition = PHYSICS_FEATURES.get(name)
                rows.append(
                    {
                        "sample_index": sample_index,
                        "feature": name,
                        "display_name": definition.display_name if definition else name,
                        "feature_value": float(frame.iloc[sample_index, feature_index]),
                        "shap_value": float(values[sample_index, feature_index]),
                        "abs_shap_value": abs(float(values[sample_index, feature_index])),
                    }
                )
        return pd.DataFrame(rows)

    def dependence_data(
        self,
        feature: str,
        features: pd.DataFrame | np.ndarray,
        *,
        max_samples: int | None = 1000,
    ) -> pd.DataFrame:

        if feature not in self.feature_names:
            raise ValueError(f"未知特征: {feature}")
        frame = _as_dataframe(features, self.feature_names)
        if max_samples is not None and len(frame) > max_samples:
            frame = frame.sample(max_samples, random_state=0).reset_index(drop=True)
        values, _ = self._explain_matrix(frame)
        index = self.feature_names.index(feature)
        definition = PHYSICS_FEATURES.get(feature)
        result = pd.DataFrame(
            {
                "feature_value": frame[feature].to_numpy(dtype=float),
                "shap_value": values[:, index],
            }
        )
        if definition is not None:
            formula_loss = np.array(
                [definition.loss_db(v) for v in result["feature_value"]], dtype=float
            )
            result["formula_loss"] = formula_loss
            result["formula_centered_contribution"] = (
                formula_loss - self._background_formula_mean[feature]
            )
            result["shap_minus_formula"] = (
                result["shap_value"] - result["formula_centered_contribution"]
            )
        return result.sort_values("feature_value").reset_index(drop=True)

    def formula_residual_data(
        self,
        features: pd.DataFrame | np.ndarray,
        *,
        reference_values: Sequence[float] | np.ndarray | None = None,
    ) -> tuple[pd.DataFrame, dict[str, float]]:

        frame = _as_dataframe(features, self.feature_names)
        prediction = self._model_predict(frame)
        analytic = np.zeros(len(frame), dtype=float)
        for name in self.feature_names:
            definition = PHYSICS_FEATURES.get(name)
            if definition is None:
                continue
            analytic += np.array(
                [definition.loss_db(v) for v in frame[name].to_numpy(dtype=float)],
                dtype=float,
            )
        residual = prediction - analytic
        data = frame.copy()
        data["model_prediction"] = prediction
        data["analytic_single_factor_sum"] = analytic
        data["formula_interaction_residual"] = residual
        if reference_values is not None:
            reference = np.asarray(reference_values, dtype=float).reshape(-1)
            if len(reference) != len(frame):
                raise ValueError("reference_values 长度必须与特征样本数一致")
            data["reference_value"] = reference
            data["model_reference_error"] = prediction - reference
            data["reference_formula_residual"] = reference - analytic

        summary = {
            "sample_count": float(len(frame)),
            "mean_residual": float(np.mean(residual)),
            "mean_abs_residual": float(np.mean(np.abs(residual))),
            "rms_residual": float(np.sqrt(np.mean(residual**2))),
            "p95_abs_residual": float(np.quantile(np.abs(residual), 0.95)),
        }
        if reference_values is not None:
            error = data["model_reference_error"].to_numpy(dtype=float)
            summary.update(
                {
                    "reference_mae": float(np.mean(np.abs(error))),
                    "reference_rmse": float(np.sqrt(np.mean(error**2))),
                    "reference_bias": float(np.mean(error)),
                }
            )
        return data, summary

    @staticmethod
    def physics_consistency_risks(
        consistency: Sequence[FormulaConsistency],
        residual_summary: Mapping[str, float] | None = None,
    ) -> list[dict[str, object]]:
        risks: list[dict[str, object]] = []
        for item in consistency:
            if item.level == "low":
                severity = "high"
            elif item.level == "medium":
                severity = "medium"
            else:
                continue
            risks.append(
                {
                    "type": "formula_consistency",
                    "feature": item.feature,
                    "severity": severity,
                    "message": "模型 SHAP 趋势与单因素解析公式一致性不足，需检查数据覆盖、交互效应或非物理相关。",
                }
            )
        if residual_summary is not None:
            mean_abs = float(residual_summary.get("mean_abs_residual", 0.0))
            p95 = float(residual_summary.get("p95_abs_residual", 0.0))
            if p95 > 1.0:
                risks.append(
                    {
                        "type": "formula_residual",
                        "severity": "high" if p95 > 2.0 else "medium",
                        "p95_abs_residual": p95,
                        "mean_abs_residual": mean_abs,
                        "message": "单因素解析公式无法解释较大的模型损失，可能存在交互、像差、孔径截断或数据偏差。",
                    }
                )
        return risks

    def global_importance(
        self,
        features: pd.DataFrame | np.ndarray,
        *,
        max_samples: int | None = None,
    ) -> list[dict[str, object]]:
        frame = _as_dataframe(features, self.feature_names)
        if max_samples is not None and len(frame) > max_samples:
            frame = frame.sample(max_samples, random_state=0).reset_index(drop=True)
        values, _ = self._explain_matrix(frame)
        output: list[dict[str, object]] = []
        for index, name in enumerate(self.feature_names):
            definition = PHYSICS_FEATURES.get(name)
            output.append(
                {
                    "feature": name,
                    "display_name": definition.display_name if definition else name,
                    "symbol_latex": definition.symbol_latex if definition else name,
                    "mean_abs_shap": float(np.mean(np.abs(values[:, index]))),
                    "mean_signed_shap": float(np.mean(values[:, index])),
                    "std_shap": float(np.std(values[:, index])),
                    "sample_count": int(len(frame)),
                }
            )
        output.sort(key=lambda item: float(item["mean_abs_shap"]), reverse=True)
        for rank, item in enumerate(output, start=1):
            item["rank"] = rank
        return output

    def formula_consistency(
        self,
        features: pd.DataFrame | np.ndarray,
        *,
        max_samples: int | None = None,
    ) -> list[FormulaConsistency]:
        frame = _as_dataframe(features, self.feature_names)
        if max_samples is not None and len(frame) > max_samples:
            frame = frame.sample(max_samples, random_state=0).reset_index(drop=True)
        shap_values, _ = self._explain_matrix(frame)
        results: list[FormulaConsistency] = []

        for index, name in enumerate(self.feature_names):
            definition = PHYSICS_FEATURES.get(name)
            if definition is None or not self.formula_comparison_enabled:
                continue
            formula = np.array(
                [definition.loss_db(v) for v in frame[name].to_numpy(dtype=float)],
                dtype=float,
            )
            formula_centered = formula - self._background_formula_mean[name]
            observed = shap_values[:, index]
            finite = np.isfinite(formula_centered) & np.isfinite(observed)
            x = formula_centered[finite]
            y = observed[finite]

            pearson = None
            spearman = None
            slope = None
            intercept = None
            nrmse = None
            sign_agreement = None
            if len(x) >= 3 and np.std(x) > 1.0e-12 and np.std(y) > 1.0e-12:
                pearson = float(pearsonr(x, y).statistic)
                spearman = float(spearmanr(x, y).statistic)
                slope, intercept = [float(v) for v in np.polyfit(x, y, deg=1)]
                fitted = slope * x + intercept
                rmse = float(np.sqrt(np.mean((y - fitted) ** 2)))
                nrmse = rmse / max(float(np.std(y)), 1.0e-12)
                active = (np.abs(x) > 1.0e-9) | (np.abs(y) > 1.0e-9)
                if np.any(active):
                    sign_agreement = float(np.mean(np.sign(x[active]) == np.sign(y[active])))

            score = abs(pearson) if pearson is not None else 0.0
            if score >= 0.85:
                level = "high"
            elif score >= 0.60:
                level = "medium"
            else:
                level = "low"
            results.append(
                FormulaConsistency(
                    feature=name,
                    sample_count=int(len(x)),
                    pearson_correlation=pearson,
                    spearman_correlation=spearman,
                    calibrated_slope=slope,
                    calibrated_intercept=intercept,
                    normalized_rmse=nrmse,
                    sign_agreement=sign_agreement,
                    level=level,
                )
            )
        return results

    def interaction_importance(
        self,
        features: pd.DataFrame | np.ndarray,
        *,
        max_samples: int = 128,
        top_k: int | None = None,
    ) -> tuple[list[InteractionContribution], np.ndarray | None]:
        frame = _as_dataframe(features, self.feature_names)
        if len(frame) > max_samples:
            frame = frame.sample(max_samples, random_state=0).reset_index(drop=True)
        shap = _load_shap()
        try:
            tree_explainer = shap.TreeExplainer(
                self.model,
                feature_names=list(self.feature_names),
                feature_perturbation="tree_path_dependent",
            )
            with warnings.catch_warnings():
                warnings.filterwarnings(
                    "ignore",
                    message="X does not have valid feature names.*",
                    category=UserWarning,
                )
                raw = tree_explainer.shap_interaction_values(self._model_input(frame))
        except Exception:
            return [], None

        if isinstance(raw, list):
            raw = raw[self.target_index]
        interactions = np.asarray(raw, dtype=float)
        if interactions.ndim == 4:
            interactions = interactions[:, :, :, self.target_index]
        if interactions.ndim != 3:
            return [], None
        interactions = interactions * self.output_scale
        matrix = np.mean(np.abs(interactions), axis=0)

        pairs: list[InteractionContribution] = []
        for i, name_a in enumerate(self.feature_names):
            for j in range(i + 1, len(self.feature_names)):
                name_b = self.feature_names[j]
                values = interactions[:, i, j]
                pairs.append(
                    InteractionContribution(
                        feature_a=name_a,
                        feature_b=name_b,
                        mean_abs_interaction=float(np.mean(np.abs(values))),
                        mean_signed_interaction=float(np.mean(values)),
                        rank=0,
                    )
                )
        pairs.sort(key=lambda item: item.mean_abs_interaction, reverse=True)
        if top_k is not None:
            pairs = pairs[: max(0, int(top_k))]
        pairs = [replace(item, rank=rank) for rank, item in enumerate(pairs, start=1)]
        return pairs, matrix

    def analyze(
        self,
        local_features: Mapping[str, float],
        dataset_features: pd.DataFrame | np.ndarray,
        *,
        local_top_k: int | None = None,
        global_max_samples: int | None = 512,
        interaction_max_samples: int = 128,
        interaction_top_k: int | None = 10,
    ) -> ShapFormulaLinkageReport:
        report = self.explain_one(local_features, top_k=local_top_k)
        report.global_importance = self.global_importance(
            dataset_features, max_samples=global_max_samples
        )
        report.formula_consistency = self.formula_consistency(
            dataset_features, max_samples=global_max_samples
        )
        interactions, matrix = self.interaction_importance(
            dataset_features,
            max_samples=interaction_max_samples,
            top_k=interaction_top_k,
        )
        report.interactions = interactions
        report.interaction_matrix = None if matrix is None else matrix.tolist()
        if matrix is None:
            report.warnings.append("当前模型或 SHAP 解释器不支持交互值，已跳过交互分析。")
        return report

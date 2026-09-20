"""链式法则把 17 特征 SHAP 回传到 8 个设计变量（总归因）。

方法
----
模型 y = m(X, P) 把 8 个设计变量 X 和 9 个物理失配特征 P 都当作输入。
但 P 实际是 X 的确定性函数 P = h(X)（给定固定光源/接收端时），因此设计
变量 X_i 的总影响为：

    total(X_i) = SHAP(X_i)                      # 直接项
               + Σ_j SHAP(P_j) * w[j][i]        # 通过物理特征的间接项

权重 w[j][i] 按"弹性"分配：物理特征 P_j 的 SHAP 按各设计变量对它的相对
敏感度 |∂P_j/∂X_i * X_i| 等比回传给 X_i。雅可比用中心差分数值求解。

该分配满足加性守恒：Σ_i total(X_i) = Σ_i SHAP(X_i) + Σ_j SHAP(P_j)
                                    = 预测值 - 基准值。

本模块是论文图（重要性排名/蜂群图/依赖网格/依赖趋势/物理一致性/瀑布图）
的数据来源，被后端 explainability 服务调用。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np
import pandas as pd

from machine_learning.explainability.physics_residual import (
    FORMULA_FEATURES,
    formula_baseline_db,
)
from machine_learning.explainability.shap_service import ShapFormulaLinkageAnalyzer
from shared_contracts.project import ProjectSnapshot


def _enrich_candidate_features(base_project: ProjectSnapshot, raw: dict):
    """惰性导入，避免与 ``coupling_physics`` 之间的循环导入。"""
    from machine_learning.features.coupling_physics import enrich_candidate_features

    return enrich_candidate_features(base_project, raw)

# 纵坐标紧凑英文记号（论文图统一使用）
DESIGN_SHORT = {
    "surfaces[0].radius_mm": "L1-r",
    "surfaces[0].distance_to_next_mm": "L1-d",
    "surfaces[2].radius_mm": "L2-r",
    "surfaces[2].distance_to_next_mm": "L2-d",
    "surfaces[4].radius_mm": "L3-r",
    "surfaces[4].distance_to_next_mm": "L3-d",
    "surfaces[6].radius_mm": "L4-r",
    "surfaces[6].distance_to_next_mm": "L4-d",
}
# 中文全称（用于悬停/图例说明）
DESIGN_LABEL = {
    "surfaces[0].radius_mm": "第一片透镜前表面曲率半径",
    "surfaces[0].distance_to_next_mm": "第一片透镜厚度",
    "surfaces[2].radius_mm": "第二片透镜前表面曲率半径",
    "surfaces[2].distance_to_next_mm": "第二片透镜厚度",
    "surfaces[4].radius_mm": "第三片透镜前表面曲率半径",
    "surfaces[4].distance_to_next_mm": "第三片透镜厚度",
    "surfaces[6].radius_mm": "第四片透镜前表面曲率半径",
    "surfaces[6].distance_to_next_mm": "第四片透镜厚度",
}


@dataclass
class DesignVariableAttribution:
    """链式回传后 8 个设计变量的总归因（逐样本）。"""

    total: np.ndarray          # (n, 8) 总归因
    Xmat: np.ndarray           # (n, 8) 设计变量原始值
    base: np.ndarray           # (n,) 基准值 E[f(X)]
    targets: np.ndarray        # (n,) 实际目标值
    sample_ids: list[str]      # (n,)
    design_paths: list[str]    # (8,)
    physics_paths: list[str]   # (9,)
    base_project: ProjectSnapshot
    target_name: str = ""

    @property
    def n(self) -> int:
        return int(self.total.shape[0])


def compute_design_variable_attribution(
    registry,
    store,
    model_id: str,
    *,
    sample_ids: Sequence[str] | None = None,
    max_samples: int | None = None,
    eps_rel: float = 1e-4,
) -> DesignVariableAttribution:
    """从已注册模型 + 数据集计算 8 设计变量的链式总归因。

    复用平台自身的 ``ShapFormulaLinkageAnalyzer`` 处理特征缩放与目标
    反变换，保证 SHAP 值在原始输出单位；随后用数值雅可比把物理特征
    SHAP 回传到设计变量。
    """
    model, _preprocessing, manifest = registry.load(model_id)
    feature_paths = [str(p) for p in manifest["feature_paths"]]
    design_paths = [str(p) for p in manifest["design_variable_paths"]]
    physics_paths = [str(p) for p in manifest["physics_feature_paths"]]
    target_name = str(manifest["target_names"][0])
    dataset_id = str(manifest["dataset_id"])
    base_project = ProjectSnapshot.model_validate(manifest["source_project"])

    dmanifest = store.load_manifest(dataset_id)
    train_ids = [str(x) for x in dmanifest.train_ids]
    val_ids = [str(x) for x in dmanifest.validation_ids]
    test_ids = [str(x) for x in dmanifest.test_ids]
    all_ids = train_ids + val_ids + test_ids

    samples = [r for r in store.iter_samples(dataset_id) if r.get("valid")]
    by_id = {r["sample_id"]: r for r in samples}

    if sample_ids:
        requested = [str(sid) for sid in sample_ids]
        all_ids = [sid for sid in requested if sid in by_id]
    if max_samples is not None and len(all_ids) > int(max_samples):
        all_ids = all_ids[: int(max_samples)]

    background = pd.DataFrame(
        [[by_id[sid]["feature_values"][p] for p in feature_paths] for sid in train_ids],
        columns=feature_paths,
    )
    analyzer = ShapFormulaLinkageAnalyzer.from_registered_model(
        registry, model_id, background
    )
    explain_frame = pd.DataFrame(
        [[by_id[sid]["feature_values"][p] for p in feature_paths] for sid in all_ids],
        columns=feature_paths,
    )
    with __import__("warnings").catch_warnings():
        __import__("warnings").simplefilter("ignore")
        shap, base = analyzer._explain_matrix(explain_frame)  # (n, 17)

    di = {p: feature_paths.index(p) for p in design_paths}
    pi = {p: feature_paths.index(p) for p in physics_paths}
    n = len(all_ids)
    m = len(design_paths)

    def physics_at(design_vals):
        raw = dict(zip(design_paths, [float(v) for v in design_vals]))
        return _enrich_candidate_features(base_project, raw)

    direct = np.zeros((n, m))
    through = np.zeros((n, m))
    Xmat = np.zeros((n, m))
    for s in range(n):
        x = np.array([by_id[all_ids[s]]["feature_values"][p] for p in design_paths], float)
        phi = shap[s]
        direct[s] = phi[[di[p] for p in design_paths]]
        Xmat[s] = x

        # 雅可比 J[j][i] = dP_j / dX_i
        J = np.zeros((len(physics_paths), m))
        for i in range(m):
            eps = max(1e-5, eps_rel * abs(x[i]))
            up = x.copy()
            up[i] = x[i] + eps
            dn = x.copy()
            dn[i] = x[i] - eps
            try:
                pu = physics_at(up)
                pd_ = physics_at(dn)
                for j, p in enumerate(physics_paths):
                    J[j, i] = (pu[p] - pd_[p]) / (2.0 * eps)
            except Exception:
                try:
                    pu = physics_at(up)
                    p0 = physics_at(x)
                    for j, p in enumerate(physics_paths):
                        J[j, i] = (pu[p] - p0[p]) / eps
                except Exception:
                    pass

        for j, p in enumerate(physics_paths):
            pj_shap = phi[pi[p]]
            elast = np.abs(J[j] * x)
            denom = elast.sum()
            if denom > 1e-12:
                through[s] += pj_shap * (elast / denom)

    total = direct + through
    targets = np.array(
        [by_id[sid]["target_values"][target_name] for sid in all_ids], dtype=float
    )
    return DesignVariableAttribution(
        total=total,
        Xmat=Xmat,
        base=np.asarray(base, dtype=float),
        targets=targets,
        sample_ids=list(all_ids),
        design_paths=design_paths,
        physics_paths=physics_paths,
        base_project=base_project,
        target_name=target_name,
    )


def chain_rule_attribution_from_shap(
    manifest: dict,
    shap_matrix: np.ndarray,
    x_raw: np.ndarray,
    *,
    eps_rel: float = 1e-4,
) -> tuple[np.ndarray, list[str]] | None:
    """把已算好的全特征 SHAP 经链式法则回传到 8 个设计变量。

    供后端 ``explain_shap`` 在「当前系统」单样本场景复用：后端已经算出了
    17 特征的逐样本 SHAP（``shap_matrix``）与原始特征值（``x_raw``），这里
    只需按数值雅可比把 9 个物理失配特征的 SHAP 按弹性权重回传到设计变量，
    得到与 ``compute_design_variable_attribution`` 一致的总归因：

        total(X_i) = SHAP(X_i) + Σ_j SHAP(P_j) * |∂P_j/∂X_i·X_i| / Σ_i'|∂P_j/∂X_i'·X_i'|

    仅当模型 manifest 定义了 design_variable_paths / physics_feature_paths /
    source_project 时才生效，否则返回 None（调用方退回「其他模型特征（合并）」
    的旧行为）。
    """
    design_paths = [str(p) for p in (manifest.get("design_variable_paths") or [])]
    physics_paths = [str(p) for p in (manifest.get("physics_feature_paths") or [])]
    feature_paths = [str(p) for p in (manifest.get("feature_paths") or [])]
    if not design_paths or not physics_paths or not feature_paths:
        return None
    if "source_project" not in manifest:
        return None
    if shap_matrix.ndim != 2 or shap_matrix.shape[1] != len(feature_paths):
        return None
    if x_raw.ndim != 2 or x_raw.shape[1] != len(feature_paths):
        return None

    base_project = ProjectSnapshot.model_validate(manifest["source_project"])
    di = {p: feature_paths.index(p) for p in design_paths}
    pi = {p: feature_paths.index(p) for p in physics_paths}
    n = shap_matrix.shape[0]
    m = len(design_paths)

    def physics_at(design_vals):
        raw = dict(zip(design_paths, [float(v) for v in design_vals]))
        return _enrich_candidate_features(base_project, raw)

    direct = shap_matrix[:, [di[p] for p in design_paths]].copy()
    through = np.zeros((n, m))
    Xmat = x_raw[:, [di[p] for p in design_paths]].astype(float)

    for s in range(n):
        x = Xmat[s]
        J = np.zeros((len(physics_paths), m))
        for i in range(m):
            eps = max(1e-5, eps_rel * abs(x[i]))
            up = x.copy()
            up[i] = x[i] + eps
            dn = x.copy()
            dn[i] = x[i] - eps
            try:
                pu = physics_at(up)
                pd_ = physics_at(dn)
                for j, p in enumerate(physics_paths):
                    J[j, i] = (pu[p] - pd_[p]) / (2.0 * eps)
            except Exception:
                try:
                    pu = physics_at(up)
                    p0 = physics_at(x)
                    for j, p in enumerate(physics_paths):
                        J[j, i] = (pu[p] - p0[p]) / eps
                except Exception:
                    pass

        for j, p in enumerate(physics_paths):
            pj_shap = shap_matrix[s, pi[p]]
            elast = np.abs(J[j] * x)
            denom = elast.sum()
            if denom > 1e-12:
                through[s] += pj_shap * (elast / denom)

    return direct + through, design_paths


def physics_consistency(attr: DesignVariableAttribution, *, eps_rel: float = 1e-4) -> dict:
    """数据驱动 SHAP 重要性 vs 物理解析重要性（8 个设计变量）。

    横轴 = 平均 |总归因|；纵轴 = 平均 |∂η/∂X_i · X_i / η|（由 paraxial +
    模场耦合公式数值中心差分得到）。二者共线说明 ML 学到的"哪个变量重要"
    与光学理论一致。
    """
    design_paths = attr.design_paths
    base_project = attr.base_project
    n = attr.total.shape[0]
    m = len(design_paths)

    def analytical_eta(design_vals):
        raw = dict(zip(design_paths, [float(v) for v in design_vals]))
        p = _enrich_candidate_features(base_project, raw)
        frame = pd.DataFrame([{f: float(p[f]) for f in FORMULA_FEATURES}])
        loss_db = float(formula_baseline_db(frame)[0])
        return 10.0 ** (-loss_db / 10.0)

    shap_imp = np.abs(attr.total).mean(axis=0)
    phys_imp = np.zeros(m)
    for s in range(n):
        x = attr.Xmat[s]
        eta0 = analytical_eta(x)
        for i in range(m):
            eps = max(1e-5, eps_rel * abs(x[i]))
            up = x.copy()
            up[i] += eps
            dn = x.copy()
            dn[i] -= eps
            deta = (analytical_eta(up) - analytical_eta(dn)) / (2.0 * eps)
            elast = deta * x[i] / max(eta0, 1e-12)
            phys_imp[i] += abs(elast)
    phys_imp /= n

    pearson = float(np.corrcoef(shap_imp, phys_imp)[0, 1])
    try:
        from scipy.stats import spearmanr

        spearman = float(spearmanr(shap_imp, phys_imp).statistic)
    except Exception:
        spearman = float("nan")

    return {
        "shap_importance": shap_imp.tolist(),
        "physics_elasticity": phys_imp.tolist(),
        "pearson": pearson,
        "spearman": spearman,
    }


__all__ = [
    "DESIGN_SHORT",
    "DESIGN_LABEL",
    "DesignVariableAttribution",
    "compute_design_variable_attribution",
    "chain_rule_attribution_from_shap",
    "physics_consistency",
]

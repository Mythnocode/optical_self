
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt



plt.rcParams["font.sans-serif"] = [
    "Noto Sans CJK SC",
    "Microsoft YaHei",
    "SimHei",
    "DejaVu Sans",
]
plt.rcParams["axes.unicode_minus"] = False
import numpy as np
import pandas as pd

from machine_learning.explainability.contracts import ShapFormulaLinkageReport


def plot_local_contributions(report: ShapFormulaLinkageReport, path: Path) -> None:
    items = list(reversed(report.feature_contributions))
    labels = [item.feature for item in items]
    values = [item.shap_value for item in items]
    fig, ax = plt.subplots(figsize=(8.2, 4.8))
    ax.barh(labels, values)
    ax.axvline(0.0, linewidth=1.0)
    ax.set_xlabel(f"SHAP contribution ({report.target_unit})")
    ax.set_title("Local SHAP decomposition")
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def plot_global_importance(report: ShapFormulaLinkageReport, path: Path) -> None:
    items = list(reversed(report.global_importance))
    labels = [str(item["feature"]) for item in items]
    values = [float(item["mean_abs_shap"]) for item in items]
    fig, ax = plt.subplots(figsize=(8.2, 4.8))
    ax.barh(labels, values)
    ax.set_xlabel(f"Mean |SHAP| ({report.target_unit})")
    ax.set_title("Global feature importance")
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def plot_formula_dependence(feature: str, data: pd.DataFrame, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(7.2, 4.8))
    ax.scatter(data["feature_value"], data["shap_value"], s=12, alpha=0.45, label="SHAP")
    if "formula_centered_contribution" in data:
        ordered = data.sort_values("feature_value")
        ax.plot(
            ordered["feature_value"],
            ordered["formula_centered_contribution"],
            linewidth=1.6,
            label="Centered analytic formula",
        )
    ax.set_xlabel(feature)
    ax.set_ylabel("Contribution (dB)")
    ax.set_title(f"Formula linkage: {feature}")
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def plot_beeswarm(data: pd.DataFrame, path: Path) -> None:
    features = list(dict.fromkeys(data["feature"].tolist()))
    fig, ax = plt.subplots(figsize=(8.4, 5.4))
    rng = np.random.default_rng(0)
    for y, feature in enumerate(features):
        subset = data[data["feature"] == feature]
        jitter = rng.normal(0.0, 0.08, len(subset))
        ax.scatter(subset["shap_value"], y + jitter, s=9, alpha=0.4)
    ax.axvline(0.0, linewidth=1.0)
    ax.set_yticks(range(len(features)), features)
    ax.set_xlabel("SHAP contribution (dB)")
    ax.set_title("SHAP distribution")
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def plot_interaction_matrix(report: ShapFormulaLinkageReport, path: Path) -> None:
    if report.interaction_matrix is None:
        return
    matrix = np.asarray(report.interaction_matrix, dtype=float)
    fig, ax = plt.subplots(figsize=(6.5, 5.6))
    image = ax.imshow(matrix)
    ax.set_xticks(range(len(report.feature_order)), report.feature_order, rotation=35, ha="right")
    ax.set_yticks(range(len(report.feature_order)), report.feature_order)
    ax.set_title("Mean absolute SHAP interaction")
    fig.colorbar(image, ax=ax, label="dB")
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)

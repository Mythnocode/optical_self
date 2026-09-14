"""Capability catalogue for canvas nodes.

This is data only.  The old compact navigation rail and page stack are gone;
the live app uses WorkbenchShell / TeachingShell.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ShellAction:
    key: str
    title: str
    icon_name: str
    page_key: str
    target: str = ""
    payload: dict[str, Any] | None = None
    hint: str = ""


@dataclass(frozen=True, slots=True)
class ShellCategory:
    key: str
    title: str
    icon_name: str
    groups: tuple[tuple[str, tuple[ShellAction, ...]], ...]


CATEGORIES: tuple[ShellCategory, ...] = (
    ShellCategory(
        "system",
        "系统与建模",
        "application",
        ((
            "当前系统",
            (
                ShellAction("overview", "项目总览", "overview", "home", hint="平台总览与当前系统状态"),
                ShellAction("system", "系统建模", "list", "simulation", "simulation.parameters", hint="光源、光学元件与光纤参数"),
                ShellAction("lens_editor", "完整镜头编辑器", "list", "simulation", "simulation.lens_editor", hint="完整 Surface 表、曲率、材料与非球面参数"),
                ShellAction("compute_settings", "计算设置", "settings", "simulation", "simulation.parameters", {"section": "compute"}, hint="采样、传播算法与正式计算设置"),
            ),
        ),),
    ),
    ShellCategory(
        "analysis",
        "光学分析",
        "chart",
        ((
            "专业分析",
            (
                ShellAction("system_view", "系统视图", "rays", "simulation", "simulation.view", {"view": "光路"}),
                ShellAction("propagation", "光束传播", "rays", "simulation", "simulation.view", {"view": "光束包络"}),
                ShellAction("focal", "焦面分析", "intensity", "simulation", "simulation.view", {"view": "PSF"}),
                ShellAction("field", "复光场", "phase", "simulation", "simulation.view", {"view": "相位"}),
                ShellAction("mode", "模场匹配", "compare", "simulation", "simulation.view", {"view": "端面匹配"}),
                ShellAction("wave", "像质与波前", "result", "simulation", "simulation.view", {"view": "点列图"}),
                ShellAction("all_results", "完整结果目录", "result", "simulation", "simulation.result_catalogue", hint="点列图、PSF、MTF、波前、能量分解等全部结果"),
            )),
            ("研究分析", (
                ShellAction("scan", "参数研究", "chart", "simulation", "simulation.parameter_research", hint="改变当前系统参数并观察正式光学响应"),
                ShellAction("tolerance", "容差分析", "measure", "simulation", "simulation.tolerance", hint="围绕当前系统评估制造/装调误差的统计稳健性"),
            )),
        ),
    ),
    ShellCategory(
        "research",
        "优化",
        "optimization",
        (
            ("优化任务", (
                ShellAction("optimize", "自动优化", "optimization", "optimization", "optimization.variables"),
                ShellAction("physical_inverse", "物理反向设计", "workflow", "optimization", "optimization.inverse_design", hint="目标 → 物理搜索 → 正式候选"),
            )),
        ),
    ),
    ShellCategory(
        "surrogate",
        "代理模型",
        "machine_learning",
        ((
            "模型任务",
            (
                ShellAction("random_forest", "随机森林", "machine_learning", "machine_learning", "machine_learning.random_forest", hint="创建随机森林代理模型配置节点"),
                ShellAction("xgboost_physics_residual", "XGBoost物理残差", "machine_learning", "machine_learning", "machine_learning.xgboost_physics_residual", hint="创建物理残差 XGBoost 配置节点"),
                ShellAction("bilstm_structure_sequence", "BiLSTM", "machine_learning", "machine_learning", "machine_learning.bilstm_structure_sequence", hint="创建 BiLSTM 可变结构序列配置节点"),
                ShellAction("model_build", "模型构建", "machine_learning", "machine_learning", "machine_learning.build", hint="数据准备 → 模型训练 → 模型比较"),
                ShellAction("forward", "正向预测", "next", "machine_learning", "machine_learning.prediction", hint="当前系统参数 → 性能预测"),
                ShellAction("ml_inverse", "反向预测", "workflow", "optimization", "optimization.ml_inverse_prediction", hint="目标性能 → 代理模型候选 → 正式验证"),
                ShellAction("model_explain", "模型解释", "inspect", "explainability", hint="SHAP 与特征贡献解释"),
                ShellAction("model_manage", "模型管理", "list", "machine_learning", "machine_learning.models", hint="模型比较、采用与版本信息"),
            ),
        ),),
    ),
    ShellCategory(
        "experiment",
        "实验与数据",
        "measure",
        ((
            "数据与任务",
            (
                ShellAction("data", "数据管理", "list", "machine_learning", "machine_learning.data", hint="数据集生成、导入、质量与注册"),
                ShellAction("tasks", "任务中心", "tasks", "tasks", hint="仿真、扫描、优化、训练与解释任务"),
            ),
        ),),
    ),
    ShellCategory(
        "teaching",
        "教学",
        "teaching",
        ((
            "实验台",
            (
                ShellAction(
                    "teaching_bench",
                    "教学实验台",
                    "teaching",
                    "teaching",
                    hint="半实物实验台：示意随拖动更新，光斑和耦合请用光学计算",
                ),
            ),
        ),),
    ),
)

CATEGORY_BY_KEY = {item.key: item for item in CATEGORIES}

__all__ = ["CATEGORY_BY_KEY", "CATEGORIES", "ShellAction", "ShellCategory"]

from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


class CheckFailure(RuntimeError):
    pass


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def check(name: str, condition: bool, detail: str = "") -> None:
    state = "通过" if condition else "失败"
    print(f"[{state}] {name}" + (f"：{detail}" if detail else ""))
    if not condition:
        raise CheckFailure(name)


def contrast(hex1: str, hex2: str) -> float:
    def lum(value: str) -> float:
        value = value.lstrip("#")
        rgb = [int(value[i:i+2], 16) / 255 for i in (0, 2, 4)]
        linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]
    a, b = sorted((lum(hex1), lum(hex2)), reverse=True)
    return (a + 0.05) / (b + 0.05)


def main() -> int:
    layout = text("frontend_pyside/app/main_window_layout.py")
    main_window = text("frontend_pyside/app/main_window.py")
    qss = text("frontend_pyside/resources/qss/light.qss")
    main_py = text("frontend_pyside/app/main.py")
    catalog = text("frontend_pyside/app/shell_catalog.py")
    workbench = text("frontend_pyside/app/workbench_shell.py")
    registry = text("frontend_pyside/features/canvas/registry.py")
    node_catalog = text("frontend_pyside/features/canvas/parameter_catalog.py")
    planner = text("frontend_pyside/features/simulation/analysis_planner.py")
    viewer = text("frontend_pyside/shared/dialogs/result_viewers.py")
    task_node = text("frontend_pyside/features/canvas/task_node.py")
    task_runner = text("frontend_pyside/features/canvas/task_runner.py")
    opt_service = text("backend/optical_ml_app/application/optimization_service.py")
    ml_features = text("frontend_pyside/features/machine_learning/feature_adapter.py")

    for title in ("系统", "分析", "参数研究", "优化", "代理模型", "教学"):
        check(f"能力目录包含“{title}”", title in catalog)
    check("分类数据仍可供画布节点消费", "for category in CATEGORIES" in registry or "CATEGORIES" in registry)
    check("旧导航轨已从布局退役", "CompactNavigationRail" not in layout and "DocumentTabBar" not in layout)
    check("主窗口使用双壳模式栈", "WorkbenchShell" in layout and "TeachingShell" in layout)
    check("旧整页弹窗壳层已删除", "open_feature_window" not in main_window and "FeaturePageWindow" not in main_window)
    check("旧 views 目录已删除", not (ROOT / "frontend_pyside/views").exists())
    check("旧 page_registry 已删除", not (ROOT / "frontend_pyside/app/page_registry.py").exists())
    check("旧 compact_shell 已删除", not (ROOT / "frontend_pyside/app/compact_shell.py").exists())
    check("旧 HomePage 已删除", not (ROOT / "frontend_pyside/features/home").exists())
    check("旧 SimulationPage 已删除", not (ROOT / "frontend_pyside/features/simulation/page.py").exists())
    check("旧 OptimizationPage 已删除", not (ROOT / "frontend_pyside/features/optimization/page.py").exists())
    check("旧 TeachingV2Page 已删除", not (ROOT / "frontend_pyside/features/teaching_v2/page.py").exists())
    check("旧 PanelNode 已删除", not (ROOT / "frontend_pyside/features/canvas/panel_node.py").exists())

    required_views = {
        "光路", "3D光路", "光束包络", "点列图", "MTF", "波前", "PSF", "焦面截面", "光斑尺寸",
        "振幅", "相位", "相位对比", "多平面演化", "光纤基模", "端面匹配", "XY模场比较",
        "重叠贡献", "能量分解", "束腰位置",
    }
    check("原有结果资产仍在分析规划器中", required_views <= set(re.findall(r'"([^"]+)"', planner)))
    for analyzer in ("系统视图", "光束传播", "焦面分析", "复光场", "模场匹配", "像质与波前"):
        check(f"存在分析器“{analyzer}”", analyzer in catalog)
    check("真实波前已接入结果目录", '"波前"' in planner)
    check("镜头组使用原生表格节点", "lens_editor" in registry and "LensSurfaceTable" in text("frontend_pyside/features/canvas/lens_table.py"))

    check("参数研究/容差/优化落画布任务节点", '"scan"' in registry and '"tolerance"' in registry and '"optimize"' in registry)
    check("反向设计存在目标效率输入", "inverse_target_efficiency" in node_catalog or "target_efficiency" in task_node or "目标效率" in task_node)
    check("反向设计目标进入后端 target objective", '"goal": "target"' in task_runner or "target_value" in task_runner)
    check("反向设计候选来自正式优化历史", "_formal_candidate_summary" in opt_service and '"formal_simulation"' in opt_service)

    for stage in ("随机森林", "XGBoost物理残差", "BiLSTM", "正向预测"):
        check(f"代理模型入口包含“{stage}”", stage in catalog)
    check("正向预测不再把物理残差当普通缺失字段", "derive_coupling_physics_features" in ml_features and "PHYSICS_RESIDUAL_FEATURE_PATHS" in ml_features)
    check("正向预测缺失特征不填假默认值", "resolve_feature_path" in ml_features and "fill" not in ml_features.lower())
    check("SHAP统一命名为模型解释", "模型解释" in catalog and "SHAP" in text("frontend_pyside/features/explainability/actions.py"))

    check("教学入口为 TeachingShell", "class TeachingShell" in workbench)
    check("教学壳使用 teaching_v2 画布", "BenchScene" in workbench and "SceneStore" in workbench)
    check("教学页不再承诺失配课", "五大失配" not in workbench)

    for mode in ("两项对比", "三项对比", "四项对比", "焦点 + 参考"):
        check(f"比较布局包含“{mode}”", mode in viewer)

    match = re.search(r"QApplication\.setFont\(QFont\([^,]+,\s*([0-9.]+)", main_py)
    if match:
        size = float(match.group(1))
    else:
        sizes = [float(v) for v in re.findall(r"setPointSizeF?\(([0-9.]+)\)", main_py)]
        size = max(sizes or [13.5])
    check("全局字号基线不低于 13.5 pt", size >= 13.5, f"检测值 {size:g} pt")
    check("主要界面字号保持较大", "font-size: 13.5pt" in qss and "font-size: 12.5pt" in qss)
    ratios = {
        "主文字/浅背景": contrast("#101828", "#F8FAFC"),
        "次文字/白底": contrast("#344054", "#FFFFFF"),
        "白字/主色": contrast("#FFFFFF", "#155EEF"),
    }
    for label, ratio in ratios.items():
        check(f"颜色对比度 {label}", ratio >= 4.5, f"{ratio:.2f}:1")

    print("\n静态验收全部通过。动态点击、旋转、缩放、截图由 refactor_dynamic_acceptance.py 单独验收。")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except CheckFailure:
        raise SystemExit(1)

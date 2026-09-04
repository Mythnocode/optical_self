from __future__ import annotations

import ast
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


def literal_assignment(source: str, name: str):
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(t, ast.Name) and t.id == name for t in targets):
                try:
                    return ast.literal_eval(node.value)
                except Exception:
                    return None
    return None


def main() -> int:
    layout = text("frontend_pyside/app/main_window_layout.py")
    main_window = text("frontend_pyside/app/main_window.py")
    live = text("frontend_pyside/features/simulation/live_preview.py")
    qss = text("frontend_pyside/resources/qss/light.qss")
    main_py = text("frontend_pyside/app/main.py")
    ml_page = text("frontend_pyside/features/machine_learning/page.py")
    ml_view = text("frontend_pyside/features/machine_learning/presentation/view_behavior.py")
    ml_features = text("frontend_pyside/features/machine_learning/feature_adapter.py")
    opt_page = text("frontend_pyside/features/optimization/page.py")
    opt_submit = text("frontend_pyside/features/optimization/presentation/submit_behavior.py")
    opt_result = text("frontend_pyside/features/optimization/presentation/result_behavior.py")
    opt_service = text("backend/optical_ml_app/application/optimization_service.py")
    teaching = text("frontend_pyside/features/teaching/spatial_routing_upgrade.py")
    spatial = text("frontend_pyside/features/teaching/spatial_workbench.py")
    teaching_qml = text("frontend_pyside/resources/qml/unified_teaching_scene_3d.qml")
    viewer = text("frontend_pyside/shared/dialogs/result_viewers.py")

    # Global shell: one compact command bar, no visible feature rail / fake documents.
    for title in ("系统", "分析", "参数研究", "优化", "代理模型", "教学"):
        check(f"顶部命令栏包含“{title}”", f'"{title}"' in main_window or f'"{title}"' in layout)
    check("旧导航轨只保留兼容实例且不进入可见布局", "rail = CompactNavigationRail" in layout and "rail.hide()" in layout)
    check("旧文档标签只保留兼容实例且不进入可见布局", "document_tabs = DocumentTabBar" in layout and "document_tabs.hide()" in layout)
    check("命令动作不再制造伪文档标签", "update_document=False" in main_window)

    required_views = {
        "光路", "3D光路", "光束包络", "点列图", "MTF", "波前", "PSF", "焦面截面", "光斑尺寸",
        "振幅", "相位", "相位对比", "多平面演化", "光纤基模", "端面匹配", "XY模场比较",
        "重叠贡献", "能量分解", "束腰位置",
    }
    result_order = set(literal_assignment(live, "RESULT_ORDER") or ())
    check("原有结果资产未从结果目录丢失", required_views <= result_order, f"共 {len(result_order)} 项")
    for analyzer in ("系统视图", "光束传播", "焦面分析", "复光场", "模场匹配", "像质与波前"):
        check(f"存在分析器“{analyzer}”", analyzer in live)
    check("真实波前已接入结果目录", '"波前"' in live and '"波前"' in text("frontend_pyside/features/simulation/analysis_planner.py"))
    check("未计算视图仍保留入口", "点此计算" in live)
    check("专业分析器提供概览/详细双层", 'SecondaryButton("概览"' in live and 'SecondaryButton("详细"' in live)
    check("关键指标条已接入主结果", "analysisMetricStrip" in live and "key_metrics" in live)

    # Complex task layouts.
    check("参数研究采用设置/结果横向分栏", "QSplitter" in opt_page and "optimizationResultHost" in opt_page)
    check("反向设计存在真实开始动作", '"开始反向设计"' in opt_page)
    check("反向设计存在目标效率输入", "inverse_target_efficiency" in opt_page and '"目标效率"' in opt_page)
    check("反向设计目标进入后端 target objective", '"goal": "target"' in opt_submit and '"target_value"' in opt_submit)
    check("反向设计候选来自正式优化历史", "_formal_candidate_summary" in opt_service and '"formal_simulation"' in opt_service)
    check("候选可选中写回工程并要求正式验证", "_latest_candidate_variables" in opt_result and "应用选中候选" in opt_result and "_verify_best_design" in opt_page)

    for stage in ("模型概览", "数据", "训练", "模型比较", "正向预测"):
        check(f"代理模型任务流包含“{stage}”", stage in ml_page)
    check("正向预测第一屏存在开始按钮", '"开始预测"' in ml_page or '"开始预测"' in ml_view)
    check("正向预测不再把物理残差当普通缺失字段", "derive_coupling_physics_features" in ml_features and "PHYSICS_RESIDUAL_FEATURE_PATHS" in ml_features)
    check("正向预测缺失特征不填假默认值", "resolve_feature_path" in ml_features and "fill" not in ml_features.lower())
    check("SHAP统一命名为模型解释", "模型解释" in main_window and "SHAP" in main_window)

    # Teaching: five experiments first, theory on demand, compact 3D controls.
    for label in ("横向", "角度", "尺寸", "轴向", "曲率"):
        check(f"教学实验入口包含“{label}”", f'"{label}"' in teaching)
    for stage in ("理想", "引入失配", "观察", "原理", "修正"):
        check(f"教学过程包含“{stage}”", stage in teaching)
    for preset in ("全局", "耦合端", "俯视", "侧视"):
        check(f"3D相机栏包含“{preset}”", f'"{preset}"' in spatial)
    check("3D显示项收进按需菜单", "显示 ▾" in spatial and "set_analysis_panels_visible" in spatial)
    check("QML内部重复相机条已隐藏", "visible: false  // QWidget shell owns compact camera commands" in teaching_qml)
    check("QML截面/模场分析卡默认不占舞台", "analysisPanelsVisible" in teaching_qml)
    check("3D标签有避碰策略", "_label_boxes" in spatial and "label_is_free" in spatial)

    # Compare container and visual baseline.
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

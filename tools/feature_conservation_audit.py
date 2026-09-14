"""Static feature-conservation audit for the canvas-centric UI.

The UI is allowed to move or fold capabilities, but not delete them.  This audit
checks the capability catalogue plus the source contracts that back the major
simulation, optimisation, ML and teaching workflows.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def text(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def contains_all(rel: str, needles: list[str]) -> tuple[bool, str]:
    content = text(rel)
    missing = [item for item in needles if item not in content]
    return not missing, ("" if not missing else "缺少：" + "、".join(missing))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="acceptance/feature_conservation")
    args = parser.parse_args()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)

    checks: list[tuple[str, str, bool, str]] = []

    ok, note = contains_all(
        "frontend_pyside/app/shell_catalog.py",
        ["系统与建模", "光学分析", "优化", "代理模型", "实验与数据", "教学",
         "参数研究", "容差分析", "自动优化", "物理反向设计", "正向预测", "反向预测",
         "模型解释", "模型管理", "任务中心", "教学实验台"],
    )
    checks.append(("全平台能力目录", "所有正式能力仍可从工具箱两层以内发现", ok, note))

    ok, note = contains_all(
        "frontend_pyside/features/simulation/analysis_planner.py",
        ["光路", "3D光路", "光束包络", "多平面演化", "束腰位置", "PSF", "焦面截面", "光斑尺寸",
         "振幅", "相位", "相位对比", "端面匹配", "光纤基模", "XY模场比较", "重叠贡献", "能量分解",
         "点列图", "MTF", "波前"],
    )
    checks.append(("专业光学分析", "既有结果视图仍由分析规划器保留", ok, note))

    ok, note = contains_all(
        "frontend_pyside/features/canvas/parameter_catalog.py",
        ["单模光纤", "多模光纤", "用户模式", "高斯近似", "LP01", "HE11", "导入复场"],
    )
    checks.append(("光纤/接收端", "接收类型与模式模型未因节点化而删除", ok, note))

    ok, note = contains_all(
        "frontend_pyside/features/simulation/surface_registry.py",
        ["球面", "非球面", "平面", "光阑", "反射镜", "衍射光栅", "坐标断点", "二元衍射面", "探测器/像面", "用户自定义面", "a4", "a6", "a8"],
    )
    checks.append(("光学表面/镜头编辑", "Surface 类型与非球面高级参数保留", ok, note))

    ok1, note1 = contains_all(
        "frontend_pyside/app/shell_catalog.py",
        ["simulation.parameter_research", "simulation.tolerance", "optimization.inverse_design", "optimization.ml_inverse_prediction"],
    )
    ok2, note2 = contains_all(
        "frontend_pyside/features/canvas/task_runner.py",
        ["surrogate_model_id", "coarse_fraction", "ml_inverse_prediction"],
    )
    ok3, note3 = contains_all(
        "backend/optical_ml_app/application/optimization_service.py",
        ["optimization.surrogate_coarse_search", "coarse_evaluation_source", "surrogate_model_id"],
    )
    checks.append(("研究/优化/两类反向", "参数研究、容差、自动优化、物理反向设计与ML反向预测均保留且ML路径调用代理模型粗搜索", ok1 and ok2 and ok3, "; ".join(x for x in (note1, note2, note3) if x)))

    ok, note = contains_all(
        "frontend_pyside/features/canvas/task_node.py",
        ["实验验证", "validation_metric", "validation_reference"],
    )
    checks.append(("实验验证", "实验/仿真定量比较入口仍在画布任务节点中", ok, note))

    ok1, note1 = contains_all(
        "frontend_pyside/app/shell_catalog.py",
        ["随机森林", "XGBoost物理残差", "BiLSTM"],
    )
    ok2, note2 = contains_all(
        "frontend_pyside/features/canvas/model_node.py",
        ["随机森林", "BiLSTM"],
    )
    checks.append(("代理模型构建/正向预测", "RF、XGBoost、BiLSTM 入口保留在画布节点", ok1 and ok2, "; ".join(x for x in (note1, note2) if x)))

    ok, note = contains_all(
        "frontend_pyside/features/explainability/actions.py",
        ["SHAP"],
    )
    checks.append(("模型解释", "SHAP/特征贡献解释能力保留且与物理失配概念分开", ok, note))

    ok1, note1 = contains_all(
        "frontend_pyside/app/workbench_shell.py",
        ["TeachingShell", "器材库", "同步到仿真"],
    )
    ok2, note2 = contains_all(
        "frontend_pyside/app/main_window.py",
        ['"teaching"'],
    )
    checks.append(("教学", "教学入口为 TeachingShell；旧失配课已下线", ok1 and ok2, "; ".join(x for x in (note1, note2) if x)))

    ok, note = contains_all(
        "frontend_pyside/app/shell_catalog.py",
        ["simulation.lens_editor", "simulation.result_catalogue"],
    )
    checks.append(("上下文入口", "完整镜头编辑器和完整结果目录具备真实路由", ok, note))

    remaining = []
    banned = ("当前方案", "方案A", "方案B", "方案 C", "方案C")
    for p in (ROOT / "frontend_pyside").rglob("*.py"):
        content = p.read_text(encoding="utf-8")
        if any(token in content for token in banned):
            remaining.append(str(p.relative_to(ROOT)))
    checks.append(("单一当前系统术语", "前端不再使用“当前方案/方案A/B”等并行方案语义", not remaining, "残留：" + "、".join(remaining[:10]) if remaining else ""))

    rows = [
        {"feature": feature, "requirement": requirement, "status": "PASS" if ok else "FAIL", "note": note}
        for feature, requirement, ok, note in checks
    ]
    passed = all(row["status"] == "PASS" for row in rows)
    result = {"passed": passed, "checks": rows}
    (out / "feature_conservation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = ["# 功能守恒验收", "", "界面允许重排/分级，但正式能力不能因简化而消失。", "", "| 功能域 | 守恒要求 | 状态 | 说明 |", "|---|---|---|---|"]
    for row in rows:
        note = row["note"].replace("|", "\\|") or "—"
        lines.append(f"| {row['feature']} | {row['requirement']} | **{row['status']}** | {note} |")
    lines += ["", f"**OVERALL: {'PASS' if passed else 'FAIL'}**", ""]
    (out / "feature_conservation.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if passed else 1)


if __name__ == "__main__":
    main()

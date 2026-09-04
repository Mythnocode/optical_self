"""Static feature-conservation audit for the 2026-08-17 UI rework.

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
        "frontend_pyside/app/compact_shell.py",
        ["系统与建模", "光学分析", "研究与优化", "代理模型", "实验与数据", "教学",
         "参数研究", "容差分析", "自动优化", "物理反向设计", "模型构建", "正向预测", "反向预测",
         "模型解释", "模型管理", "实验验证", "任务中心", "五大失配实验", "自由实验", "实验库"],
    )
    checks.append(("全平台能力目录", "所有正式能力仍可从工具箱两层以内发现", ok, note))

    ok, note = contains_all(
        "frontend_pyside/features/simulation/live_preview.py",
        [
            '("系统视图", ("光路", "3D光路"))',
            '("光束传播", ("光束包络", "多平面演化", "束腰位置"))',
            '("焦面分析", ("PSF", "焦面截面", "光斑尺寸"))',
            '("复光场", ("振幅", "相位", "相位对比"))',
            '("模场匹配", ("端面匹配", "光纤基模", "XY模场比较", "重叠贡献", "能量分解"))',
            '("像质与波前", ("点列图", "PSF", "MTF", "波前"))',
        ],
    )
    checks.append(("专业光学分析", "6组分析器及全部既有结果视图保留", ok, note))

    ok, note = contains_all(
        "frontend_pyside/features/simulation/components/parameter_parts/page_builders.py",
        ["单模光纤", "多模光纤", "用户模式", "高斯近似", "LP01", "HE11", "导入复场"],
    )
    checks.append(("光纤/接收端", "接收类型与模式模型未因侧栏压缩而删除", ok, note))

    ok, note = contains_all(
        "frontend_pyside/features/simulation/surface_registry.py",
        ["球面", "非球面", "平面", "光阑", "反射镜", "衍射光栅", "坐标断点", "二元衍射面", "探测器/像面", "用户自定义面", "a4", "a6", "a8"],
    )
    checks.append(("光学表面/镜头编辑", "Surface 类型与非球面高级参数保留", ok, note))

    ok1, note1 = contains_all(
        "frontend_pyside/features/optimization/page.py",
        ["optimization.scan", "optimization.tolerance", "optimization.inverse_design", "optimization.ml_inverse_prediction", "optimization.validation"],
    )
    ok2, note2 = contains_all(
        "frontend_pyside/features/optimization/presentation/submit_behavior.py",
        ["surrogate_model_id", "coarse_fraction", "ml_inverse_prediction"],
    )
    ok3, note3 = contains_all(
        "backend/optical_ml_app/application/optimization_service.py",
        ["optimization.surrogate_coarse_search", "coarse_evaluation_source", "surrogate_model_id"],
    )
    checks.append(("研究/优化/两类反向", "参数研究、容差、自动优化、物理反向设计与ML反向预测均保留且ML路径调用代理模型粗搜索", ok1 and ok2 and ok3, "; ".join(x for x in (note1, note2, note3) if x)))

    ok, note = contains_all(
        "frontend_pyside/features/optimization/experiment_validation.py",
        ["RMSE", "MAE", "归一化残差", "实验", "仿真"],
    )
    checks.append(("实验验证", "实验/仿真定量比较与误差指标保留", ok, note))

    ok1, note1 = contains_all(
        "frontend_pyside/features/machine_learning/presentation/view_behavior.py",
        ["随机森林", "XGBoost物理残差"],
    )
    ok2, note2 = contains_all("frontend_pyside/features/machine_learning/page.py", ["BiLSTM", "数据准备", "模型训练", "模型比较", "正向预测"])
    checks.append(("代理模型构建/正向预测", "RF、XGBoost、BiLSTM 与 数据→训练→比较→预测 链路保留", ok1 and ok2, "; ".join(x for x in (note1, note2) if x)))

    ok, note = contains_all(
        "frontend_pyside/features/explainability/presentation/shap_behavior.py",
        ["SHAP"],
    )
    checks.append(("模型解释", "SHAP/特征贡献解释能力保留且与物理失配概念分开", ok, note))

    ok1, note1 = contains_all(
        "frontend_pyside/features/teaching/unified_workbench.py",
        ["横向", "角度", "尺寸", "轴向", "曲率", "教学环境", "当前系统"],
    )
    teaching_text = "\n".join(
        p.read_text(encoding="utf-8")
        for p in (ROOT / "frontend_pyside/features/teaching").rglob("*.py")
    )
    ok2 = "自动吸附" not in teaching_text and "解除吸附" not in teaching_text
    note2 = "" if ok2 else "仍存在自动吸附可见逻辑"
    checks.append(("教学", "五大失配、2D/3D/自由实验保留；器件/仪器不再使用自动吸附式交互", ok1 and ok2, "; ".join(x for x in (note1, note2) if x)))

    ok, note = contains_all("frontend_pyside/features/simulation/page.py", ["simulation.lens_editor", "simulation.result_catalogue"])
    checks.append(("上下文入口", "完整镜头编辑器和完整结果目录具备真实路由", ok, note))

    # User-facing source code must no longer create a parallel multi-scheme concept.
    remaining = []
    for p in (ROOT / "frontend_pyside").rglob("*.py"):
        if "方案" in p.read_text(encoding="utf-8"):
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

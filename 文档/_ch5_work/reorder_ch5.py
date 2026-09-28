# -*- coding: utf-8 -*-
"""
重排《研究报告》第五章，使其贴合 app 的一级界面逻辑：

    首页 → 教学 → 仿真 → 模型 → 优化 → 解释   （+ 5.7 模块联动与 AI 辅助）

原来章节顺序是 教学 → 建模 → 优化 → SHAP解释 → 仿真，与 app 标签顺序不符，
也与本报告 5.1 自己描述的"教学→仿真→模型→优化→解释"流程自相矛盾。

本脚本只做三件事：
  1. 调整 5.1~5.6 六个小节的先后顺序；
  2. 同步重排小节编号与图号（含正文"如图 5-x 所示"引用），并修复重复的"图5-6"；
  3. 把少数与 app 实际界面不一致的措辞对齐（模块名、按钮名）。

插图本身（w:drawing）一个字节都不改，只随所在段落整体移动。
"""
import re
import sys
from copy import deepcopy
from pathlib import Path

import docx
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("研究报告.docx")
DST = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("研究报告.new.docx")

d = docx.Document(str(SRC))
body = d.element.body
paras = d.paragraphs
pidx = {id(p._p): i for i, p in enumerate(paras)}

# ---------------------------------------------------------------- 文本工具

CJK = re.compile(r"[⺀-鿿　-〿＀-￯]")
RPR_CJK = {"ascii": "宋体", "hAnsi": "宋体", "cs": "Times New Roman"}
RPR_LAT = {"cs": "Times New Roman"}


def _mk_rpr(attrs):
    rpr = OxmlElement("w:rPr")
    rf = OxmlElement("w:rFonts")
    for k, v in attrs.items():
        rf.set(qn("w:" + k), v)
    rpr.append(rf)
    col = OxmlElement("w:color")
    col.set(qn("w:val"), "000000")
    rpr.append(col)
    return rpr


def set_para_text(p, text):
    """整段重写，按文档既有约定把中英文拆到不同 run（中文宋体 / 西文 Times New Roman）。"""
    bad = p._p.findall(".//" + qn("w:bookmarkStart")) + p._p.findall(".//" + qn("w:bookmarkEnd"))
    assert not bad, f"段内含书签，禁止整段重写: {text[:20]}"
    for r in list(p.runs):
        r._r.getparent().remove(r._r)
    segs = []
    for ch in text:
        lat = not CJK.match(ch)
        if segs and segs[-1][1] == lat:
            segs[-1][0] += ch
        else:
            segs.append([ch, lat])
    for s, lat in segs:
        r = OxmlElement("w:r")
        r.append(_mk_rpr(RPR_LAT if lat else RPR_CJK))
        t = OxmlElement("w:t")
        t.set(qn("xml:space"), "preserve")
        t.text = s
        r.append(t)
        p._p.append(r)


def replace_in_para(p, old, new, required=True):
    """优先在单个 run 内替换（保持原格式），跨 run 时整段重写。"""
    for r in p.runs:
        if old in r.text:
            r.text = r.text.replace(old, new, 1)
            return True
    full = "".join(r.text for r in p.runs)
    if old in full:
        set_para_text(p, full.replace(old, new, 1))
        return True
    if required:
        raise SystemExit(f"未找到待替换文本 {old!r} in {full[:40]!r}")
    return False


def set_runs(p, mapping):
    """按 run 下标精确改写（用于分段排版的标题/图题）。"""
    for i, txt in mapping.items():
        p.runs[i].text = txt


# ---------------------------------------------------------------- 1. 文本修正

# --- 标题：重排编号 + 统一模块名 ---
set_runs(paras[260], {0: "5.1 ", 1: "首页"})          # 原 5.1 功能区总览
set_runs(paras[275], {0: "5.5 "})                     # 原 5.4 优化模块
set_runs(paras[270], {0: "5.4 ", 1: "模型模块"})      # 原 5.3 建模模块
set_runs(paras[280], {0: "5.6 ", 1: "解释模块"})      # 原 5.5 SHAP 解释模块
set_runs(paras[288], {0: "5.3 ", 1: "仿真模块"})      # 原 5.6 仿真模块

# --- 图题重排 ---
set_runs(paras[274], {1: "5-5 ", 2: "模型模块的数据源选择与联合训练结果"})   # 原 图5-3
set_runs(paras[279], {1: "5-6 "})                                            # 原 图5-4
set_runs(paras[284], {1: "5-7 "})                                            # 原 图5-5
set_runs(paras[287], {0: "图5-8 耦合效率随参数变化【待换】"})                 # 原 图5-6(重复)
set_runs(paras[293], {1: "5-3 "})                                            # 原 图5-6(重复)
set_runs(paras[296], {0: "图5-4 仿真结果"})                                   # 原 图5-7

# --- 正文中的图号引用 ---
replace_in_para(paras[285], "图5-6", "图5-8")
replace_in_para(paras[294], "图5-7", "图5-4")

# --- 与 app 界面不一致的措辞 ---
set_para_text(
    paras[261],
    "打开平台后首先进入首页。首页中央以“光学研究工作流”为主题，按一级功能栏的顺序横向排列"
    "教学、仿真、模型、优化和解释五个功能区，每个功能区用若干快捷卡片说明该环节的用途，"
    "并给出直达入口。五个功能区既是功能说明，也是快捷入口；点击卡片即可直接跳转到对应模块"
    "的相应页面，使用者不需要先熟悉复杂的菜单层级即可定位任务。",
)
replace_in_para(paras[262], "物理分析", "物理链路")
set_para_text(
    paras[267],
    "教学桌面支持清空场景、重置视角和重新加载标准方案。选择内置的“四非球面 · 780 nm 高效耦合”"
    "方案后，使用者可以观察四片透镜的排布、光线逐片偏折以及最终会聚进入光纤的过程。"
    "教学模块还可与仿真工程同步，使同一套器件位置、波长和光纤模场参数能够从教学演示延伸到正式仿真。",
)
replace_in_para(paras[271], "建模模块", "模型模块")
set_para_text(
    paras[272],
    "点击“开始训练”后，平台联合训练随机森林与物理残差 XGBoost 模型，并输出残差图、"
    "实测值与预测值对照、残差分布和验证误差曲线。四类视图分别用于观察单样本误差、"
    "预测与真实结果的一致性、误差是否存在系统性偏差以及训练过程是否收敛充分。"
    "训练完成的模型可在模型预测页中直接使用，输入新的参数组合即可快速得到预测结果，"
    "为参数扫描和优化提供高速近似计算。",
)
set_para_text(
    paras[276],
    "进入优化模块后，使用者先在左栏的参数列表中勾选需要优化的变量并设定取值范围，"
    "再选择优化方式、优化目标和最大评价次数，启动优化任务。优化过程中，界面实时显示"
    "目标指标的过程曲线，并通过候选对照表呈现不同参数组合的性能与状态。",
)
set_para_text(
    paras[277],
    "优化完成后，优化结果页给出多个可比较的候选方案及其状态。使用者选择方案后点击“应用方案”，"
    "优化参数随即回写到当前工程，并由平台自动发起一次正式仿真验证。除多变量优化外，"
    "平台还提供参数扫描功能，可以固定其他条件，观察耦合效率随某一个参数变化的趋势，"
    "为判断局部最优、敏感区间和后续实验取值提供依据。",
)
set_para_text(
    paras[281],
    "为解释模型预测和优化结果背后的依据，平台提供解释模块。使用者在贡献排序页选择已经训练的"
    "模型并点击“计算解释”后，平台输出全局特征重要性排名、蜂群图、特征依赖网格图、"
    "单变量依赖趋势图、物理一致性图和瀑布图。全局视图用于判断哪些参数在整体样本中最重要，"
    "局部视图用于解释某一个候选方案的预测值由哪些参数共同形成。",
)
set_para_text(
    paras[282],
    "对于贡献度较高的参数，平台在物理链路页进一步给出对应的物理解释，将统计结论与光斑尺寸、"
    "焦面位置、波前曲率、横向偏移或轴向离焦等光学量联系起来。SHAP 结果不被单独当作因果证明，"
    "而是与单变量扫描、解析公式和正式物理复算交叉检查；只有当模型解释与光学规律基本一致时，"
    "才把它作为参数筛选和实验设计的依据。",
)
set_para_text(
    paras[290],
    "使用者可以直接调用优化模块得到的参数，点击一级功能栏的“开始计算”提交仿真。"
    "计算完成后，平台按光路图、光斑图、光纤耦合、波前与衍射四个结果页依次展示："
    "光路图用于观察光线在四片透镜之间的传播和会聚，光斑图用于查看尺寸、形状与能量分布，"
    "耦合结果用于判断入射场与目标模式的匹配程度，波前与衍射分析则用于评价光束质量和相位传播状态。",
)
replace_in_para(paras[291], "是建模、优化", "是模型、优化")
replace_in_para(paras[298], "建模模块", "模型模块")

print("text patched.")

# ---------------------------------------------------------------- 2. 重排小节


def ptext(el):
    return "".join(t.text or "" for t in el.findall(".//" + qn("w:t")))


def find_body_idx(pred):
    for ci, ch in enumerate(body):
        if ch.tag == qn("w:p"):
            i = pidx.get(id(ch))
            if i is not None and pred(paras[i].text.strip()):
                return ci
    raise SystemExit("anchor not found")


start = find_body_idx(lambda t: t.startswith("5平台功能介绍"))
end = find_body_idx(lambda t: t.startswith("6 平台可行性验证"))

# 小节块边界（body 下标）：5.1..5.7 的起点 + 章末 bookmarkEnd
BOUNDS = [263, 268, 273, 278, 283, 291, 300, 303]
blocks = {k: [body[i] for i in range(BOUNDS[k], BOUNDS[k + 1])] for k in range(7)}

for k, blk in sorted(blocks.items()):
    nimg = sum(len(e.findall(".//" + qn("w:drawing"))) for e in blk)
    print(f"  block {k} <- {ptext(blk[0])[:22]!r} elems={len(blk)} imgs={nimg}")

NEW_ORDER = [0, 1, 5, 2, 3, 4, 6]  # 首页 教学 仿真 模型 优化 解释 联动
header = body[start]

for k in range(7):                       # 先摘除
    for el in blocks[k]:
        body.remove(el)

cursor = header                          # 再按新顺序插回
for k in NEW_ORDER:
    for el in blocks[k]:
        cursor.addnext(el)
        cursor = el

print("reordered.")
d.save(str(DST))
print(f"saved -> {DST}")

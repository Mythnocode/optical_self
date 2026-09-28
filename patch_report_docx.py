from __future__ import annotations

import argparse
import json
import os
import zipfile
from copy import deepcopy
from pathlib import Path

from lxml import etree


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
XML_NS = "http://www.w3.org/XML/1998/namespace"
NS = {"w": W_NS}


def q(name: str) -> str:
    return f"{{{W_NS}}}{name}"


def text_of(p: etree._Element) -> str:
    return "".join(p.xpath(".//w:t/text()", namespaces=NS))


def style_of(p: etree._Element) -> str:
    value = p.xpath("string(./w:pPr/w:pStyle/@w:val)", namespaces=NS)
    return value or ""


def ensure_ppr(p: etree._Element) -> etree._Element:
    ppr = p.find(q("pPr"))
    if ppr is None:
        ppr = etree.Element(q("pPr"))
        p.insert(0, ppr)
    return ppr


def set_child_attr(parent: etree._Element, tag: str, attrs: dict[str, str]) -> etree._Element:
    child = parent.find(q(tag))
    if child is None:
        child = etree.SubElement(parent, q(tag))
    for key, value in attrs.items():
        child.set(q(key), value)
    return child


def set_style(p: etree._Element, style_id: str) -> None:
    ppr = ensure_ppr(p)
    ps = ppr.find(q("pStyle"))
    if ps is None:
        ps = etree.Element(q("pStyle"))
        ppr.insert(0, ps)
    ps.set(q("val"), style_id)


def set_spacing(p: etree._Element, *, before: int, after: int, line: int = 360) -> None:
    ppr = ensure_ppr(p)
    spacing = ppr.find(q("spacing"))
    if spacing is None:
        spacing = etree.SubElement(ppr, q("spacing"))
    spacing.set(q("before"), str(before))
    spacing.set(q("after"), str(after))
    spacing.set(q("line"), str(line))
    spacing.set(q("lineRule"), "auto")


def set_indentation(p: etree._Element, *, first_line: int | None = None, left: int | None = None) -> None:
    ppr = ensure_ppr(p)
    ind = ppr.find(q("ind"))
    if ind is None:
        ind = etree.SubElement(ppr, q("ind"))
    for attr in ("firstLine", "left", "hanging", "right"):
        ind.attrib.pop(q(attr), None)
    if first_line is not None:
        ind.set(q("firstLine"), str(first_line))
    if left is not None:
        ind.set(q("left"), str(left))


def set_alignment(p: etree._Element, value: str) -> None:
    ppr = ensure_ppr(p)
    jc = ppr.find(q("jc"))
    if jc is None:
        jc = etree.SubElement(ppr, q("jc"))
    jc.set(q("val"), value)


def add_keep_next(p: etree._Element) -> None:
    ppr = ensure_ppr(p)
    if ppr.find(q("keepNext")) is None:
        ppr.append(etree.Element(q("keepNext")))


def set_rfonts(rpr: etree._Element, *, east: str, latin: str = "Times New Roman") -> None:
    rfonts = rpr.find(q("rFonts"))
    if rfonts is None:
        rfonts = etree.Element(q("rFonts"))
        rpr.insert(0, rfonts)
    rfonts.set(q("hint"), "eastAsia")
    rfonts.set(q("ascii"), latin)
    rfonts.set(q("hAnsi"), latin)
    rfonts.set(q("eastAsia"), east)
    rfonts.set(q("cs"), east)


def set_run_properties(
    r: etree._Element,
    *,
    east: str,
    size_half_points: int,
    bold: bool = False,
    color: str = "000000",
    italic: bool = False,
) -> None:
    rpr = r.find(q("rPr"))
    if rpr is None:
        rpr = etree.Element(q("rPr"))
        r.insert(0, rpr)
    set_rfonts(rpr, east=east)
    for tag in ("sz", "szCs", "b", "bCs", "i", "iCs", "color"):
        for node in rpr.findall(q(tag)):
            rpr.remove(node)
    sz = etree.SubElement(rpr, q("sz"))
    sz.set(q("val"), str(size_half_points))
    szcs = etree.SubElement(rpr, q("szCs"))
    szcs.set(q("val"), str(size_half_points))
    if bold:
        etree.SubElement(rpr, q("b"))
        etree.SubElement(rpr, q("bCs"))
    if italic:
        etree.SubElement(rpr, q("i"))
        etree.SubElement(rpr, q("iCs"))
    color_node = etree.SubElement(rpr, q("color"))
    color_node.set(q("val"), color)


def clear_runs_and_content(p: etree._Element) -> None:
    ppr = p.find(q("pPr"))
    for child in list(p):
        if child is not ppr:
            p.remove(child)


def add_text_run(
    p: etree._Element,
    text: str,
    *,
    east: str = "宋体",
    size_half_points: int = 24,
    bold: bool = False,
    italic: bool = False,
) -> etree._Element:
    r = etree.SubElement(p, q("r"))
    set_run_properties(
        r,
        east=east,
        size_half_points=size_half_points,
        bold=bold,
        italic=italic,
    )
    t = etree.SubElement(r, q("t"))
    if text[:1].isspace() or text[-1:].isspace():
        t.set(f"{{{XML_NS}}}space", "preserve")
    t.text = text
    return r


def replace_text(
    p: etree._Element,
    text: str,
    *,
    style_id: str | None = None,
    kind: str = "body",
    alignment: str | None = None,
) -> None:
    clear_runs_and_content(p)
    if style_id:
        set_style(p, style_id)
    if kind == "h1":
        set_spacing(p, before=360, after=360, line=360)
        set_indentation(p)
        if alignment:
            set_alignment(p, alignment)
        add_keep_next(p)
        add_text_run(p, text, east="黑体", size_half_points=44, bold=True)
    elif kind == "h2":
        set_spacing(p, before=240, after=240, line=300)
        set_indentation(p)
        if alignment:
            set_alignment(p, alignment)
        add_keep_next(p)
        add_text_run(p, text, east="黑体", size_half_points=30, bold=True)
    elif kind == "h3":
        set_spacing(p, before=140, after=140, line=280)
        set_indentation(p)
        if alignment:
            set_alignment(p, alignment)
        add_keep_next(p)
        add_text_run(p, text, east="黑体", size_half_points=28, bold=True)
    elif kind == "h4":
        set_spacing(p, before=120, after=120, line=260)
        set_indentation(p)
        if alignment:
            set_alignment(p, alignment)
        add_keep_next(p)
        add_text_run(p, text, east="黑体", size_half_points=24, bold=True)
    elif kind == "caption":
        set_spacing(p, before=60, after=120, line=240)
        set_indentation(p)
        set_alignment(p, alignment or "center")
        add_text_run(p, text, east="宋体", size_half_points=21)
    elif kind == "toc":
        set_spacing(p, before=0, after=0, line=300)
        set_indentation(p, left=360 if style_id == "TOC2" else 0)
        set_alignment(p, "left")
        tabs = p.find(q("pPr")).find(q("tabs"))
        if tabs is None:
            tabs = etree.SubElement(p.find(q("pPr")), q("tabs"))
        else:
            for child in list(tabs):
                tabs.remove(child)
        tab = etree.SubElement(tabs, q("tab"))
        tab.set(q("val"), "right")
        tab.set(q("leader"), "dot")
        tab.set(q("pos"), "9355")
        label, page = text.split("\t", 1)
        add_text_run(p, label, east="宋体", size_half_points=24)
        etree.SubElement(p, q("r"))
        tab_run = p[-1]
        etree.SubElement(tab_run, q("tab"))
        add_text_run(p, page, east="宋体", size_half_points=24)
    else:
        set_spacing(p, before=0, after=0, line=360)
        set_indentation(p, first_line=480)
        add_text_run(p, text, east="宋体", size_half_points=24)


def new_paragraph(text: str, *, kind: str = "body", style_id: str | None = None) -> etree._Element:
    p = etree.Element(q("p"))
    replace_text(p, text, style_id=style_id, kind=kind)
    return p


def patch_heading_format(p: etree._Element, level: int, *, alignment: str | None = None) -> None:
    # This source document uses compact custom style IDs 1/2/3/4 for
    # heading 1/2/3/4 (the display names are Heading 1, Heading 2, ...).
    style_id = str(level)
    set_style(p, style_id)
    kind = {1: "h1", 2: "h2", 3: "h3", 4: "h4"}[level]
    set_spacing(
        p,
        before={1: 360, 2: 240, 3: 140, 4: 120}[level],
        after={1: 360, 2: 240, 3: 140, 4: 120}[level],
        line={1: 360, 2: 300, 3: 280, 4: 260}[level],
    )
    set_indentation(p)
    if alignment:
        set_alignment(p, alignment)
    add_keep_next(p)
    for r in p.findall(q("r")):
        set_run_properties(
            r,
            east="黑体",
            size_half_points={1: 44, 2: 30, 3: 28, 4: 24}[level],
            bold=True,
        )


def format_toc_title(p: etree._Element) -> None:
    replace_text(p, "目录", style_id="TOC1", kind="h1", alignment="center")


def make_toc_entry(label: str, page: str, level: int) -> etree._Element:
    return new_paragraph(
        f"{label}\t{page}",
        kind="toc",
        style_id="TOC2" if level == 2 else "TOC1",
    )


def find_paragraphs(body: etree._Element) -> list[etree._Element]:
    return [child for child in body if child.tag == q("p")]


def find_first(body: etree._Element, predicate) -> etree._Element:
    for p in find_paragraphs(body):
        if predicate(p):
            return p
    raise ValueError("target paragraph not found")


def remove_blank_paragraphs_between(body: etree._Element, start: etree._Element, end: etree._Element) -> None:
    children = list(body)
    start_i = children.index(start)
    end_i = children.index(end)
    for node in children[start_i + 1 : end_i]:
        if node.tag != q("p"):
            continue
        if text_of(node).strip():
            continue
        if node.xpath(".//w:drawing|.//w:pict|.//w:object", namespaces=NS):
            continue
        body.remove(node)


def insert_before(body: etree._Element, ref: etree._Element, paragraphs: list[etree._Element]) -> None:
    for p in paragraphs:
        ref.addprevious(p)


def section4_content() -> list[etree._Element]:
    items: list[etree._Element] = []

    def h(text: str) -> None:
        items.append(new_paragraph(text, kind="h2", style_id="2"))

    def b(text: str) -> None:
        items.append(new_paragraph(text, kind="body", style_id="a"))

    def fig(text: str) -> None:
        items.append(new_paragraph(text, kind="caption", style_id="a3"))

    h("4.1 平台总体架构与开发思路")
    b("仿真平台开发围绕“可视化建模—正式仿真—参数研究—智能优化—结果解释—任务追溯”这一主线展开。平台首先把光源、透镜组、光纤和环境条件组织为统一的光学工程，再根据同一份工程快照完成实时预览、正式物理计算和后续数据分析，避免教学界面、仿真界面与优化界面各自维护一套参数而产生结果不一致。")
    b("从系统结构看，平台由交互展示层、工程与任务管理层、物理计算层以及机器学习与解释层组成。交互展示层负责光学元件布置、参数输入和结果可视化；工程与任务管理层负责保存项目、调度计算、记录任务状态和管理结果版本；物理计算层依次完成 Gaussian/ABCD 解析估算、顺序光线追迹、公共出射面复场重建、数值传播和模式重叠计算；机器学习与解释层则对正式仿真结果进行建模、预测、优化和 SHAP 分析。各层通过统一的数据结构传递参数和结果，形成可复用的研究工作流。")
    fig("图4-1 平台总体架构与任务数据流（待补图）")
    b("平台开发时将实时预览与正式结果明确区分。实时预览用于帮助使用者理解光路和快速检查参数，允许在拖拽或输入坐标后即时观察光路变化；正式结果必须经过完整的光线追迹、复场传播、网格诊断和能量闭合检查，才能进入数据集、代理模型和优化结果库。这样的分工既保证交互响应速度，也避免把教学近似结果误当作定量研究结论。")

    h("4.2 工程参数与任务数据组织")
    b("平台以工程快照作为各模块共享的最小数据单元。快照中保存光源波长、束腰半径、束腰位置、质量因子和功率分布，保存每片透镜的面型、曲率半径、中心厚度、材料、有效孔径、位置和姿态，也保存光纤模场参数、端面位置、偏移与倾角，以及温度、气压、采样网格、传播距离和目标模式等计算条件。每个光学元件具有稳定的 component_id 和传播顺序，几何视图、物理计算和结果分析均从同一序列读取数据。")
    b("工程建立或修改后，平台先进行参数完整性和物理可行性检查，包括光轴方向、元件顺序、单位量纲、有效孔径、机械间距、材料数据和参数边界等。对于不满足约束的方案，界面给出明确提示，任务不会直接进入正式仿真。对于满足条件的方案，系统生成任务标识并保存输入快照、计算方法、网格设置和版本信息，使后续能够区分不同方案、重现同一计算并追踪结果来源。")
    b("任务结果按照“输入快照—计算状态—中间诊断—最终指标—可视化产物”的方式组织。中间诊断包括有效光线比例、边缘功率比例、网格收敛和能量闭合误差；最终指标至少区分模式耦合效率与系统总效率，并保留光斑、波前、光纤耦合和光路等结果。这样，优化模块读取的不是孤立的效率数字，而是带有物理条件、质量检查和来源信息的完整结果。")
    fig("图4-2 工程快照、任务状态与结果追溯关系（待补图）")

    h("4.3 正式仿真链路与数值实现")
    b("正式仿真采用从解析基线到复场结果的分级计算链。第一步用 Gaussian 光束和 ABCD/q 矩阵快速估计束腰位置、输出光斑和波前曲率，检查参数是否处于合理范围；第二步按照元件顺序进行几何光线追迹，记录光线位置、方向、光程、振幅权重和孔径截取；第三步在公共出射面将离散光线沉积到二维网格，重建同时包含振幅和相位的复场；第四步采用角谱法、带限角谱法或 Fresnel 方法将复场传播到光纤端面；第五步在相同坐标网格上构造 Gaussian、LP01 或 HE11 目标模式，并通过归一化复场重叠积分得到模式耦合效率。")
    b("数值实现中，平台对入射复场和目标模式使用统一的坐标原点、采样间隔、窗口范围和传播方向。传播前检查空间频率采样和窗口覆盖范围，传播后检查边缘功率比例、能量闭合误差和网格收敛趋势。只有当主要能量没有被窗口截断、采样条件满足传播方法要求且相邻网格结果趋于稳定时，结果才被标记为可用于定量分析的正式结果。")
    b("在正式计算中，平台同时输出光路图、光斑分布、光纤端面耦合结果以及波前与衍射分析。温度和气压等环境因素作为工程条件参与材料和传播计算，使结果能够反映理想模型与实际使用条件之间的差异。对于需要优化的参数，系统还把光斑半径、质心偏移、束腰位置、波前曲率、离焦量和能量诊断量保存为物理特征，为后续代理模型和可解释分析提供输入。")
    fig("图4-3 正式仿真计算链与结果诊断（待补图）")

    h("4.4 数据生成与智能分析集成")
    b("参数研究任务由工程快照派生参数样本，并按照设定的范围、步长或采样策略批量提交正式仿真。数据集支持使用平台内置数据、导入外部数据以及以仿真结果为基准自动生成三种来源。每个样本同时保存输入参数、模式耦合效率、系统总效率、物理特征和质量诊断，使训练数据能够回溯到具体工程和计算条件。")
    b("对于固定光学结构，随机森林和 XGBoost 用于建立结构参数与耦合性能之间的代理关系，并可将解析物理量作为特征或基线；对于元件数量和排列可变的结构，BiLSTM 将光学元件序列编码为模型输入。训练完成后，平台通过残差图、实测值与预测值对照、残差分布和验证误差曲线检查模型的拟合和泛化情况，合格模型才能进入模型预测模块，为优化提供高速近似计算。")
    b("优化模块在代理模型或正式仿真基础上完成全局搜索和局部精调，贝叶斯优化、差分进化和 Powell 分别承担候选区域探索、群体搜索和局部复核。优化候选必须满足参数边界、孔径、机械间距和准直等硬约束，并回到正式物理计算链进行复算。SHAP 模块进一步把模型贡献映射到尺寸失配、位置偏移、角度倾斜、轴向离焦和曲率失配等物理因素，形成“代理筛选—正式复核—物理解释”的闭环。")
    fig("图4-4 物理仿真、代理模型、优化和 SHAP 的闭环（待补图）")

    h("4.5 开发验证、封装与可复现性")
    b("平台验证分为物理计算验证、模块接口验证和界面交互验证三个层次。物理计算验证关注光线追迹、复场传播、模式重叠、光斑和波前结果是否满足理论关系；模块接口验证关注教学、仿真、建模、优化和解释之间的数据是否能够正确传递；界面交互验证关注拖拽布置、坐标编辑、任务提交、结果切换和参数回写是否与工程快照一致。")
    b("在封装和交付时，平台保留内置四透镜标杆工程、数据集和可复用的任务流程，使用者可以从首页直接进入教学示例，也可以从仿真工程生成建模数据。每次任务保存参数、模型、约束、结果和版本信息，必要时可以重新加载快照进行复算。该机制使平台既能用于课堂演示，也能用于参数研究和实验前的虚拟装调。")
    b("本章中的结构图和流程图用于说明平台内部开发逻辑；第 5 章中的界面截图用于说明平台实际功能。正式提交前，建议将标有“待补图”的位置替换为平台截图或绘制的流程图，并保留图号与题注格式。")

    return items


def section5_content() -> list[etree._Element]:
    items: list[etree._Element] = []

    def h(text: str) -> None:
        items.append(new_paragraph(text, kind="h2", style_id="2"))

    def b(text: str) -> None:
        items.append(new_paragraph(text, kind="body", style_id="a"))

    def fig(text: str) -> None:
        items.append(new_paragraph(text, kind="caption", style_id="a3"))

    h("5.1 功能区总览")
    b("打开平台后首先进入首页。首页中央以“光学研究工作流”为主题，用五张功能卡片概括平台的主要研究环节：教学、仿真、模型、优化和解释。五个功能区既是功能说明，也是快捷入口；点击卡片中的子功能按钮，可以直接跳转到对应模块的相应环节，使用者不需要先熟悉复杂的菜单层级即可定位任务。")
    b("五个功能区之间按照研究流程形成联动关系。教学区帮助使用者理解光路结构和器件作用；仿真区负责建立工程、提交正式计算并查看光学结果；模型区负责生成数据、训练代理模型和进行快速预测；优化区根据目标筛选参数组合并把候选方案回写工程；解释区利用 SHAP 和物理分析说明模型为什么给出当前判断。整个过程中，平台保留任务状态和工程快照，并支持在需要时调用 AI 进行概念讲解、结果说明和操作建议。")
    fig("图5-1 首页“光学研究工作流”五大功能区总览（待截图）")

    h("5.2 教学模块")
    b("进入教学模块后，界面显示一张空白的光学桌面和器材区。使用者可以将激光器、透镜和光纤拖入桌面，组成一条基础光路；点击成像与耦合更新后，平台即时显示接收面光斑和耦合效率。点击器件可以查看当前位置、姿态和参数，也可以直接输入坐标与朝向进行精确设定。拖拽操作适合建立直观认识，坐标输入适合进行精细调整，工业常用规格则降低了初始建模的门槛。")
    b("教学桌面支持清空场景、重置视角和重新加载标准案例。调用内置四透镜耦合模型后，使用者可以观察四片透镜的排布、光线逐片偏折以及最终会聚进入光纤的过程。教学模块还可与仿真工程同步，使同一套器件位置、波长和光纤模场参数能够从教学演示延伸到正式仿真。")
    fig("图5-2 教学模块中的器材拖拽、四透镜模型和即时耦合结果（待截图）")

    h("5.3 建模模块")
    b("建模模块支持按照元件参数建模，也支持按照镜头采样组织数据。数据来源包括平台内置数据集、外部导入数据集和由仿真数据自动生成的数据集。以仿真数据为基准生成数据时，平台将工程参数研究与建模过程衔接起来，使每个训练样本都能够对应到物理仿真输入和输出。")
    b("点击开始联合训练后，平台输出残差图、实测值与预测值对照、残差分布和验证误差曲线。四类视图分别用于观察单样本误差、预测与真实结果的一致性、误差是否存在系统性偏差以及训练过程是否收敛充分。训练完成的模型可在模型预测模块中直接使用，输入新的参数组合即可快速得到预测结果，为参数扫描和优化提供高速近似计算。")
    fig("图5-3 建模模块的数据源选择与联合训练结果（待截图）")

    h("5.4 优化模块")
    b("进入优化模块后，使用者在参数列表中勾选需要优化的变量，设定目标指标和约束条件，再启动优化任务。优化过程中，界面实时显示目标指标的收敛曲线，并通过候选方案对照表呈现不同参数组合的性能、约束状态和复核结果。")
    b("优化完成后，界面顶部生成多个可比较的方案。使用者选择方案后，可以将其直接应用到当前工程，优化参数随即回写到系统。除多变量优化外，平台还提供参数扫描功能，可以固定其他条件，观察耦合效率随某一个参数变化的趋势，为判断局部最优、敏感区间和后续实验取值提供依据。")
    fig("图5-4 优化模块的收敛曲线与候选方案列表（待截图）")

    h("5.5 SHAP 解释模块")
    b("为解释模型预测和优化结果背后的依据，平台提供 SHAP 解释模块。使用者选择已经训练的模型并发起分析后，平台输出全局特征重要性排名、蜂群图、特征依赖网格图、单变量依赖趋势图、物理一致性图和瀑布图。全局视图用于判断哪些参数在整体样本中最重要，局部视图用于解释某一个候选方案的预测值由哪些参数共同形成。")
    b("对于贡献度较高的参数，平台进一步给出对应的物理解释，将统计结论与光斑尺寸、焦面位置、波前曲率、横向偏移或轴向离焦等光学量联系起来。SHAP 结果不被单独当作因果证明，而是与单变量扫描、解析公式和正式物理复算交叉检查；只有当模型解释与光学规律基本一致时，才把它作为参数筛选和实验设计的依据。")
    fig("图5-5 SHAP 解释模块的特征重要性与物理一致性视图（待截图）")

    h("5.6 仿真模块")
    b("仿真模块用于对当前工程或优化方案进行正式物理验证。除理想光学参数外，平台还允许设置温度和气压等环境条件，以反映材料性能和传播状态在真实环境中的变化。透镜位置、镜间距、曲率半径、厚度、有效孔径和光纤端面位置等参数均可在工程中调整，并在提交任务前经过边界和可行性检查。")
    b("使用者可以直接调用优化模块得到的参数，点击运行按钮提交仿真。计算完成后，平台依次展示光路图、光斑图、光纤耦合结果以及波前与衍射分析：光路图用于观察光线在四片透镜之间的传播和会聚，光斑图用于查看尺寸、形状与能量分布，耦合结果用于判断入射场与目标模式的匹配程度，波前与衍射分析则用于评价光束质量和相位传播状态。")
    b("仿真结果与工程快照绑定，使用者可以在不同结果文档之间切换，也可以返回参数页面修改方案后重新计算。正式仿真结果是建模、优化和 SHAP 分析的物理依据；当代理模型提出候选方案时，平台仍要求回到仿真模块进行独立复核。")
    fig("图5-6 仿真模块的光路、光斑、耦合及波前分析结果（待截图）")

    h("5.7 模块联动与 AI 辅助")
    b("平台的功能区不是相互独立的页面，而是围绕同一工程快照形成连续链路。教学模块可以从器材布置开始建立直观光路，仿真模块将其转化为正式计算，建模模块把仿真结果组织为数据集，优化模块从模型和正式结果中筛选参数，解释模块再将结果还原为可理解的物理原因。任一环节产生的参数、结果和状态都可回溯到对应任务，便于重复计算和实验前检查。")
    b("在各模块中，AI 可用于解释公式、说明界面指标、提示参数之间的关系和给出下一步操作建议，但不替代光学计算、约束检查和正式复算。涉及最终结论时，仍以工程快照、正式仿真结果、独立实验对比和结果版本记录为准。正式提交前，建议将本节六张界面截图替换到对应题注上方，并删除题注中的“待截图”字样。")

    return items


def update_headings(body: etree._Element) -> None:
    chapter_texts = {
        "1引言",
        "2物理模型与理论研究",
        "3机器学习与寻优算法",
        "4仿真平台开发",
        "5平台功能介绍",
        "6 实验验证",
        "7总结及展望",
        "8团队成员贡献",
        "9参考文献",
        "附录",
    }
    centered_h1 = {"激光耦合仿真系统及智能优化平台", "摘要", "Abstract", "研究报告", "目录"}
    for p in find_paragraphs(body):
        t = text_of(p).strip()
        current = style_of(p)
        if t in chapter_texts or current == "1":
            if t in centered_h1 or t == "目录":
                patch_heading_format(p, 1, alignment="center")
            else:
                patch_heading_format(p, 1)
        elif current in {"2", "3", "4"}:
            level = int(current[-1])
            if current == "4" and t.startswith(("3.2.1", "3.2.2", "3.3.1", "3.4.1", "3.4.2")):
                level = 3
            if t.startswith(("附录A", "附录B", "附录C")):
                level = 2
            patch_heading_format(p, level)
        elif t.startswith(("1.1", "1.2")) and len(t) < 40:
            patch_heading_format(p, 2)
    # The title and front-matter headings are already marked as Heading 1 in the source;
    # the loop above also brings their direct formatting in line with 格式.docx.


def rebuild_toc(body: etree._Element, pages: dict[str, str]) -> None:
    title = find_first(body, lambda p: text_of(p).strip() == "目录")
    format_toc_title(title)
    children = list(body)
    title_i = children.index(title)
    toc_end = None
    for node in children[title_i + 1 :]:
        if node.tag == q("p") and node.find(q("pPr")) is not None and node.find(q("pPr")).find(q("sectPr")) is not None:
            toc_end = node
            break
    if toc_end is None:
        raise ValueError("TOC section boundary not found")
    for node in children[title_i + 1 : children.index(toc_end)]:
        if node.tag == q("p"):
            body.remove(node)

    entries = [
        ("摘要", "I", 2),
        ("Abstract", "II", 1),
        ("1 引言", pages.get("1引言", "1"), 1),
        ("1.1 选题意义", pages.get("1.1选题意义", "1"), 2),
        ("1.2 目标定位", pages.get("1.2目标定位", "2"), 2),
        ("2 物理模型与理论研究", pages.get("2物理模型与理论研究", "3"), 1),
        ("3 机器学习与寻优算法", pages.get("3机器学习与寻优算法", "11"), 1),
        ("4 仿真平台开发", pages.get("4 仿真平台开发", "--"), 1),
        ("4.1 平台总体架构与开发思路", pages.get("4.1 平台总体架构与开发思路", "--"), 2),
        ("4.2 工程参数与任务数据组织", pages.get("4.2 工程参数与任务数据组织", "--"), 2),
        ("4.3 正式仿真链路与数值实现", pages.get("4.3 正式仿真链路与数值实现", "--"), 2),
        ("4.4 数据生成与智能分析集成", pages.get("4.4 数据生成与智能分析集成", "--"), 2),
        ("4.5 开发验证、封装与可复现性", pages.get("4.5 开发验证、封装与可复现性", "--"), 2),
        ("5 平台功能介绍", pages.get("5 平台功能介绍", "--"), 1),
        ("5.1 功能区总览", pages.get("5.1 功能区总览", "--"), 2),
        ("5.2 教学模块", pages.get("5.2 教学模块", "--"), 2),
        ("5.3 建模模块", pages.get("5.3 建模模块", "--"), 2),
        ("5.4 优化模块", pages.get("5.4 优化模块", "--"), 2),
        ("5.5 SHAP 解释模块", pages.get("5.5 SHAP 解释模块", "--"), 2),
        ("5.6 仿真模块", pages.get("5.6 仿真模块", "--"), 2),
        ("5.7 模块联动与 AI 辅助", pages.get("5.7 模块联动与 AI 辅助", "--"), 2),
        ("6 实验验证", pages.get("6 实验验证", "--"), 1),
        ("7 总结及展望", pages.get("7总结及展望", "--"), 1),
        ("8 团队成员贡献", pages.get("8团队成员贡献", "--"), 1),
        ("9 参考文献", pages.get("9参考文献", "--"), 1),
        ("附录", pages.get("附录", "--"), 1),
    ]
    for label, page, level in entries:
        toc_end.addprevious(make_toc_entry(label, page, level))


def update_fields(settings_xml: bytes) -> bytes:
    root = etree.fromstring(settings_xml)
    node = root.find(q("updateFields"))
    if node is None:
        node = etree.SubElement(root, q("updateFields"))
    node.set(q("val"), "true")
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def patch_document_xml(document_xml: bytes, toc_pages: dict[str, str]) -> bytes:
    root = etree.fromstring(document_xml)
    body = root.find(q("body"))
    if body is None:
        raise ValueError("document body missing")

    p4 = find_first(body, lambda p: text_of(p).strip().replace(" ", "") == "4仿真平台开发")
    p5 = find_first(body, lambda p: text_of(p).strip().replace(" ", "") == "5平台功能介绍")
    # The static TOC also contains a line beginning with 6; select the real
    # chapter heading by its source heading style, not by text alone.
    p6 = find_first(
        body,
        lambda p: style_of(p) == "1"
        and text_of(p).strip().startswith("6")
        and "实验验证" in text_of(p),
    )

    replace_text(p4, "4 仿真平台开发", style_id="1", kind="h1")
    replace_text(p5, "5 平台功能介绍", style_id="1", kind="h1")

    remove_blank_paragraphs_between(body, p4, p5)
    remove_blank_paragraphs_between(body, p5, p6)
    insert_before(body, p5, section4_content())
    insert_before(body, p6, section5_content())

    update_headings(body)
    rebuild_toc(body, toc_pages)
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def patch_package(source: Path, output: Path, toc_pages: dict[str, str]) -> None:
    with zipfile.ZipFile(source, "r") as zin:
        document_xml = zin.read("word/document.xml")
        settings_xml = zin.read("word/settings.xml") if "word/settings.xml" in zin.namelist() else None
        patched_document = patch_document_xml(document_xml, toc_pages)
        patched_settings = update_fields(settings_xml) if settings_xml is not None else None
        output.parent.mkdir(parents=True, exist_ok=True)
        temp = output.with_suffix(output.suffix + ".tmp")
        if temp.exists():
            temp.unlink()
        with zipfile.ZipFile(temp, "w") as zout:
            for info in zin.infolist():
                data = zin.read(info.filename)
                if info.filename == "word/document.xml":
                    data = patched_document
                elif info.filename == "word/settings.xml" and patched_settings is not None:
                    data = patched_settings
                zout.writestr(info, data)
        os.replace(temp, output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--toc-pages-json", type=Path)
    parser.add_argument("--toc-pages-json-text")
    args = parser.parse_args()
    pages: dict[str, str] = {}
    if args.toc_pages_json and args.toc_pages_json.exists():
        pages = json.loads(args.toc_pages_json.read_text(encoding="utf-8"))
    if args.toc_pages_json_text:
        pages = json.loads(args.toc_pages_json_text)
    patch_package(args.source, args.output, pages)
    print(args.output)


if __name__ == "__main__":
    main()

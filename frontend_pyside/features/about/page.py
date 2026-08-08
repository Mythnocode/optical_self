from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSplitter,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from frontend_pyside.shared.components.basic import (
    Card,
    FeatureCard,
    InfoRow,
    MetricCard,
    PageHeader,
    PageScrollArea,
    SectionTitle,
    SummaryStrip,
)
from frontend_pyside.shared.components.tables import DataTable
from frontend_pyside.shared.components.navigation import CollapsibleSectionNavigator, SectionItem


class AboutPage(QWidget):
    def __init__(self, context, parent=None):
        super().__init__(parent)
        self.context = context
        self.sections = self._section_content()

        content = QWidget()
        root = QVBoxLayout(content)
        root.setContentsMargins(20, 14, 20, 20)
        root.setSpacing(9)
        root.addWidget(
            PageHeader(
                "平台介绍",
                "从光学系统建模、复场传播和光纤耦合，到参数优化、机器学习、模型解释与教学实验的一体化桌面平台。",
            )
        )
        root.addWidget(
            SummaryStrip(
                [
                    ("定位", "科研仿真 + 智能优化 + 教学"),
                    ("前端", "PySide6 模块化桌面端"),
                    ("正式计算", "FastAPI / optical_runtime"),
                    ("教学计算", "本地解析近似"),
                    ("结果管理", "项目、任务、数据集、模型分层"),
                ]
            )
        )

        metric_row = QHBoxLayout()
        metric_row.setSpacing(8)
        for title, value, unit, note in [
            ("业务模块", "7", "个", "仿真、优化、ML、解释、教学等"),
            ("教学课程", "4", "个", "Gaussian、光纤、耦合、PSF"),
            ("结果工作区", "5", "类", "光路、几何、成像、耦合、诊断"),
            ("解释层次", "4", "层", "SHAP、公式、一致性、报告"),
            ("计算边界", "2", "层", "正式后端与教学近似分离"),
        ]:
            metric_row.addWidget(MetricCard(title, value, unit, note=note))
        root.addLayout(metric_row)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        section_icons = ["overview", "function", "workflow", "guide", "advantage", "application"]
        self.nav = CollapsibleSectionNavigator(
            [SectionItem(text, section_icons[index]) for index, text in enumerate(self.sections)],
            expanded_width=242,
            collapsed_width=56,
        )
        splitter.addWidget(self.nav)

        self.detail = QWidget()
        self.detail_layout = QVBoxLayout(self.detail)
        self.detail_layout.setContentsMargins(0, 0, 0, 0)
        self.detail_layout.setSpacing(8)
        splitter.addWidget(self.detail)
        splitter.setSizes([242, 1180])
        root.addWidget(splitter, 1)

        scroll = PageScrollArea(content)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        self.nav.currentRowChanged.connect(self._render_section)
        self.nav.setCurrentRow(0)

    def _clear_detail(self):
        while self.detail_layout.count():
            item = self.detail_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                while item.layout().count():
                    child = item.layout().takeAt(0)
                    if child.widget():
                        child.widget().deleteLater()

    def _render_section(self, index: int):
        self._clear_detail()
        if not 0 <= index < len(self.sections):
            return
        title = list(self.sections)[index]
        section = self.sections[title]
        self.detail_layout.addWidget(SectionTitle(title))
        intro = Card("本节概览", compact=True)
        text = QLabel(section["intro"])
        text.setWordWrap(True)
        intro.body.addWidget(text)
        self.detail_layout.addWidget(intro)

        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        for i, item in enumerate(section["cards"]):
            card = FeatureCard(
                item[0],
                item[1],
                details=item[2],
                status=item[3],
                button_text="查看要点",
            )
            grid.addWidget(card, i // 3, i % 3)
        self.detail_layout.addLayout(grid)

        table_card = Card(section["table_title"], compact=True)
        rows = section["table"]
        table = DataTable(len(rows), len(rows[0]))
        table.setHorizontalHeaderLabels(rows[0])
        table.setRowCount(len(rows) - 1)
        for r, row in enumerate(rows[1:]):
            for c, value in enumerate(row):
                table.setItem(r, c, QTableWidgetItem(value))
        table.stretch_columns(max(0, len(rows[0]) - 1))
        table_card.body.addWidget(table)
        self.detail_layout.addWidget(table_card)

        note = Card("设计原则与边界", compact=True)
        for label, value in section["notes"]:
            note.body.addWidget(InfoRow(label, value))
        self.detail_layout.addWidget(note)
        self.detail_layout.addStretch()

    @staticmethod
    def _section_content():
        return {
            "系统概览": {
                "intro": "平台围绕同一个当前项目组织建模、正式仿真、参数规律研究、传统优化、机器学习代理建模、模型解释和教学实验，减少数据重复录入和页面之间的状态割裂。",
                "cards": [
                    ("统一项目上下文", "波长、光源、光学表面、接收器和版本在各业务模块间共享。", ["项目版本", "参数快照", "结果来源"], "核心"),
                    ("多结果工作区", "单图、双图、四宫格和最大化模式适应不同分析任务。", ["固定结果", "预设组合", "来源标记"], "可用"),
                    ("任务与资产分层", "临时任务、正式结果、数据集、模型和报告使用不同生命周期。", ["任务中心", "版本追踪", "结果复用"], "可扩展"),
                ],
                "table_title": "平台层级",
                "table": [
                    ["层级", "主要职责", "典型内容"],
                    ["桌面前端", "输入、工作流、展示", "PySide6 页面、图表、状态管理"],
                    ["应用后端", "正式任务编排", "仿真、训练、优化、解释接口"],
                    ["计算运行时", "数值计算", "optical_runtime、optical_core、机器学习"],
                    ["教学运行时", "即时近似教学", "解析公式、规律扫描、评分和报告"],
                ],
                "notes": [("设计目标", "专业、紧凑、可扩展、可追溯"), ("当前边界", "教学近似不替代正式研究仿真")],
            },
            "核心功能": {
                "intro": "功能按照用户真实研究阶段划分，每个页面只承担独有职责，避免在不同页面重复编辑完整光学系统。",
                "cards": [
                    ("仿真系统", "编辑多透镜系统并查看几何、成像、耦合和诊断结果。", ["光路", "PSF/MTF", "复场与耦合"], "核心"),
                    ("参数研究与优化", "先理解参数规律，再寻找满足约束的候选解。", ["扫描", "自动调参", "前后对比"], "核心"),
                    ("机器学习与解释", "生成数据、训练代理模型并用 SHAP 和公式解释。", ["数据集", "模型", "一致性验证"], "需后端"),
                    ("教学中心", "用预测、操作、记录、诊断和报告形成学习闭环。", ["4 个课程", "本地近似", "自动评分"], "本地可用"),
                ],
                "table_title": "功能职责边界",
                "table": [
                    ["模块", "回答的问题", "主要输出"],
                    ["仿真系统", "当前系统表现如何", "光路、场、PSF、MTF、耦合、诊断"],
                    ["参数遍历", "参数变化有什么规律", "曲线、热图、敏感度、最佳区域"],
                    ["自动调参", "哪组参数更优", "收敛曲线、最优参数、约束状态"],
                    ["模型解释", "模型为什么这样预测", "SHAP、公式贡献、一致性报告"],
                ],
                "notes": [("页面原则", "同一参数只在一个主编辑器中维护"), ("结果原则", "所有图表标记来源和精度")],
            },
            "技术链路": {
                "intro": "正式研究链路从输入参数开始，经几何与波动光学计算得到接收面复场，再与光纤模式进行重叠，最后开展参数研究、优化和代理建模。",
                "cards": [
                    ("几何链路", "材料、表面、光阑和光线状态共同决定几何传播。", ["折射", "OPL", "最佳焦面"], "正式后端"),
                    ("波动链路", "公共 Cartesian 出瞳复场通过传播算法到达接收面。", ["角谱", "Fresnel", "采样诊断"], "正式后端"),
                    ("耦合链路", "接收面复场与单模光纤模式执行归一化复场重叠。", ["振幅", "相位", "偏移/倾斜"], "正式后端"),
                ],
                "table_title": "数据在链路中的流动",
                "table": [
                    ["阶段", "输入", "输出"],
                    ["系统编译", "项目参数", "正式仿真请求"],
                    ["几何追迹", "光线与曲面", "落点、方向、状态、OPL"],
                    ["复场传播", "出瞳复振幅", "接收面复场与诊断"],
                    ["模式重叠", "光束场与光纤模式", "效率与损失分解"],
                ],
                "notes": [("Zemax 定位", "仅作为对比验证，不进入本征仿真数据"), ("可信度", "边缘功率、能量闭合和收敛检查优先于正式结论")],
            },
            "典型工作流": {
                "intro": "平台强调从建模到正式复核的闭环，而不是只输出一个数值。每一步都保留版本、任务和结果来源。",
                "cards": [
                    ("研究主流程", "建模 → 仿真 → 扫描 → 优化 → 正式复核。", ["项目版本", "候选方案", "质量审计"], "推荐"),
                    ("机器学习流程", "数据生成 → 训练 → 候选搜索 → 正式复核。", ["数据契约", "模型版本", "Top-K"], "需后端"),
                    ("教学流程", "预测 → 操作 → 记录 → 规律探索 → 评分 → 报告。", ["本地近似", "即时反馈", "适用条件"], "本地可用"),
                ],
                "table_title": "工作流关键闸门",
                "table": [
                    ["闸门", "通过条件", "未通过时处理"],
                    ["参数完整性", "单位、范围、对象有效", "阻止提交并定位字段"],
                    ["数值可信度", "采样、边缘功率、能量闭合通过", "扩大窗口或提升采样"],
                    ["优化候选", "约束满足且正式复核通过", "回到扫描或优化阶段"],
                    ["代理模型", "误差达标且适用域覆盖", "补充数据并重新训练"],
                ],
                "notes": [("快捷入口", "首页只负责继续工作，不承担完整编辑"), ("长任务", "统一进入任务中心")],
            },
            "技术优势": {
                "intro": "软件的优势不是单独的某个算法，而是完整的物理链路、统一的数据语义、可追溯的结果来源和从规律研究到智能优化的闭环。",
                "cards": [
                    ("物理链完整", "从几何光学到复场、成像和光纤耦合使用统一项目。", ["几何", "波动", "模式"], "优势"),
                    ("结果可解释", "将 SHAP、解析公式、局部灵敏度和失效条件组合。", ["黑箱解释", "白箱公式", "一致性"], "优势"),
                    ("教学与科研分层", "教学近似追求直观，正式后端追求可信和可追溯。", ["边界明确", "接口预留", "避免混用"], "优势"),
                ],
                "table_title": "平台优势与证据",
                "table": [
                    ["优势", "具体实现", "用户价值"],
                    ["模块化", "页面、工作流、绘图、布局、组件分离", "修改范围可控"],
                    ["多结果分析", "单图/双图/四宫格/最大化", "减少页面跳转"],
                    ["统一项目", "跨页面共享项目快照", "避免重复录入"],
                    ["近似与正式分层", "来源徽章和独立运行时", "防止教学结果误用"],
                ],
                "notes": [("工程价值", "适合持续增加算法和实验模块"), ("答辩价值", "技术链和优势可直接从介绍页展示")],
            },
            "应用场景": {
                "intro": "平台既能承载光纤耦合与复场传播的研究主线，也能扩展到一般成像系统、激光光束、参数灵敏度分析和大学物理实验教学。",
                "cards": [
                    ("单模光纤耦合", "研究模式匹配、五轴误差和自动对准。", ["偏移", "倾斜", "离焦"], "重点"),
                    ("激光与成像系统", "分析 Gaussian 传播、PSF、MTF、像差和最佳焦面。", ["束腰", "波前", "成像质量"], "适用"),
                    ("光学教学", "开展 Gaussian、光纤、耦合、Airy/PSF 等交互实验。", ["预测", "扫描", "报告"], "适用"),
                ],
                "table_title": "典型用户与任务",
                "table": [
                    ["用户", "典型任务", "主要页面"],
                    ["光学研究者", "建立系统、复场传播、耦合与优化", "仿真、优化"],
                    ["算法研究者", "代理建模、候选搜索、模型解释", "机器学习、模型解释"],
                    ["教师", "课堂演示、实验任务和报告", "教学中心"],
                    ["学生", "预测规律、操作参数、记录结论", "教学中心、理论资源"],
                ],
                "notes": [("扩展方向", "牛顿环、干涉、衍射、偏振等经典实验"), ("使用提醒", "教学结果不作为工程定量结论")],
            },
        }

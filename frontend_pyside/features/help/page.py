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
    Badge,
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


class HelpPage(QWidget):
    def __init__(self, context, parent=None):
        super().__init__(parent)
        content = QWidget()
        root = QVBoxLayout(content)
        root.setContentsMargins(20, 14, 20, 20)
        root.setSpacing(9)
        root.addWidget(
            PageHeader(
                "使用指南",
                "按研究阶段使用平台，并始终区分前端预览、教学近似和后端正式结果。",
            )
        )
        root.addWidget(
            SummaryStrip(
                [
                    ("推荐起点", "首页 → 仿真系统"),
                    ("正式结果", "必须由后端任务生成"),
                    ("教学中心", "本地解析近似"),
                    ("长任务", "任务中心统一管理"),
                    ("问题定位", "先看状态栏与来源徽章"),
                ]
            )
        )

        metrics = QHBoxLayout()
        metrics.setSpacing(8)
        for title, value, unit, note in [
            ("上手步骤", "5", "步", "建模到正式复核"),
            ("主要页面", "8", "个", "业务职责独立"),
            ("结果来源", "3", "类", "预览、教学、正式"),
            ("常见检查", "4", "项", "窗口、网格、能量、收敛"),
            ("帮助主题", "6", "组", "快速开始到故障排查"),
        ]:
            metrics.addWidget(MetricCard(title, value, unit, note=note))
        root.addLayout(metrics)

        tabs = QSplitter(Qt.Orientation.Horizontal)
        nav = CollapsibleSectionNavigator(
            [
                SectionItem("快速开始", "guide"),
                SectionItem("页面职责", "overview"),
                SectionItem("结果来源", "result"),
                SectionItem("正式工作流", "workflow"),
                SectionItem("教学中心", "teaching"),
                SectionItem("故障排查", "warning"),
            ],
            expanded_width=242,
            collapsed_width=56,
        )
        tabs.addWidget(nav)
        self.content_stack = QWidget()
        self.content_layout = QVBoxLayout(self.content_stack)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(8)
        tabs.addWidget(self.content_stack)
        tabs.setSizes([242, 1180])
        root.addWidget(tabs, 1)

        scroll = PageScrollArea(content)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        nav.currentRowChanged.connect(self._render)
        nav.setCurrentRow(0)

    def _clear(self):
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                while item.layout().count():
                    child = item.layout().takeAt(0)
                    if child.widget():
                        child.widget().deleteLater()

    def _render(self, index: int):
        self._clear()
        renderers = [
            self._quick_start,
            self._page_roles,
            self._result_sources,
            self._formal_workflow,
            self._teaching,
            self._troubleshooting,
        ]
        if 0 <= index < len(renderers):
            renderers[index]()
        self.content_layout.addStretch()

    def _quick_start(self):
        self.content_layout.addWidget(SectionTitle("五步完成一次完整研究流程"))
        grid = QGridLayout()
        steps = [
            ("1　建立项目", "在仿真系统中设置波长、光源、多透镜表面、接收器和计算设置。", ["检查单位", "保存版本"], "起点"),
            ("2　快速预览", "使用前端预览检查布局、趋势和参数是否明显错误。", ["非正式结果", "即时反馈"], "预览"),
            ("3　研究规律", "在参数遍历中观察一维/二维趋势并确定高效区域。", ["曲线", "热图", "敏感度"], "分析"),
            ("4　寻找候选", "自动调参在约束内搜索候选解，并保存优化前后参数。", ["目标函数", "约束", "收敛"], "优化"),
            ("5　正式复核", "提交后端正式仿真，检查采样、边缘功率、能量闭合和收敛。", ["正式来源", "质量闸门"], "必须"),
        ]
        for i, step in enumerate(steps):
            grid.addWidget(FeatureCard(*step[:2], details=step[2], status=step[3], button_text="查看"), i // 3, i % 3)
        self.content_layout.addLayout(grid)
        card = Card("开始前检查", compact=True)
        for label, value, status, tone in [
            ("当前项目", "确认名称、版本和波长正确", "必查", "warning"),
            ("参数单位", "长度、角度、NA、功率单位一致", "必查", "warning"),
            ("计算来源", "预览与正式结果不能混用", "重要", "danger"),
            ("保存策略", "重要修改前创建新项目版本", "推荐", "info"),
        ]:
            card.body.addWidget(InfoRow(label, value, status, tone))
        self.content_layout.addWidget(card)

    def _page_roles(self):
        self.content_layout.addWidget(SectionTitle("各页面只处理自己的业务职责"))
        rows = [
            ["页面", "主要用途", "不要在这里做什么", "输出"],
            ["首页", "项目概览、快捷入口和警告摘要", "编辑完整表面参数", "当前状态"],
            ["仿真系统", "建立系统并查看物理结果", "训练机器学习模型", "光路、场、成像、耦合"],
            ["参数研究与优化", "研究规律和寻找候选解", "复制一套完整系统编辑器", "扫描与优化结果"],
            ["机器学习", "数据集、训练、模型、代理搜索", "替代正式物理复核", "模型和候选方案"],
            ["模型解释", "SHAP、公式和一致性验证", "重新训练模型", "解释报告"],
            ["教学中心", "理解物理规律和完成实验闭环", "生成工程定量结论", "教学记录与报告"],
            ["任务中心", "查看长任务、日志和结果入口", "修改光学参数", "任务状态"],
        ]
        self._add_table("页面职责速查", rows)

    def _result_sources(self):
        self.content_layout.addWidget(SectionTitle("先看来源徽章，再解读结果"))
        grid = QGridLayout()
        sources = [
            ("前端快速预览", "用于检查布局、交互和趋势，不包含完整正式数值诊断。", ["即时", "轻量", "不可作为论文数据"], "预览"),
            ("教学近似", "由本地解析公式和简化模型计算，强调主要物理规律。", ["适用条件", "即时动画", "不可替代工程仿真"], "教学"),
            ("后端正式结果", "由正式仿真、优化或训练任务生成，包含任务与质量信息。", ["可追溯", "可复核", "正式来源"], "正式"),
        ]
        for i, source in enumerate(sources):
            grid.addWidget(FeatureCard(source[0], source[1], details=source[2], status=source[3], button_text="了解"), 0, i)
        self.content_layout.addLayout(grid)
        card = Card("正式结果最低检查项", compact=True)
        card.body.addWidget(InfoRow("接收窗口", "边缘功率建议低于设定阈值，防止能量被窗口截断"))
        card.body.addWidget(InfoRow("网格采样", "比较多个网格规模，确认目标指标已收敛"))
        card.body.addWidget(InfoRow("光瞳采样", "比较不同光瞳点数，排除离散误差"))
        card.body.addWidget(InfoRow("能量闭合", "输入、透射、吸收、截断和接收功率应可解释"))
        self.content_layout.addWidget(card)

    def _formal_workflow(self):
        self.content_layout.addWidget(SectionTitle("正式工作流与质量闸门"))
        rows = [
            ["阶段", "操作", "判断标准", "下一步"],
            ["系统建模", "完成表面、光源、接收器和全局参数", "无非法参数或缺失单位", "保存项目版本"],
            ["预览检查", "查看光路、点列、PSF 和 MTF", "无明显截断或异常趋势", "提交正式仿真"],
            ["正式计算", "运行完整几何与波动链路", "任务完成且无关键告警", "进行质量审计"],
            ["质量审计", "检查边缘功率、闭合和收敛", "全部通过预设阈值", "生成正式结果"],
            ["优化复核", "将候选参数重新正式计算", "收益真实且约束满足", "应用或另存方案"],
        ]
        self._add_table("正式计算步骤", rows)
        note = Card("重要提醒", compact=True)
        note.body.addWidget(InfoRow("候选解", "扫描或优化得到的是候选参数，不能跳过正式仿真复核", "必须复核", "danger"))
        note.body.addWidget(InfoRow("Zemax 数据", "仅用于对比验证，不进入本征仿真输入链路", "隔离", "warning"))
        self.content_layout.addWidget(note)

    def _teaching(self):
        self.content_layout.addWidget(SectionTitle("教学中心使用规则"))
        grid = QGridLayout()
        for i, item in enumerate([
            ("课程目录", "先选择 Gaussian、光纤、耦合或 PSF/像差课程。", ["学习目标", "难度", "进度"], "步骤 1"),
            ("实验工作台", "完成预测、调参、观察、记录、规律探索和方案比较。", ["即时曲线", "公式解释", "数据记录"], "步骤 2"),
            ("评分与报告", "填写结论、查看评分并导出 Markdown/CSV/JSON。", ["过程记录", "自动评分", "适用条件"], "步骤 3"),
        ]):
            grid.addWidget(FeatureCard(item[0], item[1], details=item[2], status=item[3], button_text="查看"), 0, i)
        self.content_layout.addLayout(grid)
        card = Card("教学近似边界", compact=True)
        card.body.addWidget(InfoRow("计算方式", "当前全部由本地 teaching_runtime 解析近似计算", "本地", "info"))
        card.body.addWidget(InfoRow("适用用途", "课堂演示、规律理解、预测验证和实验报告", "适用", "success"))
        card.body.addWidget(InfoRow("不适用用途", "正式工程设计、论文定量数据和复杂多透镜复场", "禁止误用", "danger"))
        self.content_layout.addWidget(card)

    def _troubleshooting(self):
        self.content_layout.addWidget(SectionTitle("常见问题与处理顺序"))
        rows = [
            ["现象", "优先检查", "处理建议"],
            ["字体过小或模糊", "Windows 显示缩放和 Qt 高 DPI", "保持系统缩放 100%–150%，重启应用"],
            ["页面显得空", "窗口是否过宽、是否使用单图模式", "切换双图/四宫格，展开信息面板"],
            ["页面拥挤", "左侧参数区是否过宽", "拖动分隔条、折叠高级参数、最大化图表"],
            ["正式按钮无结果", "FastAPI 后端与地址", "启动后端，检查状态栏和任务中心"],
            ["教学曲线无变化", "参数范围与模块选择", "恢复默认参数后重新操作"],
            ["结果看起来不可信", "来源徽章和数值诊断", "不要使用预览/教学结果作为正式结论"],
        ]
        self._add_table("故障排查", rows)
        card = Card("推荐定位顺序", compact=True)
        for label, value in [
            ("1", "查看顶部项目、版本、来源和连接状态"),
            ("2", "查看当前页面的告警和数值诊断"),
            ("3", "打开任务中心检查状态、进度和说明"),
            ("4", "确认输入参数、单位和范围"),
            ("5", "重新运行最小示例或恢复默认参数"),
        ]:
            card.body.addWidget(InfoRow(label, value))
        self.content_layout.addWidget(card)

    def _add_table(self, title: str, rows: list[list[str]]):
        card = Card(title, compact=True)
        table = DataTable(len(rows) - 1, len(rows[0]))
        table.setHorizontalHeaderLabels(rows[0])
        for r, row in enumerate(rows[1:]):
            for c, value in enumerate(row):
                table.setItem(r, c, QTableWidgetItem(value))
        table.stretch_columns(len(rows[0]) - 1)
        card.body.addWidget(table)
        self.content_layout.addWidget(card)

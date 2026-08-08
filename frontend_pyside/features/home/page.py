from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRect, QSize, QTimer, Signal, Qt
from PySide6.QtGui import QPainter, QPixmap
from frontend_pyside.core.constants import APP_NAME

from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from frontend_pyside.infrastructure.api.clients import DatasetClient, TrainingClient
from frontend_pyside.shared.components.basic import (
    Card,
    InfoRow,
    InlineMetric,
    PrimaryButton,
    SecondaryButton,
    SummaryStrip,
)
from frontend_pyside.shared.components.tables import DataTable
from frontend_pyside.shared.components.workbench import Accordion, ExpandableSection
from frontend_pyside.state.project_context import default_project


class _AspectRatioImage(QWidget):


    def __init__(self, image_path: Path, parent=None):
        super().__init__(parent)
        self._source = QPixmap(str(image_path))
        self.setObjectName("homePlatformWorkflowImage")
        self.setContentsMargins(0, 0, 0, 0)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        self.setMinimumSize(0, 0)
        self.setToolTip("平台研究闭环流程")

    def hasHeightForWidth(self) -> bool:  
        return not self._source.isNull()

    def heightForWidth(self, width: int) -> int:  
        if self._source.isNull() or width <= 0:
            return 0
        ratio = self._source.height() / max(1, self._source.width())
        return max(1, round(width * ratio))

    def sizeHint(self) -> QSize:  
        if self._source.isNull():
            return QSize(0, 0)
        preferred_width = min(1200, max(640, self._source.width()))
        return QSize(preferred_width, self.heightForWidth(preferred_width))

    def minimumSizeHint(self) -> QSize:  
        return QSize(0, 0)

    def paintEvent(self, event) -> None:  
        super().paintEvent(event)
        if self._source.isNull() or self.width() <= 0 or self.height() <= 0:
            return

        target = self._source.scaled(
            self.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        x = max(0, (self.width() - target.width()) // 2)
        
        
        y = 0
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.drawPixmap(QRect(x, y, target.width(), target.height()), target)


class HomePage(QWidget):
    navigateRequested = Signal(str)

    def __init__(self, context, parent=None):
        super().__init__(parent)
        self.context = context
        self.api_client = context.api_client
        self.dataset_client = DatasetClient(self.api_client)
        self.training_client = TrainingClient(self.api_client)
        self._remote_datasets: list[dict] = context.registry.datasets
        self._remote_models: list[dict] = context.registry.models

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 9, 14, 12)
        root.setSpacing(7)

        # 首页直接进入平台介绍与当前工作区，避免重复的大标题和项目摘要条。
        workspace = QSplitter(Qt.Orientation.Horizontal)
        workspace.setChildrenCollapsible(False)

        intro_scroll = QScrollArea()
        intro_scroll.setObjectName("homeIntroScroll")
        intro_scroll.setWidgetResizable(True)
        intro_scroll.setFrameShape(QFrame.Shape.NoFrame)
        intro_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        intro_scroll.setWidget(self._build_intro())
        workspace.addWidget(intro_scroll)

        work_panel = QWidget()
        work_panel.setMinimumWidth(300)
        work_panel.setMaximumWidth(360)
        work_layout = QVBoxLayout(work_panel)
        work_layout.setContentsMargins(0, 0, 0, 0)
        work_layout.setSpacing(7)

        current = Card("当前项目", compact=True)
        self.project = InlineMetric("项目", "—")
        self.eff = InlineMetric("最新结果", "—")
        self.state = InlineMetric("质量状态", "—")
        self.wave = InlineMetric("波长", "—")
        self.surface = InlineMetric("表面", "—")
        self.task_count = InlineMetric("活动任务", "—")
        current.body.addWidget(self.project)
        self.project_summary = QLabel()
        self.project_summary.setWordWrap(True)
        current.body.addWidget(self.project_summary)
        current.body.addWidget(self.eff)
        current.body.addWidget(self.state)
        project_actions = QHBoxLayout()
        new_project = SecondaryButton("新建项目")
        new_project.clicked.connect(self._new_project)
        project_actions.addWidget(new_project)
        teaching = SecondaryButton("教学中心")
        teaching.clicked.connect(lambda: self.navigateRequested.emit("teaching"))
        project_actions.addWidget(teaching)
        project_actions.addStretch(1)
        continue_project = PrimaryButton("继续当前项目")
        continue_project.clicked.connect(lambda: self.navigateRequested.emit("simulation"))
        project_actions.addWidget(continue_project)
        current.body.addLayout(project_actions)
        work_layout.addWidget(current)

        recent = Card("最近任务", compact=True)
        self.task_text = QLabel("暂无任务")
        self.task_text.setWordWrap(True)
        self.task_text.setObjectName("compactTaskText")
        recent.body.addWidget(self.task_text)
        open_tasks = SecondaryButton("打开任务中心")
        open_tasks.clicked.connect(lambda: self.navigateRequested.emit("tasks"))
        recent.body.addWidget(open_tasks)
        work_layout.addWidget(recent)

        pending = Card("待处理事项", compact=True)
        self.quality_rows = QVBoxLayout()
        self.quality_rows.setSpacing(4)
        pending.body.addLayout(self.quality_rows)
        work_layout.addWidget(pending)

        assets = Card("最近资产", compact=True)
        self.asset_text = QLabel("当前项目｜尚无远程数据集或模型")
        self.asset_text.setObjectName("compactAssetText")
        self.asset_text.setWordWrap(True)
        assets.body.addWidget(self.asset_text)
        work_layout.addWidget(assets)
        work_layout.addStretch(1)

        workspace.addWidget(work_panel)
        workspace.setStretchFactor(0, 3)
        workspace.setStretchFactor(1, 1)
        workspace.setSizes([1100, 360])
        root.addWidget(workspace, 1)

        context.project.project_changed.connect(self._refresh)
        context.tasks.tasks_changed.connect(self._refresh_tasks)
        self.api_client.completed.connect(self._api_completed)
        self.api_client.failed.connect(self._api_failed)
        context.registry.datasets_changed.connect(self._registry_datasets_changed)
        context.registry.models_changed.connect(self._registry_models_changed)
        self._refresh(context.project.project)
        self._refresh_tasks(context.tasks.tasks)
        QTimer.singleShot(200, self._refresh_remote_assets)

    def _build_intro(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(8)
        layout.addWidget(self._overview_content())
        layout.addWidget(self._functions_content())
        layout.addWidget(
            ExpandableSection(
                "技术能力与应用场景",
                self._details_content,
                expanded=False,
            )
        )
        layout.addStretch(1)
        return container

    def _overview_content(self) -> QWidget:
        card = Card("系统概述", compact=True)
        title = QLabel(APP_NAME)
        title.setObjectName("homeSystemTitle")
        title.setWordWrap(True)
        card.body.addWidget(title)

        text = QLabel(
            "本平台面向单模光纤耦合系统，提供建模、仿真、研究、优化、智能分析与教学实验的一体化研究环境。"
            "平台将光学系统建模、正式数值仿真、参数研究与优化、智能分析、正式复核和教学实验统一在同一项目上下文中管理，"
            "确保数据可追溯、流程可复现。"
        )
        text.setWordWrap(True)
        text.setObjectName("homeOverviewText")
        card.body.addWidget(text)

        workflow_image = _AspectRatioImage(
            Path(__file__).resolve().parents[2]
            / "resources"
            / "images"
            / "home_platform_research_workflow.png"
        )
        card.body.addWidget(workflow_image)

        actions = QHBoxLayout()
        formal = PrimaryButton("建立正式仿真")
        formal.clicked.connect(lambda: self.navigateRequested.emit("simulation"))
        teaching = SecondaryButton("进入教学中心")
        teaching.clicked.connect(lambda: self.navigateRequested.emit("teaching"))
        actions.addWidget(formal)
        actions.addWidget(teaching)
        actions.addStretch(1)
        card.body.addLayout(actions)

        card.body.addWidget(
            InfoRow(
                "结果来源",
                "正式数值结果由后端生成并通过数值质量检查；教学中心使用独立本地近似模型，两者数据严格隔离。",
            )
        )
        card.body.addWidget(
            SummaryStrip(
                [
                    ("01 建立系统", "光源 / 镜组 / 光纤"),
                    ("02 正式计算", "光路 / 复场 / 效率"),
                    ("03 参数研究", "扫描 / 候选 / 复核"),
                    ("04 智能研究", "模型 / SHAP / 公式"),
                ]
            )
        )

        boundary = Card("结果来源与质量闸门", compact=True)
        boundary.body.addWidget(InfoRow("前端快速预览", "检查结构合理性与变化趋势，不作为正式结论"))
        boundary.body.addWidget(InfoRow("教学近似", "用于课堂演示和物理规律理解，不作为正式结论"))
        boundary.body.addWidget(InfoRow("后端正式计算", "通过边缘功率、能量闭合、网格收敛和光瞳采样检查后可作为正式结果"))
        card.body.addWidget(boundary)
        return card

    def _functions_content(self) -> QWidget:
        card = Card("核心功能", compact=True)
        for title, detail, page in (
            ("光学仿真", "光路、复场、耦合效率与数值诊断", "simulation"),
            ("研究与优化", "参数扫描、候选方案与正式复核", "optimization"),
            ("智能分析", "代理模型、关键因素与预测可信度", "machine_learning"),
            ("模型解释", "SHAP 蜂群图、瀑布图与物理公式联动", "explainability"),
            ("教学实验", "装调失配、模场整形与实验报告", "teaching"),
        ):
            row = QHBoxLayout()
            row.addWidget(InfoRow(title, detail), 1)
            button = SecondaryButton("进入")
            button.clicked.connect(lambda checked=False, key=page: self.navigateRequested.emit(key))
            row.addWidget(button)
            card.body.addLayout(row)
        return card

    def _details_content(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        layout.addWidget(self._innovation_content())
        layout.addWidget(self._sources_content())
        layout.addWidget(self._applications_content())
        return widget

    def _workflow_content(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(14, 12, 14, 12)
        for index, (title, detail, page) in enumerate(
            [
                ("建立项目", "配置光源、多透镜表面、光纤和计算设置", "simulation"),
                ("教学理解", "在半实物实验平台中观察光束、仪器和模场匹配", "teaching"),
                ("快速预览", "检查结构、趋势和明显参数错误", "simulation"),
                ("正式仿真", "生成可追溯的正式结果与质量诊断", "simulation"),
                ("参数研究", "扫描规律、确定高效区域并寻找候选解", "optimization"),
                ("智能分析", "解释当前候选为何改善并判断预测可信度", "machine_learning"),
                ("模型解释", "将 SHAP 与解析公式、物理机制直接联动", "explainability"),
            ],
            1,
        ):
            row = QHBoxLayout()
            label = QLabel(f"{index:02d}　{title}　{detail}")
            label.setWordWrap(True)
            row.addWidget(label, 1)
            button = SecondaryButton("进入")
            button.clicked.connect(lambda checked=False, key=page: self.navigateRequested.emit(key))
            row.addWidget(button)
            layout.addLayout(row)
        return widget

    def _innovation_content(self) -> QWidget:
        widget = QWidget()
        layout = QGridLayout(widget)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setHorizontalSpacing(12)
        layout.setVerticalSpacing(6)
        groups = [
            ("物理链路", ["几何追迹与公共复场重建", "波动传播与模式重叠", "数值质量与收敛诊断", "五轴寻优与灵敏度分析"]),
            ("平台能力", ["项目、任务、数据集和模型分层管理", "正式结果与教学近似严格区分", "SHAP 与物理公式直接联动", "本地离线帮助与确定性诊断"]),
        ]
        for column, (title, items) in enumerate(groups):
            card = Card(title, compact=True)
            for item in items:
                card.body.addWidget(InfoRow("•", item))
            layout.addWidget(card, 0, column)
        return widget

    def _sources_content(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(14, 12, 14, 12)
        table = DataTable(3, 3)
        table.setHorizontalHeaderLabels(["来源", "用途", "能否作为正式结论"])
        rows = [
            ["前端快速预览", "检查结构和变化趋势", "否"],
            ["教学近似", "课堂演示与规律理解", "否"],
            ["后端正式计算", "数值研究与正式报告", "通过质量检查后可以"],
        ]
        for r, values in enumerate(rows):
            for c, value in enumerate(values):
                table.setItem(r, c, QTableWidgetItem(value))
        table.stretch_columns(0, 1, 2)
        table.setMinimumHeight(170)
        layout.addWidget(table)
        layout.addWidget(InfoRow("质量闸门", "边缘功率、能量闭合、网格收敛和光瞳采样必须通过设定阈值。", "必须", "warning"))
        return widget

    def _applications_content(self) -> QWidget:
        widget = QWidget()
        layout = QGridLayout(widget)
        layout.setContentsMargins(14, 12, 14, 12)
        items = [
            "候选镜片组合与方向筛选",
            "单模光纤耦合系统设计",
            "五轴装调与参数研究",
            "参数规律与最佳焦面分析",
            "机器学习代理模型",
            "教学演示与实验报告",
        ]
        for index, text in enumerate(items):
            card = Card(text, compact=True)
            card.body.addWidget(QLabel("从统一项目上下文进入相关工作页面。"))
            layout.addWidget(card, index // 2, index % 2)
        return widget

    def _new_project(self):
        self.context.project.set_project(default_project())
        self.context.tasks.add("新建项目", "项目", "已完成", 100, "已重置为默认四透镜耦合系统", page="home")

    def _refresh(self, project):
        self.project.set_value(project.name, note=f"版本 {project.version}")
        self.wave.set_value(f"{project.wavelength_nm:.0f}", "nm")
        self.surface.set_value(len(project.surfaces), "个")
        metrics = project.metrics or {}
        efficiency = metrics.get("coupling_efficiency")
        self.eff.set_value(f"{100 * efficiency:.1f}" if isinstance(efficiency, (int, float)) else "—", "%")
        self.state.set_value("待正式验证" if metrics else "待计算")
        self.project_summary.setText(
            f"{project.version} · {project.wavelength_nm:.0f} nm · {len(project.surfaces)} 个表面\n"
            "当前项目作为仿真、研究与优化、智能分析和高级解释的共同上下文。"
        )
        self._refresh_quality(project)

    def _refresh_quality(self, project):
        while self.quality_rows.count():
            item = self.quality_rows.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        metrics = project.metrics or {}
        entries = [
            ("正式结果", "尚未生成" if not metrics else "待正式复核", "待处理", "warning"),
            ("网格收敛", "65 / 129 / 257 / 513", "待执行", "warning"),
            ("光瞳收敛", "17 / 33 / 49 / 65", "待执行", "warning"),
        ]
        if metrics and "edge_power" in metrics:
            edge = float(metrics.get("edge_power", 0.0))
            entries.insert(0, ("边缘功率", f"{100 * edge:.3f}%", "通过" if edge < 0.002 else "待检查", "success" if edge < 0.002 else "warning"))
        for label, value, status, tone in entries[:4]:
            self.quality_rows.addWidget(InfoRow(label, value, status, tone))

    def _refresh_tasks(self, tasks):
        active = [item for item in tasks if item.get("status") not in ("已完成", "已取消")]
        self.task_count.set_value(len(active), "个")
        if not tasks:
            self.task_text.setText("暂无任务。可从仿真、参数研究或教学中心发起任务。")
            return
        lines = []
        for item in tasks[:3]:
            lines.append(f"{item.get('kind', '任务')}｜{item.get('name', '—')}\n{item.get('status', '—')} · {item.get('progress', 0)}%")
        self.task_text.setText("\n\n".join(lines))

    def _refresh_remote_assets(self, force: bool = False) -> None:
        registry = self.context.registry
        self._registry_datasets_changed(registry.datasets)
        self._registry_models_changed(registry.models)
        if registry.should_refresh("datasets", force=force):
            self.dataset_client.list_datasets("home.datasets")
        if registry.should_refresh("models", force=force):
            self.training_client.list_models("home.models")

    def _api_completed(self, key: str, data) -> None:
        if key == "home.datasets":
            records = data.get("items", data) if isinstance(data, dict) else data
            self.context.registry.set_datasets([item for item in (records or []) if isinstance(item, dict)])
        elif key == "home.models":
            records = data.get("models", data.get("items", data)) if isinstance(data, dict) else data
            self.context.registry.set_models([item for item in (records or []) if isinstance(item, dict)])

    def _registry_datasets_changed(self, records: list[dict]) -> None:
        self._remote_datasets = [dict(item) for item in records if isinstance(item, dict)]
        self._populate_asset_table()

    def _registry_models_changed(self, records: list[dict]) -> None:
        self._remote_models = [dict(item) for item in records if isinstance(item, dict)]
        self._populate_asset_table()

    def _api_failed(self, key: str, _message: str) -> None:
        if key == "home.datasets":
            self.context.registry.refresh_failed("datasets")
        elif key == "home.models":
            self.context.registry.refresh_failed("models")

    def _populate_asset_table(self) -> None:
        project = self.context.project.project
        lines = [f"项目｜{project.name}｜今天"]
        for dataset in self._remote_datasets[:1]:
            dataset_id = str(dataset.get("dataset_id", dataset.get("id", "")))
            name = str(dataset.get("dataset_name", dataset_id))
            created = str(dataset.get("created_at", "—"))[:16]
            lines.append(f"数据集｜{name}｜{created}")
        for model in self._remote_models[:1]:
            model_id = str(model.get("model_id", model.get("id", "")))
            name = str(model.get("name", model_id))
            created = str(model.get("created_at", "—"))[:16]
            lines.append(f"模型｜{name}｜{created}")
        self.asset_text.setText("\n".join(lines))
        self.asset_text.setToolTip("\n".join(lines))


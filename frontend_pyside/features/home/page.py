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
    assistantActionRequested = Signal(object)

    def __init__(self, context, parent=None):
        super().__init__(parent)
        self.context = context
        self.api_client = context.api_client
        self.dataset_client = DatasetClient(self.api_client)
        self.training_client = TrainingClient(self.api_client)
        self._remote_datasets: list[dict] = context.registry.datasets
        self._remote_models: list[dict] = context.registry.models

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 12, 18, 12)
        root.setSpacing(10)

        # 首页只承担“平台总览”这一件事。完整能力目录由左下悬浮工具箱负责，
        # 任务/历史/数据由底部全局入口负责，避免首页重复制造中转入口。
        title = QLabel(APP_NAME)
        title.setObjectName("homePlatformTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        root.addWidget(title)

        intro_scroll = QScrollArea()
        intro_scroll.setObjectName("homeIntroScroll")
        intro_scroll.setWidgetResizable(True)
        intro_scroll.setFrameShape(QFrame.Shape.NoFrame)
        intro_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        intro_scroll.setWidget(self._build_intro())
        root.addWidget(intro_scroll, 1)

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
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(self._overview_content())
        layout.addStretch(1)
        return container


    def _goal_content(self) -> QWidget:
        card = Card("你现在想做什么？", compact=True)
        intro = QLabel("按研究目的进入，平台会把你带到对应工作区；熟悉平台后仍可直接使用左侧导航。")
        intro.setObjectName("helperText")
        intro.setWordWrap(True)
        card.body.addWidget(intro)
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        goals = [
            ("查看光路与耦合", "simulation", {"target": "simulation.view", "level": "prepare", "payload": {"view": "端面匹配"}}),
            ("诊断耦合问题", "simulation", {"target": "simulation.view", "level": "prepare", "payload": {"view": "XY模场比较"}}),
            ("研究参数规律", "optimization", {"target": "optimization.scan", "level": "prepare"}),
            ("检查装调容差", "optimization", {"target": "optimization.tolerance", "level": "prepare"}),
            ("自动寻找更优参数", "optimization", {"target": "optimization.variables", "level": "prepare"}),
            ("正向预测当前系统", "machine_learning", {"target": "machine_learning.prediction", "level": "prepare"}),
            ("按目标反推参数", "optimization", {"target": "optimization.inverse_design", "level": "prepare"}),
            ("进入教学实验", "teaching", {"target": "teaching.mismatch", "level": "prepare", "payload": {"mismatch": "lateral"}}),
        ]
        for index, (text, page, action) in enumerate(goals):
            button = SecondaryButton(text)
            button.setMinimumHeight(44)
            button.clicked.connect(lambda checked=False, p=page, a=action: self._open_goal(p, a))
            grid.addWidget(button, index // 4, index % 4)
        card.body.addLayout(grid)
        return card

    def _open_goal(self, page: str, action: dict) -> None:
        payload = dict(action or {})
        if "payload" not in payload:
            payload["payload"] = {}
        payload.setdefault("label", "继续")
        self.assistantActionRequested.emit(payload)
        if not payload.get("target"):
            self.navigateRequested.emit(page)

    def _overview_content(self) -> QWidget:
        # 首页主视觉已经包含项目简介、能力和研究闭环，不再在外层重复标题/说明。
        card = Card("", compact=True)
        workflow_image = _AspectRatioImage(
            Path(__file__).resolve().parents[2] / "resources" / "images" / "Frame1.png"
        )
        workflow_image.setToolTip("激光耦合仿真系统及智能优化平台 · 研究流程总览")
        card.body.addWidget(workflow_image)

        # 首页主视觉只负责展示研究流程；具体能力统一由工具箱进入。
        return card

    def _functions_content(self) -> QWidget:
        card = Card("核心功能", compact=True)
        for title, detail, page in (
            ("光学仿真", "光路、复场、耦合效率与数值诊断", "simulation"),
            ("研究与优化", "参数扫描、自动优化与容差分析", "optimization"),
            ("模型分析", "代理模型、关键因素与预测可靠性", "machine_learning"),
            ("模型解释", "SHAP 结果、主要因素与物理公式", "explainability"),
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

    def assistant_context(self) -> dict:
        project = self.context.project.project
        metrics = dict(getattr(project, "metrics", {}) or {})
        tasks = [dict(item) for item in list(getattr(self.context.tasks, "tasks", []) or []) if isinstance(item, dict)]
        active = [item for item in tasks if str(item.get("status", "")) not in {"已完成", "已取消", "失败"}]
        return {
            "page": "首页",
            "current_view": "平台总览",
            "project_name": str(getattr(project, "name", "") or ""),
            "project_version": str(getattr(project, "version", "") or ""),
            "wavelength_nm": float(getattr(project, "wavelength_nm", 0.0) or 0.0),
            "surface_count": len(getattr(project, "surfaces", []) or []),
            "has_project_metrics": bool(metrics),
            "coupling_efficiency": metrics.get("coupling_efficiency"),
            "active_task_count": len(active),
            "total_task_count": len(tasks),
            "current_task": str(dict(getattr(self.context.project, "research_context", {}) or {}).get("current_task", "") or ""),
        }

    def _refresh(self, project):
        # 首页不再重复显示“当前工作/当前工程”卡片；项目状态由全局状态区和
        # 各工作区上下文呈现。保留刷新钩子仅用于兼容项目状态事件。
        return

    def _refresh_quality(self, project):
        while self.quality_rows.count():
            item = self.quality_rows.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        metrics = project.metrics or {}
        entries = [
            ("完整结果", "尚未生成" if not metrics else "待质量检查", "待处理", "warning"),
            ("网格收敛", "65 / 129 / 257 / 513", "待执行", "warning"),
            ("光瞳收敛", "17 / 33 / 49 / 65", "待执行", "warning"),
        ]
        if metrics and "edge_power" in metrics:
            edge = float(metrics.get("edge_power", 0.0))
            entries.insert(0, ("边缘功率", f"{100 * edge:.3f}%", "通过" if edge < 0.002 else "待检查", "success" if edge < 0.002 else "warning"))
        for label, value, status, tone in entries[:4]:
            self.quality_rows.addWidget(InfoRow(label, value, status, tone))

    def _refresh_tasks(self, tasks):
        # 首页不承担任务中心摘要；任务入口统一位于全局底栏/工具箱。
        return


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
        if hasattr(self, "asset_text"):
            self._populate_asset_table()

    def _registry_models_changed(self, records: list[dict]) -> None:
        self._remote_models = [dict(item) for item in records if isinstance(item, dict)]
        if hasattr(self, "asset_text"):
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


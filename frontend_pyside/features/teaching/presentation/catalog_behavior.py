from __future__ import annotations


from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from frontend_pyside.shared.components.basic import (
    Card,
    InfoRow,
    PrimaryButton,
)
from frontend_pyside.shared.components.inputs import ParameterControl


class TeachingCatalogMixin:
    def _build_catalog(self):
        page = QWidget()
        root = QHBoxLayout(page)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        path = Card("主实验学习路径", compact=True)
        path.setMinimumWidth(300)
        path.setMaximumWidth(360)
        self._catalog_keys = list(self.catalog["modules"])
        self.catalog_list = QListWidget()
        for index, key in enumerate(self._catalog_keys, start=1):
            spec = self.catalog["modules"][key]
            self.catalog_list.addItem(f"{index:02d}  {spec.get('short_title', spec['title'])}")
        self.catalog_list.currentRowChanged.connect(self._select_catalog_row)
        path.body.addWidget(self.catalog_list, 1)
        path.body.addWidget(InfoRow("当前可用", f"{len(self._catalog_keys)} 个完整实验"))
        path.body.addWidget(InfoRow("计算方式", "教学近似，本地即时响应"))
        root.addWidget(path)

        detail = QWidget()
        detail_layout = QVBoxLayout(detail)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        detail_layout.setSpacing(8)

        overview = Card("当前实验", compact=True)
        self.catalog_title = QLabel()
        self.catalog_title.setObjectName("pageTitle")
        overview.body.addWidget(self.catalog_title)
        self.catalog_summary = QLabel()
        self.catalog_summary.setWordWrap(True)
        overview.body.addWidget(self.catalog_summary)
        self.catalog_objectives = QLabel()
        self.catalog_objectives.setWordWrap(True)
        self.catalog_objectives.setObjectName("mutedText")
        overview.body.addWidget(self.catalog_objectives)
        action = QHBoxLayout()
        action.addStretch()
        self.catalog_start = PrimaryButton("开始当前实验")
        self.catalog_start.clicked.connect(self._open_selected_catalog)
        action.addWidget(self.catalog_start)
        overview.body.addLayout(action)
        detail_layout.addWidget(overview)

        workflow = Card("统一实验流程", compact=True)
        workflow.body.addWidget(InfoRow("1", "观察初始状态并阅读任务"))
        workflow.body.addWidget(InfoRow("2", "先预测参数变化方向"))
        workflow.body.addWidget(InfoRow("3", "调节核心参数并观察主图"))
        workflow.body.addWidget(InfoRow("4", "完成记录、诊断和方案比较"))
        workflow.body.addWidget(InfoRow("5", "评分并导出实验报告"))
        detail_layout.addWidget(workflow)

        boundary = Card("教学结果边界", compact=True)
        boundary.body.addWidget(InfoRow("适用", "课堂演示、规律理解、实验训练和报告生成", "适用", "success"))
        boundary.body.addWidget(InfoRow("不适用", "正式设计定型、科研发表和工程验收", "禁止替代", "warning"))
        boundary.body.addWidget(InfoRow("结果标识", "全部结果固定标注教学近似来源"))
        detail_layout.addWidget(boundary)
        detail_layout.addStretch(1)
        root.addWidget(detail, 1)

        if self._catalog_keys:
            self.catalog_list.setCurrentRow(0)
        return page

    def _select_catalog_row(self, row: int) -> None:
        if not 0 <= row < len(self._catalog_keys):
            return
        key = self._catalog_keys[row]
        spec = self.catalog["modules"][key]
        self.catalog_title.setText(f"实验 {row + 1}　{spec['title']}")
        self.catalog_summary.setText(spec["summary"])
        self.catalog_objectives.setText(
            "学习目标：" + "；".join(map(str, spec.get("objectives", [])[:4]))
        )

    def _open_selected_catalog(self) -> None:
        row = self.catalog_list.currentRow()
        if 0 <= row < len(self._catalog_keys):
            self._open_module(self._catalog_keys[row])

    def _open_module(self, key):
        self.load_module(key)
        self.tabs.setCurrentWidget(self.workspace)

    def load_module(self, key):
        self.current_module = key
        spec = self.catalog["modules"][key]
        self.course_label.setText(f"{spec['title']}　｜　层级：{self.level.currentText()}")
        self.pred_prompt.setText(spec["prediction"]["prompt"])
        for button in self.pred_group.buttons():
            self.pred_group.removeButton(button)
            button.deleteLater()
        self._clear_layout(self.pred_options)
        for choice_id, label in spec["prediction"]["choices"]:
            radio = QRadioButton(label)
            radio.setProperty("choice_id", choice_id)
            self.pred_group.addButton(radio)
            self.pred_options.addWidget(radio)
        self.pred_feedback.clear()
        self.pred_card.set_expanded(True)

        self._clear_layout(self.parameter_layout)
        self.controls = {}
        level = self.level.currentData()
        for name, parameter in spec["parameters"].items():
            if level not in parameter["levels"]:
                continue
            control = ParameterControl(
                parameter["label"],
                parameter["unit"],
                parameter["minimum"],
                parameter["maximum"],
                parameter["step"],
                parameter["default"],
            )
            control.valueChanged.connect(self._evaluate)
            self.parameter_layout.addWidget(control)
            self.controls[name] = control
        self.parameter_layout.addStretch()
        self.task_label.setText("当前任务：" + spec["task"])
        if hasattr(self, "_populate_scan_controls"):
            self._populate_scan_controls()
        self._rebuild_metric_cards(spec)
        self.formula_label.setText("核心公式\n" + spec["formula"])
        self.theory_label.setText("物理含义\n" + spec["theory"])
        self.assumption_label.setText("适用条件\n• " + "\n• ".join(spec["assumptions"]))
        self._evaluate()
        self._refresh_records()
        if self.theory is not None:
            self._update_theory()

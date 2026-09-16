"""Optimization goal inspector shared by the shell and optimization tabs.

The visible optimization-variable Tab mounts this inspector, while the object
rail may reuse it as a compact configuration surface.
"""

from __future__ import annotations

from frontend_pyside.modules import shared as _shared

globals().update(
    {
        name: value
        for name, value in vars(_shared).items()
        if not name.startswith("__")
    }
)

class OptimizationGoalInspector(QFrame):
    startRequested = Signal()

    def __init__(self, context=None, parent=None) -> None:
        super().__init__(parent)
        self.context = context
        self.setObjectName("ObjectInspector")
        root = QVBoxLayout(self)
        root.setContentsMargins(2, 2, 2, 4)
        root.setSpacing(6)

        box, layout = _field_group("评价")
        self.goal = QComboBox()
        self.goal.addItems(list(OPTIMIZATION_OBJECTIVE_CHOICES))
        self.evaluation = QComboBox()
        # The optimisation objective is currently the fibre-mode overlap.  Do
        # not expose alternate planes until they are implemented as distinct
        # formal objective definitions.
        self.evaluation.addItem("光纤模场")
        self.evaluation.setToolTip("当前优化以光纤端面模场重叠为评价面。")
        self.eval_mode = QComboBox()
        self.eval_mode.addItem("光学仿真", "formal")
        self.eval_mode.addItem("已训练模型", "surrogate")
        self.predict_model = QComboBox()
        self._eval_model_row = _labeled_field("模型", self.predict_model)
        layout.addLayout(
            _field_grid(
                [
                    _labeled_field("目标", self.goal),
                    _labeled_field("面", self.evaluation),
                    _labeled_field("方式", self.eval_mode),
                    self._eval_model_row,
                ],
                columns=2,
            )
        )
        root.addWidget(box)

        engineering, engineering_layout = _field_group("工程约束")
        self.max_length = _spin(0.1, 1e6, 3, " mm", 80.0)
        self.min_edge = _spin(0.0, 100.0, 3, " mm", 0.3)
        # Edge thickness needs two explicitly paired optical surfaces and a
        # sag calculation.  The current generic surface table has neither, so
        # leave it visibly unavailable rather than accept a value we cannot
        # enforce truthfully.
        self.min_edge.setEnabled(False)
        self.min_edge.setToolTip("当前表面模型未声明透镜前后面配对，暂不能可靠约束边缘厚度。")
        self.min_center = _spin(0.0, 100.0, 3, " mm", 0.3)
        self.min_air = _spin(0.0, 100.0, 3, " mm", 0.1)
        self.aperture_limit = QCheckBox("半口径不超过机械口径")
        self.aperture_limit.setChecked(True)
        engineering_layout.addLayout(
            _field_grid(
                [
                    _labeled_field("最大系统总长", self.max_length),
                    _labeled_field("最小边缘厚度", self.min_edge),
                    _labeled_field("最小厚度", self.min_center),
                    _labeled_field("最小空气厚度", self.min_air),
                ],
                columns=2,
            )
        )
        engineering_layout.addWidget(self.aperture_limit)
        root.addWidget(engineering)

        collimation, collimation_layout = _field_group("准直约束")
        self.collimation = QCheckBox("启用")
        self.collimation_surface = QComboBox()
        self.collimation_surface.addItem("自动识别准直输出面", "")
        surfaces = list(getattr(getattr(getattr(context, "project", None), "project", None), "surfaces", ()) or ())
        for index, surface in enumerate(surfaces):
            name = str(getattr(surface, "name", "") or f"面{index}")
            self.collimation_surface.addItem(f"S{index + 1} · {name}", index)
        self.collimation_span = _spin(0.1, 1000.0, 3, " mm", 10.0)
        self.collimation_radius = _spin(0.01, 100.0, 3, " %", 2.0)
        self.collimation_curvature = _spin(0.00001, 10.0, 5, "", 0.05)
        self.collimation_centroid = _spin(0.001, 100.0, 3, " %", 1.0)
        self.collimation_tilt = _spin(0.001, 1000.0, 3, " mrad", 1.0)
        self._collimation_hosts = [
            _labeled_field("评价面", self.collimation_surface),
            _labeled_field("评价段", self.collimation_span),
            _labeled_field("最大半径变化", self.collimation_radius),
            _labeled_field("最大归一化曲率", self.collimation_curvature),
            _labeled_field("最大质心漂移", self.collimation_centroid),
            _labeled_field("最大光轴倾角", self.collimation_tilt),
        ]
        collimation_layout.addWidget(self.collimation)
        collimation_layout.addLayout(_field_grid(self._collimation_hosts, columns=2))
        root.addWidget(collimation)

        self.eval_mode.currentIndexChanged.connect(lambda _index: self._sync_eval_mode())
        self.collimation.toggled.connect(self._sync_collimation)
        self._sync_eval_mode()
        self._sync_collimation()

    def set_trained_models(self, models: list[dict[str, Any]]) -> None:
        previous = self.predict_model.currentText()
        self.predict_model.blockSignals(True)
        self.predict_model.clear()
        for item in models:
            self.predict_model.addItem(str(item.get("title") or item.get("id") or "模型"), dict(item))
        self.predict_model.blockSignals(False)
        if previous and self.predict_model.findText(previous) >= 0:
            self.predict_model.setCurrentText(previous)
        elif self.predict_model.count():
            self.predict_model.setCurrentIndex(0)
        self._sync_eval_mode()

    def evaluation_mode(self) -> str:
        return str(self.eval_mode.currentData() or "formal")

    def _sync_eval_mode(self) -> None:
        ml = self.evaluation_mode() == "surrogate"
        self._eval_model_row.setVisible(ml)
        self.predict_model.setVisible(ml)
        if ml and self.predict_model.count() == 0:
            self.predict_model.setPlaceholderText("请先在模型页训练")
            self.predict_model.setToolTip("请先在数据集页训练，再选择已训练模型。")
        else:
            self.predict_model.setToolTip("")

    def _sync_collimation(self, *_args) -> None:
        enabled = self.collimation.isChecked()
        for host in self._collimation_hosts:
            host.setVisible(enabled)
        for widget in (
            self.collimation_surface,
            self.collimation_span,
            self.collimation_radius,
            self.collimation_curvature,
            self.collimation_centroid,
            self.collimation_tilt,
        ):
            widget.setVisible(enabled)

__all__ = ["OptimizationGoalInspector"]

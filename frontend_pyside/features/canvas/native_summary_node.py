"""原生画布摘要节点：只绘制关键状态，不嵌入任何完整页面或 QWidget。"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QPen
from PySide6.QtWidgets import QMenu

from frontend_pyside.api.payloads import serialize_project
from frontend_pyside.features.machine_learning.feature_adapter import FeaturePathError, features_from_project
from frontend_pyside.infrastructure.api.clients import TrainingClient

from frontend_pyside.features.canvas.node import CanvasNode
from frontend_pyside.features.canvas.prediction_compare import (
    build_forward_compare,
    compare_rows,
)
from frontend_pyside.features.canvas.theme import C


def _font(px: int, bold: bool = False) -> QFont:
    font = QFont()
    font.setPixelSize(px)
    font.setBold(bold)
    return font


_INTRO = {
    "overview": "当前项目的核心状态",
    "system": "光源、光学元件与光纤参数的系统摘要；编辑请打开完整镜头编辑器",
    "model_build": "从上方 Ribbon 选择一个具体模型",
    "forward": "使用当前代理模型进行性能预测",
    "forward_result": "当前透镜参数 vs 正式基线 / 残差",
    "model_explain": "显示当前模型的解释任务与关键贡献",
    "model_manage": "已训练模型与当前采用版本",
    "data": "训练与验证数据集状态",
    "tasks": "后端任务、训练任务与运行状态",
}


class NativeSummaryNode(CanvasNode):
    """自绘摘要卡；中心画布只显示关键信息，不复制旧页面结构。"""

    predictionCompleted = Signal(dict)

    def __init__(self, node_id: str, spec, context=None, parent=None):
        super().__init__(node_id, spec, parent)
        self.context = context
        self._rows: list[tuple[str, str]] = []
        self._model_selector_rect = QRectF()
        self._prediction_button_rect = QRectF()
        self._model_menu: QMenu | None = None
        self._prediction_token = ""
        self._prediction_status = "idle"
        self._prediction_result: dict[str, Any] = {}
        self.result_child_id: str | None = None
        self._bind_context()
        self.refresh_summary()

    def _bind_context(self) -> None:
        if self.context is None:
            return
        project = getattr(self.context, "project", None)
        registry = getattr(self.context, "registry", None)
        tasks = getattr(self.context, "tasks", None)
        for owner, signal_names in (
            (project, ("project_changed", "dirty_changed", "formal_result_changed")),
            (registry, ("datasets_changed", "models_changed", "training_tasks_changed", "current_dataset_changed", "current_model_changed")),
            (tasks, ("tasks_changed", "current_task_changed")),
        ):
            if owner is None:
                continue
            for name in signal_names:
                signal = getattr(owner, name, None)
                if signal is not None:
                    signal.connect(self._refresh_from_signal)
        api = getattr(self.context, "api_client", None)
        if api is not None:
            api.completed.connect(self._on_prediction_completed)
            api.failed.connect(self._on_prediction_failed)

    def _refresh_from_signal(self, *_args) -> None:
        self.refresh_summary()

    @staticmethod
    def _short(value: Any, fallback: str = "—", limit: int = 24) -> str:
        text = str(value or "").strip()
        if not text:
            return fallback
        return text if len(text) <= limit else text[: limit - 1] + "…"

    @staticmethod
    def _prediction_label(name: str) -> str:
        labels = {
            "coupling_efficiency": "耦合效率",
            "coupling_loss_db": "耦合损耗",
            "rms_spot_radius_um": "RMS 光斑",
            "strehl_estimate_marechal": "Strehl",
        }
        return labels.get(str(name), str(name))

    @staticmethod
    def _format_prediction_value(name: str, raw: Any) -> str:
        try:
            number = float(raw)
        except (TypeError, ValueError):
            return str(raw)
        key = str(name).lower()
        if "efficiency" in key:
            return f"{number * 100.0:.2f} %"
        if "db" in key:
            return f"{number:.3g} dB"
        if "um" in key:
            return f"{number:.3g} μm"
        return f"{number:.4g}"

    def refresh_summary(self) -> None:
        key = self.spec.key
        context = self.context
        if context is None:
            self._rows = [("状态", "等待工作区上下文")]
            self.update()
            return
        project_context = getattr(context, "project", None)
        project = getattr(project_context, "project", None)
        registry = getattr(context, "registry", None)
        tasks = getattr(context, "tasks", None)

        if key == "overview":
            surfaces = list(getattr(project, "surfaces", ()) or ())
            self._rows = [
                ("项目", self._short(getattr(project, "name", ""))),
                ("镜头表面", f"{len(surfaces)} 个"),
                ("工作波长", f"{float(getattr(project, 'wavelength_nm', 0.0)):.1f} nm"),
                ("设计版本", f"rev {int(getattr(project_context, 'design_revision', 0))}"),
                ("保存状态", "有未保存修改" if bool(getattr(project_context, "dirty", False)) else "已同步"),
            ]
        elif key == "system":
            surfaces = list(getattr(project, "surfaces", ()) or ())
            groups = {str(getattr(item, "group_id", "") or "") for item in surfaces}
            groups.discard("")
            wavelength = float(getattr(project, "wavelength_nm", 0.0) or 0.0)
            pupil = float(getattr(project, "pupil_radius_mm", 0.0) or 0.0)
            mfd = float(getattr(project, "receiver_mfd_um", 0.0) or 0.0)
            self._rows = [
                ("工作波长", f"{wavelength:.1f} nm"),
                ("光源 / 入瞳", f"{pupil:.3g} mm"),
                ("光纤 MFD", f"{mfd:.3g} μm"),
                ("镜头组", f"{len(groups)} 组 · {len(surfaces)} 面"),
                ("编辑入口", "完整镜头编辑器（Surface 表）"),
            ]
        elif key == "forward_result":
            self._rows = compare_rows(self._prediction_result)
        elif key in {"model_build", "forward", "model_explain", "model_manage"}:
            models = list(getattr(registry, "models", []) or [])
            current_id = str(getattr(registry, "current_model_id", "") or "")
            current = registry.model(current_id) if current_id and registry is not None else None
            current = current if isinstance(current, dict) else {}
            rows = [
                ("已训练模型", f"{len(models)} 个"),
                ("当前模型", self._short(current.get("name") or current.get("model_name") or current_id, "尚未采用")),
                ("模型类型", self._short(current.get("model_type"), "—")),
            ]
            if key == "model_build":
                rows.append(("下一步", "在 Ribbon 选择具体模型"))
            elif key == "forward":
                selected = self._short(
                    current.get("name") or current.get("model_name") or current_id,
                    "点击选择模型",
                )
                # 该摘要节点是正向预测的实际落点，不能只展示“当前模型”。
                # 选择器会直接采用用户选择的模型，供预测与后续节点共享。
                rows.insert(0, ("预测模型", selected + "  ▾"))
                output = {
                    "running": "预测计算中…",
                    "completed": "已完成，结果已生成子节点",
                    "failed": "预测失败，请检查模型与特征",
                }.get(self._prediction_status, "选择模型后生成预测")
                rows.extend((("输入", "当前镜头组参数"), ("输出", output)))
            elif key == "model_explain":
                status = "点 ▶ 用当前模型计算参数贡献" if current_id else "请先训练模型"
                rows.extend((("解释内容", "当前模型最敏感的参数"), ("状态", status)))
            else:
                rows.append(("管理原则", "训练不自动替换当前模型"))
            self._rows = rows
        elif key == "data":
            datasets = list(getattr(registry, "datasets", []) or [])
            training = list(getattr(registry, "training_tasks", []) or [])
            current_id = str(getattr(registry, "current_dataset_id", "") or "")
            self._rows = [
                ("数据集", f"{len(datasets)} 个"),
                ("当前数据集", self._short(current_id, "尚未选择")),
                ("训练记录", f"{len(training)} 条"),
                ("数据真值", "以后端注册表为准"),
            ]
        elif key == "tasks":
            records = list(getattr(tasks, "tasks", []) or [])
            active = int(getattr(tasks, "active_count", 0) or 0)
            latest = records[0] if records and isinstance(records[0], dict) else {}
            self._rows = [
                ("任务总数", str(len(records))),
                ("正在运行", str(active)),
                ("最近任务", self._short(latest.get("name"), "尚无任务")),
                ("最近状态", self._short(latest.get("status"), "—")),
            ]
        else:
            self._rows = [
                ("状态", "画布原生功能"),
                ("显示原则", "场景、参数和结果分离"),
            ]
        self.update()

    def summary_text(self) -> str:
        if not self._rows:
            return _INTRO.get(self.spec.key, "原生摘要")
        return f"{self._rows[0][0]}：{self._rows[0][1]}"

    def _paint_content(self, painter, rect: QRectF) -> None:
        painter.setClipRect(rect)
        self._model_selector_rect = QRectF()
        self._prediction_button_rect = QRectF()
        intro = _INTRO.get(self.spec.key, self.spec.hint or "关键状态摘要")
        painter.setPen(QColor(C["text_muted"]))
        painter.setFont(_font(10))
        painter.drawText(
            QRectF(rect.left(), rect.top() + 2.0, rect.width(), 18.0),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            intro,
        )
        top = rect.top() + 28.0
        row_h = 28.0 if self.spec.key == "forward_result" else 25.0
        metric_labels = {"耦合效率", "耦合损耗", "RMS 光斑", "Strehl"}
        for index, (label, value) in enumerate(self._rows[:8]):
            row = QRectF(rect.left(), top + index * row_h, rect.width(), row_h - 3.0)
            if row.bottom() > rect.bottom():
                break
            painter.setPen(QPen(QColor(C["grid_dot"]), 1.0))
            selectable = self.spec.key == "forward" and label == "预测模型"
            metric = self.spec.key == "forward_result" and (
                label in metric_labels or str(label).startswith("预测 ")
            )
            residual = self.spec.key == "forward_result" and label == "残差"
            painter.setBrush(QColor("#EEF4FF") if selectable or metric else QColor(C["rail_bg"]))
            painter.drawRoundedRect(row, 5.0, 5.0)
            painter.setPen(QColor(C["text_muted"]))
            painter.setFont(_font(10))
            painter.drawText(
                QRectF(row.left() + 7.0, row.top(), row.width() * 0.36, row.height()),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                label,
            )
            if residual and str(value).startswith("+"):
                painter.setPen(QColor(C["ok"]))
            elif residual and str(value).startswith("-"):
                painter.setPen(QColor(C["warn"]))
            else:
                painter.setPen(QColor(C["text"]))
            painter.setFont(_font(14 if metric else 10, True))
            painter.drawText(
                QRectF(row.left() + row.width() * 0.36, row.top(), row.width() * 0.61, row.height()),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                value,
            )
            if metric and "%" in str(value):
                try:
                    ratio = max(0.0, min(1.0, float(str(value).split()[0]) / 100.0))
                except ValueError:
                    ratio = 0.0
                bar = QRectF(row.left() + 8.0, row.bottom() - 5.0, (row.width() - 16.0) * ratio, 3.0)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor("#1D4ED8"))
                painter.drawRoundedRect(bar, 1.5, 1.5)
            if selectable:
                self._model_selector_rect = QRectF(row)
        if self.spec.key == "forward":
            button = QRectF(rect.left(), rect.bottom() - 26.0, rect.width(), 22.0)
            painter.setPen(QPen(QColor(C["grid_dot"]), 1.0))
            painter.setBrush(QColor("#1F2937"))
            painter.drawRoundedRect(button, 5.0, 5.0)
            painter.setPen(QColor("#FFFFFF"))
            painter.setFont(_font(10, True))
            painter.drawText(button, Qt.AlignmentFlag.AlignCenter, "开始预测")
            self._prediction_button_rect = button
        painter.setClipping(False)

    def mousePressEvent(self, event) -> None:
        if self.spec.key == "forward" and self._model_selector_rect.contains(event.pos()):
            self._open_model_selector()
            event.accept()
            return
        if self.spec.key == "forward" and self._prediction_button_rect.contains(event.pos()):
            self._start_prediction()
            event.accept()
            return
        super().mousePressEvent(event)

    def _open_model_selector(self) -> None:
        registry = getattr(self.context, "registry", None) if self.context is not None else None
        records = list(getattr(registry, "models", []) or []) if registry is not None else []
        menu = QMenu()
        self._model_menu = menu  # 保持菜单生命周期到用户完成选择
        if not records:
            unavailable = menu.addAction("暂无已训练模型")
            unavailable.setEnabled(False)
        for record in records:
            if not isinstance(record, dict):
                continue
            model_id = str(record.get("model_id", record.get("id", "")) or "")
            if not model_id:
                continue
            name = self._short(record.get("name") or record.get("model_name") or model_id, model_id, 36)
            model_type = self._short(record.get("model_type"), "", 16)
            action = menu.addAction(f"{name}" + (f"  ·  {model_type}" if model_type else ""))
            action.setData(model_id)
        menu.triggered.connect(self._select_model)
        menu.aboutToHide.connect(menu.deleteLater)
        menu.popup(QCursor.pos())

    def _select_model(self, action) -> None:
        model_id = str(action.data() or "")
        registry = getattr(self.context, "registry", None) if self.context is not None else None
        if model_id and registry is not None:
            registry.set_current_model(model_id)
        self.refresh_summary()

    def set_prediction_result(self, result: dict[str, Any]) -> None:
        self._prediction_result = dict(result or {})
        self.refresh_summary()

    def _start_prediction(self) -> None:
        """在画布节点内直接发起预测，完成后由壳层创建结果子节点。"""
        if self.context is None or self._prediction_status == "running":
            return
        registry = getattr(self.context, "registry", None)
        model_id = str(getattr(registry, "current_model_id", "") or "")
        if not model_id:
            self._prediction_status = "failed"
            self._prediction_result = {"error": "请先点击预测模型行选择一个模型"}
            self.refresh_summary()
            return
        record = registry.model(model_id) if registry is not None else None
        if not isinstance(record, dict):
            self._prediction_status = "failed"
            self._prediction_result = {"error": "当前模型不在已训练模型列表中，请刷新模型"}
            self.refresh_summary()
            return
        try:
            shared = getattr(self.context.project, "simulation_project_payload", {})
            project_payload = dict(shared) if isinstance(shared, dict) and shared.get("surfaces") else serialize_project(self.context.project.project)
            features = features_from_project(project_payload, list(record.get("feature_paths", []) or []))
        except FeaturePathError as exc:
            self._prediction_status = "failed"
            self._prediction_result = {"error": f"当前项目无法构造模型特征：{exc}"}
            self.refresh_summary()
            return
        self._prediction_status = "running"
        self._prediction_result = {
            "model_id": model_id,
            "model_name": record.get("name") or record.get("model_name") or model_id,
            "feature_count": len(features),
            "features": dict(features),
        }
        self.refresh_summary()
        self._prediction_token = uuid4().hex[:12]
        client = TrainingClient(self.context.api_client)
        client.predict(f"canvas.forward.predict.{self._prediction_token}.{model_id}", model_id, features)

    def _on_prediction_completed(self, key: str, data: object) -> None:
        prefix = f"canvas.forward.predict.{self._prediction_token}."
        if not self._prediction_token or not str(key).startswith(prefix):
            return
        body = dict(data or {}) if isinstance(data, dict) else {}
        predictions = dict(body.get("predictions", {}) or {})
        self._prediction_status = "completed" if predictions else "failed"
        self._prediction_result.update({"predictions": predictions, "response": body})
        if not predictions:
            self._prediction_result["error"] = "后端未返回预测值"
            self.refresh_summary()
            return
        compared = build_forward_compare(
            dict(self._prediction_result),
            features=dict(self._prediction_result.get("features") or {}),
            context=self.context,
        )
        self._prediction_result = compared
        self.refresh_summary()
        self.predictionCompleted.emit(dict(compared))

    def _on_prediction_failed(self, key: str, message: str) -> None:
        prefix = f"canvas.forward.predict.{self._prediction_token}."
        if not self._prediction_token or not str(key).startswith(prefix):
            return
        self._prediction_status = "failed"
        self._prediction_result["error"] = str(message)
        self.refresh_summary()


__all__ = ["NativeSummaryNode"]

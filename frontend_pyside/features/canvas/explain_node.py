"""模型解释节点：跟随当前已训练模型，计算参数贡献并显示在画布上。"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from PySide6.QtCore import QRectF, QTimer, Qt
from PySide6.QtGui import QColor, QFont, QPainter

from frontend_pyside.features.canvas.node import CanvasNode
from frontend_pyside.features.canvas.theme import C
from frontend_pyside.infrastructure.api.clients import TrainingClient
from frontend_pyside.shared.feature_labels import display_feature_name


def _font(px: int, bold: bool = False) -> QFont:
    font = QFont()
    font.setPixelSize(px)
    font.setBold(bold)
    return font


def shap_contribution_rows(payload: dict[str, Any] | None, *, limit: int = 5) -> list[tuple[str, str]]:
    data = dict(payload or {})
    target = str(data.get("target_name") or "").lower()
    items = list(data.get("top_features") or [])
    rows: list[tuple[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        label = display_feature_name(item.get("feature"))
        mean = float(item.get("mean_shap", 0.0) or 0.0)
        if abs(mean) < 1e-12:
            effect = "影响很小"
        elif "loss" in target or target.endswith("_db"):
            effect = "更容易增加损耗" if mean > 0 else "更容易降低损耗"
        elif "efficiency" in target:
            effect = "更容易提高耦合" if mean > 0 else "更容易降低耦合"
        else:
            effect = "推高预测" if mean > 0 else "拉低预测"
        rows.append((label, effect))
        if len(rows) >= limit:
            break
    return rows


def explain_shap_failure(message: str) -> str:
    text = str(message or "").strip()
    lowered = text.lower()
    if (
        "schema" in lowered
        or "missing_feature" in lowered
        or "missing one or more trained features" in lowered
    ):
        return "当前镜头组参数和这个模型对不上。请用训练该模型时的镜头组再解释。"
    if "model_not_found" in lowered or "could not be loaded" in lowered:
        return "找不到这个已训练模型。请重新训练后再解释。"
    if "not configured" in lowered or "shap_backend" in lowered:
        return "本机还没装好解释组件，暂时无法计算参数贡献。"
    if "dataset" in lowered and "mismatch" in lowered:
        return "解释用的数据集和训练这个模型时不一致。请改用训练时的数据集。"
    if "internal server error" in lowered:
        return "解释失败：后端解释服务发生内部错误，请查看后端日志或重新训练模型。"
    if not text:
        return "解释失败，请稍后重试。"
    if "学不成" in text or "数据管理" in text:
        return text
    return f"解释失败：{text}"


class ExplainNode(CanvasNode):
    """跟随 registry 当前模型；点 ▶ 或模型就绪后自动计算参数贡献。"""

    def __init__(self, node_id: str, spec, context=None, parent=None):
        super().__init__(node_id, spec, parent)
        self.context = context
        self._chrome_run = True
        self._phase = "idle"
        self._note = ""
        self._token = ""
        self._explained_model_id = ""
        self._rows: list[tuple[str, str]] = []
        self.runRequested.connect(self.run_explain)
        self._bind_context()
        QTimer.singleShot(0, self._maybe_auto_explain)

    def _bind_context(self) -> None:
        registry = getattr(self.context, "registry", None)
        if registry is None:
            return
        for name in ("models_changed", "current_model_changed"):
            signal = getattr(registry, name, None)
            if signal is not None:
                signal.connect(self._on_model_context_changed)
        api = getattr(self.context, "api_client", None)
        if api is not None:
            api.completed.connect(self._on_explain_completed)
            api.failed.connect(self._on_explain_failed)

    def _current_model(self) -> dict[str, Any] | None:
        registry = getattr(self.context, "registry", None) if self.context is not None else None
        if registry is None:
            return None
        model_id = str(getattr(registry, "current_model_id", "") or "")
        record = registry.model(model_id) if model_id else None
        if isinstance(record, dict) and model_id:
            return record
        models = [item for item in (getattr(registry, "models", []) or []) if isinstance(item, dict)]
        return models[-1] if models else None

    def _model_id(self, record: dict[str, Any] | None) -> str:
        if not isinstance(record, dict):
            return ""
        return str(record.get("model_id", record.get("id", "")) or "")

    def _model_title(self, record: dict[str, Any] | None) -> str:
        if not isinstance(record, dict):
            return "尚未训练"
        model_id = self._model_id(record)
        return str(record.get("name") or record.get("model_name") or model_id or "未命名模型")

    def _on_model_context_changed(self, *_args) -> None:
        self.update()
        self._maybe_auto_explain()

    def _maybe_auto_explain(self) -> None:
        if getattr(self.context, "api_client", None) is None:
            self.update()
            return
        record = self._current_model()
        model_id = self._model_id(record)
        if not model_id or model_id == self._explained_model_id or self._phase == "running":
            self.update()
            return
        self.run_explain()

    def run_explain(self) -> None:
        record = self._current_model()
        model_id = self._model_id(record)
        if not model_id:
            self._phase = "idle"
            self._note = "请先训练模型。训练完成后会自动用当前模型计算参数贡献。"
            self.update()
            return
        api = getattr(self.context, "api_client", None) if self.context is not None else None
        if api is None:
            self._phase = "failed"
            self._note = "解释服务还没准备好。"
            self.update()
            return
        if self._phase == "running":
            return
        payload: dict[str, Any] = {"top_k": 6, "max_samples": 80, "background_sample_count": 80}
        dataset_id = str((record or {}).get("dataset_id", "") or "")
        if dataset_id:
            payload["dataset_id"] = dataset_id
        self._token = uuid4().hex[:12]
        self._phase = "running"
        self._note = "正在分析当前模型最敏感的参数…"
        self._rows = []
        self.update()
        TrainingClient(api).explain_shap(
            f"canvas.explain.{self._token}.{model_id}",
            model_id,
            payload,
        )

    def _on_explain_completed(self, key: str, data: object) -> None:
        prefix = f"canvas.explain.{self._token}."
        if not self._token or not str(key).startswith(prefix):
            return
        body = dict(data or {}) if isinstance(data, dict) else {}
        if isinstance(body.get("result"), dict) and not body.get("top_features"):
            body = dict(body.get("result") or {})
        self._phase = "done"
        self._explained_model_id = str(key.rsplit(".", 1)[-1] or self._model_id(self._current_model()))
        self._token = ""
        self._rows = shap_contribution_rows(body)
        self._note = "" if self._rows else "计算完成，但没有返回可显示的参数贡献。"
        self.update()

    def _on_explain_failed(self, key: str, message: str) -> None:
        prefix = f"canvas.explain.{self._token}."
        if not self._token or not str(key).startswith(prefix):
            return
        self._phase = "failed"
        self._token = ""
        self._note = explain_shap_failure(message)
        self.update()

    def summary_text(self) -> str:
        if self._phase == "running":
            return "正在分析参数贡献"
        if self._phase == "failed":
            return (self._note or "解释失败")[:22]
        if self._rows:
            return f"影响最大：{self._rows[0][0]}"[:22]
        if self._current_model() is not None:
            return "点 ▶ 查看参数贡献"
        return "请先训练模型"

    def _paint_content(self, painter: QPainter, rect: QRectF) -> None:
        painter.setClipRect(rect)
        record = self._current_model()
        painter.setPen(QColor(C["text"]))
        painter.setFont(_font(11, True))
        painter.drawText(QRectF(rect.left(), rect.top(), rect.width(), 18.0), Qt.AlignmentFlag.AlignLeft, "当前模型的参数贡献")
        painter.setFont(_font(10))
        painter.setPen(QColor(C["text_muted"]))
        painter.drawText(
            QRectF(rect.left(), rect.top() + 20.0, rect.width(), 16.0),
            Qt.AlignmentFlag.AlignLeft,
            f"跟随：{self._model_title(record)}",
        )
        y = rect.top() + 44.0
        if self._phase == "running":
            painter.setPen(QColor(C["text"]))
            painter.setFont(_font(10, True))
            painter.drawText(QRectF(rect.left(), y, rect.width(), 36.0), Qt.TextFlag.TextWordWrap, self._note)
        elif self._phase == "failed" or (self._note and not self._rows):
            painter.setPen(QColor("#B00020") if self._phase == "failed" else QColor(C["text"]))
            painter.drawText(
                QRectF(rect.left(), y, rect.width(), max(36.0, rect.height() - 50.0)),
                Qt.TextFlag.TextWordWrap,
                self._note,
            )
        elif self._rows:
            painter.setPen(QColor(C["text_muted"]))
            painter.drawText(QRectF(rect.left(), y, rect.width(), 16.0), Qt.AlignmentFlag.AlignLeft, "对结果影响最大的参数")
            y += 20.0
            for label, effect in self._rows[:5]:
                if y + 18.0 > rect.bottom():
                    break
                painter.setPen(QColor(C["text"]))
                painter.setFont(_font(10, True))
                painter.drawText(QRectF(rect.left(), y, rect.width() * 0.58, 18.0), Qt.AlignmentFlag.AlignLeft, label[:16])
                painter.setPen(QColor(C["text_muted"]))
                painter.setFont(_font(10))
                painter.drawText(
                    QRectF(rect.left() + rect.width() * 0.58, y, rect.width() * 0.42, 18.0),
                    Qt.AlignmentFlag.AlignRight,
                    effect,
                )
                y += 20.0
        else:
            painter.setPen(QColor(C["text"]))
            painter.setFont(_font(10, True))
            painter.drawText(
                QRectF(rect.left(), y, rect.width(), 48.0),
                Qt.TextFlag.TextWordWrap,
                "请先训练模型。点右上角 ▶ 会用当前采用的模型计算哪些参数最影响结果。",
            )
        painter.setClipping(False)


__all__ = ["ExplainNode", "explain_shap_failure", "shap_contribution_rows"]

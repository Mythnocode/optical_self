from __future__ import annotations

import json

from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from frontend_pyside.api.training_client import TrainingClient


class VerificationPage(QWidget):
    def __init__(self, api_client):
        super().__init__()
        self.training_client = TrainingClient(api_client)

        self.model_id_edit = QLineEdit()
        self.model_id_edit.setPlaceholderText("model-...")

        self.offset_y = QDoubleSpinBox()
        self.offset_y.setDecimals(4)
        self.offset_y.setRange(-10.0, 10.0)
        self.offset_y.setValue(0.01)

        form = QFormLayout()
        form.addRow("Model id", self.model_id_edit)
        form.addRow("receiver.offset_y_mm", self.offset_y)

        predict_button = QPushButton("Predict")
        predict_button.clicked.connect(self.predict)

        self.status_label = QLabel("Prediction: idle")
        self.result_text = QTextEdit()
        self.result_text.setReadOnly(True)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(predict_button)
        layout.addWidget(self.status_label)
        layout.addWidget(self.result_text)

        api_client.completed.connect(self._completed)
        api_client.failed.connect(self._failed)

    def set_model_id(self, model_id: str):
        if model_id:
            self.model_id_edit.setText(model_id)
            self.status_label.setText(f"Model selected: {model_id}")

    def predict(self):
        model_id = self.model_id_edit.text().strip()
        if not model_id:
            self.result_text.setPlainText("Please train or enter a model id first.")
            return

        payload = {
            "model_id": model_id,
            "features": {
                "receiver.offset_y_mm": float(self.offset_y.value()),
            },
        }
        self.status_label.setText("Prediction: requesting")
        self.training_client.predict("prediction.result", model_id, payload)

    def _completed(self, key, body):
        if key == "prediction.result":
            self.status_label.setText("Prediction complete")
            self.result_text.setPlainText(json.dumps(body, ensure_ascii=False, indent=2))

    def _failed(self, key, message):
        if key.startswith("prediction"):
            self.status_label.setText("Prediction request failed")
            self.result_text.setPlainText(f"{key}\n{message}")

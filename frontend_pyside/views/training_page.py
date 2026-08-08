from __future__ import annotations

import json

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from frontend_pyside.api.job_client import JobClient
from frontend_pyside.api.training_client import TrainingClient


class TrainingPage(QWidget):
    model_ready = Signal(str)

    def __init__(self, api_client):
        super().__init__()
        self.training_client = TrainingClient(api_client)
        self.job_client = JobClient(api_client)
        self.job_id = ""
        self.model_id = ""

        self.dataset_id_edit = QLineEdit()
        self.dataset_id_edit.setPlaceholderText("dataset-...")

        self.model_type_box = QComboBox()
        self.model_type_box.addItems(["random_forest", "mlp"])

        form = QFormLayout()
        form.addRow("Dataset id", self.dataset_id_edit)
        form.addRow("Model type", self.model_type_box)

        train_button = QPushButton("Train model")
        train_button.clicked.connect(self.train_model)

        self.status_label = QLabel("Training: idle")
        self.result_text = QTextEdit()
        self.result_text.setReadOnly(True)

        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(500)
        self.poll_timer.timeout.connect(self.poll_job)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(train_button)
        layout.addWidget(self.status_label)
        layout.addWidget(self.result_text)

        api_client.completed.connect(self._completed)
        api_client.failed.connect(self._failed)

    def set_dataset_id(self, dataset_id: str):
        if dataset_id:
            self.dataset_id_edit.setText(dataset_id)
            self.status_label.setText(f"Dataset selected: {dataset_id}")

    def train_model(self):
        dataset_id = self.dataset_id_edit.text().strip()
        if not dataset_id:
            self.result_text.setPlainText("Please generate or enter a dataset id first.")
            return

        payload = {
            "dataset_id": dataset_id,
            "model_type": self.model_type_box.currentText(),
            "target_names": ["coupling_efficiency"],
            "hyperparameters": {},
            "random_seed": 42,
        }
        self.status_label.setText("Training: submitting")
        self.result_text.setPlainText(json.dumps(payload, ensure_ascii=False, indent=2))
        self.training_client.submit("training.submit", payload)

    def poll_job(self):
        if self.job_id:
            self.job_client.get_status("training.status", self.job_id)

    def _completed(self, key, body):
        if key == "training.submit":
            self.job_id = str(body.get("job_id", ""))
            self.status_label.setText(f"Training job: {self.job_id}")
            self.poll_timer.start()
            return

        if key == "training.status":
            status = body.get("status", "")
            self.status_label.setText(f"Training job {self.job_id}: {status}")
            if status in {"completed", "failed", "cancelled"}:
                self.poll_timer.stop()
                self.job_client.get_result("training.result", self.job_id)
            return

        if key == "training.result":
            self.model_id = str(body.get("model_id", ""))
            self.model_ready.emit(self.model_id)
            summary = {
                "model_id": self.model_id,
                "dataset_id": body.get("dataset_id"),
                "model_type": body.get("model_type"),
                "validation_metrics": body.get("validation_metrics"),
                "test_metrics": body.get("test_metrics"),
                "warnings": body.get("warnings"),
            }
            self.status_label.setText(f"Model ready: {self.model_id}")
            self.result_text.setPlainText(json.dumps(summary, ensure_ascii=False, indent=2))

    def _failed(self, key, message):
        if key.startswith("training"):
            self.poll_timer.stop()
            self.status_label.setText("Training request failed")
            self.result_text.setPlainText(f"{key}\n{message}")

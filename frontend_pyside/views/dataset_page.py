from __future__ import annotations

import json

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from frontend_pyside.api.dataset_client import DatasetClient
from frontend_pyside.api.job_client import JobClient
from frontend_pyside.views.demo_payloads import dataset_payload


class DatasetPage(QWidget):
    dataset_ready = Signal(str)

    def __init__(self, api_client):
        super().__init__()
        self.dataset_client = DatasetClient(api_client)
        self.job_client = JobClient(api_client)
        self.job_id = ""
        self.dataset_id = ""

        self.sample_count = QSpinBox()
        self.sample_count.setRange(3, 200)
        self.sample_count.setValue(10)

        self.lower_bound = QDoubleSpinBox()
        self.lower_bound.setDecimals(4)
        self.lower_bound.setRange(-10.0, 10.0)
        self.lower_bound.setValue(-0.1)

        self.upper_bound = QDoubleSpinBox()
        self.upper_bound.setDecimals(4)
        self.upper_bound.setRange(-10.0, 10.0)
        self.upper_bound.setValue(0.1)

        form = QFormLayout()
        form.addRow("Sample count", self.sample_count)
        form.addRow("receiver.offset_y_mm lower", self.lower_bound)
        form.addRow("receiver.offset_y_mm upper", self.upper_bound)

        submit_button = QPushButton("Generate dataset")
        submit_button.clicked.connect(self.generate_dataset)

        self.status_label = QLabel("Dataset: idle")
        self.result_text = QTextEdit()
        self.result_text.setReadOnly(True)

        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(500)
        self.poll_timer.timeout.connect(self.poll_job)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(submit_button)
        layout.addWidget(self.status_label)
        layout.addWidget(self.result_text)

        api_client.completed.connect(self._completed)
        api_client.failed.connect(self._failed)

    def generate_dataset(self):
        if self.lower_bound.value() >= self.upper_bound.value():
            self.result_text.setPlainText("Lower bound must be smaller than upper bound.")
            return

        payload = dataset_payload(
            sample_count=int(self.sample_count.value()),
            lower_bound=float(self.lower_bound.value()),
            upper_bound=float(self.upper_bound.value()),
        )
        self.status_label.setText("Dataset: submitting")
        self.result_text.setPlainText(json.dumps(payload, ensure_ascii=False, indent=2))
        self.dataset_client.submit("dataset.submit", payload)

    def poll_job(self):
        if self.job_id:
            self.job_client.get_status("dataset.status", self.job_id)

    def _completed(self, key, body):
        if key == "dataset.submit":
            self.job_id = str(body.get("job_id", ""))
            self.status_label.setText(f"Dataset job: {self.job_id}")
            self.poll_timer.start()
            return

        if key == "dataset.status":
            status = body.get("status", "")
            self.status_label.setText(
                f"Dataset job {self.job_id}: {status} {body.get('completed_items', 0)}/{body.get('total_items', 1)}"
            )
            if status in {"completed", "failed", "cancelled"}:
                self.poll_timer.stop()
                self.job_client.get_result("dataset.result", self.job_id)
            return

        if key == "dataset.result":
            self.dataset_id = str(body.get("dataset_id", ""))
            self.dataset_ready.emit(self.dataset_id)
            summary = {
                "dataset_id": self.dataset_id,
                "sample_count": body.get("sample_count"),
                "valid_sample_count": body.get("valid_sample_count"),
                "failed_sample_count": body.get("failed_sample_count"),
                "target_names": body.get("target_names"),
                "status": body.get("status"),
            }
            self.status_label.setText(f"Dataset ready: {self.dataset_id}")
            self.result_text.setPlainText(json.dumps(summary, ensure_ascii=False, indent=2))

    def _failed(self, key, message):
        if key.startswith("dataset"):
            self.poll_timer.stop()
            self.status_label.setText("Dataset request failed")
            self.result_text.setPlainText(f"{key}\n{message}")

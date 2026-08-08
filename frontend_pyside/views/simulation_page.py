from __future__ import annotations

import json

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from frontend_pyside.api.engine_client import EngineClient
from frontend_pyside.api.job_client import JobClient
from frontend_pyside.api.simulation_client import SimulationClient
from frontend_pyside.views.demo_payloads import simulation_payload


class SimulationPage(QWidget):
    def __init__(self, api_client):
        super().__init__()
        self.api_client = api_client
        self.engine_client = EngineClient(api_client)
        self.simulation_client = SimulationClient(api_client)
        self.job_client = JobClient(api_client)
        self.job_id = ""

        self.status_label = QLabel("Backend: not connected")
        self.version_label = QLabel("Version: not loaded")
        self.capabilities_label = QLabel("Capabilities: not loaded")

        self.analysis_box = QComboBox()
        self.analysis_box.addItems(["coupling", "diffraction", "psf", "mtf"])

        connect_button = QPushButton("Connect backend")
        connect_button.clicked.connect(self.connect_backend)

        run_button = QPushButton("Run simulation")
        run_button.clicked.connect(self.run_simulation)

        self.result_text = QTextEdit()
        self.result_text.setReadOnly(True)

        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(500)
        self.poll_timer.timeout.connect(self.poll_job)

        layout = QVBoxLayout(self)
        layout.addWidget(self.status_label)
        layout.addWidget(self.version_label)
        layout.addWidget(self.capabilities_label)
        layout.addWidget(self.analysis_box)
        layout.addWidget(connect_button)
        layout.addWidget(run_button)
        layout.addWidget(self.result_text)

        self.api_client.completed.connect(self._completed)
        self.api_client.failed.connect(self._failed)

    def connect_backend(self):
        self.status_label.setText("Backend: connecting...")
        self.engine_client.get_health()
        self.engine_client.get_version()
        self.engine_client.get_capabilities()

    def run_simulation(self):
        analysis = self.analysis_box.currentText()
        self.result_text.setPlainText(f"Submitting simulation: {analysis}")
        self.simulation_client.submit("simulation.submit", simulation_payload(analysis))

    def poll_job(self):
        if self.job_id:
            self.job_client.get_status("simulation.status", self.job_id)

    def _completed(self, key, body):
        if key == "health":
            optional = body.get("optional_dependencies", {})
            self.status_label.setText(
                "Backend: {status} | engine={engine} | Zemax={zemax}".format(
                    status=body.get("status", ""),
                    engine=body.get("default_engine", ""),
                    zemax=optional.get("zemax", ""),
                )
            )
            return

        if key == "version":
            self.version_label.setText(
                "Version: app={app} | api={api} | contract={contract}".format(
                    app=body.get("app_version", ""),
                    api=body.get("api_version", ""),
                    contract=body.get("contract_version", ""),
                )
            )
            return

        if key == "capabilities":
            engines = body.get("engines", {})
            engine_names = ", ".join(sorted(engines.keys()))
            self.capabilities_label.setText(
                "Capabilities: default={default_engine} | engines={engines}".format(
                    default_engine=body.get("default_engine", ""),
                    engines=engine_names,
                )
            )
            return

        if key == "simulation.submit":
            self.job_id = str(body.get("job_id", ""))
            self.result_text.setPlainText(f"Simulation job submitted: {self.job_id}")
            self.poll_timer.start()
            return

        if key == "simulation.status":
            status = body.get("status", "")
            self.result_text.setPlainText(
                f"Simulation job {self.job_id}: {status} ({body.get('stage', '')})"
            )
            if status in {"completed", "failed", "cancelled"}:
                self.poll_timer.stop()
                self.job_client.get_result("simulation.result", self.job_id)
            return

        if key == "simulation.result":
            summary = {
                "status": body.get("status"),
                "converged": body.get("converged"),
                "metrics": body.get("metrics", {}),
                "warnings": body.get("warnings", []),
                "errors": body.get("errors", []),
                "metadata": body.get("metadata", {}),
            }
            self.result_text.setPlainText(json.dumps(summary, ensure_ascii=False, indent=2))

    def _failed(self, key, message):
        if key.startswith("simulation") or key in {"health", "version", "capabilities"}:
            self.poll_timer.stop()
            self.result_text.setPlainText(f"Request failed: {key}\n{message}")

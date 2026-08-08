from __future__ import annotations

from frontend_pyside.api.headless_dataset_client import HeadlessDatasetClient
from frontend_pyside.api.multipath_client import MultiPathClient
from frontend_pyside.api.optimization_client import OptimizationClient
from frontend_pyside.api.scan_client import ScanClient


class JobClient:
    def __init__(self, api):
        self.api = api

    def list_jobs(self, key: str = "job_list", limit: int = 20, offset: int = 0, status: str | None = None, job_type: str | None = None) -> None:
        query = [f"limit={limit}", f"offset={offset}"]
        if status:
            query.append(f"status={status}")
        if job_type:
            query.append(f"job_type={job_type}")
        self.api.get(key, "/jobs?" + "&".join(query))

    def get_status(self, key: str, job_id: str) -> None:
        self.api.get(key, f"/jobs/{job_id}")

    def get_result(self, key: str, job_id: str) -> None:
        self.api.get(key, f"/jobs/{job_id}/result")

    def get_live_result_local(self, key: str, job_id: str) -> None:
        self.api.get(key, f"/jobs/{job_id}/live-result-local")

    def get_result_analysis(self, key: str, job_id: str, analysis: str) -> None:
        self.api.get(key, f"/jobs/{job_id}/result/{analysis}")

    def cancel(self, key: str, job_id: str) -> None:
        self.api.post(key, f"/jobs/{job_id}/cancel", {})


class SimulationClient:
    def __init__(self, api):
        self.api = api

    def submit(self, key: str, payload: dict) -> None:
        self.api.post(key, "/simulation/jobs", payload)

    def surrogate_preview(self, key: str, payload: dict) -> None:
        self.api.post(key, "/simulation/surrogate-preview", payload)


class DatasetClient:
    def __init__(self, api):
        self.api = api

    def submit(self, key: str, payload: dict) -> None:
        self.api.post(key, "/dataset/jobs", payload)

    def list_datasets(self, key: str = "dataset_list") -> None:
        self.api.get(key, "/headless-datasets")


class TrainingClient:
    def __init__(self, api):
        self.api = api

    def submit(self, key: str, payload: dict) -> None:
        self.api.post(key, "/training/jobs", payload)

    def list_models(self, key: str = "model_list") -> None:
        self.api.get(key, "/models")

    def predict(self, key: str, model_id: str, features: dict) -> None:
        self.api.post(key, f"/models/{model_id}/predict", {"model_id": model_id, "features": features})


class HealthClient:


    def __init__(self, api):
        self.api = api

    def health(self, key: str = "health") -> None:
        self.api.get(key, "/health")

    def version(self, key: str = "version") -> None:
        self.api.get(key, "/version")

    def capabilities(self, key: str = "capabilities") -> None:
        self.api.get(key, "/capabilities")


__all__ = [
    "DatasetClient",
    "HeadlessDatasetClient",
    "HealthClient",
    "JobClient",
    "MultiPathClient",
    "OptimizationClient",
    "ScanClient",
    "SimulationClient",
    "TrainingClient",
]

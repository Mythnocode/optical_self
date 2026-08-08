from __future__ import annotations

from frontend_pyside.api.client import ApiClient


class TrainingClient:
    def __init__(self, api_client: ApiClient):
        self.api_client = api_client

    def submit(self, key: str, payload: dict) -> None:
        self.api_client.post(key, "/training/jobs", payload)

    def predict(self, key: str, model_id: str, payload: dict) -> None:
        self.api_client.post(key, f"/models/{model_id}/predict", payload)

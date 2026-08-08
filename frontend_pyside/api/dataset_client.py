from __future__ import annotations

from frontend_pyside.api.client import ApiClient


class DatasetClient:
    def __init__(self, api_client: ApiClient):
        self.api_client = api_client

    def submit(self, key: str, payload: dict) -> None:
        self.api_client.post(key, "/dataset/jobs", payload)

    def list_datasets(self, key: str) -> None:
        self.api_client.get(key, "/headless-datasets")

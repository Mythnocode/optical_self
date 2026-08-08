from __future__ import annotations

from frontend_pyside.api.client import ApiClient


class JobClient:
    def __init__(self, api_client: ApiClient):
        self.api_client = api_client

    def get_status(self, key: str, job_id: str) -> None:
        self.api_client.get(key, f"/jobs/{job_id}")

    def get_result(self, key: str, job_id: str) -> None:
        self.api_client.get(key, f"/jobs/{job_id}/result")

    def cancel(self, key: str, job_id: str) -> None:
        self.api_client.post(key, f"/jobs/{job_id}/cancel", {})

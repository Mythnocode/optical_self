from __future__ import annotations

from frontend_pyside.api.client import ApiClient


class SimulationClient:
    def __init__(self, api_client: ApiClient):
        self.api_client = api_client

    def submit(self, key: str, payload: dict) -> None:
        self.api_client.post(key, "/simulation/jobs", payload)

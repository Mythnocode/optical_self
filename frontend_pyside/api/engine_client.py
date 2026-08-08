from __future__ import annotations

from frontend_pyside.api.client import ApiClient


class EngineClient:
    def __init__(self, api_client: ApiClient):
        self.api_client = api_client

    def get_health(self) -> None:
        self.api_client.get("health", "/health")

    def get_version(self) -> None:
        self.api_client.get("version", "/version")

    def get_capabilities(self) -> None:
        self.api_client.get("capabilities", "/capabilities")
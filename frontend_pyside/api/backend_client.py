from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(frozen=True)
class BackendHealth:
    status: str
    default_engine: str
    zemax_status: str


class BackendClient:
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8000",
        timeout_s: float = 5.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s

    def get_health(self) -> BackendHealth:
        data = self._get_json("/api/v1/health")
        optional = data.get("optional_dependencies", {})

        return BackendHealth(
            status=str(data.get("status", "")),
            default_engine=str(data.get("default_engine", "")),
            zemax_status=str(optional.get("zemax", "")),
        )

    def get_version(self) -> dict[str, Any]:
        return self._get_json("/api/v1/version")

    def get_capabilities(self) -> dict[str, Any]:
        return self._get_json("/api/v1/capabilities")

    def _get_json(self, path: str) -> dict[str, Any]:
        url = f"{self.base_url}{path}"

        with httpx.Client(timeout=self.timeout_s) as client:
            response = client.get(url)
            response.raise_for_status()
            data = response.json()

        if not isinstance(data, dict):
            raise RuntimeError(f"Backend response is not a JSON object: {url}")

        return data

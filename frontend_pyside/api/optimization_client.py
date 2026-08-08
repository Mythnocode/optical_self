from __future__ import annotations


class OptimizationClient:


    def __init__(self, api_client):
        self.api_client = api_client

    def submit(self, key: str, payload: dict) -> None:
        self.api_client.post(key, "/optimization/jobs", payload)

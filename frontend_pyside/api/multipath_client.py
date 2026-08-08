from __future__ import annotations


class MultiPathClient:


    def __init__(self, api_client):
        self.api_client = api_client

    def submit(self, key: str, payload: dict) -> None:
        self.api_client.post(key, "/simulation/multipath/jobs", payload)

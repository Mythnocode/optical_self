from __future__ import annotations


class LstmClient:


    def __init__(self, api_client):
        self.api_client = api_client

    def train(self, key: str, model_id: str, payload: dict) -> None:
        self.api_client.post(key, f"/models/{model_id}/lstm/train", payload)

    def predict(self, key: str, model_id: str, payload: dict) -> None:
        self.api_client.post(key, f"/models/{model_id}/lstm/predict", payload)

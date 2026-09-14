from __future__ import annotations


class HeadlessDatasetClient:


    def __init__(self, api_client):
        self.api_client = api_client

    def get_dataset(self, key: str, dataset_id: str) -> None:
        self.api_client.get(key, f"/headless-datasets/{dataset_id}")

    def submit_coupling(self, key: str, payload: dict) -> None:
        self.api_client.post(key, "/headless-datasets/coupling/jobs", payload)

    def import_file(self, key: str, payload: dict) -> None:
        self.api_client.post(key, "/headless-datasets/import-file", payload)

    def download_manifest(self, key: str, dataset_id: str) -> None:
        self.api_client.get_binary(key, f"/headless-datasets/{dataset_id}/files/manifest")

    def download_samples_flat(self, key: str, dataset_id: str) -> None:
        self.api_client.get_binary(key, f"/headless-datasets/{dataset_id}/files/samples-flat")

    def download_samples_jsonl(self, key: str, dataset_id: str) -> None:
        self.api_client.get_binary(key, f"/headless-datasets/{dataset_id}/files/samples-jsonl")

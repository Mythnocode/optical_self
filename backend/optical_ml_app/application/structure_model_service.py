
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from machine_learning.neural_networks import (
    BiLSTMConfig,
    load_bilstm,
    load_long_format_sequences,
    predict_bilstm,
    save_bilstm,
    train_bilstm,
)


def _run_bilstm_training_task(
    context: Any,
    request_data: dict[str, Any],
    model_root: str,
) -> dict[str, Any]:
    samples = load_long_format_sequences(
        request_data["dataset_path"],
        system_id_column=request_data["system_id_column"],
        order_column=request_data["order_column"],
        element_type_column=request_data["element_type_column"],
        numeric_feature_columns=request_data["numeric_feature_columns"],
        target_columns=request_data["target_columns"],
    )
    config = BiLSTMConfig(**request_data["config"])
    artifact = train_bilstm(
        samples,
        numeric_feature_names=request_data["numeric_feature_columns"],
        target_names=request_data["target_columns"],
        config=config,
        progress=context.progress,
        cancellation=context.cancellation,
    )
    model_id = "bilstm-" + uuid.uuid4().hex[:12]
    model_dir = Path(model_root) / model_id
    save_bilstm(artifact, model_dir)
    context.progress.update(1.0, "training.bilstm.completed")
    return {
        "model_id": model_id,
        "model_type": "bilstm_structure_sequence",
        "model_dir": str(model_dir),
        "metrics": artifact["metrics"],
        "split_counts": artifact["split_counts"],
        "numeric_feature_names": artifact["numeric_feature_names"],
        "target_names": artifact["target_names"],
        "research_scope": "different_lens_counts_and_element_orderings",
    }


class StructureModelApplicationService:
    def __init__(self, task_manager: Any, model_root: Path) -> None:
        self.task_manager = task_manager
        self.model_root = Path(model_root)
        self.model_root.mkdir(parents=True, exist_ok=True)

    def submit_training(self, request_data: dict[str, Any]) -> str:
        return self.task_manager.submit(
            "bilstm_structure_training",
            _run_bilstm_training_task,
            request_data,
            str(self.model_root),
            timeout_seconds=1800.0,
        )

    def predict(self, model_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        model_dir = self.model_root / model_id
        artifact = load_bilstm(model_dir)
        result = predict_bilstm(
            artifact,
            element_types=payload["element_types"],
            numeric_values=payload["numeric_values"],
        )
        result["model_id"] = model_id
        return result


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

    def list_models(self) -> list[dict[str, Any]]:
        import json
        records: list[dict[str, Any]] = []
        for model_dir in sorted((path for path in self.model_root.iterdir() if path.is_dir()), key=lambda path: path.name):
            manifest_path = model_dir / "manifest.json"
            if not manifest_path.exists():
                records.append({"model_id": model_dir.name, "name": model_dir.name, "model_type": "bilstm_structure_sequence", "status": "incomplete"})
                continue
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                records.append({"model_id": model_dir.name, "name": model_dir.name, "model_type": "bilstm_structure_sequence", "status": "invalid_manifest", "manifest_error": str(exc)})
                continue
            records.append({
                "model_id": model_dir.name,
                "name": str(manifest.get("name") or model_dir.name),
                "model_type": "bilstm_structure_sequence",
                "status": "available",
                "metrics": dict(manifest.get("metrics", {}) or {}),
                "target_names": list(manifest.get("target_names", []) or []),
                "numeric_feature_names": list(manifest.get("numeric_feature_names", []) or []),
                "element_types": sorted(str(key) for key in dict(manifest.get("vocabulary", {}) or {}).keys()),
                "split_counts": dict(manifest.get("split_counts", {}) or {}),
            })
        return records


def _target_quality(artifact: dict[str, Any], target_name: str) -> dict[str, float]:
    block = artifact.get("metrics", {})
    target = block.get(target_name, {}) if isinstance(block, dict) else {}
    if not isinstance(target, dict):
        return {}
    result: dict[str, float] = {}
    for key in ("r2", "mae", "rmse"):
        try:
            result[key] = float(target[key])
        except (KeyError, TypeError, ValueError):
            continue
    return result


def generate_bilstm_candidates(
    artifact: dict[str, Any],
    *,
    min_elements: int,
    max_elements: int,
    max_candidates: int,
    target_name: str | None = None,
    goal: str = "maximize",
    allowed_element_types: list[str] | None = None,
    seed_element_types: list[str] | None = None,
    numeric_template: list[float] | None = None,
    element_numeric_templates: dict[str, list[float]] | None = None,
    allow_weak_model: bool = False,
) -> dict[str, Any]:
    """Generate *screening* candidates for a trained structure-sequence model.

    This is intentionally not a physical lens prescription generator.  When no
    explicit numeric templates are supplied, each element uses the training-set
    mean numeric features so the ranking isolates sequence/count effects.
    """
    from itertools import product
    import numpy as np

    vocabulary = sorted(str(name) for name in dict(artifact.get("vocabulary", {})).keys())
    allowed = [str(name) for name in (allowed_element_types or vocabulary) if str(name) in vocabulary]
    if not allowed:
        raise ValueError("候选元件类型与BiLSTM训练词表没有交集")
    feature_names = [str(name) for name in artifact.get("numeric_feature_names", [])]
    feature_count = len(feature_names)
    if feature_count <= 0:
        raise ValueError("BiLSTM模型缺少数值特征定义")
    targets = [str(name) for name in artifact.get("target_names", [])]
    if not targets:
        raise ValueError("BiLSTM模型缺少预测目标")
    target = str(target_name or targets[0])
    if target not in targets:
        target = targets[0]
    quality = _target_quality(artifact, target)
    r2 = quality.get("r2")
    if not allow_weak_model and (r2 is None or r2 < 0.60):
        reason = (
            f"结构模型在目标 {target} 上缺少独立测试 R²"
            if r2 is None
            else f"结构模型在目标 {target} 上的独立测试 R²={r2:.4f}<0.60"
        )
        return {
            "status": "blocked",
            "target_name": target,
            "goal": goal,
            "model_quality": quality,
            "candidates": [],
            "warnings": [reason + "，已阻止候选排序。请先改进/评估模型；如仅做探索，可显式允许弱模型筛选。"],
            "screening_scope": "structure_sequence_only",
        }

    scaler = artifact.get("feature_scaler")
    mean = np.asarray(getattr(scaler, "mean_", np.zeros(feature_count)), dtype=float)
    mean = np.nan_to_num(mean, nan=0.0, posinf=0.0, neginf=0.0)
    if mean.size != feature_count:
        mean = np.zeros(feature_count, dtype=float)
    if numeric_template is not None:
        base = np.asarray(numeric_template, dtype=float)
        if base.size != feature_count:
            raise ValueError(f"numeric_template需要{feature_count}个数值特征")
    else:
        base = mean
    templates = {str(k): np.asarray(v, dtype=float) for k, v in dict(element_numeric_templates or {}).items()}
    for key, value in templates.items():
        if value.size != feature_count:
            raise ValueError(f"元件 {key} 的数值模板需要{feature_count}个特征")

    min_count = max(1, int(min_elements))
    max_count = max(min_count, int(max_elements))
    limit = max(1, min(int(max_candidates), 500))
    # Evaluate a bounded deterministic pool.  Shorter structures are covered first,
    # then lexicographic sequences; a seed sequence is always included when valid.
    pool_limit = max(limit * 8, 120)
    sequences: list[tuple[str, ...]] = []
    seed = tuple(str(x) for x in (seed_element_types or []) if str(x) in allowed)
    if min_count <= len(seed) <= max_count and seed:
        sequences.append(seed)
    for length in range(min_count, max_count + 1):
        for seq in product(allowed, repeat=length):
            if seq not in sequences:
                sequences.append(seq)
            if len(sequences) >= pool_limit:
                break
        if len(sequences) >= pool_limit:
            break

    rows: list[dict[str, Any]] = []
    for seq in sequences:
        numeric_values = [templates.get(kind, base).tolist() for kind in seq]
        prediction = predict_bilstm(artifact, element_types=seq, numeric_values=numeric_values)
        predictions = dict(prediction.get("predictions", {}) or {})
        score = predictions.get(target)
        try:
            score_value = float(score)
        except (TypeError, ValueError):
            continue
        rows.append({
            "element_types": list(seq),
            "element_count": len(seq),
            "predictions": predictions,
            "score": score_value,
            "attention": list(prediction.get("attention", []) or []),
        })
    reverse = str(goal).lower() != "minimize"
    rows.sort(key=lambda item: float(item["score"]), reverse=reverse)
    rows = rows[:limit]
    for rank, row in enumerate(rows, 1):
        row["rank"] = rank

    warnings = [
        "这些候选只用于结构序列筛选，不是可直接制造的镜片处方；必须经过工程约束与正式复场仿真。"
    ]
    if numeric_template is None and not element_numeric_templates:
        warnings.append("未提供候选镜片数值模板，本次使用训练集均值数值特征，只比较元件数量/顺序的结构趋势。")
    if r2 is None:
        warnings.append("该目标缺少独立测试R²，候选排序仅作探索性参考。")
    elif r2 < 0.6:
        warnings.append(f"该目标独立测试R²={r2:.4f}，候选排序可信度较低。")
    return {
        "status": "completed",
        "target_name": target,
        "goal": goal,
        "model_quality": quality,
        "numeric_feature_names": feature_names,
        "candidate_pool_size": len(sequences),
        "candidates": rows,
        "warnings": warnings,
        "screening_scope": "structure_sequence_only",
    }


# Attach as a method without changing existing callers.
def _generate_candidates_method(self, model_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    artifact = load_bilstm(self.model_root / model_id)
    result = generate_bilstm_candidates(artifact, **payload)
    result["model_id"] = model_id
    return result


StructureModelApplicationService.generate_candidates = _generate_candidates_method

# -*- coding: utf-8 -*-
"""把内置演示数据集重建为 samples_flat(3).xlsx 的 8 透镜数据。

原内置演示 dataset-880bdde6c292 / model-63d9d3ea55cf 是「2 变量光纤对准」
（receiver.offset_x_mm + axial_offset_z_mm），无法做设计变量链式归因。
本脚本把它们重建为「8 设计变量 + 9 物理失配特征」的 8 透镜耦合数据，
同步写入运行实例 user_data/ 与打包资产 resources/demo_assets/。

用法：在 D:\\python\\optical_self 目录下运行
    python tools/rebuild_builtin_8lens.py
"""
from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from machine_learning.datasets.splitter import split_ids
from machine_learning.datasets.storage import FileDatasetStore
from machine_learning.registry.model_registry import FileModelRegistry
from machine_learning.training.service import TrainingService
from shared_contracts.datasets import DatasetManifest
from shared_contracts.training import TrainingRequest

XLSX = r"C:\Users\Alienware\Desktop\samples_flat(3).xlsx"
PROJECT_JSON = ROOT / "data_templates" / "lens_4lens_anchor_project.json"
BUNDLE = ROOT / "resources" / "demo_assets" / "quick_real_780nm"

DATASET_ID = "dataset-880bdde6c292"
MODEL_ID = "model-63d9d3ea55cf"

DESIGN_PATHS = [
    "surfaces[0].radius_mm",
    "surfaces[0].distance_to_next_mm",
    "surfaces[2].radius_mm",
    "surfaces[2].distance_to_next_mm",
    "surfaces[4].radius_mm",
    "surfaces[4].distance_to_next_mm",
    "surfaces[6].radius_mm",
    "surfaces[6].distance_to_next_mm",
]
PHYSICS_PATHS = [
    "size_log_mismatch",
    "size_log_signed",
    "size_ratio",
    "fiber_mode_radius_um",
    "beam_radius_at_receiver_um",
    "lateral_mismatch",
    "angular_mismatch",
    "axial_mismatch",
    "curvature_mismatch",
]
FEATURE_PATHS = DESIGN_PATHS + PHYSICS_PATHS

FEATURE_NAMES = [
    "surface_0_radius_mm",
    "surface_0_distance_to_next_mm",
    "surface_2_radius_mm",
    "surface_2_distance_to_next_mm",
    "surface_4_radius_mm",
    "surface_4_distance_to_next_mm",
    "surface_6_radius_mm",
    "surface_6_distance_to_next_mm",
    "size_log_mismatch",
    "size_log_signed",
    "size_ratio",
    "fiber_mode_radius_um",
    "beam_radius_at_receiver_um",
    "lateral_mismatch",
    "angular_mismatch",
    "axial_mismatch",
    "curvature_mismatch",
]
FEATURE_UNITS = ["mm"] * 8 + ["1", "1", "1", "um", "um", "1", "1", "1", "1"]


def load_records() -> tuple[dict, list[dict]]:
    source_project = json.loads(PROJECT_JSON.read_text(encoding="utf-8"))
    df = pd.read_excel(XLSX)
    df = df.dropna(subset=["sample_id"]).reset_index(drop=True)
    df = df.sort_values("sample_id").reset_index(drop=True)
    records = []
    for _, row in df.iterrows():
        valid = bool(row["valid"]) if pd.notna(row["valid"]) else True
        records.append(
            {
                "sample_id": str(row["sample_id"]),
                "split": "train",
                "request_id": "",
                "project_fingerprint": source_project.get("fingerprint", ""),
                "feature_values": {p: float(row[p]) for p in FEATURE_PATHS},
                "target_values": {
                    "coupling_loss_db": float(row["coupling_loss_db"]),
                    "coupling_efficiency": float(row["coupling_efficiency"]),
                },
                "valid": valid,
                "failure_code": "" if pd.isna(row["failure_code"]) else str(row["failure_code"]),
                "failure_message": "",
                "engine_name": "headless",
                "engine_version": "native-optical-core-v3.2",
                "elapsed_ms": 0,
                "converged": True,
                "metadata": {},
            }
        )
    return source_project, records


def build_manifest(source_project: dict, records: list[dict]) -> DatasetManifest:
    ids = [r["sample_id"] for r in records]
    train, val, test = split_ids(ids, 0.7, 0.15, 42)
    split_of = {}
    for name, subset in (("train", train), ("validation", val), ("test", test)):
        for sid in subset:
            split_of[sid] = name
    for r in records:
        r["split"] = split_of[r["sample_id"]]
    return DatasetManifest(
        dataset_id=DATASET_ID,
        dataset_name="内置演示·780 nm 四透镜八变量耦合",
        engine_name="headless",
        engine_version="native-optical-core-v3.2",
        feature_schema_version="1.0",
        created_at=datetime.now(timezone.utc).isoformat(),
        sample_count=len(records),
        valid_sample_count=len(records),
        failed_sample_count=0,
        feature_names=FEATURE_NAMES,
        feature_paths=FEATURE_PATHS,
        feature_units=FEATURE_UNITS,
        target_names=["coupling_loss_db", "coupling_efficiency"],
        train_ids=train,
        validation_ids=val,
        test_ids=test,
        random_seed=42,
        source_project_fingerprint=source_project.get("fingerprint", ""),
        status="completed",
        variable_scheme_id="basic_4_lens",
        lens_count=4,
        design_variable_paths=DESIGN_PATHS,
        physics_feature_paths=PHYSICS_PATHS,
        metadata={
            "source_project": source_project,
            "variable_scheme_id": "basic_4_lens",
            "lens_count": 4,
            "design_variable_paths": DESIGN_PATHS,
            "physics_feature_paths": PHYSICS_PATHS,
            "sampling_method": "external_xlsx",
            "analytic_coupling_baseline": True,
            "coupling_physics_features": PHYSICS_PATHS,
        },
    )


def write_dataset(manifest: DatasetManifest, records: list[dict], root: Path) -> None:
    store = FileDatasetStore(root)
    store.save_manifest(manifest)
    # 先清空再写入，避免 append 残留旧行
    samples_path = store.dataset_dir(DATASET_ID) / "samples.jsonl"
    samples_path.write_text("", encoding="utf-8")
    for record in records:
        store.append_sample(DATASET_ID, record)


def write_flat_csv(records: list[dict], root: Path) -> None:
    import csv

    header = ["sample_id"] + FEATURE_PATHS + ["coupling_loss_db", "coupling_efficiency", "valid", "failure_code"]
    path = root / DATASET_ID / "samples_flat.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        for r in records:
            row = [r["sample_id"]]
            row += [r["feature_values"][p] for p in FEATURE_PATHS]
            row += [r["target_values"]["coupling_loss_db"], r["target_values"]["coupling_efficiency"]]
            row += [r["valid"], r["failure_code"]]
            writer.writerow(row)


def main() -> None:
    source_project, records = load_records()
    manifest = build_manifest(source_project, records)

    user_datasets = ROOT / "user_data" / "datasets"
    bundle_datasets = BUNDLE / "datasets"
    write_dataset(manifest, records, user_datasets)
    write_dataset(manifest, records, bundle_datasets)
    write_flat_csv(records, user_datasets)
    write_flat_csv(records, bundle_datasets)
    print(f"[dataset] {DATASET_ID} samples={len(records)}")

    # 训练随机森林，再把产物改写到固定的内置模型 ID。
    registry = FileModelRegistry(ROOT / "user_data" / "models")
    store = FileDatasetStore(user_datasets)
    service = TrainingService(store, registry)
    result = service.train(
        TrainingRequest(
            dataset_id=DATASET_ID,
            model_type="random_forest",
            target_names=["coupling_efficiency"],
            hyperparameters={},
            random_seed=42,
        )
    )
    tmp_model_id = result.model_id
    tmp_dir = ROOT / "user_data" / "models" / tmp_model_id
    model_manifest = json.loads((tmp_dir / "manifest.json").read_text(encoding="utf-8"))
    model_manifest["model_id"] = MODEL_ID
    model_manifest["dataset_id"] = DATASET_ID
    model_manifest["name"] = MODEL_ID

    for target in (ROOT / "user_data" / "models" / MODEL_ID, BUNDLE / "models" / MODEL_ID):
        target.mkdir(parents=True, exist_ok=True)
        shutil.copy2(tmp_dir / "model.joblib", target / "model.joblib")
        shutil.copy2(tmp_dir / "preprocessing.joblib", target / "preprocessing.joblib")
        (target / "manifest.json").write_text(
            json.dumps(model_manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    print(f"[model] {MODEL_ID} <- {tmp_model_id}")
    print(f"[metrics] test={result.test_metrics}")

    # 清掉训练过程产生的临时模型目录（已改写到固定 ID）。
    shutil.rmtree(tmp_dir, ignore_errors=True)
    print("done")


if __name__ == "__main__":
    main()

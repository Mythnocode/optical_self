# -*- coding: utf-8 -*-
"""把 samples_flat(3).xlsx 导入为 optical_self 数据集并训练随机森林模型。

数据 = 8 透镜系统（4 片透镜 × {前表面曲率半径, 厚度} = 8 个设计变量）
      + 9 个物理失配特征 + coupling_efficiency 目标。

生成的模型 manifest 会带 design_variable_paths(8) + physics_feature_paths(9)
+ source_project，因此「设计变量」标签页的链式法则归因与 6 张论文图可以正常计算。

用法：在 D:\\python\\optical_self 目录下运行
    python tools/import_xlsx_8lens.py
"""
from __future__ import annotations

import json
import sys
import uuid
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
FEATURE_UNITS = (
    ["mm"] * 8 + ["1", "1", "1", "um", "um", "1", "1", "1", "1"]
)


def main() -> None:
    source_project = json.loads(PROJECT_JSON.read_text(encoding="utf-8"))

    df = pd.read_excel(XLSX)
    df = df.dropna(subset=["sample_id"]).reset_index(drop=True)
    df = df.sort_values("sample_id").reset_index(drop=True)
    if len(df) == 0:
        raise SystemExit("xlsx 里没有有效样本（sample_id 为空的行全部被剔除）。")

    records = []
    for _, row in df.iterrows():
        feature_values = {p: float(row[p]) for p in FEATURE_PATHS}
        target_values = {
            "coupling_loss_db": float(row["coupling_loss_db"]),
            "coupling_efficiency": float(row["coupling_efficiency"]),
        }
        valid = bool(row["valid"]) if pd.notna(row["valid"]) else True
        records.append(
            {
                "sample_id": str(row["sample_id"]),
                "split": "train",
                "request_id": "",
                "project_fingerprint": source_project.get("fingerprint", ""),
                "feature_values": feature_values,
                "target_values": target_values,
                "valid": valid,
                "failure_code": "",
                "failure_message": "",
                "engine_name": "headless",
                "engine_version": "native-optical-core-v3.2",
                "elapsed_ms": 0,
                "converged": True,
                "metadata": {},
            }
        )

    ids = [r["sample_id"] for r in records]
    train, val, test = split_ids(ids, 0.7, 0.15, 42)
    split_of = {}
    for split_name, subset in (("train", train), ("validation", val), ("test", test)):
        for sid in subset:
            split_of[sid] = split_name
    for r in records:
        r["split"] = split_of[r["sample_id"]]

    dataset_id = "dataset-" + uuid.uuid4().hex[:12]
    manifest = DatasetManifest(
        dataset_id=dataset_id,
        dataset_name="xlsx-8lens-" + dataset_id[-6:],
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

    store = FileDatasetStore(ROOT / "user_data" / "datasets")
    store.save_manifest(manifest)
    for record in records:
        store.append_sample(dataset_id, record)
    print(f"[dataset] {dataset_id}  samples={len(records)}  "
          f"split={len(train)}/{len(val)}/{len(test)}")

    registry = FileModelRegistry(ROOT / "user_data" / "models")
    service = TrainingService(store, registry)
    request = TrainingRequest(
        dataset_id=dataset_id,
        model_type="random_forest",
        target_names=["coupling_efficiency"],
        hyperparameters={},
        random_seed=42,
    )
    result = service.train(request)
    print(f"[model]   {result.model_id}")
    print(f"[metrics] test={result.test_metrics}")
    print("done")


if __name__ == "__main__":
    main()

"""Export valid simulated optical systems into BiLSTM long-table form."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Mapping

from machine_learning.datasets.variable_schemes import resolve_lens_bindings


SEQUENCE_NUMERIC_COLUMNS = (
    "front_radius_mm",
    "back_radius_mm",
    "thickness_mm",
    "front_conic",
    "back_conic",
    "front_semi_aperture_mm",
    "back_semi_aperture_mm",
    "air_gap_after_mm",
    "receiver_offset_x_um",
    "receiver_offset_y_um",
    "receiver_axial_offset_z_um",
)


def _number(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _surface_value(
    surfaces: list[Mapping[str, Any]], feature_values: Mapping[str, Any], index: int, field: str
) -> float:
    path = f"surfaces[{index}].{field}"
    if path in feature_values:
        return _number(feature_values[path])
    return _number(surfaces[index].get(field)) if 0 <= index < len(surfaces) else 0.0


def export_sequence_long_table(manifest, store) -> dict[str, Any]:
    """Write ``sequence_samples.csv`` from a completed dataset manifest.

    The generator already persisted the perturbed design variables and formal
    labels for every valid system.  Reconstructing each lens row from those
    records avoids a second simulation pass and keeps tabular and sequence
    datasets subject to the same validity checks.
    """
    source = dict((manifest.metadata or {}).get("source_project") or {})
    surfaces = [row for row in source.get("surfaces", []) if isinstance(row, Mapping)]
    receiver = source.get("receiver") if isinstance(source.get("receiver"), Mapping) else {}
    bindings = resolve_lens_bindings(source)
    if not bindings:
        raise ValueError("当前光学系统没有可识别的实体镜片，无法生成序列数据集")

    path = Path(store.dataset_dir(manifest.dataset_id)) / "sequence_samples.csv"
    targets = list(manifest.target_names or [])
    fields = ["system_id", "element_index", "element_type", *SEQUENCE_NUMERIC_COLUMNS, *targets]
    systems = 0
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for sample in store.iter_samples(manifest.dataset_id):
            if not bool(sample.get("valid")):
                continue
            target_values = dict(sample.get("target_values") or {})
            if any(name not in target_values for name in targets):
                continue
            feature_values = dict(sample.get("feature_values") or {})
            system_id = str(sample.get("sample_id") or f"system-{systems + 1:06d}")
            for binding in bindings:
                front, back = binding.front_surface_index, binding.back_surface_index
                material = str(surfaces[front].get("material_after") or "lens").strip() or "lens"
                writer.writerow({
                    "system_id": system_id,
                    "element_index": binding.lens_index,
                    "element_type": material,
                    "front_radius_mm": _surface_value(surfaces, feature_values, front, "radius_mm"),
                    "back_radius_mm": _surface_value(surfaces, feature_values, back, "radius_mm"),
                    "thickness_mm": _surface_value(surfaces, feature_values, front, "distance_to_next_mm"),
                    "front_conic": _surface_value(surfaces, feature_values, front, "conic"),
                    "back_conic": _surface_value(surfaces, feature_values, back, "conic"),
                    "front_semi_aperture_mm": _surface_value(surfaces, feature_values, front, "semi_aperture_mm"),
                    "back_semi_aperture_mm": _surface_value(surfaces, feature_values, back, "semi_aperture_mm"),
                    "air_gap_after_mm": _surface_value(surfaces, feature_values, back, "distance_to_next_mm"),
                    "receiver_offset_x_um": _number(feature_values.get("receiver.offset_x_um", receiver.get("offset_x_um"))),
                    "receiver_offset_y_um": _number(feature_values.get("receiver.offset_y_um", receiver.get("offset_y_um"))),
                    "receiver_axial_offset_z_um": _number(feature_values.get("receiver.axial_offset_z_um", receiver.get("axial_offset_z_um"))),
                    **{name: _number(target_values[name]) for name in targets},
                })
            systems += 1
    if systems < 10:
        raise ValueError(f"序列模型至少需要 10 个有效系统样本，当前仅有 {systems} 个")
    return {
        "sequence_dataset_path": str(path),
        "system_id_column": "system_id",
        "order_column": "element_index",
        "element_type_column": "element_type",
        "numeric_feature_columns": list(SEQUENCE_NUMERIC_COLUMNS),
        "target_columns": targets,
        "element_count": len(bindings),
        "valid_system_count": systems,
    }

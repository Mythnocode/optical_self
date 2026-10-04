"""Original engineering-project → Teaching scene mapping, without Qt."""
from typing import Any
from shared_presentation.teaching_model import BENCH_ORIGIN_X_MM

def engineering_lens_groups(project: object) -> list[list[object]]:
    """Return consecutive lens-surface groups, preserving prescription order."""
    surfaces = list(getattr(project, "surfaces", ()) or ())
    groups: list[list[object]] = []
    current: list[object] = []
    current_key = ""
    for index, surface in enumerate(surfaces):
        kind = str(getattr(surface, "surface_type", "") or "").strip().lower()
        if kind in {"detector", "探测器/像面", "coordinate_break", "坐标断点"}:
            continue
        key = str(getattr(surface, "group_id", "") or "").strip() or f"pair-{index // 2 + 1}"
        if current and key != current_key:
            groups.append(current)
            current = []
        current.append(surface)
        current_key = key
    if current:
        groups.append(current)
    return groups


def scene_from_engineering(store, project, serialized):
    source = dict(serialized.get("source") or {})
    receiver = dict(serialized.get("receiver") or {})
    system = dict(serialized)
    axis_height = float(store.reference.axis_height_mm)
    wavelength = float(source.get("wavelength_nm") or getattr(project, "wavelength_nm", 0.0) or 780.0)
    waist = max(0.01, float(source.get("waist_x_mm") or 0.5))
    mfd = float(receiver.get("mode_field_diameter_x_um") or getattr(project, "receiver_mfd_um", 0.0) or 5.0)
    na = float(receiver.get("na_x") or 0.12)
    # 整条光路一起右移一段台面留白（见 BENCH_ORIGIN_X_MM）：光源 x 是出光面，
    # 摆在台面左端时管身会悬空，而相对间距不变，所以光学问题不变。
    components: list[dict[str, Any]] = [
        {
            "component_id": "laser-001",
            "kind": "laser",
            "label": "工程光源",
            "pose": {"x_mm": BENCH_ORIGIN_X_MM, "y_mm": 0.0, "z_mm": axis_height},
            "params": {"wavelength_nm": wavelength, "beam_radius_mm": waist},
        }
    ]
    axial = 0.0
    for ordinal, group in enumerate(engineering_lens_groups(project), start=1):
        front = group[0]
        rear = group[-1] if len(group) > 1 else None
        thickness = max(0.1, float(getattr(front, "thickness_mm", 0.0) or 0.0))
        axial += thickness * 0.5
        first_radius = float(getattr(front, "radius_mm", 0.0) or 0.0)
        second_radius = float(getattr(rear, "radius_mm", 0.0) or 0.0) if rear is not None else 0.0
        aperture = float(getattr(front, "semi_aperture_mm", 0.0) or 0.0)
        label = str(getattr(front, "group_id", "") or f"L{ordinal}")
        components.append(
            {
                "component_id": f"lens-{ordinal + 1:03d}",
                "kind": "lens",
                "label": f"{label} 透镜",
                "pose": {"x_mm": BENCH_ORIGIN_X_MM + max(8.0, axial), "y_mm": 0.0, "z_mm": axis_height},
                "params": {
                    "radius1_mm": first_radius,
                    "radius2_mm": second_radius,
                    "center_thickness_mm": thickness,
                    "material": str(getattr(front, "material", "N-BK7") or "N-BK7"),
                    "clear_aperture_mm": aperture,
                    "diameter_mm": max(2.0 * aperture, 1.0),
                    "conic": float(getattr(front, "conic", 0.0) or 0.0),
                },
            }
        )
        axial += max(0.0, sum(float(getattr(item, "thickness_mm", 0.0) or 0.0) for item in group) - thickness * 0.5)
    image_distance = max(4.0, float(system.get("image_distance_mm") or 8.0))
    components.append(
        {
            "component_id": f"fiber-{len(components) + 1:03d}",
            "kind": "fiber",
            "label": "工程光纤接收端",
            "pose": {"x_mm": BENCH_ORIGIN_X_MM + max(24.0, axial + image_distance), "y_mm": 0.0, "z_mm": axis_height},
            "params": {"mfd_um": mfd, "na": na},
        }
    )
    snapshot = store.to_dict()
    snapshot.update(
        {
            "revision": int(store.revision) + 1,
            "components": components,
            # 基准线画在光源出光面上，和默认方案保持一致。
            "baseline_x_mm": BENCH_ORIGIN_X_MM,
            "selected_component_id": components[1]["component_id"] if len(components) > 2 else components[0]["component_id"],
            "results": {},
            "active_result_revision": None,
        }
    )
    store.restore_dict(snapshot, reason="从仿真更新教学台")
    return store.to_dict()


def publish_parameters(store):
    """Original shell's explicitly mapped wavelength and fiber mode diameter."""
    changes = {}
    for item in store.components.values():
        if not item.enabled:
            continue
        if item.kind == 'laser':
            try:
                wavelength = float(item.params.get('wavelength_nm',0.0) or 0.0)
            except (TypeError,ValueError):
                wavelength = 0.0
            if wavelength > 0.0:
                changes['source.wavelength_nm'] = wavelength
        elif item.kind == 'fiber':
            try:
                mfd = float(item.params.get('mfd_um',0.0) or 0.0)
            except (TypeError,ValueError):
                mfd = 0.0
            if mfd > 0.0:
                changes['receiver.mode_field_diameter_x_um'] = mfd
    return changes

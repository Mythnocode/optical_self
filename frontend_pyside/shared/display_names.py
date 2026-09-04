
from __future__ import annotations

from datetime import datetime
from typing import Any

from PySide6.QtCore import QSettings


METRIC_LABELS: dict[str, str] = {
    "coupling_efficiency": "模式耦合效率",
    "total_coupling_efficiency": "总耦合效率",
    "system_efficiency": "系统效率",
    "receiver_efficiency": "接收效率",
    "geometric_throughput": "几何透过率",
    "coupling_loss_db": "耦合损耗",
    "insertion_loss_db": "插入损耗",
    "rms_spot_radius_um": "RMS光斑半径",
    "strehl": "Strehl比",
    "strehl_estimate_marechal": "Strehl比",
    "beam_radius_x": "X方向光斑半径",
    "beam_radius_y": "Y方向光斑半径",
    "focus_offset": "焦面偏移",
    "wavefront_rms": "波前RMS",
    "prediction_value": "预测值",
    "simulation_value": "仿真值",
    "target_value": "目标值",
}

MODEL_TYPE_LABELS: dict[str, str] = {
    "random_forest": "随机森林",
    "random forest": "随机森林",
    "randomforest": "随机森林",
    "xgboost": "XGBoost",
    "xgboost_physics_residual": "XGBoost物理残差",
    "xgboost物理残差": "XGBoost物理残差",
    "bilstm": "BiLSTM",
}

SOURCE_MODE_LABELS: dict[str, str] = {
    "Gaussian": "高斯模式",
    "gaussian": "高斯模式",
    "均匀光瞳": "均匀光瞳",
    "点光源": "点光源",
    "用户复场": "导入复场",
    "plane_wave": "平面波",
}

FIBER_MODE_LABELS: dict[str, str] = {
    "Gaussian": "高斯近似",
    "gaussian": "高斯近似",
    "LP01": "LP01模式",
    "HE11": "HE11模式",
    "用户模式": "导入复场",
}


def metric_label(name: object) -> str:
    text = str(name or "").strip()
    return METRIC_LABELS.get(text, text.replace("_", " ") if text else "输出")


def model_type_label(name: object) -> str:
    text = str(name or "模型").strip()
    return MODEL_TYPE_LABELS.get(text.lower(), MODEL_TYPE_LABELS.get(text, text.replace("_", " ")))


def source_mode_label(name: object) -> str:
    text = str(name or "").strip()
    return SOURCE_MODE_LABELS.get(text, text)


def fiber_mode_label(name: object) -> str:
    text = str(name or "").strip()
    return FIBER_MODE_LABELS.get(text, text)


def _short_time(value: object) -> str:
    text = str(value or "").replace("T", " ").strip()
    if not text:
        return ""
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed.strftime("%m-%d %H:%M")
    except ValueError:
        return text[:16]


class RegistryAliasStore:


    def __init__(self) -> None:
        self.settings = QSettings("Optical ML Platform", "OpticalFrontend")

    @staticmethod
    def _key(kind: str, record_id: str) -> str:
        return f"registry_alias/{kind}/{record_id}"

    def get(self, kind: str, record_id: str) -> str:
        return str(self.settings.value(self._key(kind, record_id), "") or "").strip()

    def set(self, kind: str, record_id: str, name: str) -> None:
        key = self._key(kind, record_id)
        value = str(name or "").strip()
        if value:
            self.settings.setValue(key, value)
        else:
            self.settings.remove(key)
        self.settings.sync()


def record_id(record: dict[str, Any], kind: str) -> str:
    key = "dataset_id" if kind == "dataset" else "model_id"
    return str(record.get(key, record.get("id", "")) or "")


def readable_dataset_name(record: dict[str, Any], index: int = 0, *, aliases: RegistryAliasStore | None = None) -> str:
    rid = record_id(record, "dataset")
    alias = aliases.get("dataset", rid) if aliases and rid else ""
    if alias:
        return alias
    raw = str(record.get("display_name") or record.get("dataset_name") or record.get("name") or "").strip()
    if raw and not raw.lower().startswith("dataset-") and len(raw) <= 42:
        return raw
    target = metric_label((record.get("target_names") or [record.get("target_column") or ""])[0])
    if target and target != "输出":
        return f"{target}训练数据"
    created = _short_time(record.get("created_at"))
    return f"训练数据 · {created or f'#{index + 1}'}"


def readable_model_name(record: dict[str, Any], index: int = 0, *, aliases: RegistryAliasStore | None = None) -> str:
    rid = record_id(record, "model")
    alias = aliases.get("model", rid) if aliases and rid else ""
    if alias:
        return alias
    raw = str(record.get("display_name") or record.get("name") or "").strip()
    if raw and not raw.lower().startswith("model-") and len(raw) <= 42:
        return raw
    model_type = model_type_label(record.get("model_type") or "模型")
    targets = list(record.get("target_names", []) or [])
    target = metric_label(targets[0]) if targets else ""
    created = _short_time(record.get("created_at"))
    parts = [target, model_type, created or f"#{index + 1}"]
    return " · ".join(item for item in parts if item)


def parameter_label(name: object) -> str:
    text = str(name or "").strip()
    direct = {
        "receiver.axial_offset_z_mm": "光纤轴向位置",
        "receiver_axial_offset_z_mm": "光纤轴向位置",
        "receiver.axial_offset_z_um": "光纤轴向位置",
        "receiver_axial_offset_z_um": "光纤轴向位置",
        "receiver.offset_x_mm": "光纤X方向偏移",
        "receiver_offset_x_mm": "光纤X方向偏移",
        "receiver.offset_y_mm": "光纤Y方向偏移",
        "receiver_offset_y_mm": "光纤Y方向偏移",
        "receiver.tilt_x_deg": "光纤X方向倾角",
        "receiver_tilt_x_deg": "光纤X方向倾角",
        "receiver.tilt_y_deg": "光纤Y方向倾角",
        "receiver_tilt_y_deg": "光纤Y方向倾角",
        "receiver.mode_field_diameter_x_um": "光纤模场直径",
        "source.wavelength_nm": "波长",
        "wavelength_nm": "波长",
    }
    if text in direct:
        return direct[text]
    if text.startswith("surfaces["):
        try:
            index = int(text.split("[", 1)[1].split("]", 1)[0])
        except (ValueError, IndexError):
            index = -1
        surface_no = index + 1 if index >= 0 else "?"
        if text.endswith("radius_mm"):
            return f"S{surface_no}曲率半径"
        if text.endswith("distance_to_next_mm") or text.endswith("thickness_mm"):
            
            
            if isinstance(surface_no, int) and surface_no == 8:
                return "L4–名义焦面距离"
            if isinstance(surface_no, int) and surface_no % 2 == 0:
                lens = surface_no // 2
                return f"L{lens}–L{lens + 1}空气间隔"
            return f"S{surface_no}后距离"
        if text.endswith("semi_aperture_mm"):
            return f"S{surface_no}有效孔径"
        return f"S{surface_no}参数"
    aliases = {
        "spacing": "空气间隔",
        "curvature": "镜面曲率",
        "fiber": "光纤位置",
        "alignment": "五轴装调",
        "lens_count": "镜片数量",
        "lens_type": "镜片类型",
        "lens_order": "镜片排列",
        "fiber_axial": "光纤轴向位置",
        "fiber lateral": "光纤横向位置",
        "fiber_lateral": "光纤横向位置",
        "fiber tilt": "光纤角度倾斜",
        "fiber_tilt": "光纤角度倾斜",
    }
    return aliases.get(text, text.replace("_", " ") or "参数")


__all__ = [
    "RegistryAliasStore",
    "fiber_mode_label",
    "metric_label",
    "model_type_label",
    "parameter_label",
    "readable_dataset_name",
    "readable_model_name",
    "record_id",
    "source_mode_label",
]


from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np


@dataclass(frozen=True)
class TargetTransform:
    key: str
    display_name: str
    forward: Callable[[np.ndarray], np.ndarray]
    inverse: Callable[[np.ndarray], np.ndarray]
    output_unit: str
    additive_for_shap: bool

    def transform(self, values):
        return self.forward(np.asarray(values, dtype=float))

    def inverse_transform(self, values):
        return self.inverse(np.asarray(values, dtype=float))


def _clip_efficiency(values: np.ndarray) -> np.ndarray:
    return np.clip(values, 1.0e-12, 1.0)


def _to_loss_db(values: np.ndarray) -> np.ndarray:
    return -10.0 * np.log10(_clip_efficiency(values))


def _from_loss_db(values: np.ndarray) -> np.ndarray:
    return np.power(10.0, -np.asarray(values, dtype=float) / 10.0)


def _to_negative_log(values: np.ndarray) -> np.ndarray:
    return -np.log(_clip_efficiency(values))


def _from_negative_log(values: np.ndarray) -> np.ndarray:
    return np.exp(-np.asarray(values, dtype=float))


TARGET_TRANSFORMS: dict[str, TargetTransform] = {
    "identity": TargetTransform(
        key="identity",
        display_name="原始目标",
        forward=lambda x: x,
        inverse=lambda x: x,
        output_unit="target_unit",
        additive_for_shap=True,
    ),
    "coupling_loss_db": TargetTransform(
        key="coupling_loss_db",
        display_name="耦合损失",
        forward=_to_loss_db,
        inverse=_from_loss_db,
        output_unit="dB",
        additive_for_shap=True,
    ),
    "negative_log_coupling": TargetTransform(
        key="negative_log_coupling",
        display_name="负对数耦合损失",
        forward=_to_negative_log,
        inverse=_from_negative_log,
        output_unit="Np",
        additive_for_shap=True,
    ),
}


def get_target_transform(key: str) -> TargetTransform:
    try:
        return TARGET_TRANSFORMS[key]
    except KeyError as exc:
        raise ValueError(f"不支持的目标变换: {key}") from exc

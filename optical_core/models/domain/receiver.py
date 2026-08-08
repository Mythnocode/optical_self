# 定义光纤接收器。

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FiberReceiver:


    na_x: float
    na_y: float
    mode_field_diameter_x_um: float
    mode_field_diameter_y_um: float
    offset_x_mm: float = 0.0
    offset_y_mm: float = 0.0
    axial_offset_z_mm: float = 0.0
    tilt_x_deg: float = 0.0
    tilt_y_deg: float = 0.0
    receiver_type: str = "single_mode_fiber"
    mode_model: str = "gaussian"
    core_diameter_um: float | None = None
    core_refractive_index: float | None = None
    cladding_refractive_index: float | None = None
    outside_refractive_index: float = 1.0
    endface_transmission: float = 1.0
    fiber_length_m: float = 0.0
    attenuation_db_per_km: float = 0.0
    connector_loss_db: float = 0.0

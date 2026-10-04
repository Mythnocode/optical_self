"""Original equipment catalog and engineering presets, without Qt dependencies."""
from .teaching_model import PLACEABLE_KINDS

EQUIPMENT_PRESETS = {
            "laser": (
                "工业常用激光器规格",
                [("780 nm 外腔二极管 · 50 mW · 0.70 mm", {"wavelength_nm": 780.0, "power_mw": 50.0, "beam_radius_mm": 0.70}),
                 ("850 nm VCSEL · 10 mW · 0.35 mm", {"wavelength_nm": 850.0, "power_mw": 10.0, "beam_radius_mm": 0.35}),
                 ("1064 nm DPSS · 100 mW · 0.80 mm", {"wavelength_nm": 1064.0, "power_mw": 100.0, "beam_radius_mm": 0.80}),
                 ("1310 nm DFB · 10 mW · 0.45 mm", {"wavelength_nm": 1310.0, "power_mw": 10.0, "beam_radius_mm": 0.45}),
                 ("1550 nm DFB · 10 mW · 0.50 mm", {"wavelength_nm": 1550.0, "power_mw": 10.0, "beam_radius_mm": 0.50}),
                 ("自定义波长", None)],
            ),
            "lens": (
                "工程常用透镜规格",
                [("焦距 25 mm · 直径 12.7 mm", {"focal_length_mm": 25.0, "diameter_mm": 12.7}),
                 ("焦距 50 mm · 直径 25.4 mm", {"focal_length_mm": 50.0, "diameter_mm": 25.4}),
                 ("焦距 100 mm · 直径 25.4 mm", {"focal_length_mm": 100.0, "diameter_mm": 25.4})],
            ),
            "mirror": (
                "工程常用反射镜规格",
                [("圆形 12.7 mm", {"diameter_mm": 12.7}), ("圆形 25.4 mm", {"diameter_mm": 25.4})],
            ),
            "aperture": (
                "工程常用光阑规格",
                [("通光直径 4 mm", {"diameter_mm": 4.0}), ("通光直径 8 mm", {"diameter_mm": 8.0}),
                 ("通光直径 12 mm", {"diameter_mm": 12.0})],
            ),
            "fiber": (
                "工程常用光纤规格",
                [("单模 · 模场 5.6 μm · NA 0.12", {"mfd_um": 5.6, "na": 0.12}),
                 ("单模 · 模场 10.4 μm · NA 0.14", {"mfd_um": 10.4, "na": 0.14}),
                 ("多模 · 芯径 50 μm · NA 0.22", {"core_diameter_um": 50.0, "na": 0.22})],
            ),
            "detector": (
                "工程常用探测器规格",
                [("小面阵 6.4 × 4.8 mm", {"sensor_width_mm": 6.4, "sensor_height_mm": 4.8}),
                 ("大面阵 13.2 × 8.8 mm", {"sensor_width_mm": 13.2, "sensor_height_mm": 8.8})],
            ),
        }

def equipment_groups():
    return (
            ("光源", [item for item in PLACEABLE_KINDS if item[0] == "laser"]),
            ("光学元件", [item for item in PLACEABLE_KINDS if item[0] in {
                "isolator", "waveplate", "lens", "cylindrical_lens", "beam_expander",
                "aperture", "pbs", "splitter", "beam_sampler", "grating", "mirror",
            }]),
            ("接收与测量", [item for item in PLACEABLE_KINDS if item[0] in {
                "fiber", "ccd", "power_meter", "wavefront_sensor",
            }]),
            ("台面", [item for item in PLACEABLE_KINDS if item[0] == "oscilloscope"]),
        )

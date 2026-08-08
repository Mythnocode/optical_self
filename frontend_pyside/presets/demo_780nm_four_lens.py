from __future__ import annotations



PROJECT_NAME = "780 nm 四透镜高效耦合方案"
DEFAULT_WAVELENGTH_NM = 780.0
DEFAULT_WAIST_RADIUS_UM = 1380.0
DEFAULT_WAIST_POSITION_MM = 0.0
DEFAULT_BEAM_QUALITY_M2 = 1.0
DEFAULT_SOURCE_NA = 0.00018
DEFAULT_SOURCE_POWER_MW = 1.0

DEFAULT_RECEIVER_NA = 0.13
DEFAULT_RECEIVER_MFD_UM = 4.0
DEFAULT_RECEIVER_CORE_DIAMETER_UM = 3.0
DEFAULT_RECEIVER_N_CORE = 1.450000
DEFAULT_RECEIVER_N_CLAD = 1.440000
DEFAULT_RECEIVER_OUTSIDE_INDEX = 1.0
DEFAULT_RECEIVER_ENDFACE_TRANSMISSION = 0.995

DEFAULT_OBJECT_DISTANCE_MM = 18.182441199500627
DEFAULT_PUPIL_RADIUS_MM = 3.0
DEFAULT_IMAGE_DISTANCE_MM = 8.973730675077647

DEFAULT_CALCULATION_PRECISION_TEXT = "标准"
DEFAULT_CALCULATION_PRECISION = "standard"
DEFAULT_OUTPUT_GRID_SIZE = 513
DEFAULT_LAYOUT_PUPIL_SAMPLE_COUNT = 9
DEFAULT_PUPIL_SAMPLE_COUNT = 49
DEFAULT_PROPAGATION_TEXT = "缩放 Fresnel"
DEFAULT_PROPAGATION_MODEL = "scaled_fresnel"
DEFAULT_ZERO_PADDING_FACTOR = 2.0
DEFAULT_OUTPUT_EXTENT_MM = 0.024
DEFAULT_ANALYSES = ("raytrace", "coupling")
DEFAULT_ONLY_VISIBLE_RESULTS = False
DEFAULT_HIGH_PRECISION_COUPLING = True

REFERENCE_COUPLING_EFFICIENCY = 0.9769065351385269
REFERENCE_GRID_SIZE = 513
REFERENCE_ELAPSED_SECONDS = 2.132368888998826


FOUR_LENS_SURFACES = (
    {
        "name": "L1 前表面", "radius_mm": 5.11, "thickness_mm": 3.0,
        "material": "N-BK7", "semi_aperture_mm": 3.0,
        "surface_type": "非球面", "conic": -1.068158491228596,
        "group_id": "L1", "mechanical_diameter_mm": 6.0,
    },
    {
        "name": "L1 后表面", "radius_mm": 0.0,
        "thickness_mm": 14.843576053563464,
        "material": "AIR", "semi_aperture_mm": 3.0,
        "surface_type": "平面", "conic": 0.0,
        "group_id": "L1", "mechanical_diameter_mm": 6.0,
    },
    {
        "name": "L2 前表面", "radius_mm": 4.088, "thickness_mm": 4.0,
        "material": "N-BK7", "semi_aperture_mm": 3.0,
        "surface_type": "非球面", "conic": -1.0118,
        "group_id": "L2", "mechanical_diameter_mm": 6.0,
    },
    {
        "name": "L2 后表面", "radius_mm": 0.0,
        "thickness_mm": 27.374376240007166,
        "material": "AIR", "semi_aperture_mm": 3.0,
        "surface_type": "平面", "conic": 0.0,
        "group_id": "L2", "mechanical_diameter_mm": 6.0,
    },
    {
        "name": "L3 前表面", "radius_mm": 25.55, "thickness_mm": 3.0,
        "material": "N-BK7", "semi_aperture_mm": 3.0,
        "surface_type": "非球面", "conic": -1.0118,
        "group_id": "L3", "mechanical_diameter_mm": 6.0,
    },
    {
        "name": "L3 后表面", "radius_mm": 0.0,
        "thickness_mm": 15.674091779008947,
        "material": "AIR", "semi_aperture_mm": 3.0,
        "surface_type": "平面", "conic": 0.0,
        "group_id": "L3", "mechanical_diameter_mm": 6.0,
    },
    {
        "name": "L4 前表面", "radius_mm": 6.132, "thickness_mm": 3.0,
        "material": "N-BK7", "semi_aperture_mm": 3.0,
        "surface_type": "非球面", "conic": -0.8385398893571219,
        "group_id": "L4", "mechanical_diameter_mm": 6.0,
    },
    {
        "name": "L4 后表面", "radius_mm": 0.0, "thickness_mm": 0.0,
        "material": "AIR", "semi_aperture_mm": 3.0,
        "surface_type": "平面", "conic": 0.0,
        "group_id": "L4", "mechanical_diameter_mm": 6.0,
    },
)

__all__ = [name for name in globals() if name.isupper()]

"""Asset drop contract for Teaching Center V2.

On-bench millimetre size is the housing catalog, not the glb AABB and not
optical params (beam waist, MFD, sensor).  Native files may be any millimetre
scale; the view fits each AABB to the catalog box.  Replacing a glb must keep
the recorded native AABB, axes and optical-port origin.

File axes: **+X optical**, **+Z up**.  Pose is the optical centre / port:
emitters sit behind the pose (body in −X), receivers sit downstream
(body in +X), centred optics stay centred.  Origin is taken from the fitted
AABB, not from unvalidated artist notes.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import struct
from functools import lru_cache
from pathlib import Path
from typing import Any

from PySide6.QtCore import QUrl

from .coordinates import AXIS_HEIGHT_MM


ASSET_DIR = Path(__file__).resolve().parent / "assets"
BODY_ASSET_KEYS = (
    "laser",
    "isolator",
    "waveplate",
    "lens",
    "cylindrical_lens",
    "beam_expander",
    "aperture",
    "pbs",
    "splitter",
    "beam_sampler",
    "grating",
    "mirror",
    "fiber",
    "ccd",
    "power_meter",
    "wavefront_sensor",
    "oscilloscope",
)
POST_STEM_KEY = "post_stem"
FIBER_STAGE_KEY = "fiber_stage"
ASSET_SUFFIXES = (".glb", ".mesh")
MESH_AXES = "+X optical, +Z up"
NATIVE_AABB_TOL_MM = 0.25

ORIGIN_OUTPUT_FACE = "output_face"
ORIGIN_INPUT_FACE = "input_face"
ORIGIN_CENTER = "center"
ORIGIN_TOP = "top"
ORIGIN_BOTTOM = "bottom"
ORIGIN_HARDWARE = "hardware"
POST_BASE_KEY = "mount_post_base"
MOUNT_RING_KEY = "mount_ring"
MOUNT_CLAMP_KEY = "mount_clamp"
MOUNT_KM_KEY = "mount_km"
MOUNT_PLATE_KEY = "mount_plate"

PLACEHOLDER_CYLINDER = "cylinder"
PLACEHOLDER_CUBE = "cube"

# Catalog housings (student-lab Ø1/2 in class).  Optical params do not size these.
HALF_INCH_MM = 12.7
POST_DIAMETER_MM = HALF_INCH_MM
# Visual post at 25 mm axis height.  Catalog TR is Ø12.7; that reads as a tower.
POST_DISPLAY_DIA_MM = 8.0
# LMR05: OD 17.53 mm around Ø12.7, ~9 mm thick.  Wall = (17.53 − 12.7) / 2.
LMR_WALL_MM = 2.4
LMR_THICKNESS_MM = 7.0
# PH2 plate is 25.4 mm, equal to the 25 mm axis, so it fills the view.  Compact holder.
PH_PLATE_MM = 16.0
DEFAULT_LENS_THICKNESS_MM = 2.0
MIRROR_THICKNESS_MM = 6.0
LASER_HOUSING_LENGTH_MM = 40.0
LASER_HOUSING_DIA_MM = 11.0
FIBER_HOUSING_LENGTH_MM = 18.0
FIBER_HOUSING_DIA_MM = 11.0
CCD_HOUSING_LENGTH_MM = 21.8
CCD_HOUSING_FACE_MM = 30.0
APERTURE_THICKNESS_MM = 0.5
DEFAULT_APERTURE_DIA_MM = 5.0
ISOLATOR_HOUSING_LENGTH_MM = 36.0
ISOLATOR_HOUSING_DIA_MM = 25.0
BREADBOARD_KEY = "breadboard"
BREADBOARD_LENGTH_MM = 450.0
BREADBOARD_WIDTH_MM = 300.0
BREADBOARD_THICKNESS_MM = 12.7
BREADBOARD_HOLE_PITCH_MM = 25.0
BREADBOARD_HOLE_SIZE = "M6"
STEM_BOARD_GAP_MM = 0.2
# File is 36x44x40; on the bench it is a small coupler head, not a mid-air fridge.
FIBER_STAGE_DISPLAY_LENGTH_MM = 18.0
FIBER_STAGE_DISPLAY_WIDTH_MM = 20.0
FIBER_STAGE_DISPLAY_HEIGHT_MM = 12.0
FIBER_MOUNT_PAD_LENGTH_MM = 10.0
FIBER_MOUNT_PAD_WIDTH_MM = 11.0
FIBER_MOUNT_PAD_HEIGHT_MM = 5.0
FIBER_DISPLAY_LENGTH_MM = 11.0
FIBER_DISPLAY_DIA_MM = 6.5


@dataclass(frozen=True, slots=True)
class HousingSpec:
    """Frozen on-bench millimetres for one kind.  Mesh files are a skin on this box."""

    key: str
    catalog: str
    length_mm: float
    width_mm: float
    height_mm: float
    origin: str
    mesh_key: str
    placeholder: str = PLACEHOLDER_CYLINDER
    length_param: str = ""
    aperture_param: str = ""


@dataclass(frozen=True, slots=True)
class NativeMeshSpec:
    """Shipped glb AABB in file millimetres.  View fits this box onto HousingSpec."""

    key: str
    min_xyz: tuple[float, float, float]
    max_xyz: tuple[float, float, float]
    origin: str


@dataclass(frozen=True, slots=True)
class HousingTarget:
    """Resolved visual shell for one component instance."""

    length_mm: float
    width_mm: float
    height_mm: float
    origin: str
    catalog: str
    placeholder: str = PLACEHOLDER_CYLINDER

    @property
    def aperture_mm(self) -> float:
        return max(self.width_mm, self.height_mm)


@dataclass(frozen=True, slots=True)
class MeshExtents:
    min_xyz: tuple[float, float, float]
    max_xyz: tuple[float, float, float]

    @property
    def size_mm(self) -> tuple[float, float, float]:
        return (
            self.max_xyz[0] - self.min_xyz[0],
            self.max_xyz[1] - self.min_xyz[1],
            self.max_xyz[2] - self.min_xyz[2],
        )

    @property
    def aperture_mm(self) -> float:
        width, height = self.size_mm[1], self.size_mm[2]
        return max(width, height, 0.0)

    @property
    def thickness_mm(self) -> float:
        return max(self.size_mm[0], 0.0)


@dataclass(frozen=True, slots=True)
class MeshPlacement:
    scale: tuple[float, float, float]
    offset_mm: tuple[float, float, float]


HOUSING_SPECS: dict[str, HousingSpec] = {
    spec.key: spec
    for spec in (
        HousingSpec(
            "laser",
            "Thorlabs CPS635 dia11x40 mm",
            LASER_HOUSING_LENGTH_MM,
            LASER_HOUSING_DIA_MM,
            LASER_HOUSING_DIA_MM,
            ORIGIN_OUTPUT_FACE,
            "laser",
        ),
        HousingSpec(
            "lens",
            "dia 1/2 in optic",
            DEFAULT_LENS_THICKNESS_MM,
            HALF_INCH_MM,
            HALF_INCH_MM,
            ORIGIN_CENTER,
            "lens",
            length_param="center_thickness_mm",
            aperture_param="diameter_mm",
        ),
        HousingSpec(
            "cylindrical_lens",
            "dia 1/2 in cylindrical optic",
            DEFAULT_LENS_THICKNESS_MM,
            HALF_INCH_MM,
            HALF_INCH_MM,
            ORIGIN_CENTER,
            "cylindrical_lens",
            length_param="center_thickness_mm",
            aperture_param="diameter_mm",
        ),
        HousingSpec(
            "fiber",
            "Thorlabs F220FC dia11x18 mm",
            FIBER_HOUSING_LENGTH_MM,
            FIBER_HOUSING_DIA_MM,
            FIBER_HOUSING_DIA_MM,
            ORIGIN_INPUT_FACE,
            "fiber",
        ),
        HousingSpec(
            "isolator",
            "Thorlabs IO-3-780-HP class dia25x36 mm",
            ISOLATOR_HOUSING_LENGTH_MM,
            ISOLATOR_HOUSING_DIA_MM,
            ISOLATOR_HOUSING_DIA_MM,
            ORIGIN_CENTER,
            "isolator",
            aperture_param="diameter_mm",
        ),
        HousingSpec(
            "ccd",
            "Thorlabs Zelux CS165 30x30x21.8 mm",
            CCD_HOUSING_LENGTH_MM,
            CCD_HOUSING_FACE_MM,
            CCD_HOUSING_FACE_MM,
            ORIGIN_INPUT_FACE,
            "ccd",
            PLACEHOLDER_CUBE,
        ),
        HousingSpec(
            "mirror",
            "Thorlabs BB05 dia12.7x6 mm",
            MIRROR_THICKNESS_MM,
            HALF_INCH_MM,
            HALF_INCH_MM,
            ORIGIN_OUTPUT_FACE,
            "mirror",
            aperture_param="diameter_mm",
        ),
        HousingSpec(
            "aperture",
            "iris / spatial filter disc",
            APERTURE_THICKNESS_MM,
            DEFAULT_APERTURE_DIA_MM,
            DEFAULT_APERTURE_DIA_MM,
            ORIGIN_CENTER,
            "aperture",
            aperture_param="diameter_mm",
        ),
        HousingSpec(
            "waveplate",
            "Thorlabs WPQ05M class dia12.7x6 mm",
            6.0,
            HALF_INCH_MM,
            HALF_INCH_MM,
            ORIGIN_CENTER,
            "waveplate",
            aperture_param="diameter_mm",
        ),
        HousingSpec(
            "beam_expander",
            "Thorlabs GBE02 class dia25x45 mm",
            45.0,
            25.0,
            25.0,
            ORIGIN_CENTER,
            "beam_expander",
        ),
        HousingSpec(
            "pbs",
            "Thorlabs PBS122 12.7 mm cube",
            HALF_INCH_MM,
            HALF_INCH_MM,
            HALF_INCH_MM,
            ORIGIN_CENTER,
            "pbs",
            PLACEHOLDER_CUBE,
        ),
        HousingSpec(
            "splitter",
            "Thorlabs BSW plate 50/50 dia12.7x3 mm",
            3.0,
            HALF_INCH_MM,
            HALF_INCH_MM,
            ORIGIN_OUTPUT_FACE,
            "splitter",
            aperture_param="diameter_mm",
        ),
        HousingSpec(
            "beam_sampler",
            "Thorlabs BSF pickoff dia12.7x1 mm",
            1.0,
            HALF_INCH_MM,
            HALF_INCH_MM,
            ORIGIN_OUTPUT_FACE,
            "beam_sampler",
            aperture_param="diameter_mm",
        ),
        HousingSpec(
            "grating",
            "Thorlabs GR13 ruled 12.7x12.7x6 mm",
            6.0,
            HALF_INCH_MM,
            HALF_INCH_MM,
            ORIGIN_OUTPUT_FACE,
            "grating",
            PLACEHOLDER_CUBE,
        ),
        HousingSpec(
            "power_meter",
            "Thorlabs S120C class dia30x22 mm",
            22.0,
            30.0,
            30.0,
            ORIGIN_INPUT_FACE,
            "power_meter",
            PLACEHOLDER_CUBE,
        ),
        HousingSpec(
            "wavefront_sensor",
            "Thorlabs WFS compact 40x40x32 mm",
            32.0,
            40.0,
            40.0,
            ORIGIN_INPUT_FACE,
            "wavefront_sensor",
            PLACEHOLDER_CUBE,
        ),
        HousingSpec(
            "oscilloscope",
            "USB scope brick 120x80x50 mm",
            120.0,
            80.0,
            50.0,
            ORIGIN_BOTTOM,
            "oscilloscope",
            PLACEHOLDER_CUBE,
        ),
        HousingSpec(
            FIBER_STAGE_KEY,
            "compact fiber mount under F220, not Newport 561",
            36.0,
            44.0,
            40.0,
            ORIGIN_TOP,
            FIBER_STAGE_KEY,
            PLACEHOLDER_CUBE,
        ),
        HousingSpec(
            BREADBOARD_KEY,
            "Thorlabs MB1218/M 450x300x12.7 mm, M6-25",
            BREADBOARD_LENGTH_MM,
            BREADBOARD_WIDTH_MM,
            BREADBOARD_THICKNESS_MM,
            ORIGIN_TOP,
            BREADBOARD_KEY,
            PLACEHOLDER_CUBE,
        ),
        HousingSpec(
            POST_STEM_KEY,
            "Thorlabs TR75/M dia12.7 x z_mm",
            POST_DIAMETER_MM,
            POST_DIAMETER_MM,
            POST_DIAMETER_MM,
            ORIGIN_TOP,
            POST_STEM_KEY,
        ),
    )
}

def target_aabb_for_housing(spec: HousingSpec) -> NativeMeshSpec:
    """Delivery AABB in file millimetres so the artist models at catalog size."""
    length, width, height = spec.length_mm, spec.width_mm, spec.height_mm
    half_y, half_z = 0.5 * width, 0.5 * height
    if spec.origin == ORIGIN_OUTPUT_FACE:
        minimum, maximum = (-length, -half_y, -half_z), (0.0, half_y, half_z)
    elif spec.origin == ORIGIN_INPUT_FACE:
        minimum, maximum = (0.0, -half_y, -half_z), (length, half_y, half_z)
    elif spec.origin == ORIGIN_TOP:
        half_x, half_y = 0.5 * length, 0.5 * width
        minimum, maximum = (-half_x, -half_y, -height), (half_x, half_y, 0.0)
    elif spec.origin == ORIGIN_BOTTOM:
        half_x, half_y = 0.5 * length, 0.5 * width
        minimum, maximum = (-half_x, -half_y, 0.0), (half_x, half_y, height)
    else:
        half_x = 0.5 * length
        minimum, maximum = (-half_x, -half_y, -half_z), (half_x, half_y, half_z)
    return NativeMeshSpec(spec.mesh_key or spec.key, minimum, maximum, spec.origin)


# Artist delivery AABB: model at catalog millimetres, origin already on the optical port / table.
TARGET_MESH_SPECS: dict[str, NativeMeshSpec] = {
    spec.mesh_key: target_aabb_for_housing(spec) for spec in HOUSING_SPECS.values()
}
TARGET_MESH_SPECS[POST_STEM_KEY] = NativeMeshSpec(
    POST_STEM_KEY, (-6.35, -6.35, -1.0), (6.35, 6.35, 0.0), ORIGIN_TOP
)
# Hardware skins sit beside optic housings.  Missing files fall back to cubes.
MOUNT_MESH_SPECS: dict[str, NativeMeshSpec] = {
    POST_BASE_KEY: NativeMeshSpec(POST_BASE_KEY, (-12.5, -12.5, 0.0), (12.5, 12.5, 10.0), ORIGIN_BOTTOM),
    MOUNT_RING_KEY: NativeMeshSpec(MOUNT_RING_KEY, (-5.0, -10.0, -10.0), (5.0, 10.0, 10.0), ORIGIN_CENTER),
    MOUNT_CLAMP_KEY: NativeMeshSpec(MOUNT_CLAMP_KEY, (-28.0, -9.0, -13.0), (-12.0, 9.0, -5.5), ORIGIN_HARDWARE),
    MOUNT_KM_KEY: NativeMeshSpec(MOUNT_KM_KEY, (-14.0, -13.0, -13.0), (-6.0, 13.0, 13.0), ORIGIN_HARDWARE),
    MOUNT_PLATE_KEY: NativeMeshSpec(MOUNT_PLATE_KEY, (0.0, -17.0, -21.0), (22.0, 17.0, -15.0), ORIGIN_HARDWARE),
}
MOUNT_KEY_BY_STYLE = {
    "ring": MOUNT_RING_KEY,
    "clamp": MOUNT_CLAMP_KEY,
    "km": MOUNT_KM_KEY,
    "plate": MOUNT_PLATE_KEY,
}
# Shipped files are modelled at catalog millimetres.  Check them against this box.
NATIVE_MESH_SPECS: dict[str, NativeMeshSpec] = dict(TARGET_MESH_SPECS)
NATIVE_MESH_SPECS.update(MOUNT_MESH_SPECS)


def housing_spec(kind: str) -> HousingSpec:
    key = str(kind or "")
    return HOUSING_SPECS.get(key) or HOUSING_SPECS["lens"]


def mesh_key_for_kind(kind: str, asset_key: str = "") -> str:
    explicit = str(asset_key or "").strip()
    if explicit:
        return explicit
    return housing_spec(kind).mesh_key


def visual_housing(kind: str, params: dict[str, Any] | None = None) -> HousingTarget:
    """Catalog millimetres on the bench.  Beam / MFD / sensor do not size this box."""
    spec = housing_spec(kind)
    params = dict(params or {})
    length = spec.length_mm
    width = spec.width_mm
    height = spec.height_mm
    if spec.length_param:
        raw = params.get(spec.length_param)
        if raw not in (None, ""):
            length = max(float(raw), 0.2)
    if spec.aperture_param:
        raw = params.get(spec.aperture_param)
        if raw not in (None, ""):
            width = height = float(raw) or width
    return HousingTarget(length, width, height, spec.origin, spec.catalog, spec.placeholder)


def fiber_stage_display_housing() -> HousingTarget:
    """Small F220 mount head.  The glb stays 36x44x40 and is scaled down to this."""
    return HousingTarget(
        FIBER_STAGE_DISPLAY_LENGTH_MM,
        FIBER_STAGE_DISPLAY_WIDTH_MM,
        FIBER_STAGE_DISPLAY_HEIGHT_MM,
        ORIGIN_TOP,
        "compact F220 mount head",
        PLACEHOLDER_CUBE,
    )


def stem_clearance_mm(kind: str, params: dict[str, Any] | None = None) -> float:
    """Pose down to the housing underside.  The post starts here so it does not pierce the optic."""
    body = 0.5 * float(visual_housing(kind, params).height_mm)
    if str(kind or "") == "fiber":
        return 0.5 * FIBER_DISPLAY_DIA_MM + FIBER_MOUNT_PAD_HEIGHT_MM
    return body


def stem_draw_height_mm(z_mm: float, kind: str, params: dict[str, Any] | None = None) -> float:
    """Post length from housing underside to the breadboard top, minus a hairline gap."""
    return max(float(z_mm) - stem_clearance_mm(kind, params) - STEM_BOARD_GAP_MM, 0.2)


def _axis_scale(native: float, target: float) -> float:
    return float(target) / max(float(native), 0.2)


def fit_mesh_to_housing(extents: MeshExtents, target: HousingTarget) -> MeshPlacement:
    """Scale the AABB to the catalog box, then slide the optical port onto Pose.

    RuntimeLoader scales about the file origin, so the offset is applied in
    mesh millimetres after that scale.
    """
    size = extents.size_mm
    sx = _axis_scale(size[0], target.length_mm)
    sy = _axis_scale(size[1], target.width_mm)
    sz = _axis_scale(size[2], target.height_mm)
    min_x, min_y, min_z = extents.min_xyz
    max_x, max_y, max_z = extents.max_xyz
    if target.origin == ORIGIN_OUTPUT_FACE:
        ox = -max_x * sx
    elif target.origin == ORIGIN_INPUT_FACE:
        ox = -min_x * sx
    else:
        ox = -0.5 * (min_x + max_x) * sx
    oy = -0.5 * (min_y + max_y) * sy
    if target.origin == ORIGIN_TOP:
        oz = -max_z * sz
    elif target.origin == ORIGIN_BOTTOM:
        oz = -min_z * sz
    else:
        oz = -0.5 * (min_z + max_z) * sz
    return MeshPlacement((sx, sy, sz), (ox, oy, oz))


def stem_mesh_placement(
    z_mm: float, extents: MeshExtents | None, diameter_mm: float | None = None
) -> MeshPlacement:
    """``post_stem.glb``: +Z is the post axis, origin at the optical centre (Z=0, body −Z)."""
    height = max(float(z_mm), 0.2)
    dia = POST_DIAMETER_MM if diameter_mm is None else float(diameter_mm)
    if extents is None:
        return MeshPlacement((1.0, 1.0, height), (0.0, 0.0, 0.0))
    size = extents.size_mm
    native_height = max(size[2], 0.2)
    native_dia = max(size[0], size[1], 0.2)
    scale_xy = dia / native_dia
    sz = height / native_height
    min_x, min_y, min_z = extents.min_xyz
    max_x, max_y, max_z = extents.max_xyz
    ox = -0.5 * (min_x + max_x) * scale_xy
    oy = -0.5 * (min_y + max_y) * scale_xy
    oz = -max_z * sz
    return MeshPlacement((scale_xy, scale_xy, sz), (ox, oy, oz))


def resolve_asset_file(asset_key: str) -> Path | None:
    key = str(asset_key or "").strip()
    if not key:
        return None
    for suffix in ASSET_SUFFIXES:
        path = ASSET_DIR / f"{key}{suffix}"
        if path.is_file() and path.stat().st_size > 0:
            return path
    return None


def mesh_url(asset_key: str) -> str:
    path = resolve_asset_file(asset_key)
    if path is None:
        return ""
    return QUrl.fromLocalFile(str(path.resolve())).toString(QUrl.ComponentFormattingOption.FullyEncoded)


def _glb_json(path: Path) -> dict[str, Any] | None:
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if len(data) < 20 or data[:4] != b"glTF":
        return None
    _magic, _version, length = struct.unpack_from("<4sII", data, 0)
    offset = 12
    while offset + 8 <= min(length, len(data)):
        chunk_len, chunk_type = struct.unpack_from("<I4s", data, offset)
        offset += 8
        chunk = data[offset : offset + chunk_len]
        offset += chunk_len
        if chunk_type.startswith(b"JSON"):
            try:
                payload = json.loads(chunk.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                return None
            return payload if isinstance(payload, dict) else None
    return None


def _position_accessor_indices(payload: dict[str, Any]) -> tuple[int, ...]:
    indices: list[int] = []
    for mesh in payload.get("meshes") or ():
        if not isinstance(mesh, dict):
            continue
        for primitive in mesh.get("primitives") or ():
            if not isinstance(primitive, dict):
                continue
            position = (primitive.get("attributes") or {}).get("POSITION")
            if isinstance(position, int):
                indices.append(position)
    return tuple(indices)


@lru_cache(maxsize=32)
def _mesh_extents_cached(path_str: str, mtime_ns: int) -> MeshExtents | None:
    payload = _glb_json(Path(path_str))
    if not payload:
        return None
    accessors = payload.get("accessors") or ()
    chosen = _position_accessor_indices(payload)
    if not chosen:
        chosen = tuple(
            index
            for index, accessor in enumerate(accessors)
            if isinstance(accessor, dict) and accessor.get("type") == "VEC3"
        )
    mins = [float("inf"), float("inf"), float("inf")]
    maxs = [float("-inf"), float("-inf"), float("-inf")]
    found = False
    for index in chosen:
        if index < 0 or index >= len(accessors):
            continue
        accessor = accessors[index]
        if not isinstance(accessor, dict) or accessor.get("type") != "VEC3":
            continue
        minimum = accessor.get("min")
        maximum = accessor.get("max")
        if not isinstance(minimum, (list, tuple)) or not isinstance(maximum, (list, tuple)):
            continue
        if len(minimum) < 3 or len(maximum) < 3:
            continue
        found = True
        for axis in range(3):
            mins[axis] = min(mins[axis], float(minimum[axis]))
            maxs[axis] = max(maxs[axis], float(maximum[axis]))
    if not found:
        return None
    return MeshExtents((mins[0], mins[1], mins[2]), (maxs[0], maxs[1], maxs[2]))


def mesh_extents(asset_key: str) -> MeshExtents | None:
    path = resolve_asset_file(asset_key)
    if path is None or path.suffix.lower() != ".glb":
        return None
    try:
        mtime_ns = path.stat().st_mtime_ns
    except OSError:
        return None
    return _mesh_extents_cached(str(path.resolve()), mtime_ns)


def expected_asset_keys() -> tuple[str, ...]:
    keys = [spec.mesh_key for spec in HOUSING_SPECS.values() if spec.mesh_key]
    keys.extend(MOUNT_MESH_SPECS)
    return tuple(dict.fromkeys(keys))


def _origin_violations(key: str, extents: MeshExtents, origin: str, tol: float) -> list[str]:
    min_x, min_y, min_z = extents.min_xyz
    max_x, max_y, max_z = extents.max_xyz
    notes: list[str] = []
    if origin == ORIGIN_HARDWARE:
        return notes
    if origin == ORIGIN_OUTPUT_FACE and abs(max_x) > tol:
        notes.append(f"{key} output face max_x={max_x:g} mm, expected 0")
    elif origin == ORIGIN_INPUT_FACE and abs(min_x) > tol:
        notes.append(f"{key} input face min_x={min_x:g} mm, expected 0")
    elif origin == ORIGIN_CENTER and abs(0.5 * (min_x + max_x)) > tol:
        notes.append(f"{key} centre mid_x={0.5 * (min_x + max_x):g} mm, expected 0")
    elif origin == ORIGIN_TOP and abs(max_z) > tol:
        notes.append(f"{key} top max_z={max_z:g} mm, expected 0")
    elif origin == ORIGIN_BOTTOM and abs(min_z) > tol:
        notes.append(f"{key} bottom min_z={min_z:g} mm, expected 0")
    if origin not in {ORIGIN_TOP, ORIGIN_BOTTOM} and abs(0.5 * (min_y + max_y)) > tol:
        notes.append(f"{key} not centred in Y")
    if origin not in {ORIGIN_TOP, ORIGIN_BOTTOM} and abs(0.5 * (min_z + max_z)) > tol:
        notes.append(f"{key} not centred in Z")
    if origin in {ORIGIN_TOP, ORIGIN_BOTTOM}:
        if abs(0.5 * (min_x + max_x)) > tol or abs(0.5 * (min_y + max_y)) > tol:
            notes.append(f"{key} not centred in XY")
    return notes


def shipped_mesh_violations(*, tol_mm: float = NATIVE_AABB_TOL_MM) -> tuple[str, ...]:
    """Empty when missing (procedural fallback) or when each present glb matches spec."""
    notes: list[str] = []
    for key, spec in NATIVE_MESH_SPECS.items():
        extents = mesh_extents(key)
        if extents is None:
            continue
        for index, axis in enumerate("xyz"):
            actual_min = extents.min_xyz[index]
            actual_max = extents.max_xyz[index]
            if abs(actual_min - spec.min_xyz[index]) > tol_mm:
                notes.append(f"{key} min_{axis}={actual_min:g} mm, spec {spec.min_xyz[index]:g}")
            if abs(actual_max - spec.max_xyz[index]) > tol_mm:
                notes.append(f"{key} max_{axis}={actual_max:g} mm, spec {spec.max_xyz[index]:g}")
        notes.extend(_origin_violations(key, extents, spec.origin, tol_mm))
    return tuple(notes)


def inventory() -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for key in expected_asset_keys():
        path = resolve_asset_file(key)
        extents = mesh_extents(key) if path is not None else None
        native = NATIVE_MESH_SPECS.get(key)
        target = visual_housing(key) if key in HOUSING_SPECS and key != POST_STEM_KEY else None
        placement = None
        if extents is not None and target is not None:
            placement = fit_mesh_to_housing(extents, target)
        elif extents is not None and key == POST_STEM_KEY:
            placement = stem_mesh_placement(AXIS_HEIGHT_MM, extents)
        rows[key] = {
            "key": key,
            "path": str(path) if path is not None else "",
            "present": path is not None,
            "role": "stem" if key == POST_STEM_KEY else ("bench" if key == BREADBOARD_KEY else "body"),
            "axes": MESH_AXES,
            "origin": None if native is None else native.origin,
            "native_min": None if extents is None else [round(value, 4) for value in extents.min_xyz],
            "native_max": None if extents is None else [round(value, 4) for value in extents.max_xyz],
            "spec_min": None if native is None else list(native.min_xyz),
            "spec_max": None if native is None else list(native.max_xyz),
            "aperture_mm": None if extents is None else round(extents.aperture_mm, 3),
            "thickness_mm": None if extents is None else round(extents.thickness_mm, 3),
            "catalog": HOUSING_SPECS[key].catalog if key in HOUSING_SPECS else None,
            "visual_length_mm": POST_DIAMETER_MM if key == POST_STEM_KEY else (None if target is None else target.length_mm),
            "visual_aperture_mm": POST_DIAMETER_MM if key == POST_STEM_KEY else (None if target is None else target.aperture_mm),
            "scale": None if placement is None else [round(value, 6) for value in placement.scale],
        }
    return rows


def check_assets() -> dict[str, Any]:
    """Return presence and spec report.  Missing files are OK (procedural fallback)."""
    rows = inventory()
    present = [key for key, row in rows.items() if row["present"]]
    missing = [key for key, row in rows.items() if not row["present"]]
    empty: list[str] = []
    if ASSET_DIR.is_dir():
        for suffix in ASSET_SUFFIXES:
            for path in ASSET_DIR.glob(f"*{suffix}"):
                if path.stat().st_size <= 0:
                    empty.append(path.name)
    unexpected = []
    if ASSET_DIR.is_dir():
        expected_names = {f"{key}{suffix}" for key in expected_asset_keys() for suffix in ASSET_SUFFIXES}
        for path in ASSET_DIR.iterdir():
            if path.suffix.lower() in ASSET_SUFFIXES and path.name not in expected_names and path.name not in {"README.md"}:
                unexpected.append(path.name)
    violations = shipped_mesh_violations()
    return {
        "asset_dir": str(ASSET_DIR),
        "present": present,
        "missing": missing,
        "empty": empty,
        "unexpected": unexpected,
        "violations": list(violations),
        "fallback": "procedural" if missing else "mesh",
        "ok": not empty and not unexpected and not violations,
        "files": rows,
    }


def main() -> int:
    report = check_assets()
    print(f"asset_dir: {report['asset_dir']}")
    print(f"axes: {MESH_AXES}")
    print(f"present: {', '.join(report['present']) or '（无，使用程序几何）'}")
    print(f"missing: {', '.join(report['missing']) or '（齐）'}")
    for key, row in report["files"].items():
        catalog = row.get("catalog") or ("hardware mount" if key.startswith("mount_") else f"dia{POST_DIAMETER_MM:g} post x z_mm")
        length = row.get("visual_length_mm")
        aperture = row.get("visual_aperture_mm")
        housing = f"{length:g}×{aperture:g} mm" if length is not None and aperture is not None else "hardware"
        if row["present"] and row.get("native_min") is not None:
            print(
                f"  {key}: native {row['native_min']}..{row['native_max']}"
                f" -> housing {housing} ({catalog})"
                + (f"  scale {row['scale']}" if row.get("scale") else "")
            )
        else:
            print(f"  {key}: missing → housing {housing} ({catalog})")
    if report["empty"]:
        print(f"empty: {', '.join(report['empty'])}")
    if report["unexpected"]:
        print(f"unexpected: {', '.join(report['unexpected'])}")
    if report["violations"]:
        print("violations:")
        for note in report["violations"]:
            print(f"  {note}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

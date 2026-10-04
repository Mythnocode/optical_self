from fastapi import APIRouter, Body, Request, status

from backend.optical_ml_app.api.multipath_models import MultiPathSimulationRequest
from backend.optical_ml_app.api.responses import failure, success
from shared_contracts.simulation import SimulationRequest
from shared_contracts.project import ProjectSnapshot
from pydantic import BaseModel, Field
from typing import Literal


router = APIRouter()

class QuantityParseRequest(BaseModel):
    text: str = Field(max_length=4096)
    target_unit: str = Field(default="", max_length=128)

@router.post("/simulation/quantities/parse")
def parse_editor_quantity(payload: QuantityParseRequest, request: Request):
    from math import isfinite
    from shared_presentation.quantities import parse_quantity
    try:
        value = parse_quantity(payload.text, payload.target_unit)
        if not isfinite(value):
            raise ValueError("请输入有限数值")
        return success(request, {"value": value})
    except (ValueError, TypeError, OverflowError) as exc:
        return failure(request, status_code=422, code="QUANTITY_INVALID", stage="quantity.parse", message=str(exc))

@router.post("/simulation/surfaces/serialize")
def serialize_editor_surfaces(payload: ProjectSnapshot, request: Request):
    from backend.optical_ml_app.application.surface_presentation import canonical_surfaces
    from shared_contracts.project import SurfaceSnapshot
    try:
        rows = canonical_surfaces(payload.model_dump(mode="python"))
        # Validate at the same formal DTO boundary before returning to the renderer.
        for row in rows:
            SurfaceSnapshot.model_validate(row)
        return success(request, {"surfaces": rows})
    except (ValueError, TypeError, OverflowError, KeyError) as exc:
        return failure(request, status_code=422, code="SURFACE_EDITOR_INVALID", stage="surfaces.serialize", message=str(exc))

class CustomMaterialRecord(BaseModel):
    name: str = Field(min_length=1, max_length=256)
    model: Literal["constant", "cauchy", "sellmeier"] = "constant"
    custom: bool = True
    n: float = Field(1.5, ge=1, le=8, allow_inf_nan=False)
    k: float = Field(0, ge=0, le=20, allow_inf_nan=False)
    a: float = Field(1.5, ge=0, le=20, allow_inf_nan=False)
    b_um2: float = Field(0, ge=-1e6, le=1e6, allow_inf_nan=False)
    c_um4: float = Field(0, ge=-1e6, le=1e6, allow_inf_nan=False)
    b1: float = Field(0, ge=-1e6, le=1e6, allow_inf_nan=False)
    b2: float = Field(0, ge=-1e6, le=1e6, allow_inf_nan=False)
    b3: float = Field(0, ge=-1e6, le=1e6, allow_inf_nan=False)
    c1_um2: float = Field(0, ge=-1e6, le=1e6, allow_inf_nan=False)
    c2_um2: float = Field(0, ge=-1e6, le=1e6, allow_inf_nan=False)
    c3_um2: float = Field(0, ge=-1e6, le=1e6, allow_inf_nan=False)

class MaterialLibraryRequest(BaseModel):
    wavelength_nm: float = Field(780, gt=0, le=30000, allow_inf_nan=False)
    custom_materials: list[CustomMaterialRecord] = Field(default_factory=list, max_length=256)
    used_names: list[str] = Field(default_factory=list, max_length=4096)

@router.post("/simulation/projects/validate")
def validate_project_file(request: Request, payload: dict = Body(...)):
    from backend.optical_ml_app.application.project_files import validate_project_file as validate
    try:
        validate(payload)
        custom = (payload.get("frontend_state") or {}).get("custom_materials", [])
        if not isinstance(custom, list) or len(custom) > 256:
            raise ValueError("项目自定义材料数据无效")
        for record in custom:
            CustomMaterialRecord.model_validate(record, strict=True)
        observation = (payload.get("frontend_state") or {}).get("observation")
        if observation is not None:
            ObservationDisplay.model_validate(observation, strict=True)
        return success(request, {"valid": True})
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        return failure(request, status_code=422, code="PROJECT_FILE_INVALID", stage="projects.open", message=str(exc))

@router.post("/simulation/materials")
def materials(payload: MaterialLibraryRequest, request: Request):
    from backend.optical_ml_app.application.material_presentation import material_library
    try:
        custom = [item.model_dump(exclude_unset=True) for item in payload.custom_materials]
        return success(request, material_library(payload.wavelength_nm, custom, payload.used_names))
    except (ValueError, TypeError, OverflowError) as exc:
        return failure(request, status_code=422, code="MATERIAL_LIBRARY_INVALID", stage="materials.presentation", message=str(exc))

class ObservationDisplay(BaseModel):
    enabled: bool = True
    mode: Literal["surface", "fiber", "custom"] = "surface"
    surface_index: int = Field(0, ge=0)
    offset_mm: float = Field(0, ge=-1e6, le=1e6, allow_inf_nan=False)
    pitch_um: float = Field(5, ge=.001, le=1e6, allow_inf_nan=False)
    pixels_x: int = Field(1024, ge=1, le=1000000)
    pixels_y: int = Field(1024, ge=1, le=1000000)

class DisplayProfile(BaseModel):
    auto_display_frame: bool = True
    display_fill_fraction: float = Field(0.6700000166893005, ge=.1, le=1, allow_inf_nan=False)

class PresentationRequest(BaseModel):
    project: ProjectSnapshot
    kind: Literal["ray_layout", "layout_3d", "spot", "coupling", "wavefront"]
    observation: ObservationDisplay = Field(default_factory=ObservationDisplay)
    display_profile: DisplayProfile = Field(default_factory=DisplayProfile)

@router.post("/simulation/jobs/{job_id}/presentation")
def simulation_presentation(job_id: str, payload: PresentationRequest, request: Request):
    from backend.optical_ml_app.application.simulation_presentation import build_presentation
    from shared_presentation.local_arrays import materialize_local_arrays
    manager = request.app.state.services["task_manager"]
    try:
        result = manager.get_result(job_id)
        if manager.get_status(job_id).job_type != "simulation":
            raise ValueError("所选任务不是仿真任务")
        result = materialize_local_arrays(result)
        return success(request, build_presentation(result, payload.project.model_dump(mode="json"), payload.kind,
            payload.observation.model_dump(), payload.display_profile.model_dump()))
    except FileNotFoundError:
        return failure(request, status_code=404, code="JOB_NOT_FOUND", stage="simulation.presentation", message="未找到任务或结果数组")
    except RuntimeError as exc:
        return failure(request, status_code=409, code="JOB_RESULT_NOT_AVAILABLE", stage="simulation.presentation", message=str(exc))
    except (ValueError, TypeError, KeyError) as exc:
        return failure(request, status_code=422, code="PRESENTATION_INVALID", stage="simulation.presentation", message=str(exc))


@router.post("/simulation/import-complex-field")
def import_complex_field(request: Request, payload: dict = Body(...)):
    """Read a user-selected field with the same loader used by the Qt frontend."""
    import base64
    from zipfile import BadZipFile
    from pathlib import Path
    from tempfile import TemporaryDirectory
    from backend.optical_ml_app.application.complex_fields import load_complex_field

    try:
        grid = int(payload.get("expected_grid_size", 513))
        if grid not in {65, 129, 257, 513, 1025}:
            raise ValueError("请选择支持的接收面网格")
        source_path = str(payload.get("source_path", "") or "")
        if source_path:
            if Path(source_path).stat().st_size > 32 * 1024 * 1024:
                raise ValueError("复场文件超过 32 MiB")
            data = load_complex_field(source_path, expected_grid_size=grid)
            display_name = data.path
        else:
            filename = Path(str(payload.get("filename", "field.npy"))).name
            suffix = Path(filename).suffix.lower()
            if suffix not in {".npy", ".npz", ".csv"}:
                raise ValueError("仅支持 NPY、NPZ 和 CSV 文件")
            encoded = payload.get("contents_base64", "")
            if not isinstance(encoded, str) or len(encoded) > 44 * 1024 * 1024:
                raise ValueError("复场文件超过 32 MiB")
            contents = base64.b64decode(encoded, validate=True)
            if len(contents) > 32 * 1024 * 1024:
                raise ValueError("复场文件超过 32 MiB")
            with TemporaryDirectory(prefix="optical-field-") as folder:
                path = Path(folder) / f"field{suffix}"
                path.write_bytes(contents)
                data = load_complex_field(path, expected_grid_size=grid)
            display_name = filename
        return success(request, {**data.request_payload(), "path": display_name, "interpretation": data.interpretation})
    except (ValueError, TypeError, OSError, EOFError, BadZipFile) as exc:
        return failure(request, status_code=422, code="COMPLEX_FIELD_INVALID", stage="import", message=str(exc))


@router.post("/simulation/jobs", status_code=status.HTTP_202_ACCEPTED)
def submit_simulation(payload: SimulationRequest, request: Request):
    job_id = request.app.state.services["simulation_app"].submit(payload)
    return success(request, {"job_id": job_id}, status_code=status.HTTP_202_ACCEPTED)


@router.post("/simulation/multipath/jobs", status_code=status.HTTP_202_ACCEPTED)
def submit_multi_path_simulation(payload: MultiPathSimulationRequest, request: Request):
    job_id = request.app.state.services["simulation_app"].submit(payload)
    return success(request, {"job_id": job_id}, status_code=status.HTTP_202_ACCEPTED)


@router.post("/simulation/surrogate-preview")
def surrogate_preview(request: Request, payload: dict = Body(...)):
    result = dict(request.app.state.services["surrogate_preview_app"].preview(payload))
    result["request_id"] = str(payload.get("request_id", "") or "")
    return success(request, result)

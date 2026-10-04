from fastapi import APIRouter, Body, Request, Response, status
from shared_contracts.datasets import DatasetGenerationRequest

from backend.optical_ml_app.api.responses import failure, success
from backend.optical_ml_app.domain.error_codes import DATASET_FILE_NOT_FOUND, DATASET_NOT_FOUND
from backend.optical_ml_app.domain.errors import BackendApplicationError
from pydantic import BaseModel, Field
from typing import Literal
from shared_contracts.project import ProjectSnapshot


router = APIRouter()

def _catalog_presentation(registry, item: dict) -> dict:
    entry = registry.get(str(item['dataset_id']))
    metadata = dict(entry.metadata or {})
    return {**item, 'dataset_layout': metadata.get('dataset_layout', 'tabular')}

class GenerationOptions(BaseModel):
    dataset_name: str = Field(min_length=1, max_length=256)
    family: Literal['tabular', 'sequence'] = 'tabular'
    lens_count: int = Field(default=4, ge=1, le=4)
    include_conic: bool = False
    variable_paths: list[str] = Field(default_factory=list, max_length=256)
    sample_count: int = Field(default=50, ge=8, le=100000)
    target: Literal['耦合损耗(dB)', '耦合效率', 'RMS 光斑', 'Strehl'] = '耦合损耗(dB)'
    sampling: Literal['Latin Hypercube', 'Sobol低差异采样'] = 'Latin Hypercube'
    validation_ratio: float = Field(default=0.15, ge=0.05, le=0.4)
    random_seed: int = Field(default=42, ge=0, le=1000000000)
    precision: Literal['129×129', '257×257', '513×513'] = '257×257'

class GenerationPrepareRequest(BaseModel):
    project: ProjectSnapshot
    options: GenerationOptions
    simulation_options: dict = Field(default_factory=dict)

@router.post('/datasets/generation/presentation')
def read_generation_presentation(payload: ProjectSnapshot, request: Request):
    from backend.optical_ml_app.application.dataset_presentation import generation_presentation
    try:
        return success(request, generation_presentation(payload.model_dump(mode='python')))
    except (ValueError, TypeError, KeyError) as exc:
        return failure(request, status_code=422, code='DATASET_PROJECT_INVALID', stage='dataset.presentation', message=str(exc))

@router.post('/datasets/generation/prepare')
def prepare_generation(payload: GenerationPrepareRequest, request: Request):
    from shared_presentation.dataset_generation import generation_payload
    try:
        prepared = generation_payload(payload.project.model_dump(mode='python', exclude_unset=True), payload.options.model_dump(), payload.simulation_options)
        DatasetGenerationRequest.model_validate(prepared)
        return success(request, prepared)
    except (ValueError, TypeError, KeyError) as exc:
        return failure(request, status_code=422, code='DATASET_PARAMETERS_INVALID', stage='dataset.prepare', message=str(exc))


@router.post("/dataset/jobs", status_code=status.HTTP_202_ACCEPTED)
def submit_dataset(payload: DatasetGenerationRequest, request: Request):
    job_id = request.app.state.services["dataset_app"].submit(payload)
    return success(request, {"job_id": job_id}, status_code=status.HTTP_202_ACCEPTED)


@router.post("/headless-datasets/import-file")
def import_dataset_file(request: Request, payload: dict = Body(...)):
    """Register a user-selected local table as a native trainable dataset."""
    try:
        registry = request.app.state.services["dataset_registry"]
        entry = registry.import_tabular_file(
            str(payload.get("source_path", "") or ""),
            dataset_name=str(payload.get("dataset_name", "") or ""),
            target_name=str(payload.get("target_name", "coupling_efficiency") or "coupling_efficiency"),
            random_seed=int(payload.get("random_seed", 42) or 42),
        )
        return success(request, entry.to_dict())
    except BackendApplicationError as exc:
        return failure(request, status_code=400, **exc.to_dict())


@router.get("/headless-datasets")
def list_datasets(
    request: Request,
    dataset_type: str | None = None,
    limit: int = 20,
    offset: int = 0,
):
    try:
        registry = request.app.state.services["dataset_registry"]
        catalog = registry.list(dataset_type=dataset_type, limit=limit, offset=offset)
        return success(request, {**catalog, 'items': [_catalog_presentation(registry, item) for item in catalog['items']]})
    except BackendApplicationError as exc:
        return failure(request, status_code=404, **exc.to_dict())


@router.get("/headless-datasets/{dataset_id}")
def get_dataset(dataset_id: str, request: Request):
    try:
        registry = request.app.state.services["dataset_registry"]
        return success(request, _catalog_presentation(registry, registry.get(dataset_id).to_dict()))
    except BackendApplicationError as exc:
        status_code = 404 if exc.code == DATASET_NOT_FOUND else 400
        return failure(request, status_code=status_code, **exc.to_dict())


@router.get("/headless-datasets/{dataset_id}/files/manifest")
def download_manifest(dataset_id: str, request: Request):
    try:
        registry = request.app.state.services["dataset_registry"]
        return Response(content=registry.read_manifest_json(dataset_id), media_type="application/json")
    except BackendApplicationError as exc:
        status_code = 404 if exc.code in (DATASET_NOT_FOUND, DATASET_FILE_NOT_FOUND) else 400
        return failure(request, status_code=status_code, **exc.to_dict())


@router.get("/headless-datasets/{dataset_id}/files/samples-flat")
def download_samples_flat(dataset_id: str, request: Request):
    try:
        registry = request.app.state.services["dataset_registry"]
        return Response(content=registry.read_samples_flat_csv(dataset_id), media_type="text/csv")
    except BackendApplicationError as exc:
        status_code = 404 if exc.code in (DATASET_NOT_FOUND, DATASET_FILE_NOT_FOUND) else 400
        return failure(request, status_code=status_code, **exc.to_dict())


@router.get("/headless-datasets/{dataset_id}/files/samples-jsonl")
def download_samples_jsonl(dataset_id: str, request: Request):
    try:
        registry = request.app.state.services["dataset_registry"]
        return Response(
            content=registry.read_samples_jsonl(dataset_id),
            media_type="application/x-ndjson",
        )
    except BackendApplicationError as exc:
        status_code = 404 if exc.code in (DATASET_NOT_FOUND, DATASET_FILE_NOT_FOUND) else 400
        return failure(request, status_code=status_code, **exc.to_dict())

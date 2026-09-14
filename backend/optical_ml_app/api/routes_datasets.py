from fastapi import APIRouter, Body, Request, Response, status
from shared_contracts.datasets import DatasetGenerationRequest

from backend.optical_ml_app.api.responses import failure, success
from backend.optical_ml_app.domain.error_codes import DATASET_FILE_NOT_FOUND, DATASET_NOT_FOUND
from backend.optical_ml_app.domain.errors import BackendApplicationError


router = APIRouter()


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
        return success(request, registry.list(dataset_type=dataset_type, limit=limit, offset=offset))
    except BackendApplicationError as exc:
        return failure(request, status_code=404, **exc.to_dict())


@router.get("/headless-datasets/{dataset_id}")
def get_dataset(dataset_id: str, request: Request):
    try:
        registry = request.app.state.services["dataset_registry"]
        return success(request, registry.get(dataset_id).to_dict())
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

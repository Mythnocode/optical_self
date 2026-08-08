from fastapi import APIRouter, Request

from backend.optical_ml_app.api.responses import success
from shared_contracts.versions import API_VERSION, APP_VERSION, CONTRACT_VERSION


router = APIRouter()


@router.get("/health")
def health(request: Request):
    settings = request.app.state.services["settings"]
    return success(
        request,
        {
            "status": "healthy",
            "default_engine": settings.simulation_engine,
        },
    )


@router.get("/version")
def version(request: Request):
    return success(
        request,
        {
            "app_version": APP_VERSION,
            "api_version": API_VERSION,
            "contract_version": CONTRACT_VERSION,
        },
    )


@router.get("/capabilities")
def capabilities(request: Request):
    services = request.app.state.services
    return success(
        request,
        {
            "default_engine": services["settings"].simulation_engine,
            "engines": services["engine_registry"].capabilities(),
            "precision_profiles": ["preview", "standard", "high"],
            "dataset_sampling_methods": ["latin_hypercube", "sobol"],
            "model_types": ["random_forest", "xgboost_physics_residual"],
            "structure_model_types": ["bilstm_structure_sequence"],
            "optimization_workflow": [
                "registered_surrogate_coarse_search",
                "bayesian_or_de",
                "powell_formal_refine",
                "formal_verify",
            ],
            "contract_version": CONTRACT_VERSION,
        },
    )

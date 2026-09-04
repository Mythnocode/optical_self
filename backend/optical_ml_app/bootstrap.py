from backend.optical_ml_app.runtime_env import configure_native_thread_limits
from backend.optical_ml_app.demo_assets import install_packaged_demo_assets

configure_native_thread_limits()

from backend.optical_ml_app.application.dataset_registry_service import DatasetRegistryService
from backend.optical_ml_app.application.dataset_service import DatasetApplicationService
from backend.optical_ml_app.application.model_extension_service import ModelExtensionService
from backend.optical_ml_app.application.structure_model_service import StructureModelApplicationService
from backend.optical_ml_app.application.prediction_service import PredictionApplicationService
from backend.optical_ml_app.application.simulation_service import SimulationApplicationService
from backend.optical_ml_app.application.training_service import TrainingApplicationService
from backend.optical_ml_app.engines.registry import EngineRegistry
from backend.optical_ml_app.infrastructure.logging_config import configure_logging
from backend.optical_ml_app.jobs.event_bus import JobEventBus
from backend.optical_ml_app.jobs.task_manager import TaskManager
from backend.optical_ml_app.settings import load_settings
from backend.optical_ml_app.storage.filesystem_job_repository import FileJobRepository
from machine_learning.datasets.storage import FileDatasetStore
from machine_learning.inference.predictor import Predictor
from machine_learning.registry.model_registry import FileModelRegistry
from machine_learning.training.service import TrainingService
from backend.optical_ml_app.application.headless_dataset_service import HeadlessDatasetApplicationService
from backend.optical_ml_app.application.scan_service import ScanApplicationService
from backend.optical_ml_app.application.optimization_service import OptimizationApplicationService
from backend.optical_ml_app.application.tolerance_service import ToleranceApplicationService
from backend.optical_ml_app.application.verification_service import VerificationApplicationService
from backend.optical_ml_app.application.surrogate_preview_service import SurrogatePreviewService


def create_services():
    settings = load_settings()
    settings.user_data_dir.mkdir(parents=True, exist_ok=True)
    configure_logging(settings.user_data_dir / "logs", settings.log_level)
    # Copy only missing packaged 示例 assets.  This never changes current model or
    # current project state and never overwrites user-created files.
    install_packaged_demo_assets(settings.user_data_dir)

    event_bus = JobEventBus()
    job_repository = FileJobRepository(settings.user_data_dir / "jobs")
    recovered = job_repository.recover_interrupted_jobs()
    if recovered:
        import logging
        logging.getLogger(__name__).warning(
            "marked %d interrupted jobs failed after backend restart", len(recovered)
        )
    task_manager = TaskManager(
        job_repository,
        event_bus=event_bus,
        persistent_workers={
            "simulation": settings.simulation_worker_count,
            "training": settings.training_worker_count,
            "bilstm_structure_training": settings.training_worker_count,
            # These long-running research jobs used to spawn a fresh process
            # and rebuild the optical engine on every submission.  Keep one
            # lazily-created worker for each job family so repeated research
            # work can reuse process imports and worker-local engine caches.
            "scan": settings.analysis_worker_count,
            "tolerance": settings.analysis_worker_count,
            "dataset": settings.analysis_worker_count,
            "headless_dataset": settings.analysis_worker_count,
            "optimization": settings.analysis_worker_count,
            "verification": settings.analysis_worker_count,
        },
        internal_thread_limit=settings.native_thread_limit,
    )
    engine_registry = EngineRegistry(settings)
    dataset_store = FileDatasetStore(settings.user_data_dir / "datasets")
    dataset_registry = DatasetRegistryService(dataset_store)
    model_registry = FileModelRegistry(settings.user_data_dir / "models")
    training_service = TrainingService(dataset_store, model_registry)
    predictor = Predictor(model_registry)
    return {
        "settings": settings,
        "event_bus": event_bus,
        "task_manager": task_manager,
        "engine_registry": engine_registry,
        "dataset_store": dataset_store,
        "dataset_registry": dataset_registry,
        "model_registry": model_registry,
        "simulation_app": SimulationApplicationService(
            task_manager,
        ),
        "dataset_app": DatasetApplicationService(task_manager, dataset_store, dataset_registry),
        "training_app": TrainingApplicationService(task_manager, training_service, dataset_registry),
        "prediction_app": PredictionApplicationService(predictor),
        "surrogate_preview_app": SurrogatePreviewService(model_registry),
        "model_extension_app": ModelExtensionService(
            model_registry=model_registry,
            dataset_store=dataset_store,
        ),
        "structure_model_app": StructureModelApplicationService(
            task_manager, settings.user_data_dir / "structure_models"
        ),
        "tolerance_app": ToleranceApplicationService(task_manager),
        "scan_app": ScanApplicationService(task_manager),
        "optimization_app": OptimizationApplicationService(
            task_manager, str(dataset_store.root), model_registry
        ),
        "headless_dataset_app": HeadlessDatasetApplicationService(
            task_manager,
            engine_registry,
            dataset_store,
            dataset_registry,
        ),
        "verification_app": VerificationApplicationService(
            task_manager,
            model_registry,
        ),
    }

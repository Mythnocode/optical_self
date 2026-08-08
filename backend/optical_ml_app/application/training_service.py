from pathlib import Path

from machine_learning.training.service import TrainingService
from machine_learning.datasets.storage import FileDatasetStore
from machine_learning.registry.model_registry import FileModelRegistry

from backend.optical_ml_app.application.ports import DatasetRegistryPort, TaskManagerPort


def _run_training_task(context, request, dataset_root: str, model_root: str):
    store = FileDatasetStore(Path(dataset_root))
    model_registry = FileModelRegistry(Path(model_root))
    trainer = TrainingService(store, model_registry)
    return trainer.train(request, context.cancellation, context.progress)


class TrainingApplicationService:
    def __init__(
        self,
        task_manager: TaskManagerPort,
        training_service: TrainingService,
        dataset_registry: DatasetRegistryPort,
    ):
        self.task_manager = task_manager
        self.training_service = training_service
        self.dataset_registry = dataset_registry

    def submit(self, request):
        
        return self.task_manager.submit(
            "training",
            _run_training_task,
            request,
            str(self.training_service.dataset_store.root),
            str(self.training_service.model_registry.root),
            timeout_seconds=600.0,
        )

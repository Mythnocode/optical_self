from pathlib import Path

from machine_learning.datasets.generator import DatasetGenerator
from machine_learning.datasets.storage import FileDatasetStore
from optical_runtime import create_optical_simulation_engine

from backend.optical_ml_app.application.ports import (
    DatasetRegistryPort,
    EngineResolverPort,
    TaskManagerPort,
)
from backend.optical_ml_app.runtime_env import configured_batch_worker_count


def _run_dataset_task(context, request, dataset_root: str):
    store = FileDatasetStore(Path(dataset_root))
    engine = context.get_or_create_resource(
        "optical_engine", create_optical_simulation_engine
    )
    generator = DatasetGenerator(engine, store)
    return generator.generate(
        request,
        context.cancellation,
        context.progress,
        max_workers=configured_batch_worker_count(),
    )


class DatasetApplicationService:
    def __init__(
        self,
        task_manager: TaskManagerPort,
        dataset_store,
        dataset_registry: DatasetRegistryPort,
    ):
        self.task_manager = task_manager
        self.dataset_store = dataset_store
        self.dataset_registry = dataset_registry

    def submit(self, request):
        
        
        sample_count = int(getattr(request, "sample_count", 1000) or 1000)
        timeout = max(60.0, float(sample_count) * 1.8)  
        return self.task_manager.submit(
            "dataset",
            _run_dataset_task,
            request,
            str(self.dataset_store.root),
            on_result=lambda manifest: self.dataset_registry.register(manifest),
            timeout_seconds=timeout,
        )

from pathlib import Path
from functools import partial

from machine_learning.datasets.generator import DatasetGenerator
from machine_learning.datasets.storage import FileDatasetStore
from optical_runtime import create_optical_simulation_engine

from backend.optical_ml_app.application.ports import (
    DatasetRegistryPort,
    EngineResolverPort,
    TaskManagerPort,
)
from backend.optical_ml_app.application.dataset_registry_service import DatasetRegistryService
from backend.optical_ml_app.runtime_env import configured_batch_worker_count


DATASET_STARTUP_TIMEOUT_SECONDS = 30.0
DATASET_SECONDS_PER_SAMPLE = 15.0
DATASET_MIN_TIMEOUT_SECONDS = 300.0


def dataset_timeout_seconds(sample_count: int) -> float:
    """Return a conservative wall-clock budget for formal dataset samples.

    Dataset samples use the same wave-optics coupling path as formal
    verification.  On the supported desktop this currently takes roughly
    8--9 seconds per sample, so the old 1.8 seconds/sample budget terminated
    healthy jobs while they were still reporting progress.
    """

    count = max(1, int(sample_count or 1))
    estimated = DATASET_STARTUP_TIMEOUT_SECONDS + count * DATASET_SECONDS_PER_SAMPLE
    return max(DATASET_MIN_TIMEOUT_SECONDS, estimated)


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


def _register_dataset_manifest(manifest, dataset_root: str):
    """Persistable completion callback used by task retry payloads.

    The API service's live registry owns process-local state, including locks.
    A retry payload must not capture that service.  Rebuilding the lightweight
    registry from its shared dataset directory keeps the callback picklable;
    the API registry refreshes from the same directory when it is next read.
    """
    store = FileDatasetStore(Path(dataset_root))
    DatasetRegistryService(store).register(manifest)


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
        timeout = dataset_timeout_seconds(sample_count)
        return self.task_manager.submit(
            "dataset",
            _run_dataset_task,
            request,
            str(self.dataset_store.root),
            on_result=partial(_register_dataset_manifest, dataset_root=str(self.dataset_store.root)),
            timeout_seconds=timeout,
            # A sample reports progress after each formal evaluation.  Treat a
            # long lack of progress as a stuck worker independently of the
            # conservative total wall-clock budget above.
            stall_timeout_seconds=300.0,
        )

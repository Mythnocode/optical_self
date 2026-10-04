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


def _run_dataset_task(context, request, dataset_root: str):
    store = FileDatasetStore(Path(dataset_root))
    engine = context.get_or_create_resource(
        "optical_engine", create_optical_simulation_engine
    )
    generator = DatasetGenerator(engine, store)
    manifest = generator.generate(
        request,
        context.cancellation,
        context.progress,
        max_workers=configured_batch_worker_count(),
    )
    # A cancelled generation may have no valid systems. Let the job worker
    # finish cancellation before sequence export applies its training gate.
    if context.cancellation.is_cancelled or manifest.status == "cancelled":
        return manifest
    if getattr(request, "dataset_layout", "tabular") == "sequence_long":
        from machine_learning.datasets.sequence_export import export_sequence_long_table

        sequence_metadata = export_sequence_long_table(manifest, store)
        manifest.metadata.update({"dataset_layout": "sequence_long", **sequence_metadata})
        store.save_manifest(manifest)
    return manifest


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
        return self.task_manager.submit(
            "dataset",
            _run_dataset_task,
            request,
            str(self.dataset_store.root),
            on_result=partial(_register_dataset_manifest, dataset_root=str(self.dataset_store.root)),
            # Dataset duration depends on the optical system and the host
            # hardware, so do not impose a total wall-clock deadline.  The
            # manager still fails a genuinely wedged worker after five
            # minutes with no activity, and the UI exposes explicit cancel.
            timeout_seconds=None,
            stall_timeout_seconds=300.0,
        )

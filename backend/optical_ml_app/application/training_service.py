from pathlib import Path

from machine_learning.training.service import TrainingService
from machine_learning.datasets.storage import FileDatasetStore
from machine_learning.registry.model_registry import FileModelRegistry

from backend.optical_ml_app.application.ports import DatasetRegistryPort, TaskManagerPort
from shared_contracts.training import JointTrainingRequest, JointTrainingResult, TrainingRequest


class TrainingPreflightError(ValueError):
    """Raised before a joint task is submitted when its dataset is incompatible."""


def _joint_training_preflight(store: FileDatasetStore, request: JointTrainingRequest) -> None:
    from machine_learning.features.coupling_physics import PHYSICS_RESIDUAL_FEATURE_PATHS

    manifest = store.load_manifest(request.dataset_id)
    records = [record for record in store.iter_samples(request.dataset_id) if record.get("valid")]
    if not records:
        raise TrainingPreflightError("数据集没有有效样本，无法开始联合训练。请重新生成并检查正式仿真质量。")

    feature_paths = {str(path) for path in (getattr(manifest, "feature_paths", None) or [])}
    design_paths = list(getattr(manifest, "design_variable_paths", None) or [])
    missing_design = [path for path in design_paths if path not in feature_paths]
    missing_physics = sorted(set(PHYSICS_RESIDUAL_FEATURE_PATHS) - feature_paths)
    if missing_design:
        raise TrainingPreflightError("数据集设计变量清单与特征列不一致，请重新生成数据集。")
    if not design_paths:
        raise TrainingPreflightError("数据集没有设计变量元数据，不能用于当前曲率半径/厚度/圆锥系数闭环。")
    if missing_physics:
        raise TrainingPreflightError(
            "数据集缺少 XGBoost 物理中间特征：" + ", ".join(missing_physics)
            + "。请生成包含耦合效率和解析物理特征的数据集。"
        )
    if len(records) < 12:
        raise TrainingPreflightError(
            f"数据集只有 {len(records)} 个有效样本，至少需要 12 个有效样本才能划分训练/验证/测试集。"
        )


def _run_training_task(context, request, dataset_root: str, model_root: str):
    store = FileDatasetStore(Path(dataset_root))
    model_registry = FileModelRegistry(Path(model_root))
    trainer = TrainingService(store, model_registry)
    return trainer.train(request, context.cancellation, context.progress)


class _ScaledProgress:
    def __init__(self, progress, start: float, stop: float):
        self.progress = progress
        self.start = float(start)
        self.span = float(stop) - float(start)

    def update(self, value: float, stage: str, *args):
        scaled = self.start + self.span * max(0.0, min(1.0, float(value)))
        self.progress.update(scaled, stage, *args)


def _run_joint_training_task(context, request: JointTrainingRequest, dataset_root: str, model_root: str):
    from uuid import uuid4

    store = FileDatasetStore(Path(dataset_root))
    registry = FileModelRegistry(Path(model_root))
    trainer = TrainingService(store, registry)
    context.progress.update(0.01, "training.joint.validating")
    random_forest = trainer.train(
        TrainingRequest(
            dataset_id=request.dataset_id,
            model_type="random_forest",
            target_names=["coupling_efficiency"],
            hyperparameters=dict(request.random_forest_hyperparameters),
            random_seed=request.random_seed,
        ),
        context.cancellation,
        _ScaledProgress(context.progress, 0.03, 0.48),
    )
    try:
        xgboost = trainer.train(
            TrainingRequest(
                dataset_id=request.dataset_id,
                model_type="xgboost_physics_residual",
                target_names=["coupling_loss_db"],
                hyperparameters=dict(request.xgboost_hyperparameters),
                random_seed=request.random_seed,
            ),
            context.cancellation,
            _ScaledProgress(context.progress, 0.50, 0.98),
        )
    except Exception as exc:
        context.progress.update(1.0, "training.joint.partial")
        return JointTrainingResult(
            bundle_id="bundle-" + uuid4().hex[:12],
            dataset_id=request.dataset_id,
            random_forest=random_forest,
            status="partial",
            warnings=[f"XGBoost训练失败：{type(exc).__name__}: {exc}"],
        )
    context.progress.update(1.0, "training.joint.completed")
    return JointTrainingResult(
        bundle_id="bundle-" + uuid4().hex[:12],
        dataset_id=request.dataset_id,
        random_forest=random_forest,
        xgboost=xgboost,
        primary_model_id=xgboost.model_id,
    )


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

    def submit_joint(self, request: JointTrainingRequest):
        store = FileDatasetStore(Path(self.training_service.dataset_store.root))
        _joint_training_preflight(store, request)
        return self.task_manager.submit(
            "training",
            _run_joint_training_task,
            request,
            str(self.training_service.dataset_store.root),
            str(self.training_service.model_registry.root),
            timeout_seconds=1200.0,
        )

"""Teaching Center V2 canvas and physics, used by TeachingShell."""

from .coordinates import (
    DEFAULT_TRANSFORM,
    FRAME_ENGINE,
    FRAME_RENDER,
    FRAME_TEACHING,
    FRAMES,
    FrameTransform,
    teaching_pose_to_render,
    teaching_pose_to_simulation,
)
from .model import OpticalComponent, Pose, ResultKind, SceneSnapshot, SceneStore
from .physics import FormalTeachingGateway, PhysicsRequest, PhysicsResult


def __getattr__(name):  # pragma: no cover - GUI branch belongs to desktop runs
    if name in {"ComputationController", "TaskState"}:
        from .tasks import ComputationController, TaskState
        return {
            "ComputationController": ComputationController,
            "TaskState": TaskState,
        }[name]
    raise AttributeError(name)


__all__ = [
    "ComputationController",
    "DEFAULT_TRANSFORM",
    "FRAME_ENGINE",
    "FRAME_RENDER",
    "FRAME_TEACHING",
    "FRAMES",
    "FormalTeachingGateway",
    "FrameTransform",
    "OpticalComponent",
    "PhysicsRequest",
    "PhysicsResult",
    "Pose",
    "ResultKind",
    "SceneSnapshot",
    "SceneStore",
    "TaskState",
    "teaching_pose_to_render",
    "teaching_pose_to_simulation",
]

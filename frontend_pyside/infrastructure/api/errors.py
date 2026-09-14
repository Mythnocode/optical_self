from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

_MESSAGES = {
    "BACKEND_RESTARTED": "后端在任务完成前发生了重启，本次任务没有产生正式结果。可以重新运行该任务。",
    "JOB_RESULT_NOT_AVAILABLE": "该任务没有可用的正式结果。",
    "JOB_LIVE_RESULT_NOT_AVAILABLE": "该任务当前没有可用的实时结果。",
    "JOB_NOT_FOUND": "后端未找到这个任务，可能已被清理或来自其他数据目录。",
    "JOB_RETRY_NOT_AVAILABLE": "该任务缺少可重放的提交信息，请返回原功能页重新提交。",
    "JOB_NOT_RETRYABLE": "该失败类型不适合直接重试，请先修正失败原因。",
    "JOB_CANNOT_RETRY": "只有失败或已取消的任务可以重新运行。",
    "JOB_RETRY_FAILED": "重新提交任务失败，请查看诊断信息后再试。",
    "QUEUE_TIMEOUT": "任务排队时间异常，长时间没有获得执行资源。可以重新运行，或检查后端 Worker 是否可用。",
    "WORKER_STALLED": "任务长时间没有新的工作进度，Worker 可能失去响应。可以重新运行，并检查后端日志。",
    "WORKER_EXITED": "执行任务的 Worker 意外退出，本次任务未完成。可以重新运行。",
    "WORKER_START_FAILED": "Worker 启动失败，本次任务未开始计算。可以重新运行。",
    "TIMEOUT": "任务运行超过允许时间，已停止。请减少计算规模或检查后端资源。",
    "RESULT_PERSIST_FAILED": "计算已结束，但结果保存失败。请检查磁盘空间和用户数据目录权限后重试。",
    "NETWORK_ERROR": "无法连接后端服务，请确认后端正在运行。",
    "INVALID_RESPONSE": "后端返回了无法解析的响应，请查看后端日志。",
    "MODEL_NOT_FOUND": "找不到这个模型，可能已被删除或模型目录不完整。请刷新模型列表或重新训练。",
    "MODEL_FEATURE_MISSING": "当前镜头组缺少该模型需要的特征，已停止预测；请使用匹配的镜头组或重新训练。",
    "MODEL_QUALITY_REJECTED": "该模型测试质量未达标，不能用于预测；请重新训练或更换模型。",
    "MODEL_PREDICTION_FAILED": "模型预测失败，请检查模型与当前镜头组是否匹配。",
}

@dataclass(frozen=True)
class ApiError:
    code: str = "REQUEST_FAILED"
    message: str = "请求失败"
    stage: str = ""
    retryable: bool = False
    request_id: str = ""
    context: dict[str, Any] = field(default_factory=dict)
    raw_message: str = ""

    @classmethod
    def from_response(cls, body: object, *, fallback_message: str = "请求失败", fallback_code: str = "REQUEST_FAILED") -> "ApiError":
        payload = body if isinstance(body, dict) else {}
        raw_error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
        code = str(raw_error.get("code") or payload.get("code") or fallback_code)
        raw_message = str(raw_error.get("message") or payload.get("message") or fallback_message)
        return cls(code=code, message=_MESSAGES.get(code, raw_message or fallback_message),
            stage=str(raw_error.get("stage") or ""), retryable=bool(raw_error.get("retryable", False)),
            request_id=str(payload.get("request_id") or raw_error.get("request_id") or ""),
            context=dict(raw_error.get("context") or {}), raw_message=raw_message)

    @classmethod
    def network(cls, message: str) -> "ApiError":
        return cls(code="NETWORK_ERROR", message=_MESSAGES["NETWORK_ERROR"], raw_message=str(message or ""), retryable=True)

    def user_message(self) -> str:
        return _MESSAGES.get(self.code, self.message or self.raw_message or "请求失败")

    def diagnostic_text(self) -> str:
        parts = [f"错误代码：{self.code}"]
        if self.stage: parts.append(f"阶段：{self.stage}")
        if self.request_id: parts.append(f"request_id：{self.request_id}")
        if self.raw_message and self.raw_message != self.user_message(): parts.append(f"原始信息：{self.raw_message}")
        return "\n".join(parts)

__all__ = ["ApiError"]

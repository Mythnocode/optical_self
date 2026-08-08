from __future__ import annotations

from typing import Any


class BackendApplicationError(Exception):


    def __init__(
        self,
        code: str,
        stage: str,
        message: str,
        retryable: bool = False,
        context: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.stage = stage
        self.message = message
        self.retryable = retryable
        self.context = context or {}
        super().__init__(message)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "stage": self.stage,
            "message": self.message,
            "retryable": self.retryable,
            "context": self.context,
        }


class DatasetRegistryError(BackendApplicationError):
    pass

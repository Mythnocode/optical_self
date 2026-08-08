from __future__ import annotations

from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

Audience = Literal["beginner", "professional"]
DiagnosisScope = Literal["current_project", "general_guidance"]
RewriteOutcome = Literal["disabled", "applied", "fallback"]


class RewriteFindingInput(BaseModel):


    model_config = ConfigDict(extra="forbid")

    finding_id: str
    title: str
    original_explanation: str
    evidence_text: list[str] = Field(default_factory=list)


class LlmRewriteRequest(BaseModel):


    model_config = ConfigDict(extra="forbid")

    question: str
    audience: Audience = "professional"
    diagnosis_scope: DiagnosisScope = "general_guidance"
    original_summary: str
    findings: list[RewriteFindingInput]


class RewrittenFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    finding_id: str
    explanation: str


class LlmRewriteResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str
    findings: list[RewrittenFinding]


class RewriteTrace(BaseModel):


    model_config = ConfigDict(extra="forbid")

    outcome: RewriteOutcome
    provider: str | None = None
    message: str = ""


class ProviderUnavailable(RuntimeError):
    pass


class ProviderResponseError(RuntimeError):
    pass


class RewriteValidationError(ValueError):
    pass


@runtime_checkable
class LocalLanguageModel(Protocol):
    name: str

    def rewrite(self, request: LlmRewriteRequest) -> LlmRewriteResult:
        pass

    def healthcheck(self) -> bool:
        pass

    def close(self) -> None:
        pass

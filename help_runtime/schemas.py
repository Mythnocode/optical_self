from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

QuestionType = Literal[
    "definition",
    "how_to",
    "navigation",
    "troubleshooting",
    "diagnosis",
    "identity",
    "capability",
    "privacy",
    "help",
    "greeting",
    "out_of_scope",
]
AnswerStatus = Literal["supported", "partial", "insufficient", "unsupported"]
ConfidenceLevel = Literal["high", "medium", "low"]
FindingKind = Literal["knowledge", "diagnostic", "warning", "conflict"]


class SourceReference(BaseModel):


    model_config = ConfigDict(extra="forbid")

    source_id: str
    title: str
    source_type: Literal["docx", "pdf", "platform_code", "platform_doc"]
    location: str
    pages: list[int] = Field(default_factory=list)
    sections: list[str] = Field(default_factory=list)
    sha256: str | None = None


class KnowledgeEntry(BaseModel):


    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    entry_type: Literal[
        "guide",
        "parameter",
        "diagnostic",
        "principle",
        "teaching",
        "faq",
    ]
    module: str
    summary: str
    content: str
    keywords: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    related: list[str] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)
    route: str | None = None
    anchor: str | None = None
    version: str = "1.0"
    sources: list[SourceReference] = Field(min_length=1)
    limitations: list[str] = Field(default_factory=list)
    conflict_key: str | None = None
    claim_value: str | None = None

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        value = value.strip()
        if not value or any(char.isspace() for char in value):
            raise ValueError("knowledge entry id must be non-empty and contain no whitespace")
        return value

    @property
    def searchable_text(self) -> str:
        return "\n".join(
            part
            for part in (
                self.title,
                self.summary,
                self.content,
                " ".join(self.keywords),
                " ".join(self.aliases),
                self.module,
            )
            if part
        )


class SearchHit(BaseModel):
    id: str
    title: str
    module: str
    entry_type: str
    summary: str
    content: str
    route: str | None = None
    anchor: str | None = None
    action_ids: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    keyword_score: float = 0.0
    semantic_score: float = 0.0
    context_score: float = 0.0
    final_score: float = 0.0


class HelpContext(BaseModel):


    model_config = ConfigDict(extra="allow")

    page_id: str | None = None
    selected_control_id: str | None = None
    project_id: str | None = None
    project_version: str | None = None
    analysis_type: str | None = None
    request_id: str | None = None
    result_status: str | None = None
    result_summary: dict[str, Any] = Field(default_factory=dict)
    diagnostics: dict[str, Any] = Field(default_factory=dict)
    request_options: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    errors: list[dict[str, Any] | str] = Field(default_factory=list)
    dynamic_sources: dict[str, dict[str, Any]] = Field(default_factory=dict)

    @property
    def has_current_result(self) -> bool:
        return bool(
            self.request_id
            or self.result_status
            or self.result_summary
            or self.diagnostics
            or self.warnings
            or self.errors
        )


class AnswerFinding(BaseModel):
    title: str
    explanation: str
    source_ids: list[str] = Field(min_length=1)
    action_ids: list[str] = Field(default_factory=list)
    kind: FindingKind = "knowledge"
    evidence_paths: list[str] = Field(default_factory=list)


class AssistantAnswer(BaseModel):
    question_type: QuestionType
    status: AnswerStatus
    summary: str
    findings: list[AnswerFinding] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    action_ids: list[str] = Field(default_factory=list)
    confidence: ConfidenceLevel
    used_current_result: bool = False
    warnings: list[str] = Field(default_factory=list)


class DiagnosticFinding(BaseModel):
    rule_id: str
    title: str
    explanation: str
    source_ids: list[str] = Field(min_length=1)
    action_ids: list[str] = Field(default_factory=list)
    evidence_paths: list[str] = Field(default_factory=list)
    severity: Literal["info", "warning", "critical"] = "warning"


class ActionSpec(BaseModel):
    id: str
    title: str
    page_id: str
    tab: str | None = None
    section: str | None = None
    control_id: str | None = None
    preset: str | None = None
    description: str = ""

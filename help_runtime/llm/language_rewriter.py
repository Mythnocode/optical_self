from __future__ import annotations

import hashlib
import json
from typing import Any

from help_runtime.schemas import AssistantAnswer, HelpContext

from .base import (
    Audience,
    LlmRewriteRequest,
    LocalLanguageModel,
    RewriteFindingInput,
    RewriteTrace,
)
from .config import LlmConfig
from .rewrite_guard import RewriteGuard


def _finding_id(index: int, title: str, source_ids: list[str]) -> str:
    material = "\x1f".join([title, *source_ids]).encode("utf-8")
    suffix = hashlib.sha256(material).hexdigest()[:12]
    return f"finding-{index}-{suffix}"


def _nested_get(data: dict[str, Any], path: str) -> Any:
    current: Any = data
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current


class LanguageRewriter:


    def __init__(
        self,
        config: LlmConfig,
        provider: LocalLanguageModel,
        *,
        retriever: Any,
    ) -> None:
        self.config = config
        self.provider = provider
        self.retriever = retriever
        self.guard = RewriteGuard(config.guard)

    def _knowledge_evidence(self, source_id: str) -> str | None:
        entry = self.retriever.get_entry(source_id)
        if entry is None:
            return None
        text = f"{entry.title}：{entry.summary}\n{entry.content}"
        return text[:1800]

    def _dynamic_evidence(self, source_id: str, context: HelpContext) -> str | None:
        payload = context.dynamic_sources.get(source_id)
        if not payload:
            return None
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)[:1200]

    def _request(
        self,
        question: str,
        answer: AssistantAnswer,
        context: HelpContext,
        audience: Audience,
    ) -> LlmRewriteRequest:
        context_payload = context.model_dump(mode="python")
        findings: list[RewriteFindingInput] = []
        for index, finding in enumerate(answer.findings):
            evidence = [finding.explanation]
            for source_id in finding.source_ids:
                text = self._knowledge_evidence(source_id) or self._dynamic_evidence(source_id, context)
                if text:
                    evidence.append(text)
            for path in finding.evidence_paths:
                value = _nested_get(context_payload, path)
                if value is not None:
                    evidence.append(f"{path}={value}")
            findings.append(
                RewriteFindingInput(
                    finding_id=_finding_id(index, finding.title, finding.source_ids),
                    title=finding.title,
                    original_explanation=finding.explanation,
                    evidence_text=list(dict.fromkeys(evidence))[:6],
                )
            )
        return LlmRewriteRequest(
            question=question,
            audience=audience,
            diagnosis_scope="current_project" if answer.used_current_result else "general_guidance",
            original_summary=answer.summary,
            findings=findings,
        )

    def rewrite_or_fallback(
        self,
        question: str,
        answer: AssistantAnswer,
        context: HelpContext,
        *,
        enabled: bool | None = None,
        audience: Audience | None = None,
    ) -> tuple[AssistantAnswer, RewriteTrace]:
        use_model = self.config.enabled if enabled is None else enabled
        if not use_model:
            return answer, RewriteTrace(outcome="disabled", provider=self.provider.name)
        if answer.status != "supported" or not answer.findings:
            return answer, RewriteTrace(
                outcome="disabled",
                provider=self.provider.name,
                message="LLM rewrite is limited to supported answers with grounded findings.",
            )
        request = self._request(question, answer, context, audience or self.config.audience)
        try:
            result = self.provider.rewrite(request)
            result = self.guard.validate(request, result)
            rewritten = answer.model_copy(deep=True)
            rewritten.summary = result.summary.strip()
            by_id = {item.finding_id: item.explanation.strip() for item in result.findings}
            for index, finding in enumerate(rewritten.findings):
                internal_id = _finding_id(index, finding.title, finding.source_ids)
                finding.explanation = by_id[internal_id]
            return rewritten, RewriteTrace(
                outcome="applied",
                provider=self.provider.name,
                message="Local language rewrite passed all guards.",
            )
        except Exception as exc:
            return answer, RewriteTrace(
                outcome="fallback",
                provider=self.provider.name,
                message=f"{type(exc).__name__}: {exc}",
            )

    def close(self) -> None:
        self.provider.close()

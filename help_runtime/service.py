from __future__ import annotations

from pathlib import Path
import threading

from .answer_composer import classify_question, compose_answer
from .diagnostic_rules import DiagnosticRuleEngine
from .grounding_guard import GroundingGuard
from .hybrid_retriever import HybridRetriever
from .llm import LanguageRewriter, LlmConfig, LocalLanguageModel, RewriteTrace, create_language_model, load_llm_config
from .llm.base import Audience
from .schemas import AssistantAnswer, HelpContext
from .scope_guard import (
    KnowledgeScopeGate,
    compose_system_answer,
    compose_unsupported_answer,
    detect_system_intent,
)


class HelpService:


    def __init__(
        self,
        resources_dir: str | Path,
        *,
        rules_path: str | Path | None = None,
        llm_config_path: str | Path | None = None,
        llm_config: LlmConfig | None = None,
        llm_provider: LocalLanguageModel | None = None,
    ) -> None:
        self.resources_dir = Path(resources_dir)
        self.retriever = HybridRetriever(self.resources_dir)
        self.rules = DiagnosticRuleEngine(
            rules_path or self.resources_dir / "diagnostic_rules.yaml"
        )
        self.guard = GroundingGuard(self.resources_dir)
        self.scope_gate = KnowledgeScopeGate(self.resources_dir)
        project_root = self.resources_dir.parent.parent
        config_path = llm_config_path
        if config_path is None:
            default_config = self.resources_dir / "llm_config.yaml"
            config_path = default_config if default_config.exists() else None
        self.llm_config = llm_config or load_llm_config(config_path, project_root=project_root)
        provider = llm_provider or create_language_model(self.llm_config)
        self.language_rewriter = LanguageRewriter(
            self.llm_config,
            provider,
            retriever=self.retriever,
        )
        self.last_rewrite_trace = RewriteTrace(
            outcome="disabled",
            provider=getattr(provider, "name", None),
        )
        
        
        
        self._llm_lock = threading.RLock()

    @property
    def knowledge_entry_count(self) -> int:


        return len(self.guard.available_knowledge_ids())

    def _deterministic_answer(
        self,
        question: str,
        context: HelpContext,
        *,
        limit: int,
    ) -> AssistantAnswer:
        intent = detect_system_intent(question)
        if intent is not None:
            return compose_system_answer(intent)

        question_type = classify_question(question)
        decision = self.scope_gate.decide(question, context, question_type=question_type)
        if not decision.supported:
            return compose_unsupported_answer()

        hits = self.retriever.search(question, context=context, limit=limit)
        diagnostics = self.rules.evaluate(context) if context.has_current_result else []
        answer = compose_answer(
            question,
            context=context,
            hits=hits,
            diagnostic_findings=diagnostics,
        )
        return self.guard.validate(answer, context)

    def answer(
        self,
        question: str,
        context: HelpContext | None = None,
        *,
        limit: int = 8,
        use_llm: bool | None = None,
        audience: Audience | None = None,
    ) -> AssistantAnswer:
        context = context or HelpContext()
        question = question.strip()
        if not question:
            self.last_rewrite_trace = RewriteTrace(outcome="disabled", provider=None)
            return AssistantAnswer(
                question_type="definition",
                status="insufficient",
                summary="Question cannot be empty.",
                findings=[],
                source_ids=[],
                action_ids=[],
                confidence="low",
                warnings=[],
            )
        deterministic = self._deterministic_answer(question, context, limit=limit)
        if deterministic.status != "supported" or not deterministic.findings:
            self.last_rewrite_trace = RewriteTrace(
                outcome="disabled",
                provider=getattr(self.language_rewriter.provider, "name", None),
                message="LLM rewrite bypassed because the answer is not a grounded knowledge response.",
            )
            return deterministic

        with self._llm_lock:
            rewritten, trace = self.language_rewriter.rewrite_or_fallback(
                question,
                deterministic,
                context,
                enabled=use_llm,
                audience=audience,
            )
        
        
        rewritten = self.guard.validate(rewritten, context)
        self.last_rewrite_trace = trace
        return rewritten

    def configure_llm(self, config: LlmConfig) -> LlmConfig:


        provider = create_language_model(config)
        replacement = LanguageRewriter(config, provider, retriever=self.retriever)
        with self._llm_lock:
            previous = self.language_rewriter
            self.llm_config = config
            self.language_rewriter = replacement
            self.last_rewrite_trace = RewriteTrace(
                outcome="disabled",
                provider=getattr(provider, "name", None),
                message="Language-model settings updated for this application session.",
            )
            previous.close()
        return config

    def search(self, question: str, context: HelpContext | None = None, *, limit: int = 8):
        return self.retriever.search(question, context=context or HelpContext(), limit=limit)

    def sources_for(self, answer: AssistantAnswer, context: HelpContext | None = None) -> dict[str, dict]:
        catalog = self.guard.source_catalog(context or HelpContext())
        return {source_id: catalog[source_id] for source_id in answer.source_ids if source_id in catalog}

    def close(self) -> None:
        self.language_rewriter.close()

    def __enter__(self) -> "HelpService":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()



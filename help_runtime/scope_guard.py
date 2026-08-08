from __future__ import annotations

import json
import sqlite3
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .schemas import AssistantAnswer, HelpContext

SystemIntent = Literal["identity", "capability", "privacy", "help", "greeting"]



_SYSTEM_INTENT_PATTERNS: tuple[tuple[SystemIntent, tuple[str, ...]], ...] = (
    (
        "identity",
        (
            "\u4f60\u662f\u8c01",
            "\u4f60\u662f\u4ec0\u4e48",
            "\u4f60\u53eb\u4ec0\u4e48",
            "\u4ecb\u7ecd\u4e00\u4e0b\u4f60",
            "\u4f60\u7684\u8eab\u4efd",
        ),
    ),
    (
        "capability",
        (
            "\u4f60\u80fd\u505a\u4ec0\u4e48",
            "\u4f60\u4f1a\u505a\u4ec0\u4e48",
            "\u4f60\u53ef\u4ee5\u505a\u4ec0\u4e48",
            "\u4f60\u80fd\u5e2e\u6211\u4ec0\u4e48",
            "\u652f\u6301\u4ec0\u4e48",
            "\u5e2e\u52a9\u8303\u56f4",
        ),
    ),
    (
        "privacy",
        (
            "\u4f1a\u4e0a\u4f20",
            "\u4e0a\u4f20\u6570\u636e",
            "\u662f\u5426\u8054\u7f51",
            "\u8054\u7f51\u5417",
            "\u9690\u79c1",
            "\u672c\u5730\u8fd0\u884c",
            "\u79bb\u7ebf\u5417",
            "\u6570\u636e\u4f1a\u4e0d\u4f1a",
        ),
    ),
    (
        "help",
        (
            "\u600e\u4e48\u4f7f\u7528\u4f60",
            "\u5982\u4f55\u4f7f\u7528\u4f60",
            "\u600e\u4e48\u63d0\u95ee",
            "\u5982\u4f55\u63d0\u95ee",
            "\u4f7f\u7528\u8bf4\u660e",
        ),
    ),
    (
        "greeting",
        (
            "\u4f60\u597d",
            "\u60a8\u597d",
            "hello",
            "hi",
        ),
    ),
)



_GENERIC_TERMS = {
    "\u95ee\u9898",
    "\u7cfb\u7edf",
    "\u529f\u80fd",
    "\u7ed3\u679c",
    "\u6a21\u578b",
    "\u53c2\u6570",
    "\u8bbe\u7f6e",
    "\u65b9\u6cd5",
    "\u6d41\u7a0b",
    "\u6b65\u9aa4",
    "\u5b9a\u4e49",
    "\u89e3\u91ca",
    "\u8bf4\u660e",
    "\u5e2e\u52a9",
    "\u77e5\u8bc6\u5e93",
    "\u6570\u636e",
    "\u8f93\u5165",
    "\u8f93\u51fa",
    "\u4fe1\u606f",
    "\u5f53\u524d",
    "\u6b63\u5f0f",
    "\u9884\u89c8",
    "\u5f02\u5e38",
    "\u9519\u8bef",
    "\u5931\u8d25",
    "\u5206\u6790",
    "\u4ec0\u4e48",
    "\u4e3a\u4ec0\u4e48",
    "\u600e\u4e48",
    "\u5982\u4f55",
    "\u662f\u5426",
    "\u53ef\u4ee5",
    "\u4e00\u4e0b",
}


@dataclass(frozen=True)
class ScopeDecision:
    supported: bool
    matched_terms: tuple[str, ...] = ()
    reason: str = ""


def _normalise(text: str) -> str:
    return "".join(
        char.casefold()
        for char in unicodedata.normalize("NFKC", text)
        if char.isalnum() or "\u3400" <= char <= "\u9fff"
    )


def detect_system_intent(question: str) -> SystemIntent | None:
    text = _normalise(question)
    for intent, patterns in _SYSTEM_INTENT_PATTERNS:
        if any(_normalise(pattern) in text for pattern in patterns):
            return intent
    return None


def compose_system_answer(intent: SystemIntent) -> AssistantAnswer:
    if intent == "identity":
        summary = "\u6211\u662f\u4e00\u4e2a\u672c\u5730\u8fd0\u884c\u7684\u5149\u5b66\u4eff\u771f\u5e2e\u52a9\u95ee\u7b54\u52a9\u624b\u3002"
    elif intent == "capability":
        summary = (
            "\u6211\u53ef\u4ee5\u57fa\u4e8e\u672c\u5730\u77e5\u8bc6\u5e93\uff0c\u56de\u7b54\u5149\u5b66\u4eff\u771f\u3001\u8026\u5408\u6548\u7387\u3001"
            "\u6570\u503c\u6536\u655b\u548c\u53c2\u6570\u914d\u7f6e\u7b49\u95ee\u9898\u3002\u5bf9\u77e5\u8bc6\u5e93\u5916\u7684\u95ee\u9898\uff0c\u6211\u4f1a\u660e\u786e\u8bf4\u660e\u65e0\u6cd5\u53ef\u9760\u56de\u7b54\u3002"
        )
    elif intent == "privacy":
        summary = (
            "\u5f53\u524d\u5e2e\u52a9\u95ee\u7b54\u6a21\u5757\u4f7f\u7528\u672c\u673a\u77e5\u8bc6\u5e93\u548c\u53ef\u9009\u7684 localhost \u6a21\u578b\u670d\u52a1\u3002"
            "\u5b83\u4e0d\u4f1a\u628a\u4f60\u7684\u95ee\u9898\u53d1\u9001\u5230\u4e92\u8054\u7f51\u3002"
        )
    elif intent == "help":
        summary = (
            "\u8bf7\u5c3d\u91cf\u63d0\u4f9b\u5177\u4f53\u7684\u5149\u5b66\u53c2\u6570\u3001\u9519\u8bef\u4fe1\u606f\u6216\u6b63\u5f0f\u5206\u6790\u7ed3\u679c\u3002"
            "\u4f8b\u5982\uff1a\u201c\u4ec0\u4e48\u662f\u8fb9\u7f18\u529f\u7387\uff1f\u201d\u3001\u201c\u8026\u5408\u6548\u7387\u4e3a\u4ec0\u4e48\u4f4e\uff1f\u201d\u6216\u201c\u600e\u6837\u5bfb\u627e\u6700\u4f73\u8026\u5408\u9762\uff1f\u201d\u3002"
        )
    else:
        summary = "\u4f60\u597d\u3002\u6211\u53ef\u4ee5\u6839\u636e\u672c\u5730\u77e5\u8bc6\u5e93\u5e2e\u52a9\u89e3\u7b54\u5149\u5b66\u4eff\u771f\u76f8\u5173\u95ee\u9898\u3002"

    return AssistantAnswer(
        question_type=intent,
        status="supported",
        summary=summary,
        findings=[],
        source_ids=[],
        action_ids=[],
        confidence="high",
        used_current_result=False,
        warnings=[],
    )


def compose_unsupported_answer() -> AssistantAnswer:
    return AssistantAnswer(
        question_type="out_of_scope",
        status="unsupported",
        summary="\u5f53\u524d\u672c\u5730\u77e5\u8bc6\u5e93\u672a\u627e\u5230\u8db3\u591f\u76f8\u5173\u7684\u4f9d\u636e\uff0c\u65e0\u6cd5\u53ef\u9760\u56de\u7b54\u8be5\u95ee\u9898\u3002",
        findings=[],
        source_ids=[],
        action_ids=[],
        confidence="low",
        used_current_result=False,
        warnings=[
            "\u4e3a\u907f\u514d\u7ed9\u51fa\u65e0\u4f9d\u636e\u7684\u5185\u5bb9\uff0c\u7cfb\u7edf\u672a\u8c03\u7528\u672c\u5730\u8bed\u8a00\u6a21\u578b\u3002",
            "\u8bf7\u6539\u4e3a\u54a8\u8be2\u5149\u5b66\u4eff\u771f\u3001\u8026\u5408\u5206\u6790\u3001\u6570\u503c\u6536\u655b\u6216\u5df2\u6536\u5f55\u7684\u53c2\u6570\u914d\u7f6e\u95ee\u9898\u3002",
        ],
    )


class KnowledgeScopeGate:


    def __init__(self, resources_dir: str | Path) -> None:
        self.db_path = Path(resources_dir) / "help.db"
        self.domain_terms, self.domain_fragments = self._load_domain_terms()

    def _load_domain_terms(self) -> tuple[tuple[str, ...], tuple[str, ...]]:
        with sqlite3.connect(self.db_path) as connection:
            rows = connection.execute(
                "SELECT title, keywords, aliases FROM knowledge_entries"
            ).fetchall()

        terms: set[str] = set()
        for title, keywords_json, aliases_json in rows:
            candidates = [str(title)]
            for serialized in (keywords_json, aliases_json):
                try:
                    candidates.extend(str(item) for item in json.loads(serialized))
                except (TypeError, json.JSONDecodeError):
                    continue
            for candidate in candidates:
                term = _normalise(candidate)
                if len(term) >= 2 and term not in _GENERIC_TERMS:
                    terms.add(term)
        ordered_terms = tuple(sorted(terms, key=lambda item: (-len(item), item)))
        fragment_sources: dict[str, set[str]] = {}
        for term in ordered_terms:
            cjk_runs = re.findall(r"[\u3400-\u9fff]+", term)
            for run in cjk_runs:
                for size in range(2, min(4, len(run)) + 1):
                    for start in range(0, len(run) - size + 1):
                        fragment = run[start : start + size]
                        if fragment not in _GENERIC_TERMS:
                            fragment_sources.setdefault(fragment, set()).add(term)
        fragments = tuple(
            sorted(
                (fragment for fragment, sources in fragment_sources.items() if len(sources) >= 2),
                key=lambda item: (-len(item), item),
            )
        )
        return ordered_terms, fragments

    def decide(
        self,
        question: str,
        context: HelpContext,
        *,
        question_type: str,
    ) -> ScopeDecision:
        text = _normalise(question)
        matches = tuple(term for term in self.domain_terms if term in text)
        if matches:
            return ScopeDecision(
                supported=True,
                matched_terms=matches[:5],
                reason="question contains local-domain terminology",
            )
        fragment_matches = tuple(fragment for fragment in self.domain_fragments if fragment in text)
        if fragment_matches:
            return ScopeDecision(
                supported=True,
                matched_terms=fragment_matches[:5],
                reason="question contains a repeated local-domain term fragment",
            )
        if context.has_current_result and question_type in {"diagnosis", "troubleshooting"}:
            return ScopeDecision(
                supported=True,
                reason="current diagnostic context is available",
            )
        return ScopeDecision(
            supported=False,
            reason="question has no title, keyword, or alias from the local knowledge base",
        )

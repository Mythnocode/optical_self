from __future__ import annotations

import re
from collections import Counter

from .base import LlmRewriteRequest, LlmRewriteResult, RewriteValidationError
from .config import GuardConfig

_NUMERIC_RE = re.compile(
    r"(?<![A-Za-z0-9_.])[-+]?(?:\d+(?:\.\d+)?|\.\d+)(?:[eE][-+]?\d+)?"
    r"\s*(?:%|‰|nm|μm|µm|um|mm|cm|mrad|rad|dB|waves?|Hz|kHz|MHz|GHz|cycles/mm)?",
    re.IGNORECASE,
)
_IDENTIFIER_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9_./+\-]*\b")

_TECHNICAL_TERMS = {
    "边缘功率",
    "能量闭合",
    "网格收敛",
    "光瞳采样",
    "Nyquist",
    "模场尺寸失配",
    "尺寸失配",
    "横向偏移",
    "角度倾斜",
    "轴向离焦",
    "曲率失配",
    "相位失配",
    "偏振失配",
    "系统截光",
    "材料吸收",
    "膜层损失",
    "特征契约",
    "训练域",
    "SHAP",
    "加性误差",
    "Strehl",
    "RMS",
    "Hessian",
    "Monte Carlo",
    "LP01",
    "HE11",
    "Fresnel",
    "角谱法",
}

_POLARITY_PAIRS = (
    ("已通过", "未通过"),
    ("已收敛", "未收敛"),
    ("可接受", "不可靠"),
    ("高于", "低于"),
    ("上升", "下降"),
    ("增加", "降低"),
    ("一致", "不一致"),
    ("可以使用", "不能使用"),
    ("存在", "不存在"),
)

_UNSUPPORTED_CERTAINTY = (
    "已确认",
    "确定为",
    "证明了",
    "主要原因是",
    "根本原因是",
    "就是由于",
    "当前系统存在",
    "你的结果表明",
    "可以断定",
)


def _normalize_token(value: str) -> str:
    return re.sub(r"\s+", "", value).replace("µ", "μ").lower()


def _numeric_tokens(text: str) -> Counter[str]:
    return Counter(_normalize_token(match.group(0)) for match in _NUMERIC_RE.finditer(text))


def _identifier_tokens(text: str) -> set[str]:
    return {match.group(0).casefold() for match in _IDENTIFIER_RE.finditer(text)}


def _phrase_present(text: str, phrase: str) -> bool:
    if phrase in {"存在", "一致"}:
        negative = "不" + phrase
        stripped = text.replace(negative, "")
        return phrase in stripped
    return phrase in text


class RewriteGuard:


    def __init__(self, config: GuardConfig | None = None) -> None:
        self.config = config or GuardConfig()

    def validate(
        self,
        request: LlmRewriteRequest,
        result: LlmRewriteResult,
    ) -> LlmRewriteResult:
        expected_ids = [item.finding_id for item in request.findings]
        actual_ids = [item.finding_id for item in result.findings]
        if actual_ids != expected_ids:
            raise RewriteValidationError("finding_id order or count changed")
        if len(set(actual_ids)) != len(actual_ids):
            raise RewriteValidationError("duplicate finding_id returned")
        if not result.summary.strip():
            raise RewriteValidationError("rewritten summary is empty")
        if len(result.summary) > self.config.max_summary_chars:
            raise RewriteValidationError("rewritten summary is too long")
        original_summary_len = max(len(request.original_summary), 1)
        if len(result.summary) > original_summary_len * self.config.max_length_ratio + 40:
            raise RewriteValidationError("rewritten summary expanded beyond allowed ratio")

        allowed_text = "\n".join(
            [
                request.question,
                request.original_summary,
                *(
                    text
                    for item in request.findings
                    for text in [item.title, item.original_explanation, *item.evidence_text]
                ),
            ]
        )
        generated_text = "\n".join(
            [result.summary, *(item.explanation for item in result.findings)]
        )

        if self.config.require_exact_numeric_tokens:
            allowed_numbers = _numeric_tokens(allowed_text)
            generated_numbers = _numeric_tokens(generated_text)
            unsupported = generated_numbers - allowed_numbers
            if unsupported:
                raise RewriteValidationError(
                    "rewrite introduced or reformatted numeric tokens: "
                    + ", ".join(sorted(unsupported.elements()))
                )

        allowed_identifiers = _identifier_tokens(allowed_text)
        new_identifiers = _identifier_tokens(generated_text) - allowed_identifiers
        if new_identifiers:
            raise RewriteValidationError(
                "rewrite introduced unsupported technical identifiers: "
                + ", ".join(sorted(new_identifiers))
            )

        if self.config.require_known_technical_terms:
            for term in _TECHNICAL_TERMS:
                if term in generated_text and term not in allowed_text:
                    raise RewriteValidationError(f"rewrite introduced unsupported technical term: {term}")

        for positive, negative in _POLARITY_PAIRS:
            allowed_positive = _phrase_present(allowed_text, positive)
            allowed_negative = negative in allowed_text
            generated_positive = _phrase_present(generated_text, positive)
            generated_negative = negative in generated_text
            if generated_positive and not allowed_positive:
                raise RewriteValidationError(f"rewrite introduced unsupported polarity: {positive}")
            if generated_negative and not allowed_negative:
                raise RewriteValidationError(f"rewrite introduced unsupported polarity: {negative}")

        if request.diagnosis_scope == "general_guidance":
            for phrase in _UNSUPPORTED_CERTAINTY:
                if phrase in generated_text and phrase not in allowed_text:
                    raise RewriteValidationError(
                        f"general guidance was rewritten as project-specific certainty: {phrase}"
                    )

        by_id = {item.finding_id: item for item in request.findings}
        for item in result.findings:
            original = by_id[item.finding_id]
            if not item.explanation.strip():
                raise RewriteValidationError(f"empty explanation for {item.finding_id}")
            if len(item.explanation) > self.config.max_explanation_chars:
                raise RewriteValidationError(f"explanation too long for {item.finding_id}")
            original_len = max(len(original.original_explanation), 1)
            evidence_len = sum(len(text) for text in original.evidence_text)
            allowed_len = max(
                original_len * self.config.max_length_ratio + 80,
                min(evidence_len + original_len, self.config.max_explanation_chars),
            )
            if len(item.explanation) > allowed_len:
                raise RewriteValidationError(f"explanation expanded too much for {item.finding_id}")
        return result

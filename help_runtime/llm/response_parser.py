from __future__ import annotations

import json
import re
from typing import Any

from pydantic import ValidationError

from .base import LlmRewriteResult, ProviderResponseError

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL | re.IGNORECASE)


def _message_content(payload: dict[str, Any]) -> str:
    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ProviderResponseError("Local model response did not contain choices[0].message.content") from exc
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        if parts:
            return "".join(parts)
    raise ProviderResponseError("Local model message content was not text")


def parse_provider_payload(payload: dict[str, Any]) -> LlmRewriteResult:
    text = _message_content(payload)
    text = _THINK_RE.sub("", text).strip()
    match = _FENCE_RE.match(text)
    if match:
        text = match.group(1).strip()
    try:
        decoded = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProviderResponseError("Local model returned invalid JSON") from exc
    try:
        return LlmRewriteResult.model_validate(decoded)
    except ValidationError as exc:
        raise ProviderResponseError("Local model JSON did not match the rewrite schema") from exc

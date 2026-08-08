from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from .base import (
    LlmRewriteRequest,
    LlmRewriteResult,
    ProviderResponseError,
    ProviderUnavailable,
)
from .config import LlmConfig
from .process_manager import LocalLlamaProcessManager
from .prompt_builder import build_messages, rewrite_json_schema
from .response_parser import parse_provider_payload


class LlamaServerProvider:


    name = "llama_cpp_server"

    def __init__(
        self,
        config: LlmConfig,
        *,
        process_manager: LocalLlamaProcessManager | None = None,
    ) -> None:
        self.config = config
        self.process_manager = process_manager or LocalLlamaProcessManager(config)

    def healthcheck(self) -> bool:
        return self.process_manager.healthcheck()

    def _request_payload(self, request: LlmRewriteRequest, *, strict_schema: bool) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.config.model.model_name,
            "messages": build_messages(request),
            "temperature": self.config.generation.temperature,
            "max_tokens": self.config.generation.max_output_tokens,
            "seed": self.config.generation.seed,
            "stream": False,
        }
        if strict_schema and self.config.generation.schema_mode == "json_schema":
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "offline_help_rewrite",
                    "strict": True,
                    "schema": rewrite_json_schema(),
                },
            }
        else:
            payload["response_format"] = {"type": "json_object"}
        return payload

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = self.process_manager.base_url + self.config.server.chat_path
        headers = {"Content-Type": "application/json"}
        if api_key := self.process_manager.request_api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        request = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=self.config.server.request_timeout_s,
            ) as response:
                data = response.read(self.config.server.max_response_bytes + 1)
                if len(data) > self.config.server.max_response_bytes:
                    raise ProviderResponseError("Local llama.cpp response exceeded configured size limit")
        except urllib.error.HTTPError as exc:
            body = exc.read(4096).decode("utf-8", errors="replace")
            raise ProviderResponseError(f"Local llama.cpp HTTP {exc.code}: {body}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ProviderUnavailable(f"Local llama.cpp request failed: {exc}") from exc
        try:
            decoded = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProviderResponseError("Local llama.cpp server returned invalid response JSON") from exc
        if not isinstance(decoded, dict):
            raise ProviderResponseError("Local llama.cpp response must be a JSON object")
        return decoded

    def rewrite(self, request: LlmRewriteRequest) -> LlmRewriteResult:
        
        
        with self.process_manager.request_session():
            strict = self.config.generation.schema_mode == "json_schema"
            try:
                payload = self._post(self._request_payload(request, strict_schema=strict))
            except ProviderResponseError as exc:
                
                
                if not strict or "HTTP 400" not in str(exc):
                    raise
                payload = self._post(self._request_payload(request, strict_schema=False))
        return parse_provider_payload(payload)

    def close(self) -> None:
        self.process_manager.stop()

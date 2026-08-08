from __future__ import annotations

from .base import LocalLanguageModel
from .config import LlmConfig
from .llama_server_provider import LlamaServerProvider
from .openai_compatible_provider import OpenAICompatibleProvider


def create_language_model(config: LlmConfig) -> LocalLanguageModel:


    if config.provider == "llama_cpp_server":
        return LlamaServerProvider(config)
    if config.provider == "openai_compatible_api":
        return OpenAICompatibleProvider(config)
    raise ValueError(f"Unsupported language-model provider: {config.provider}")

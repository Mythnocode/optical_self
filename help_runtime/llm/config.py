from __future__ import annotations

from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .base import Audience

_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


class ServerConfig(BaseModel):


    model_config = ConfigDict(extra="forbid")

    host: str = "127.0.0.1"
    port: int = Field(default=18080, ge=1, le=65535)
    health_path: str = "/health"
    chat_path: str = "/v1/chat/completions"
    startup_timeout_s: float = Field(default=60.0, gt=0, le=600)
    request_timeout_s: float = Field(default=90.0, gt=0, le=600)
    max_response_bytes: int = Field(default=1_048_576, ge=1024, le=16_777_216)
    auto_start: bool = True
    
    
    
    bundled_runtime_dir: Path = Path("help_runtime/llm/runtime")
    
    
    idle_shutdown_s: float = Field(default=90.0, ge=0.0, le=3600.0)
    
    
    executable_path: Path | None = None
    executable_env_var: str = "LLAMA_CPP_SERVER_PATH"
    executable_name: str = "llama-server"
    extra_args: list[str] = Field(default_factory=list)
    api_key: str | None = None

    @field_validator("host")
    @classmethod
    def local_host_only(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in _LOCAL_HOSTS:
            raise ValueError("The local llama.cpp server may only bind to localhost")
        return value

    @field_validator("health_path", "chat_path")
    @classmethod
    def require_relative_http_path(cls, value: str) -> str:
        if not value.startswith("/") or "://" in value:
            raise ValueError("Server paths must be local relative HTTP paths")
        return value

    @field_validator("executable_env_var", "executable_name")
    @classmethod
    def require_nonempty_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Executable lookup names cannot be empty")
        return value


class LocalRuntimeConfig(BaseModel):


    model_config = ConfigDict(extra="forbid")

    
    
    
    device: Literal["auto", "cpu", "gpu"] = "auto"
    gpu_fallback_to_cpu: bool = True
    
    
    gpu_layers: int = Field(default=99, ge=1, le=10000)


class RemoteApiConfig(BaseModel):


    model_config = ConfigDict(extra="forbid")

    base_url: str = "https://api.openai.com"
    chat_path: str = "/v1/chat/completions"
    health_path: str | None = None
    models_path: str = "/v1/models"
    request_timeout_s: float = Field(default=90.0, gt=0, le=600)
    max_response_bytes: int = Field(default=1_048_576, ge=1024, le=16_777_216)
    api_key_env: str = "HELP_LLM_API_KEY"
    api_key: str | None = None

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        parsed = urlparse(value)
        if parsed.scheme != "https" or not parsed.netloc or parsed.query or parsed.fragment:
            raise ValueError("remote_api.base_url must be an absolute HTTPS URL without query or fragment")
        return value

    @field_validator("chat_path", "models_path")
    @classmethod
    def require_remote_path(cls, value: str) -> str:
        if not value.startswith("/") or "://" in value:
            raise ValueError("Remote API paths must be relative HTTP paths")
        return value

    @field_validator("health_path")
    @classmethod
    def validate_optional_health_path(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.startswith("/") or "://" in value:
            raise ValueError("remote_api.health_path must be a relative HTTP path")
        return value


class GenerationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_output_tokens: int = Field(default=512, ge=64, le=4096)
    temperature: float = Field(default=0.0, ge=0.0, le=1.0)
    seed: int = 20260726
    context_size: int = Field(default=4096, ge=1024, le=131072)
    schema_mode: Literal["json_schema", "json_object"] = "json_schema"


class ModelConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: Path | None = None
    model_name: str = "local-help-model"
    expected_sha256: str | None = None

    @field_validator("expected_sha256")
    @classmethod
    def validate_sha256(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        value = value.strip().lower()
        if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
            raise ValueError("expected_sha256 must be a 64-character hexadecimal digest")
        return value


class GuardConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_summary_chars: int = Field(default=600, ge=50, le=4000)
    max_explanation_chars: int = Field(default=1200, ge=100, le=8000)
    max_length_ratio: float = Field(default=3.0, ge=1.0, le=10.0)
    require_exact_numeric_tokens: bool = True
    require_known_technical_terms: bool = True


class LlmConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.2"
    enabled: bool = True
    provider: Literal["llama_cpp_server", "openai_compatible_api"] = "llama_cpp_server"
    audience: Audience = "professional"
    server: ServerConfig = Field(default_factory=ServerConfig)
    runtime: LocalRuntimeConfig = Field(default_factory=LocalRuntimeConfig)
    remote_api: RemoteApiConfig = Field(default_factory=RemoteApiConfig)
    generation: GenerationConfig = Field(default_factory=GenerationConfig)
    model: ModelConfig = Field(default_factory=ModelConfig)
    guard: GuardConfig = Field(default_factory=GuardConfig)

    @model_validator(mode="after")
    def local_auto_start_requires_model(self) -> "LlmConfig":
        if self.provider == "llama_cpp_server" and self.server.auto_start and self.model.path is None:
            raise ValueError("model.path is required when local llama.cpp auto_start=true")
        return self


def _resolve_path(value: Path | None, project_root: Path) -> Path | None:
    if value is None:
        return None
    return value if value.is_absolute() else (project_root / value).resolve()


def load_llm_config(
    path: str | Path | None,
    *,
    project_root: str | Path | None = None,
) -> LlmConfig:


    if path is None:
        return LlmConfig(enabled=False)
    config_path = Path(path)
    if not config_path.exists():
        return LlmConfig(enabled=False)
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    config = LlmConfig.model_validate(payload)
    root = Path(project_root).resolve() if project_root else config_path.resolve().parents[2]
    config.server.bundled_runtime_dir = _resolve_path(config.server.bundled_runtime_dir, root) or root
    config.server.executable_path = _resolve_path(config.server.executable_path, root)
    config.model.path = _resolve_path(config.model.path, root)
    return config

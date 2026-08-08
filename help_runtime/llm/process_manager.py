from __future__ import annotations

import hashlib
import os
import platform
import shutil
import secrets
import subprocess
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .base import ProviderUnavailable
from .config import LlmConfig


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class LocalLlamaProcessManager:


    def __init__(self, config: LlmConfig) -> None:
        self.config = config
        self.process: subprocess.Popen[bytes] | None = None
        self._owned_process = False
        self._effective_device: str | None = None
        self._active_requests = 0
        self._idle_timer: threading.Timer | None = None
        self._lock = threading.RLock()
        self._validated_model_signature: tuple[Path, int, int] | None = None
        self._runtime_api_key = config.server.api_key or secrets.token_urlsafe(32)

    @property
    def base_url(self) -> str:
        host = "127.0.0.1" if self.config.server.host == "localhost" else self.config.server.host
        if host == "::1":
            return f"http://[{host}]:{self.config.server.port}"
        return f"http://{host}:{self.config.server.port}"

    @property
    def effective_device(self) -> str | None:


        return self._effective_device

    @property
    def request_api_key(self) -> str | None:


        return self._runtime_api_key if self._owned_process else self.config.server.api_key

    def healthcheck(self, timeout: float = 1.5) -> bool:
        request = urllib.request.Request(self.base_url + self.config.server.health_path, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return 200 <= int(response.status) < 300
        except (urllib.error.URLError, TimeoutError, OSError):
            return False

    @staticmethod
    def _platform_tag() -> str:
        machine = platform.machine().lower()
        if machine in {"amd64", "x86_64", "x64"}:
            architecture = "x64"
        elif machine in {"arm64", "aarch64"}:
            architecture = "arm64"
        else:
            architecture = machine
        if os.name == "nt":
            return f"win-{architecture}"
        if sys_platform := platform.system().lower():
            if sys_platform == "darwin":
                return f"macos-{architecture}"
            return f"{sys_platform}-{architecture}"
        return architecture

    def _bundled_executable(self, runtime_kind: str) -> Path:
        suffix = ".exe" if os.name == "nt" else ""
        return (
            self.config.server.bundled_runtime_dir
            / f"{self._platform_tag()}-{runtime_kind}"
            / f"{self.config.server.executable_name}{suffix}"
        )

    def executable_candidates(self) -> list[tuple[Path, str]]:


        requested = self.config.runtime.device
        candidates: list[tuple[Path, str]] = []

        configured = self.config.server.executable_path
        if configured is not None and configured.is_file():
            configured_device = "gpu" if requested == "gpu" else "cpu"
            candidates.append((configured, configured_device))
        else:
            if requested in {"auto", "gpu"}:
                gpu = self._bundled_executable("cuda")
                if gpu.is_file():
                    candidates.append((gpu, "gpu"))
            if requested in {"auto", "cpu"} or (requested == "gpu" and self.config.runtime.gpu_fallback_to_cpu):
                cpu = self._bundled_executable("cpu")
                if cpu.is_file():
                    candidates.append((cpu, "cpu"))

            if not candidates:
                from_environment = os.environ.get(self.config.server.executable_env_var, "").strip()
                if from_environment:
                    candidate = Path(from_environment).expanduser()
                    if candidate.is_file():
                        candidates.append((candidate, "gpu" if requested == "gpu" else "cpu"))
                if not candidates:
                    from_path = shutil.which(self.config.server.executable_name)
                    if from_path:
                        candidates.append((Path(from_path).resolve(), "gpu" if requested == "gpu" else "cpu"))

        unique: list[tuple[Path, str]] = []
        seen: set[Path] = set()
        for executable, device in candidates:
            resolved = executable.resolve()
            if resolved not in seen:
                unique.append((resolved, device))
                seen.add(resolved)
        return unique

    def executable_path(self) -> Path | None:
        candidates = self.executable_candidates()
        return candidates[0][0] if candidates else None

    def _validate_model(self) -> Path:
        model = self.config.model.path
        if model is None or not model.is_file():
            raise ProviderUnavailable("Bundled GGUF model is not configured or does not exist")
        stat = model.stat()
        signature = (model.resolve(), stat.st_size, stat.st_mtime_ns)
        expected = self.config.model.expected_sha256
        if expected and self._validated_model_signature != signature:
            if _sha256(model) != expected:
                raise ProviderUnavailable("Bundled GGUF model SHA256 does not match model manifest")
            self._validated_model_signature = signature
        return model

    def _validate_files(self) -> tuple[list[tuple[Path, str]], Path]:
        candidates = self.executable_candidates()
        if not candidates:
            expected = self._bundled_executable("cpu")
            raise ProviderUnavailable(
                "Bundled llama.cpp runtime was not found at "
                f"{expected}. Reinstall the application package; developer overrides are available only for diagnostics."
            )
        return candidates, self._validate_model()

    def build_command(self, executable: Path, model: Path, *, device: str | None = None) -> list[str]:
        selected_device = device or self.config.runtime.device
        if selected_device == "auto":
            selected_device = "cpu"
        command = [
            str(executable),
            "-m",
            str(model),
            "--host",
            self.config.server.host,
            "--port",
            str(self.config.server.port),
            "-c",
            str(self.config.generation.context_size),
        ]
        extra_args = self.config.server.extra_args
        if not any(argument in {"-ngl", "--gpu-layers"} for argument in extra_args):
            gpu_layers = 0 if selected_device == "cpu" else self.config.runtime.gpu_layers
            command.extend(["--gpu-layers", str(gpu_layers)])
        if "--api-key" not in extra_args:
            
            
            command.extend(["--api-key", self._runtime_api_key])
        command.extend(extra_args)
        return command

    def _cancel_idle_shutdown_locked(self) -> None:
        if self._idle_timer is not None:
            self._idle_timer.cancel()
            self._idle_timer = None

    def _launch(self, executable: Path, model: Path, device: str) -> None:
        command = self.build_command(executable, model, device=device)
        kwargs: dict = {
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "cwd": str(executable.parent),
        }
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW  
        else:
            kwargs["start_new_session"] = True
        try:
            process = subprocess.Popen(command, **kwargs)
        except OSError as exc:
            raise ProviderUnavailable(f"Could not start bundled llama.cpp server: {exc}") from exc

        self.process = process
        self._owned_process = True
        deadline = time.monotonic() + self.config.server.startup_timeout_s
        while time.monotonic() < deadline:
            if process.poll() is not None:
                self.process = None
                self._owned_process = False
                raise ProviderUnavailable(
                    f"Bundled llama.cpp {device} runtime exited during startup with code {process.returncode}"
                )
            if self.healthcheck():
                self._effective_device = device
                return
            time.sleep(0.15)
        self._stop_locked()
        raise ProviderUnavailable(f"Timed out waiting for bundled llama.cpp {device} runtime health check")

    def start(self) -> None:
        with self._lock:
            if self.healthcheck():
                return
            if not self.config.server.auto_start:
                raise ProviderUnavailable("Local llama.cpp server is not running and auto_start is disabled")
            candidates, model = self._validate_files()
            failures: list[str] = []
            for executable, device in candidates:
                try:
                    self._launch(executable, model, device)
                    return
                except ProviderUnavailable as exc:
                    failures.append(str(exc))
                    self._stop_locked()
            detail = "; ".join(failures)
            raise ProviderUnavailable(f"Could not start an application-managed llama.cpp runtime: {detail}")

    def ensure_ready(self) -> None:
        with self._lock:
            self._cancel_idle_shutdown_locked()
            if not self.healthcheck():
                self.start()

    @contextmanager
    def request_session(self) -> Iterator[None]:


        self.ensure_ready()
        with self._lock:
            self._active_requests += 1
        try:
            yield
        finally:
            with self._lock:
                self._active_requests = max(0, self._active_requests - 1)
                if self._active_requests == 0:
                    self._schedule_idle_shutdown_locked()

    def _schedule_idle_shutdown_locked(self) -> None:
        idle_seconds = self.config.server.idle_shutdown_s
        self._cancel_idle_shutdown_locked()
        if idle_seconds <= 0 or not self._owned_process or self.process is None:
            return
        timer = threading.Timer(idle_seconds, self._stop_if_idle)
        timer.daemon = True
        self._idle_timer = timer
        timer.start()

    def _stop_if_idle(self) -> None:
        with self._lock:
            self._idle_timer = None
            if self._active_requests == 0:
                self._stop_locked()

    def _stop_locked(self) -> None:
        process = self.process
        if process is None or not self._owned_process:
            return
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
        self.process = None
        self._owned_process = False
        self._effective_device = None

    def stop(self) -> None:
        with self._lock:
            self._cancel_idle_shutdown_locked()
            self._stop_locked()

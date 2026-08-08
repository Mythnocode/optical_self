from dataclasses import dataclass
from pathlib import Path
import os


def _bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    app_env: str
    api_host: str
    api_port: int
    simulation_engine: str
    user_data_dir: Path
    log_level: str
    simulation_worker_count: int
    training_worker_count: int
    native_thread_limit: int


def load_settings() -> Settings:
    settings = Settings(
        app_env=os.getenv("APP_ENV", "development").lower(),
        api_host="127.0.0.1",
        api_port=8000,
        simulation_engine=os.getenv("SIMULATION_ENGINE", "headless").lower(),
        user_data_dir=Path(os.getenv("USER_DATA_DIR", "user_data")),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        simulation_worker_count=max(
            1, int(os.getenv("SIMULATION_WORKER_COUNT", "2"))
        ),
        training_worker_count=max(
            0, int(os.getenv("TRAINING_WORKER_COUNT", "1"))
        ),
        native_thread_limit=max(
            1, int(os.getenv("NATIVE_THREAD_LIMIT", "1"))
        ),
    )
    validate_settings(settings)
    return settings


def validate_settings(settings: Settings) -> None:
    if settings.simulation_engine not in {"headless"}:
        raise RuntimeError("SIMULATION_ENGINE value is invalid")
    if settings.app_env == "production":
        if settings.simulation_engine != "headless":
            raise RuntimeError("Production default engine must be headless")
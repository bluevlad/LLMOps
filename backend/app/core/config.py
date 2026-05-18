"""Pydantic Settings — 12-factor 환경변수.

Phase 1a 는 최소 필드. DB/OAuth/Poller 설정은 Phase 1b 진입 시 활성화 예정 (이미 .env.example 에 키만 정의됨).
"""
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_ENV_FILES = (str(_PROJECT_ROOT / ".env"), str(_PROJECT_ROOT / "backend" / ".env"))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_FILES,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- App ---
    app_env: str = Field(default="dev")
    app_debug: bool = Field(default=True)
    app_tz: str = Field(default="Asia/Seoul")

    # --- Backend ---
    backend_host: str = Field(default="0.0.0.0")
    backend_port: int = Field(default=9110)
    backend_cors_origins: str = Field(default="http://localhost:4110")

    # --- Database (Phase 1b 에서 사용) ---
    database_url: str = Field(default="postgresql+asyncpg://llmops_svc:CHANGE_ME@localhost:5432/llmops_dev")
    database_pool_size: int = Field(default=5)
    database_max_overflow: int = Field(default=10)

    # --- JWT (Phase 1b) ---
    jwt_secret_key: str = Field(default="CHANGE_ME")
    jwt_algorithm: str = Field(default="HS256")
    jwt_access_token_expire_minutes: int = Field(default=720)

    # --- Google OAuth (Phase 1b) ---
    google_oauth_client_id: str = Field(default="")
    google_oauth_redirect_uri: str = Field(default="https://llmops.unmong.com/auth/callback")

    # --- LLM Sources (Phase 1b) ---
    ollama_base_url: str = Field(default="http://host.docker.internal:11434")
    mlx_model_dir: str = Field(default="/Users/rainend/.cache/huggingface/hub")
    poller_ollama_interval_seconds: int = Field(default=600)
    poller_mlx_interval_seconds: int = Field(default=3600)

    @property
    def backend_cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.backend_cors_origins.split(",") if o.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

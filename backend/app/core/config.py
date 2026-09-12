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

    # 관리자 이메일 allowlist (콤마 구분). 목록 외 로그인은 llmops_guest (데이터 접근 불가)
    llmops_admin_emails: str = Field(default="")

    # --- LLM Sources (Phase 1b) ---
    ollama_base_url: str = Field(default="http://host.docker.internal:11434")
    mlx_model_dir: str = Field(default="")  # 미설정 시 MLX 스캔 skip. 실제 경로는 .env 로 주입
    poller_ollama_interval_seconds: int = Field(default=600)
    poller_mlx_interval_seconds: int = Field(default=3600)

    # --- Paid LLM API keys (Phase 2 (γ) — 무료 vs 유료 비교 실험) ---
    anthropic_api_key: str = Field(default="")
    openai_api_key: str = Field(default="")
    gemini_api_key: str = Field(default="")

    # --- 관제 알림 (v0.3.0 M3) ---
    slack_webhook_url: str = Field(default="")               # 비우면 Slack 발송 안 함 (DB 기록만)
    expected_resident_models: str = Field(default="")        # 콤마 구분 — Ollama 에 항상 올라와 있어야 하는 모델 (예: gemma4:12b-mlx)
    alert_eval_interval_seconds: int = Field(default=600)    # 알림 평가 잡 주기 (0 = 비활성)
    alert_fail_rate_threshold: float = Field(default=0.2)    # 24h 실패율 이 이상 + 건수 이상이면 failure_spike
    alert_fail_min_count: int = Field(default=3)

    # --- S2S 읽기 키 (v0.3.0 — DocPipeline 등 다른 서비스가 읽기 API 를 pull) ---
    # JSON object {client_id: api_key}. 헤더 X-API-Key 로 검증. ingest 키(LLMOPS_INGEST_KEYS)와 별도.
    llmops_read_keys: str = Field(default="{}")

    # --- Batch run content capture (표준 v0.3.0 §2-β) ---
    # 샘플링 결정은 consumer(클라이언트)가 한다. 서버는 받은 prompt/response 본문에
    # 대해 방어적 truncation 만 강제 — consumer 오작동 시 저장소 폭주 방지.
    batch_content_max_chars: int = Field(default=8000)

    @property
    def expected_resident_models_list(self) -> list[str]:
        return [m.strip() for m in self.expected_resident_models.split(",") if m.strip()]

    @property
    def backend_cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.backend_cors_origins.split(",") if o.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

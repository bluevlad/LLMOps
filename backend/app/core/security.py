"""JWT 발급·검증 + Google ID 토큰 검증.

llmops_users.role: llmops_admin / llmops_viewer / llmops_guest (3단계)
LLMOPS_ADMIN_EMAILS allowlist 기반 — 목록 외 로그인은 llmops_guest (데이터 API 접근 불가,
로그인 이력만 기록). 패턴 참조: OpsConsole/backend/app/core/security.py
"""
from __future__ import annotations

import json
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.database.session import get_db
from app.models.user import LlmopsUser

bearer_scheme = HTTPBearer(auto_error=False)
logger = logging.getLogger(__name__)


# -- JWT --------------------------------------------------------------------


def create_access_token(user: LlmopsUser) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.jwt_access_token_expire_minutes
    )
    payload: dict[str, Any] = {
        "sub": str(user.id),
        "email": user.email,
        "role": user.role,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Invalid JWT: {e}") from e


# -- Google ID token --------------------------------------------------------


def verify_google_id_token(credential: str) -> dict[str, Any]:
    if not settings.google_oauth_client_id:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "GOOGLE_OAUTH_CLIENT_ID 미설정",
        )
    try:
        idinfo = id_token.verify_oauth2_token(
            credential,
            google_requests.Request(),
            settings.google_oauth_client_id,
            clock_skew_in_seconds=10,
        )
    except ValueError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Invalid Google credential: {e}") from e

    if idinfo.get("iss") not in ("accounts.google.com", "https://accounts.google.com"):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid Google issuer")
    if not idinfo.get("email_verified", False):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Email not verified")
    return idinfo


# -- FastAPI dependency: 현재 사용자 ----------------------------------------


async def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> LlmopsUser:
    if creds is None or creds.scheme.lower() != "bearer":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Bearer token required")

    payload = decode_token(creds.credentials)
    user_id = int(payload.get("sub", 0))
    if not user_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token subject")

    user = (
        await db.execute(select(LlmopsUser).where(LlmopsUser.id == user_id))
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")
    return user


# -- 역할 게이트 ------------------------------------------------------------

ROLE_RANK = {"llmops_guest": 0, "llmops_viewer": 1, "llmops_admin": 2}
VALID_ROLES = tuple(ROLE_RANK.keys())


def resolve_role(email: str) -> str:
    """LLMOPS_ADMIN_EMAILS allowlist 기준 역할 결정. 목록 외는 전부 guest."""
    admins = {e.strip().lower() for e in settings.llmops_admin_emails.split(",") if e.strip()}
    return "llmops_admin" if email.lower() in admins else "llmops_guest"


def require_member(user: LlmopsUser = Depends(get_current_user)) -> LlmopsUser:
    """viewer 이상 (guest 차단). 데이터 API 공통 게이트."""
    if ROLE_RANK.get(user.role, 0) < ROLE_RANK["llmops_viewer"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "권한이 없습니다 (guest)")
    return user


def require_admin(user: LlmopsUser = Depends(get_current_user)) -> LlmopsUser:
    if user.role != "llmops_admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin only")
    return user


# -- S2S 읽기 키 (v0.3.0) -----------------------------------------------------
#
# DocPipeline 등이 LLMOps 읽기 API(batch-runs/usage/golden-set/comparisons)를 pull 할 때
# X-API-Key 헤더로 인증한다. 키는 LLMOPS_READ_KEYS (JSON {client_id: key}). 인증된 S2S 요청은
# DB 에 없는 합성 viewer 사용자로 귀속되며 curated_by 등에는 "s2s:<client_id>" 가 기록된다.

S2S_EMAIL_PREFIX = "s2s:"


def load_read_keys() -> dict[str, str]:
    raw = (settings.llmops_read_keys or "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("LLMOPS_READ_KEYS is not valid JSON; ignoring all read keys")
        return {}
    return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}


def resolve_s2s_client(x_api_key: str) -> str | None:
    """키와 일치하는 client_id 를 돌려준다 (없으면 None). 타이밍 안전 비교."""
    for client_id, key in load_read_keys().items():
        if key and secrets.compare_digest(x_api_key, key):
            return client_id
    return None


def s2s_user(client_id: str) -> LlmopsUser:
    return LlmopsUser(id=0, email=f"{S2S_EMAIL_PREFIX}{client_id}", name=client_id, role="llmops_viewer")


async def require_member_or_s2s(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    creds: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> LlmopsUser:
    """X-API-Key 가 있으면 S2S 읽기 키 인증(합성 viewer), 없으면 JWT member 인증."""
    if x_api_key is not None:
        client_id = resolve_s2s_client(x_api_key)
        if client_id is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid API key")
        return s2s_user(client_id)
    user = await get_current_user(creds=creds, db=db)
    return require_member(user=user)

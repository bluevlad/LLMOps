"""JWT 발급·검증 + Google ID 토큰 검증.

llmops_users.role: llmops_admin / llmops_viewer (2단계)
P0 부트스트랩: 첫 가입자가 자동으로 llmops_admin (Phase 3 에서 화이트리스트로 강화)
패턴 참조: OpsConsole/backend/app/core/security.py
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Depends, HTTPException, status
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


# -- 역할 게이트 (단순 2단계) ----------------------------------------------

ROLE_RANK = {"llmops_viewer": 0, "llmops_admin": 1}
VALID_ROLES = tuple(ROLE_RANK.keys())


def require_admin(user: LlmopsUser = Depends(get_current_user)) -> LlmopsUser:
    if user.role != "llmops_admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin only")
    return user

"""POST /api/auth/google/verify, GET /api/auth/me.

흐름:
1. 프런트가 Google Identity Services 로 credential(JWT) 획득
2. POST /api/auth/google/verify { credential } → 백엔드에서 ID token 검증
3. llmops_users upsert (이메일 기준). 역할은 LLMOPS_ADMIN_EMAILS allowlist 로 결정 —
   목록 외 계정은 llmops_guest (데이터 접근 불가, 로그인 이력만 기록)
4. LLMOps 자체 JWT 발급 후 반환
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import (
    create_access_token,
    get_current_user,
    resolve_role,
    verify_google_id_token,
)
from app.database.session import get_db
from app.models.audit import LlmopsAuditLog
from app.models.user import LlmopsUser

router = APIRouter(prefix="/auth", tags=["auth"])


class GoogleVerifyRequest(BaseModel):
    credential: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict


class MeResponse(BaseModel):
    id: int
    email: str
    name: str | None
    role: str
    last_login_at: datetime | None


@router.post("/google/verify", response_model=TokenResponse)
async def google_verify(
    body: GoogleVerifyRequest, db: AsyncSession = Depends(get_db)
) -> TokenResponse:
    idinfo = verify_google_id_token(body.credential)
    email = idinfo["email"].lower()
    google_sub = idinfo["sub"]
    name = idinfo.get("name")

    role = resolve_role(email)

    user = (
        await db.execute(select(LlmopsUser).where(LlmopsUser.email == email))
    ).scalar_one_or_none()

    if user is None:
        user = LlmopsUser(
            email=email,
            name=name,
            google_sub=google_sub,
            role=role,
            last_login_at=datetime.now(timezone.utc),
        )
        db.add(user)
        await db.flush()
    else:
        user.last_login_at = datetime.now(timezone.utc)
        if name and user.name != name:
            user.name = name
        if user.google_sub is None:
            user.google_sub = google_sub
        # allowlist 가 역할의 SSoT — 로그인 시마다 재동기화 (기존 viewer 도 guest 로 강등)
        if user.role != role:
            user.role = role

    # 로그인 이력 기록 (guest 포함 전체)
    db.add(LlmopsAuditLog(
        actor_id=user.id,
        action="user.login",
        target_type="llmops_user",
        target_id=str(user.id),
        payload={"email": email, "role": user.role},
    ))

    await db.commit()
    await db.refresh(user)

    return TokenResponse(
        access_token=create_access_token(user),
        user={"id": user.id, "email": user.email, "name": user.name, "role": user.role},
    )


@router.get("/me", response_model=MeResponse)
async def me(user: LlmopsUser = Depends(get_current_user)) -> MeResponse:
    return MeResponse(
        id=user.id,
        email=user.email,
        name=user.name,
        role=user.role,
        last_login_at=user.last_login_at,
    )

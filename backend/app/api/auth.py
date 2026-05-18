"""POST /api/auth/google/verify, GET /api/auth/me.

흐름:
1. 프런트가 Google Identity Services 로 credential(JWT) 획득
2. POST /api/auth/google/verify { credential } → 백엔드에서 ID token 검증
3. llmops_users upsert (이메일 기준). 첫 가입자는 llmops_admin (P0 부트스트랩 정책)
4. LLMOps 자체 JWT 발급 후 반환
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import (
    create_access_token,
    get_current_user,
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

    user = (
        await db.execute(select(LlmopsUser).where(LlmopsUser.email == email))
    ).scalar_one_or_none()

    if user is None:
        # P0 부트스트랩: 첫 가입자는 admin, 이후는 viewer
        total = (await db.execute(select(func.count()).select_from(LlmopsUser))).scalar_one()
        initial_role = "llmops_admin" if total == 0 else "llmops_viewer"

        user = LlmopsUser(
            email=email,
            name=name,
            google_sub=google_sub,
            role=initial_role,
            last_login_at=datetime.now(timezone.utc),
        )
        db.add(user)
        await db.flush()
        db.add(LlmopsAuditLog(
            actor_id=user.id,
            action="user.bootstrap",
            target_type="llmops_user",
            target_id=str(user.id),
            payload={"email": email, "role": initial_role},
        ))
    else:
        user.last_login_at = datetime.now(timezone.utc)
        if name and user.name != name:
            user.name = name
        if user.google_sub is None:
            user.google_sub = google_sub

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

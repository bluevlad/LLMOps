"""역할 결정(allowlist) + guest 차단 게이트 테스트."""
import pytest
from fastapi import HTTPException

from app.core.config import settings
from app.core.security import require_admin, require_member, resolve_role
from app.models.user import LlmopsUser


def test_resolve_role_admin_allowlist(monkeypatch) -> None:
    monkeypatch.setattr(settings, "llmops_admin_emails", "admin@example.com, second@example.com")
    assert resolve_role("admin@example.com") == "llmops_admin"
    assert resolve_role("ADMIN@example.com") == "llmops_admin"
    assert resolve_role("second@example.com") == "llmops_admin"


def test_resolve_role_others_are_guest(monkeypatch) -> None:
    monkeypatch.setattr(settings, "llmops_admin_emails", "admin@example.com")
    assert resolve_role("someone@example.com") == "llmops_guest"


def test_resolve_role_empty_allowlist_no_admin(monkeypatch) -> None:
    monkeypatch.setattr(settings, "llmops_admin_emails", "")
    assert resolve_role("admin@example.com") == "llmops_guest"


def test_require_member_rejects_guest() -> None:
    guest = LlmopsUser(email="g@example.com", role="llmops_guest")
    with pytest.raises(HTTPException) as exc:
        require_member(user=guest)
    assert exc.value.status_code == 403


def test_require_member_allows_viewer_and_admin() -> None:
    for role in ("llmops_viewer", "llmops_admin"):
        user = LlmopsUser(email="m@example.com", role=role)
        assert require_member(user=user) is user


def test_require_admin_rejects_non_admin() -> None:
    for role in ("llmops_guest", "llmops_viewer"):
        user = LlmopsUser(email="m@example.com", role=role)
        with pytest.raises(HTTPException):
            require_admin(user=user)

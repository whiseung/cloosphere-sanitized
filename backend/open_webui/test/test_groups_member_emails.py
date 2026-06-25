"""GET /groups/id/{id}/member-emails 라우터 단위 테스트.

Gmail 수신자 picker 의 "그룹 → 멤버 이메일 펼침" 용 엔드포인트.
라우터 함수를 직접 await (코드베이스 컨벤션), Groups/Users 를 monkeypatch.
"""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from open_webui.routers import groups as groups_router


def _user(uid="req", role="user"):
    return SimpleNamespace(id=uid, role=role)


def _patch_group(monkeypatch, group):
    monkeypatch.setattr(groups_router.Groups, "get_group_by_id", lambda *a, **k: group)


@pytest.mark.asyncio
async def test_member_gets_emails(monkeypatch):
    group = SimpleNamespace(id="g1", name="영업팀", user_ids=["u1", "u2"])
    _patch_group(monkeypatch, group)
    monkeypatch.setattr(
        groups_router.Users,
        "get_users_by_user_ids",
        lambda *a, **k: [
            SimpleNamespace(id="u1", name="Alice", email="alice@x.com"),
            SimpleNamespace(id="u2", name="Bob", email="bob@x.com"),
        ],
    )
    # u1 은 멤버 → 허용.
    res = await groups_router.get_group_member_emails(id="g1", user=_user("u1"))
    assert [r.email for r in res] == ["alice@x.com", "bob@x.com"]
    assert res[0].name == "Alice"


@pytest.mark.asyncio
async def test_non_member_forbidden(monkeypatch):
    group = SimpleNamespace(id="g1", name="영업팀", user_ids=["u1"])
    _patch_group(monkeypatch, group)
    with pytest.raises(HTTPException) as exc:
        await groups_router.get_group_member_emails(id="g1", user=_user("intruder"))
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_admin_allowed_any_group(monkeypatch):
    group = SimpleNamespace(id="g1", name="x", user_ids=["u1"])
    _patch_group(monkeypatch, group)
    monkeypatch.setattr(
        groups_router.Users,
        "get_users_by_user_ids",
        lambda *a, **k: [SimpleNamespace(id="u1", name="A", email="a@x.com")],
    )
    res = await groups_router.get_group_member_emails(
        id="g1", user=_user("admin", "admin")
    )
    assert res[0].email == "a@x.com"


@pytest.mark.asyncio
async def test_skips_members_without_email(monkeypatch):
    group = SimpleNamespace(id="g1", name="x", user_ids=["u1", "u2"])
    _patch_group(monkeypatch, group)
    monkeypatch.setattr(
        groups_router.Users,
        "get_users_by_user_ids",
        lambda *a, **k: [
            SimpleNamespace(id="u1", name="A", email="a@x.com"),
            SimpleNamespace(id="u2", name="NoMail", email=""),
        ],
    )
    res = await groups_router.get_group_member_emails(
        id="g1", user=_user("admin", "admin")
    )
    assert [r.email for r in res] == ["a@x.com"]


@pytest.mark.asyncio
async def test_missing_group_404(monkeypatch):
    _patch_group(monkeypatch, None)
    with pytest.raises(HTTPException) as exc:
        await groups_router.get_group_member_emails(
            id="nope", user=_user("admin", "admin")
        )
    assert exc.value.status_code == 404

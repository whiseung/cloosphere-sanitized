"""GET /organizations/units/{id}/member-emails 라우터 단위 테스트.

Gmail 수신자 picker 의 "부서(org-unit) → 멤버 이메일 펼침" 용 엔드포인트.
멤버 출처: unit.meta.members(이메일) + unit.member_ids(user-id 또는 이메일).
라우터 함수를 직접 await, OrganizationalUnits/Users 를 monkeypatch.
"""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from open_webui.routers import organizations as org_router


def _user(uid="req", role="user"):
    return SimpleNamespace(id=uid, role=role)


def _patch_unit(monkeypatch, unit):
    monkeypatch.setattr(
        org_router.OrganizationalUnits,
        "get_organizational_unit_by_id",
        lambda *a, **k: unit,
    )


@pytest.mark.asyncio
async def test_meta_members_emails(monkeypatch):
    unit = SimpleNamespace(
        id="u1",
        name="영업부",
        member_ids=[],
        meta={
            "members": [
                {"name": "Alice", "email": "alice@x.com"},
                {"name": "Bob", "email": "bob@x.com"},
            ]
        },
    )
    _patch_unit(monkeypatch, unit)
    res = await org_router.get_org_unit_member_emails(id="u1", user=_user())
    assert sorted(r.email for r in res) == ["alice@x.com", "bob@x.com"]


@pytest.mark.asyncio
async def test_member_ids_resolve_userid_and_email(monkeypatch):
    # member_ids 에 user-id 와 직접 이메일 혼재.
    unit = SimpleNamespace(
        id="u1", name="x", member_ids=["uid-1", "direct@x.com"], meta={}
    )
    _patch_unit(monkeypatch, unit)
    monkeypatch.setattr(
        org_router.Users,
        "get_users_by_user_ids",
        lambda *a, **k: [
            SimpleNamespace(id="uid-1", name="Carol", email="carol@x.com")
        ],
    )
    res = await org_router.get_org_unit_member_emails(id="u1", user=_user())
    assert sorted(r.email for r in res) == ["carol@x.com", "direct@x.com"]


@pytest.mark.asyncio
async def test_dedup_across_sources(monkeypatch):
    unit = SimpleNamespace(
        id="u1",
        name="x",
        member_ids=["alice@x.com"],
        meta={"members": [{"name": "Alice", "email": "alice@x.com"}]},
    )
    _patch_unit(monkeypatch, unit)
    res = await org_router.get_org_unit_member_emails(id="u1", user=_user())
    assert len(res) == 1
    assert res[0].email == "alice@x.com"


@pytest.mark.asyncio
async def test_missing_unit_404(monkeypatch):
    _patch_unit(monkeypatch, None)
    with pytest.raises(HTTPException) as exc:
        await org_router.get_org_unit_member_emails(id="nope", user=_user())
    assert exc.value.status_code == 404

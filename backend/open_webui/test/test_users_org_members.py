"""GET /users/search/organization-members 라우터 단위 테스트.

라우터 함수를 직접 await (코드베이스 컨벤션). search_organization_members 를 patch.
"""

from types import SimpleNamespace

import pytest

from open_webui.routers import users as users_router


def _user(uid="req"):
    return SimpleNamespace(id=uid, role="user")


@pytest.mark.asyncio
async def test_returns_members(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        users_router,
        "search_organization_members",
        lambda uid, q, limit: captured.update(uid=uid, q=q, limit=limit)
        or [
            {
                "id": "a@x.com",
                "name": "A",
                "email": "a@x.com",
                "job_title": "",
                "profile_image_url": "",
            }
        ],
    )
    res = await users_router.search_organization_members_route(
        q="서", limit=50, user=_user()
    )
    assert captured["uid"] == "req" and captured["q"] == "서"
    assert res[0]["email"] == "a@x.com"


@pytest.mark.asyncio
async def test_blank_query_returns_empty():
    assert (
        await users_router.search_organization_members_route(q="  ", user=_user()) == []
    )

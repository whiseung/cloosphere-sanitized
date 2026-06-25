"""Regression tests for access_control NULL-permissions handling.

Covers the signin-500 regression where users auto-enrolled into groups via
`meta.org_unit_ids` (introduced in `e96201100 feat(backend): 그룹-조직 단위 권한 연동`)
could hit a group with `permissions = NULL` and crash
`combine_permissions` / `get_permission` with `AttributeError: 'NoneType' object has no attribute 'items'`.
"""

from types import SimpleNamespace

import pytest

from open_webui.utils import access_control


class _Grp(SimpleNamespace):
    """Duck-typed group stand-in (SQLAlchemy model mock)."""


DEFAULTS = {
    "workspace": {"knowledge": "none", "agents": "read"},
    "chat": {"delete": False},
}


@pytest.fixture
def patch_groups(monkeypatch):
    def _apply(groups):
        monkeypatch.setattr(
            access_control, "get_user_groups", lambda _uid: list(groups)
        )

    return _apply


def test_get_permissions_null_group_falls_back_to_defaults(patch_groups):
    patch_groups([_Grp(id="g1", permissions=None)])

    result = access_control.get_permissions("u1", DEFAULTS)

    # caller default의 키·값은 보존되어야 한다.
    # `get_permissions`는 추가로 `DEFAULT_USER_PERMISSIONS` 모듈 상수로 missing key를
    # 채우는 2차 안전망이 있어 result는 DEFAULTS의 superset이 된다 (de795b301).
    # 이 테스트의 의도는 "NULL group이 있어도 caller default가 안전하게 적용된다"이므로
    # superset 검증으로 의도 보존.
    assert result["workspace"]["knowledge"] == "none"
    assert result["workspace"]["agents"] == "read"
    assert result["chat"]["delete"] is False


def test_get_permissions_mixed_null_and_populated_groups(patch_groups):
    patch_groups(
        [
            _Grp(id="g1", permissions=None),
            _Grp(id="g2", permissions={"workspace": {"knowledge": "write"}}),
        ]
    )

    result = access_control.get_permissions("u1", DEFAULTS)

    assert result["workspace"]["knowledge"] == "write"
    assert result["workspace"]["agents"] == "read"
    assert result["chat"]["delete"] is False


def test_has_permission_null_group_uses_defaults(patch_groups):
    patch_groups([_Grp(id="g1", permissions=None)])

    assert access_control.has_permission("u1", "workspace.agents", DEFAULTS) is True
    assert access_control.has_permission("u1", "workspace.knowledge", DEFAULTS) is False


def test_has_permission_min_level_null_group(patch_groups):
    patch_groups([_Grp(id="g1", permissions=None)])

    assert (
        access_control.has_permission_min_level(
            "u1", "workspace.agents", "read", DEFAULTS
        )
        is True
    )
    assert (
        access_control.has_permission_min_level(
            "u1", "workspace.knowledge", "read", DEFAULTS
        )
        is False
    )


from types import SimpleNamespace as _NS


class _Unit(_NS):
    """OrganizationalUnit 모델 대역."""


def test_search_org_members_matches_name(monkeypatch):
    monkeypatch.setattr(
        access_control,
        "get_user_org_unit_ids",
        lambda uid, include_ancestors=False: ["unit-a"],
    )
    units_by_id = {"unit-a": _Unit(id="unit-a", organization_id="org-1")}
    org_units = {
        "org-1": [
            _Unit(
                id="unit-a",
                organization_id="org-1",
                member_ids=["only@eacme.com"],
                meta={
                    "members": [
                        {
                            "name": "서휘승",
                            "email": "Wsseo@eacme.com",
                            "job_title": "클루커스",
                        },
                        {"name": "김철수", "email": "kim@eacme.com", "job_title": ""},
                    ]
                },
            ),
        ]
    }
    monkeypatch.setattr(
        access_control.OrganizationalUnits,
        "get_organizational_unit_by_id",
        lambda uid: units_by_id.get(uid),
    )
    monkeypatch.setattr(
        access_control.OrganizationalUnits,
        "get_organizational_units_by_organization_id",
        lambda oid: org_units.get(oid, []),
    )
    res = access_control.search_organization_members("requester", "서", 50)
    assert len(res) == 1
    assert res[0]["name"] == "서휘승"
    assert res[0]["email"] == "Wsseo@eacme.com"  # 원본 email 표시 보존
    assert res[0]["id"] == "Wsseo@eacme.com"


def test_search_org_members_email_and_member_ids(monkeypatch):
    monkeypatch.setattr(
        access_control,
        "get_user_org_unit_ids",
        lambda uid, include_ancestors=False: ["unit-a"],
    )
    units_by_id = {"unit-a": _Unit(id="unit-a", organization_id="org-1")}
    org_units = {
        "org-1": [
            _Unit(
                id="unit-a",
                organization_id="org-1",
                member_ids=["only@eacme.com"],
                meta={
                    "members": [
                        {"name": "김철수", "email": "kim@eacme.com", "job_title": ""}
                    ]
                },
            ),
        ]
    }
    monkeypatch.setattr(
        access_control.OrganizationalUnits,
        "get_organizational_unit_by_id",
        lambda uid: units_by_id.get(uid),
    )
    monkeypatch.setattr(
        access_control.OrganizationalUnits,
        "get_organizational_units_by_organization_id",
        lambda oid: org_units.get(oid, []),
    )
    # member_ids 전용 email 도 검색됨(이름은 email 로 대체)
    res = access_control.search_organization_members("requester", "only", 50)
    assert [r["email"] for r in res] == ["only@eacme.com"]
    # email 부분 매칭
    res2 = access_control.search_organization_members("requester", "kim@", 50)
    assert [r["email"] for r in res2] == ["kim@eacme.com"]


def test_search_org_members_empty_when_no_membership(monkeypatch):
    monkeypatch.setattr(
        access_control, "get_user_org_unit_ids", lambda uid, include_ancestors=False: []
    )
    assert access_control.search_organization_members("requester", "서", 50) == []


def test_search_org_members_blank_query(monkeypatch):
    assert access_control.search_organization_members("requester", "   ", 50) == []

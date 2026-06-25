"""Regression tests for agent version control (agent_version).

핵심 속성 (DB 없이 도는 순수 단위):
- base 모델(base_model_id 없음)은 버전을 만들지 않는다 — create_version 게이트.
- 복원은 내용(name/params/meta/base_model_id)만 되돌리고, access_control·is_active 는
  보안상 현재 행 값을 유지한다 (옛 버전 복원으로 제거된 그룹에 재노출 방지).
- dedup 비교는 키 순서에 무관하다.
"""

from types import SimpleNamespace

from open_webui.models.agent_version import AgentVersions, _normalize
from open_webui.routers.models import _build_restore_form


def test_base_model_gets_no_version():
    # base_model_id 가 없으면 DB 접근 전 게이트에서 None (버전 미생성)
    assert (
        AgentVersions.create_version(
            "agent-x", {"base_model_id": None, "name": "b"}, "u1", "u1"
        )
        is None
    )


def test_restore_only_params_others_kept_current():
    # '프롬프트 버전관리' 취지: params(프롬프트)만 복원, 나머지는 현재 유지
    model = SimpleNamespace(
        id="a1",
        name="current-name",
        base_model_id="gpt-4o",
        access_control={"read": {"group_ids": ["g1"], "user_ids": []}},
        is_active=True,
        params={"system": "current prompt"},
        meta={"knowledge": [{"id": "k1", "name": "KB1"}], "description": "현재"},
    )
    snapshot = {
        "name": "old-name",
        "base_model_id": "gpt-3.5",
        "params": {"system": "old prompt"},
        "meta": {"knowledge": [], "description": "옛날"},  # 옛 연결 — 복원되면 안 됨
        "access_control": None,  # 옛 공개 권한 — 복원되면 안 됨
    }
    form = _build_restore_form(model, snapshot)

    # params(프롬프트)만 snapshot 에서 복원
    assert form.params.model_dump().get("system") == "old prompt"

    # name·base_model_id·meta(연결)·access_control·is_active 는 현재 유지
    assert form.name == "current-name"
    assert form.base_model_id == "gpt-4o"
    assert form.meta.model_dump().get("knowledge") == [{"id": "k1", "name": "KB1"}]
    assert form.access_control == {"read": {"group_ids": ["g1"], "user_ids": []}}
    assert form.is_active is True


def test_normalize_is_key_order_invariant():
    assert _normalize({"a": 1, "b": {"c": 2, "d": 3}}) == _normalize(
        {"b": {"d": 3, "c": 2}, "a": 1}
    )

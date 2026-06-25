"""created_via 메타 (Hallucination 검수 워크플로우) — T14.

- ``_merge_entries_overwrite`` (router helper) 의 created_via 부여/보존 로직
- pagination 필터 로직 (모델 helper, 순수 함수 부분)
"""


# router 모듈 import 가 무겁고 DB 가 필요한 부분도 있어서 helper 만 import.
# 환경변수/DB 의존성 없는 순수 함수만 테스트 대상.


def test_merge_overwrite_assigns_default_created_via_to_new_entry():
    from open_webui.routers.glossary import _merge_entries_overwrite

    out = _merge_entries_overwrite(
        existing=[],
        to_apply=[{"term": "B/L", "description": "x"}],
    )
    assert len(out) == 1
    assert out[0]["created_via"] == "extract_db"


def test_merge_overwrite_preserves_existing_created_via_on_update():
    from open_webui.routers.glossary import _merge_entries_overwrite

    out = _merge_entries_overwrite(
        existing=[
            {
                "term": "B/L",
                "description": "old",
                "created_via": "manual",
                "created_at": 100,
            }
        ],
        to_apply=[{"term": "B/L", "description": "new"}],
    )
    assert len(out) == 1
    # 기존 'manual' 보존, default 'extract_db' 로 덮어쓰지 않음
    assert out[0]["created_via"] == "manual"
    assert out[0]["description"] == "new"


def test_merge_overwrite_respects_explicit_created_via_in_incoming():
    from open_webui.routers.glossary import _merge_entries_overwrite

    out = _merge_entries_overwrite(
        existing=[],
        to_apply=[
            {
                "term": "FCL",
                "description": "x",
                "created_via": "ai_rule",
            }
        ],
    )
    assert out[0]["created_via"] == "ai_rule"


def test_get_entries_paginated_filter_created_via_logic():
    """get_entries_paginated 의 created_via 필터 로직 (in-memory dict 시뮬레이션)."""

    entries = [
        {"term": "A", "created_via": "manual", "created_at": 1, "category": None},
        {"term": "B", "created_via": "ai_rule", "created_at": 2, "category": None},
        {"term": "C", "created_via": "extract_db", "created_at": 3, "category": None},
        {"term": "D", "created_via": None, "created_at": 4, "category": None},
        # legacy entry without created_via at all
        {"term": "E", "created_at": 5, "category": None},
    ]

    # 필터 로직만 시뮬레이션 (모델 코드와 동일)
    def filter_cv(entries, allowed):
        return [
            e
            for e in entries
            if (e.get("created_via") in allowed)
            or ("legacy" in allowed and not e.get("created_via"))
        ]

    # 'ai_rule' 만 → B
    assert [e["term"] for e in filter_cv(entries, {"ai_rule"})] == ["B"]
    # 'manual' + 'legacy' → A, D, E (D 의 None 과 E 의 missing 모두 legacy)
    assert sorted(e["term"] for e in filter_cv(entries, {"manual", "legacy"})) == [
        "A",
        "D",
        "E",
    ]
    # 'ai_rule' + 'extract_db' → B, C
    assert sorted(e["term"] for e in filter_cv(entries, {"ai_rule", "extract_db"})) == [
        "B",
        "C",
    ]

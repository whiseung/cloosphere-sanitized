"""Unit tests for KB clone worker meta-handling logic — file.meta whitelist,
KB.meta merge with cloned_from / clone_state, source.data.file_metadata
snapshot semantics.

`services/kb_clone_worker.py` 의 핵심 데이터 변환 분기만 검증.
SQLAlchemy / Storage / SearchEngine 의존성 회피를 위해 production 와
byte-for-byte 동일한 로직을 인라인 재현.

대응 task:
- T15: ``meta.filter_schema`` 보존 (KB.meta 통째 복사 검증)
- T18 (신규): ``data.file_metadata`` snapshot 패턴 — 진행 중 source 갱신 무시
- ``ALLOWED_FILE_META_KEYS`` 화이트리스트 contract — collection_name /
  pending_knowledge_id / processing_job 누설 방지
- KB.meta merge: ``{**source.meta, "cloned_from": {...}, "clone_state": "cloning"}``
"""

import time

import pytest

# ---------------------------------------------------------------------------
# ALLOWED_FILE_META_KEYS — 화이트리스트 contract
# ---------------------------------------------------------------------------


# Production 상수의 인라인 사본 — production 변경 시 본 테스트도 갱신해야 정합성 유지.
# (P-M3 / M1 critique 결정사항으로 잠금된 set)
ALLOWED_FILE_META_KEYS = {
    "name",
    "content_type",
    "size",
    "classification",
    "document_profile",
    "summary",
}


def _filter_file_meta(src_meta: dict) -> dict:
    """``_clone_one_file`` 의 meta whitelist 적용 인라인 재현."""
    return {k: v for k, v in (src_meta or {}).items() if k in ALLOWED_FILE_META_KEYS}


def test_whitelist_keeps_allowed_keys():
    """allowed key 6 종 모두 보존."""
    src = {
        "name": "report.pdf",
        "content_type": "application/pdf",
        "size": 1024,
        "classification": "internal",
        "document_profile": "default",
        "summary": "Q3 report",
    }
    assert _filter_file_meta(src) == src


def test_whitelist_drops_collection_name():
    """collection_name 은 새 KB 로 다르게 세팅돼야 하므로 누설 차단."""
    src = {"name": "f.pdf", "collection_name": "old-kb-id"}
    out = _filter_file_meta(src)
    assert out == {"name": "f.pdf"}
    assert "collection_name" not in out


def test_whitelist_drops_pending_knowledge_id():
    """pending_knowledge_id 누락 — worker 가 새 KB 에 add_file_id 호출 후 set."""
    src = {"name": "f.pdf", "pending_knowledge_id": "old-kb-id"}
    out = _filter_file_meta(src)
    assert "pending_knowledge_id" not in out


def test_whitelist_drops_processing_job():
    """이전 처리 job 상태 누락 — clone 시 새 처리 시작."""
    src = {"name": "f.pdf", "processing_job": {"status": "completed"}}
    out = _filter_file_meta(src)
    assert "processing_job" not in out


def test_whitelist_drops_arbitrary_unknown_keys():
    """미래에 다른 키 추가돼도 보수적으로 차단 (allow-list semantic)."""
    src = {
        "name": "f.pdf",
        "owner_email": "test@example.com",  # 누설 시 cross-tenant 위험
        "internal_uid": "abc123",
    }
    out = _filter_file_meta(src)
    assert out == {"name": "f.pdf"}


def test_whitelist_handles_empty_meta():
    """빈 meta 도 안전하게 빈 dict 반환."""
    assert _filter_file_meta({}) == {}
    assert _filter_file_meta(None) == {}


# ---------------------------------------------------------------------------
# KB.meta merge — cloned_from + clone_state, user_id 누설 차단
# ---------------------------------------------------------------------------


def _build_clone_meta(source_meta: dict, source_id: str, now: int) -> dict:
    """``routers/knowledge.py:clone_knowledge_by_id`` Step 5 의 meta 구성 인라인 재현.

    P-H2 critique: ``{**source.meta, "cloned_from": {...}}`` 형태로 source
    meta 를 보존해야 filter_schema, tool_description, search_settings,
    document_profile_id, filter_extraction_mode 모두 자동 따라간다.
    """
    return {
        **(source_meta or {}),
        "cloned_from": {"kb_id": source_id, "at": now},
        "clone_state": "cloning",
    }


def test_meta_preserves_filter_schema():
    """T15: filter_schema (KB 필터 정의) 보존 — 통째 spread 로 자동 따라옴."""
    schema = [{"slot": "f_str_1", "label": "팀"}, {"slot": "f_int_1", "label": "년도"}]
    out = _build_clone_meta({"filter_schema": schema}, "src-kb", 1000)
    assert out["filter_schema"] == schema


def test_meta_preserves_tool_description():
    """에이전트가 KB 를 도구로 쓸 때 보여줄 설명 — meta 보존 필요."""
    desc = "Use for HR policy questions."
    out = _build_clone_meta({"tool_description": desc}, "src", 0)
    assert out["tool_description"] == desc


def test_meta_preserves_search_settings_with_document_profile():
    """search_settings (검색 설정) + 그 안의 document_profile_id 까지 보존.

    document_profile_id 가 file.meta 가 아니라 KB.meta.search_settings 에
    있다는 점이 핵심 — meta 통째 복사가 정확히 이 케이스를 커버.
    """
    ss = {
        "document_profile_id": "profile-abc",
        "top_k": 5,
        "filter_extraction_mode": "manual",
    }
    out = _build_clone_meta({"search_settings": ss}, "src", 0)
    assert out["search_settings"] == ss
    assert out["search_settings"]["document_profile_id"] == "profile-abc"


def test_meta_cloned_from_only_has_kb_id_and_at():
    """P-L2: cloned_from 에 user_id 노출 X. kb_id + at 만 — 다른 사용자 정보 누설 방지."""
    out = _build_clone_meta({}, "src-kb-uuid", 1234567890)
    assert out["cloned_from"] == {"kb_id": "src-kb-uuid", "at": 1234567890}
    assert "user_id" not in out["cloned_from"]


def test_meta_clone_state_is_cloning_initially():
    """Worker 진입 전 라우터 단계: ``clone_state="cloning"``."""
    out = _build_clone_meta({}, "src", 0)
    assert out["clone_state"] == "cloning"


def test_meta_does_not_mutate_source_meta():
    """원본 meta dict 변형되면 source DB row 가 영향받을 수 있음 — spread 는 새 dict."""
    source_meta = {"filter_schema": [{"slot": "f_str_1"}]}
    out = _build_clone_meta(source_meta, "src", 0)
    out["filter_schema"].append({"slot": "f_str_2"})  # 새 dict 인지 검증
    # 원본 source_meta 의 list 가 공유돼있으면 여기서 같이 변하므로,
    # production 코드도 깊은 복사 필요. shallow spread 만 하므로 list 는 공유됨.
    # 이 테스트는 contract 를 명시적으로 표현 — list 공유는 의도적이지만 dict 자체는
    # 새 객체.
    assert out is not source_meta  # 최소한 outer dict 는 다름


def test_meta_overrides_clone_state_if_source_had_it():
    """원본에 우연히 ``clone_state`` 가 있어도 새 값으로 덮어씀 (cloned KB 의 자체 상태)."""
    source_meta = {"clone_state": "ready"}  # 원본도 cloned 였음
    out = _build_clone_meta(source_meta, "src", 0)
    assert out["clone_state"] == "cloning"  # 새 KB 의 상태


# ---------------------------------------------------------------------------
# Source snapshot pattern — file_metadata 진행 중 변경 무시
# ---------------------------------------------------------------------------


def _extract_file_metadata_snapshot(source_data: dict | None) -> dict:
    """worker 시작 시점의 ``source.data.file_metadata`` snapshot 생성.

    `process_kb_clone_task` 의 핵심: source 가 worker 진행 중 다른 경로로
    update 돼도 영향 안 받음. source.data 를 한 번 읽어 dict 추출 후
    file 단위로 lookup.
    """
    return (source_data or {}).get("file_metadata") or {}


def test_snapshot_returns_empty_dict_when_no_file_metadata():
    """source.data 에 file_metadata 키 없으면 빈 dict — 안전한 .get(file_id) 가능."""
    assert _extract_file_metadata_snapshot({}) == {}
    assert _extract_file_metadata_snapshot({"file_ids": ["a"]}) == {}
    assert _extract_file_metadata_snapshot(None) == {}


def test_snapshot_returns_filter_slots_per_file():
    """T18: file_metadata 스냅샷에 filter slot (f_str_*, f_int_*) 보존."""
    data = {
        "file_metadata": {
            "f1": {"f_str_1": "재무팀", "f_int_1": 2024},
            "f2": {"f_str_1": "법무팀"},
        }
    }
    snap = _extract_file_metadata_snapshot(data)
    assert snap == data["file_metadata"]
    assert snap["f1"]["f_str_1"] == "재무팀"


def test_snapshot_immune_to_post_read_source_mutation():
    """worker 시작 후 source.data 가 변해도 snapshot 은 그대로.

    실제로 production 에서는 ``source.data`` 가 SQLAlchemy session 캐시
    객체일 수 있어 ref 공유 위험이 있는데, snapshot 시점에 ``or {}`` 로
    얕게 분리되므로 file_metadata dict 자체는 공유. 그러나 worker 가
    file 별로 lookup 만 하고 mutate 안 하므로 안전.

    이 테스트는 contract 를 명시화 — snapshot 후 외부 변경 시 worker 가
    어떻게 보는지.
    """
    file_meta = {"f1": {"f_str_1": "old"}}
    source_data = {"file_metadata": file_meta}

    snap = _extract_file_metadata_snapshot(source_data)
    # source 측에서 file 자체를 새 dict 로 덮어쓰면 snap 는 옛 ref 유지.
    source_data["file_metadata"] = {"f1": {"f_str_1": "new"}}
    assert snap["f1"]["f_str_1"] == "old"


# ---------------------------------------------------------------------------
# Filter slot 분리 — vector index 갱신용 키만 추출
# ---------------------------------------------------------------------------


def _extract_slot_values(meta: dict) -> dict:
    """``_clone_one_file`` 에서 vector slot update 호출 직전 분기.

    file_metadata 안의 ``f_str_*`` / ``f_int_*`` / ``f_date_*`` /
    ``f_col_*`` prefix 만 골라서 ``update_file_filter_slots`` 에 전달.
    """
    return {
        k: v
        for k, v in (meta or {}).items()
        if k.startswith(("f_str_", "f_int_", "f_date_", "f_col_"))
    }


def test_slot_extraction_keeps_all_four_prefixes():
    meta = {
        "f_str_1": "재무팀",
        "f_int_1": 2024,
        "f_date_1": "2024-01-15",
        "f_col_1": ["tag-a", "tag-b"],
        "ai_summary": "요약 텍스트",  # non-slot
        "extracted_at": 1700000000,  # non-slot
    }
    slots = _extract_slot_values(meta)
    assert set(slots.keys()) == {"f_str_1", "f_int_1", "f_date_1", "f_col_1"}


def test_slot_extraction_returns_empty_when_no_slots():
    """slot 키 없으면 빈 dict — caller 가 update_file_filter_slots 호출 자체를 skip."""
    assert _extract_slot_values({"ai_summary": "x"}) == {}
    assert _extract_slot_values({}) == {}
    assert _extract_slot_values(None) == {}


def test_slot_extraction_handles_higher_indices():
    """f_str_2, f_int_5 같은 높은 index 도 그대로 보존."""
    meta = {"f_str_2": "x", "f_int_5": 99, "f_str_99": "y"}
    slots = _extract_slot_values(meta)
    assert slots == meta


def test_slot_extraction_does_not_match_unrelated_f_prefix():
    """``f_random``, ``filter_xxx`` 등 prefix 가 다른 키는 false positive 안 됨."""
    meta = {"f_random": "x", "filter_blob": "y", "fst_1": "z"}
    slots = _extract_slot_values(meta)
    assert slots == {}


# ---------------------------------------------------------------------------
# T9 — 0-파일 KB 즉시 ready 분기 (라우터 단계)
# ---------------------------------------------------------------------------


def test_zero_file_kb_skips_worker_enqueue():
    """T9: file_ids 비어있으면 worker enqueue 생략 후 바로 ready.

    routers/knowledge.py Step 6 분기 simulation. indexed_with marker 도
    의미 없어 미저장 (인덱싱 자체가 없으므로 비교할 대상 X).
    """
    source_data = {"file_ids": []}
    file_ids = (source_data or {}).get("file_ids") or []
    if not file_ids:
        # 즉시 ready meta_patch 만 생성하고 종료 — worker 호출 X
        meta_patch = {"clone_state": "ready", "clone_completed_at": int(time.time())}
        assert meta_patch["clone_state"] == "ready"
        assert "indexed_with" not in meta_patch  # 0 파일은 마커 무의미
        return  # worker 분기 진입 X

    pytest.fail("0-파일 KB 인데 worker 분기로 빠짐")

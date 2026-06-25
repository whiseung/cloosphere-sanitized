"""
Tests for knowledge_handler query stabilization (Variant A2).

Covers:
- Raw user message prepend (Channel B/C/D mitigation)
- Standalone-validity guard (follow-up noise skip)
- Unicode-normalized dedup
- Feature flag toggle (backward compat)

Reference: dev/active/rag-retrieval-stability/rag-retrieval-stability-plan.md
"""

from typing import List, Optional, Union

from extension_modules.react.tools_base import ReactToolsBase
from extension_modules.search_engine.filter_builder import build_knowledge_filter


def _build(
    queries: Union[str, List[str]],
    raw_user_message: Optional[str],
    enable_fallback: bool = True,
) -> List[str]:
    """Test wrapper — calls the static helper under test."""
    return ReactToolsBase._build_search_query_list(
        queries=queries,
        raw_user_message=raw_user_message,
        enable_fallback=enable_fallback,
    )


class TestRawQueryPrepend:
    """Raw user message가 LLM-generated queries 앞에 prepend되는지 검증."""

    def test_raw_prepended_to_list(self):
        result = _build(
            queries=["import manifest 신고 마감"],
            raw_user_message="태국 수입화물의 import manifest(입항목록) 신고 마감 시간은?",
        )
        assert len(result) == 2
        assert (
            result[0] == "태국 수입화물의 import manifest(입항목록) 신고 마감 시간은?"
        )
        assert result[1] == "import manifest 신고 마감"

    def test_raw_prepended_to_str_query(self):
        result = _build(
            queries="manifest deadline",
            raw_user_message="태국 import manifest 마감 시간은?",
        )
        assert result[0] == "태국 import manifest 마감 시간은?"
        assert result[1] == "manifest deadline"

    def test_raw_none_falls_back_to_llm_only(self):
        result = _build(
            queries=["LLM query 1", "LLM query 2"],
            raw_user_message=None,
        )
        assert result == ["LLM query 1", "LLM query 2"]


class TestStandaloneValidityGuard:
    """짧은/대명사-only/JSON-like raw query는 skip되어야 함 (follow-up 노이즈 방지)."""

    def test_skip_too_short_raw(self):
        # 5자 미만 → skip
        result = _build(
            queries=["부산 항만 시간"],
            raw_user_message="부산?",
        )
        assert result == ["부산 항만 시간"]

    def test_skip_pronoun_only(self):
        # "그럼", "그러면" 같은 follow-up 대명사 → skip
        for pronoun in ["그럼?", "그러면?", "그건요?", "그건 뭐야"]:
            result = _build(
                queries=["부산 LCL CFS 마감"],
                raw_user_message=pronoun,
            )
            assert result == ["부산 LCL CFS 마감"], f"failed for: {pronoun}"

    def test_skip_json_like(self):
        # JSON 형태로 들어온 raw → skip (역할 추출 실패 케이스)
        result = _build(
            queries=["import 마감"],
            raw_user_message='{"role": "user", "content": "..."}',
        )
        assert result == ["import 마감"]

    def test_keep_valid_long_korean(self):
        # 한국어 자연문 — 통과
        result = _build(
            queries=["관세 신고"],
            raw_user_message="태국 수입화물 관세 신고 마감 시간은?",
        )
        assert len(result) == 2
        assert result[0].startswith("태국")

    def test_keep_valid_long_english(self):
        result = _build(
            queries=["manifest"],
            raw_user_message="What is the manifest deadline for Thailand?",
        )
        assert len(result) == 2


class TestDedup:
    """Unicode normalize + lowercase + whitespace로 dedup."""

    def test_dedup_exact_match(self):
        # raw == LLM[0] → 1개만 남음
        same = "태국 import manifest 마감 시간은?"
        result = _build(
            queries=[same],
            raw_user_message=same,
        )
        assert len(result) == 1
        assert result[0] == same

    def test_dedup_whitespace_difference(self):
        # 공백 차이 — dedup 대상
        result = _build(
            queries=["태국  import  manifest  마감"],
            raw_user_message="태국 import manifest 마감",
        )
        assert len(result) == 1

    def test_dedup_case_insensitive(self):
        result = _build(
            queries=["IMPORT Manifest"],
            raw_user_message="import manifest",
        )
        assert len(result) == 1

    def test_dedup_preserves_first_occurrence(self):
        # dedup 시 raw (원본) 가 우선 — LLM 변형이 아닌 raw 보존
        result = _build(
            queries=["IMPORT MANIFEST 마감"],
            raw_user_message="import manifest 마감",
        )
        assert len(result) == 1
        assert result[0] == "import manifest 마감"  # raw 가 first

    def test_no_dedup_when_different(self):
        result = _build(
            queries=["DEM DET fee"],
            raw_user_message="태국 수입화물 관세 신고 마감",
        )
        assert len(result) == 2


class TestFeatureFlag:
    """enable_fallback=False → 기존 LLM-only 동작."""

    def test_flag_off_ignores_raw(self):
        result = _build(
            queries=["LLM query"],
            raw_user_message="태국 수입화물 관세 신고",
            enable_fallback=False,
        )
        assert result == ["LLM query"]

    def test_flag_off_str_to_list(self):
        # backward compat: str → [str] 변환은 유지
        result = _build(
            queries="single query",
            raw_user_message="raw input",
            enable_fallback=False,
        )
        assert result == ["single query"]


class TestEdgeCases:
    """엣지케이스 — 빈 list, 빈 string, 동일 raw + LLM 첫번째."""

    def test_empty_llm_list_keeps_raw(self):
        result = _build(
            queries=[],
            raw_user_message="태국 import manifest 마감 시간",
        )
        assert result == ["태국 import manifest 마감 시간"]

    def test_empty_llm_str(self):
        result = _build(
            queries="",
            raw_user_message="태국 import manifest 마감 시간",
        )
        # 빈 query는 dedup 후 raw만 남음
        assert "태국 import manifest 마감 시간" in result
        assert "" not in result

    def test_both_empty(self):
        result = _build(
            queries="",
            raw_user_message=None,
        )
        # str → [str]; 빈 query는 그대로 (search engine 단에서 처리)
        assert result == [""]


# ─────────────────────────────────────────────────────────────
# F2 — sentinel filter value strip
# ─────────────────────────────────────────────────────────────


class TestStripSentinelFilters:
    """LLM 이 'Any', '전체' 등 sentinel 값을 filter 에 넣으면 OData 충돌. backend 강제 strip."""

    def test_none_input(self):
        assert ReactToolsBase._strip_sentinel_filter_values(None) is None

    def test_empty_dict(self):
        assert ReactToolsBase._strip_sentinel_filter_values({}) == {}

    def test_strip_any(self):
        result = ReactToolsBase._strip_sentinel_filter_values(
            {"국가/지역": "TH", "bl_type": "Any"}
        )
        assert result == {"국가/지역": "TH"}

    def test_strip_korean_sentinels(self):
        result = ReactToolsBase._strip_sentinel_filter_values(
            {"국가": "TH", "지역": "전체", "부서": "모두", "팀": "없음"}
        )
        assert result == {"국가": "TH"}

    def test_strip_null_like(self):
        result = ReactToolsBase._strip_sentinel_filter_values(
            {"a": None, "b": "", "c": "  ", "d": "N/A", "e": "valid"}
        )
        assert result == {"e": "valid"}

    def test_list_value_sentinel_drop(self):
        # list 안 sentinel 만 제거. 남은 valid 값은 보존
        result = ReactToolsBase._strip_sentinel_filter_values(
            {"카테고리": ["MANIFEST_FILING", "Any", "CUSTOMS", None]}
        )
        assert result == {"카테고리": ["MANIFEST_FILING", "CUSTOMS"]}

    def test_list_all_sentinel_drops_key(self):
        # list 가 sentinel 만 → key 자체 제거
        result = ReactToolsBase._strip_sentinel_filter_values(
            {"카테고리": ["Any", "전체", None], "국가": "TH"}
        )
        assert result == {"국가": "TH"}

    def test_keep_non_string_values(self):
        # int/float/bool 은 그대로 통과 (year, count 등)
        result = ReactToolsBase._strip_sentinel_filter_values(
            {"연도": 2024, "활성": True, "점수": 3.5}
        )
        assert result == {"연도": 2024, "활성": True, "점수": 3.5}

    def test_all_sentinel_returns_none(self):
        # 모두 sentinel → None 반환 (filter_expr 생성 skip)
        result = ReactToolsBase._strip_sentinel_filter_values(
            {"a": "Any", "b": "전체", "c": None}
        )
        assert result is None

    def test_acme_thailand_real_case(self):
        # 실제 production 회귀 케이스 (backend log 에서 캡처)
        result = ReactToolsBase._strip_sentinel_filter_values(
            {
                "국가/지역": "TH",
                "토픽 카테고리": ["MANIFEST_FILING"],
                "bl_type": "Any",
            }
        )
        assert result == {
            "국가/지역": "TH",
            "토픽 카테고리": ["MANIFEST_FILING"],
        }


# ─────────────────────────────────────────────────────────────
# F1 — slot conflict guard in build_knowledge_filter
# ─────────────────────────────────────────────────────────────


class TestFilterSlotConflictGuard:
    """같은 slot 이 두 label 에 매핑되면 첫 적용만 통과 (OData AND 충돌 방지)."""

    def test_no_conflict_normal(self):
        result = build_knowledge_filter(
            collection_ids=["kb1"],
            filter_schema=[
                {"label": "국가/지역", "slot": "f_str_1", "type": "enum"},
                {"label": "카테고리", "slot": "f_col_1", "type": "collection"},
            ],
            filter_values={"국가/지역": "TH", "카테고리": ["MANIFEST_FILING"]},
        )
        assert "f_str_1 eq 'TH'" in result
        assert "f_col_1/any" in result

    def test_slot_conflict_skips_second(self):
        # 같은 slot 'f_str_1' 이 두 label 에 — 첫 것만 박혀야 함
        result = build_knowledge_filter(
            collection_ids=["kb1"],
            filter_schema=[
                {"label": "국가/지역", "slot": "f_str_1", "type": "enum"},
                {"label": "bl_type", "slot": "f_str_1", "type": "enum"},
            ],
            filter_values={"국가/지역": "TH", "bl_type": "Original"},
        )
        # 첫 매핑 (TH) 만 박힘
        assert result.count("f_str_1 eq") == 1
        assert "'TH'" in result
        assert "'Original'" not in result

    def test_real_acme_regression(self):
        # 본 PR 의 RCA 케이스 재현 — 'TH' + 'Any' 충돌
        result = build_knowledge_filter(
            collection_ids=["kb1"],
            filter_schema=[
                {"label": "국가/지역", "slot": "f_str_1", "type": "enum"},
                {"label": "bl_type", "slot": "f_str_1", "type": "enum"},
            ],
            filter_values={"국가/지역": "TH", "bl_type": "Any"},
        )
        # 첫 매핑만 통과 → AND 충돌 차단
        assert result.count("f_str_1 eq") == 1
        assert "'TH'" in result

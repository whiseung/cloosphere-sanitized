"""Tests for source_type-aware eval context routing (PR6).

chat_upload(사용자가 대화 중 올린 ad-hoc 파일)을 retrieval 품질 metric 에서 제외해
부당한 grounding penalty 를 막는다. faithfulness 는 업로드 파일을 출처 자료로
포함해 file-기반 주장이 ungrounded 로 오판되지 않게 한다.

- retrieval(context_relevance): chat_upload 제외 (검색 품질 측정 — 업로드는 검색 아님)
- faithfulness: 전체 포함 (응답은 KB + 업로드 파일 모두에 충실해야 함)
- quality: context 없음

Reference: dev/active/agent-file-context-prefetch/ (PR6)
"""

from extension_modules.auto_evaluation.evaluator import (
    select_eval_contexts,
    source_type_of,
)


def _ctx(source_type=None, name="x"):
    meta = {} if source_type is None else {"source_type": source_type}
    return {"source": {"name": name}, "document": ["body"], "metadata": [meta]}


KB = _ctx("knowledge_base", "kb1")
UPLOAD = _ctx("chat_upload", "f1")
WEB = _ctx("web", "w1")
KG = _ctx("knowledge_graph", "g1")
LEGACY = _ctx(None, "legacy")  # provenance 없음 → unknown


class TestSourceTypeOf:
    def test_extracts_from_metadata_list(self):
        assert source_type_of(KB) == "knowledge_base"
        assert source_type_of(UPLOAD) == "chat_upload"
        assert source_type_of(WEB) == "web"

    def test_missing_provenance_defaults_unknown(self):
        assert source_type_of(LEGACY) == "unknown"
        assert source_type_of({}) == "unknown"
        assert source_type_of({"metadata": []}) == "unknown"
        assert source_type_of({"metadata": "not-a-list"}) == "unknown"
        assert source_type_of({"metadata": [None]}) == "unknown"

    def test_falls_back_to_source_type_field(self):
        # metadata.source_type 없으면 source.type 사용 (_bundle_sources_by_provenance 와 일치)
        ctx = {"source": {"name": "x", "type": "chat_upload"}, "metadata": [{}]}
        assert source_type_of(ctx) == "chat_upload"

    def test_defensive_against_malformed_input(self):
        # 참조(_bundle_sources_by_provenance)보다 방어적 — 비-dict ctx·int metadata·비-dict
        # source 도 crash 없이 "unknown" 으로 수렴 (참조는 metadata=int 시 TypeError).
        assert source_type_of(None) == "unknown"
        assert source_type_of("not-a-dict") == "unknown"
        assert source_type_of({"metadata": 123}) == "unknown"
        assert source_type_of({"source": "notdict", "metadata": [{}]}) == "unknown"


class TestSelectEvalContexts:
    def test_retrieval_excludes_only_chat_upload(self):
        sel = select_eval_contexts("retrieval", [KB, UPLOAD, WEB, KG])
        assert [source_type_of(c) for c in sel] == [
            "knowledge_base",
            "web",
            "knowledge_graph",
        ]

    def test_retrieval_chat_upload_only_is_empty(self):
        assert select_eval_contexts("retrieval", [UPLOAD]) == []

    def test_legacy_unknown_kept_in_retrieval(self):
        # backward-safe: chat_upload 만 제외, unknown/legacy 는 retrieval 로 취급
        sel = select_eval_contexts("retrieval", [LEGACY])
        assert len(sel) == 1

    def test_faithfulness_includes_all(self):
        sel = select_eval_contexts("faithfulness", [KB, UPLOAD])
        assert [source_type_of(c) for c in sel] == ["knowledge_base", "chat_upload"]

    def test_quality_returns_none(self):
        assert select_eval_contexts("quality", [KB, UPLOAD]) is None

    def test_unknown_eval_type_returns_none(self):
        assert select_eval_contexts("bogus", [KB]) is None

    def test_none_contexts_safe(self):
        assert select_eval_contexts("retrieval", None) == []
        assert select_eval_contexts("faithfulness", None) == []
        assert select_eval_contexts("quality", None) is None

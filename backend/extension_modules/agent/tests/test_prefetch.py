"""
Tests for deterministic uploaded-file prefetch helpers (PR4).

Pure helpers (size gate, PII redaction, empty-file notice) extracted into
prefetch.py so they're unit-testable without the heavy UnifiedAgent import.

Reference: dev/active/agent-file-context-prefetch/ (PR4)
"""

import json

from extension_modules.agent.prefetch import (
    apply_size_gate,
    build_prefetch_tool_messages,
    compute_missing_file_ids,
    mark_empty_sources,
    merge_prefetched_bundles,
    redact_pii,
    truncate_to_tokens,
)


class TestBuildPrefetchToolMessages:
    def test_pair_shape_and_pairing(self):
        sources = [{"source": {"id": "f1", "name": "a.pdf"}, "document": ["body"]}]
        msgs = build_prefetch_tool_messages(sources, tool_call_id="tc1")
        assert len(msgs) == 2
        ai, tool = msgs
        # AIMessage carries the tool_call; ToolMessage carries the matching id
        assert ai["role"] == "assistant"
        assert ai["tool_calls"][0]["id"] == "tc1"
        assert ai["tool_calls"][0]["function"]["name"] == "get_file_contents"
        assert tool["role"] == "tool"
        assert tool["tool_call_id"] == "tc1"

    def test_tool_content_is_sources_json(self):
        sources = [{"source": {"id": "f1", "name": "매뉴얼.pdf"}, "document": ["내용"]}]
        _ai, tool = build_prefetch_tool_messages(sources)
        parsed = json.loads(tool["content"])
        assert parsed["sources"] == sources
        # Korean preserved (ensure_ascii=False) so the model reads it natively
        assert "매뉴얼.pdf" in tool["content"]

    def test_default_tool_call_id(self):
        ai, tool = build_prefetch_tool_messages([])
        assert ai["tool_calls"][0]["id"] == tool["tool_call_id"] == "prefetch_files"


class TestComputeMissingFileIds:
    def test_no_existing_bundles_all_missing(self):
        assert compute_missing_file_ids(["a", "b"], {}) == ["a", "b"]

    def test_dedup_existing_chat_upload_by_file_id(self):
        bundles = {"chat_upload": [{"metadata": [{"file_id": "a"}]}]}
        assert compute_missing_file_ids(["a", "b"], bundles) == ["b"]

    def test_identity_fallback_when_no_file_id(self):
        bundles = {"chat_upload": [{"metadata": [{}], "identity": "a"}]}
        assert compute_missing_file_ids(["a", "b"], bundles) == ["b"]

    def test_kb_bundles_do_not_dedup_uploads(self):
        bundles = {"knowledge_base": [{"metadata": [{"file_id": "a"}]}]}
        assert compute_missing_file_ids(["a"], bundles) == ["a"]

    def test_empty_attached(self):
        assert compute_missing_file_ids([], {"chat_upload": []}) == []
        assert compute_missing_file_ids(None, None) == []


class TestMergePrefetchedBundles:
    def test_merge_into_empty(self):
        sb: dict = {}
        out = merge_prefetched_bundles(sb, {"chat_upload": [{"x": 1}]})
        assert out["chat_upload"] == [{"x": 1}]

    def test_append_to_existing_type(self):
        sb = {"chat_upload": [{"a": 1}]}
        merge_prefetched_bundles(sb, {"chat_upload": [{"b": 2}]})
        assert sb["chat_upload"] == [{"a": 1}, {"b": 2}]

    def test_empty_prefetched_noop(self):
        sb = {"chat_upload": [{"a": 1}]}
        assert merge_prefetched_bundles(sb, {}) == {"chat_upload": [{"a": 1}]}
        assert merge_prefetched_bundles(sb, None) == {"chat_upload": [{"a": 1}]}


class TestTruncateToTokens:
    def test_under_budget_unchanged(self):
        text = "hello world"
        out, used = truncate_to_tokens(text, 1000)
        assert out == text
        assert used >= 1

    def test_empty_text(self):
        assert truncate_to_tokens("", 100) == ("", 0)

    def test_zero_budget_notice(self):
        out, used = truncate_to_tokens("x" * 100, 0)
        assert used == 0
        assert "생략" in out

    def test_over_budget_head_tail_marker(self):
        text = "가" * 5000
        out, used = truncate_to_tokens(text, 50)
        assert len(out) < len(text)
        assert "생략" in out
        assert used == 50
        # head + tail of the original content preserved
        assert out.startswith("가")
        assert out.rstrip().endswith("가")


class TestApplySizeGate:
    def test_small_files_untouched(self):
        sources = [{"document": ["small text"], "source": {"name": "a"}}]
        out = apply_size_gate(sources, per_file_cap=1000, total_cap=2000)
        assert out[0]["document"] == ["small text"]

    def test_total_budget_exhausts_second_file(self):
        big = "단어 " * 2000
        sources = [
            {"document": [big], "source": {"name": "a"}},
            {"document": [big], "source": {"name": "b"}},
        ]
        out = apply_size_gate(sources, per_file_cap=100, total_cap=120)
        # both truncated: file A consumes ~100, file B only has ~20 budget left
        assert "생략" in out[0]["document"][0]
        assert len(out[1]["document"][0]) < len(big)

    def test_empty_doc_passthrough(self):
        sources = [{"document": [""], "source": {"name": "a"}}]
        out = apply_size_gate(sources)
        assert out[0]["document"] == [""]

    def test_non_dict_source_skipped(self):
        out = apply_size_gate([None, {"document": ["x"], "source": {"name": "a"}}])
        assert out[1]["document"] == ["x"]


class TestMarkEmptySources:
    def test_empty_gets_notice(self):
        sources = [{"document": [""], "source": {"name": "scan.pdf"}}]
        out = mark_empty_sources(sources)
        assert "scan.pdf" in out[0]["document"][0]
        assert "추출" in out[0]["document"][0]

    def test_whitespace_only_gets_notice(self):
        sources = [{"document": ["   \n  "], "source": {"name": "f"}}]
        out = mark_empty_sources(sources)
        assert "추출" in out[0]["document"][0]

    def test_nonempty_unchanged(self):
        sources = [{"document": ["real content"], "source": {"name": "f"}}]
        out = mark_empty_sources(sources)
        assert out[0]["document"] == ["real content"]


class _RedactEngine:
    def process_text(self, text, is_input):
        return text.replace("SECRET", "[REDACTED]"), [{"t": "x"}], False


class _BlockEngine:
    def process_text(self, text, is_input):
        return text, [{"t": "x"}], True


class _BoomEngine:
    def process_text(self, text, is_input):
        raise RuntimeError("boom")


class TestRedactPii:
    def test_redacts_with_engine(self):
        sources = [{"document": ["my SECRET data"], "source": {"name": "f"}}]
        out = redact_pii(sources, [_RedactEngine()])
        assert out[0]["document"] == ["my [REDACTED] data"]

    def test_no_engines_unchanged(self):
        sources = [{"document": ["my SECRET data"], "source": {"name": "f"}}]
        out = redact_pii(sources, [])
        assert out[0]["document"] == ["my SECRET data"]

    def test_blocked_strategy_excludes_body(self):
        sources = [{"document": ["sensitive"], "source": {"name": "secret.pdf"}}]
        out = redact_pii(sources, [_BlockEngine()])
        body = out[0]["document"][0]
        assert "sensitive" not in body
        assert "secret.pdf" in body and "제외" in body

    def test_engine_exception_fails_closed(self):
        # 엔진 오류 시 un-redacted 본문을 흘려보내지 않고 제외 (fail-closed)
        sources = [{"document": ["sensitive data"], "source": {"name": "f.pdf"}}]
        out = redact_pii(sources, [_BoomEngine()])  # must not raise
        body = out[0]["document"][0]
        assert "sensitive data" not in body
        assert "f.pdf" in body and "제외" in body

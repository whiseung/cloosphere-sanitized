"""
Tests for final-answer prompt context split + deterministic citation (PR3).

Goal: chat-uploaded files must NOT be forced into the "Document Sources" + [1][2]
citation treatment (citation 폭격 + raw dump). Citation is a deterministic 2-state:
- KB/web present        -> "required" (citation on, legacy behavior)
- chat upload only      -> "optional" (citation off, clean summary/rewrite)
- structured / no source -> "none"

There is intentionally NO "mixed" mode (it hallucinates citation markers): when KB
and uploads coexist, citation is "required" and applies only to the KB section.

Reference: dev/active/agent-file-context-prefetch/ (PR3)
"""

from extension_modules.agent.prompts import (
    get_unified_final_answer_prompt,
    resolve_citation_mode,
    split_source_contexts,
)
from extension_modules.agent.unified_agent import build_sql_results_context
from langchain_core.messages import AIMessage, ToolMessage


def _bundle(name, docs, **extra):
    b = {"display_name": name, "document": docs, "source": {"id": name, "name": name}}
    b.update(extra)
    return b


class TestSplitSourceContexts:
    def test_chat_upload_no_citation_events(self):
        bundles = {"chat_upload": [_bundle("manual.pdf", ["body text"])]}
        src, up, events, has_cite, has_up = split_source_contexts(bundles)
        assert has_up is True
        assert has_cite is False
        assert events == []  # uploads are NOT emitted as citation sources
        assert src == ""
        assert "manual.pdf" in up
        assert "[1]" not in up  # no citation index on uploads

    def test_kb_numbered_and_emitted(self):
        bundles = {
            "knowledge_base": [
                _bundle("policy.md", ["chunk"], metadata=[{"x": 1}], distances=[0.3])
            ]
        }
        src, up, events, has_cite, has_up = split_source_contexts(bundles)
        assert has_cite is True
        assert has_up is False
        assert up == ""
        assert "[1] policy.md" in src
        assert len(events) == 1
        # emitted event keeps legacy transport shape
        assert events[0]["source"] == {"id": "policy.md", "name": "policy.md"}
        assert events[0]["distances"] == [0.3]

    def test_index_alignment_across_two_kb(self):
        bundles = {
            "knowledge_base": [
                _bundle("a.md", ["da"]),
                _bundle("b.md", ["db"]),
            ]
        }
        src, _up, events, _hc, _hu = split_source_contexts(bundles)
        assert "[1] a.md" in src
        assert "[2] b.md" in src
        # event order matches [i] numbering (single source of truth)
        assert [e["source"]["name"] for e in events] == ["a.md", "b.md"]

    def test_empty_doc_bundle_skipped_no_index_gap(self):
        bundles = {
            "knowledge_base": [
                _bundle("empty.md", ["   "]),  # whitespace-only → skipped
                _bundle("real.md", ["content"]),
            ]
        }
        src, _up, events, _hc, _hu = split_source_contexts(bundles)
        # real.md must be [1], not [2] (no gap from skipped empty bundle)
        assert "[1] real.md" in src
        assert "empty.md" not in src
        assert len(events) == 1

    def test_mixed_uploads_not_emitted_kb_cited(self):
        bundles = {
            "chat_upload": [_bundle("up.pdf", ["upbody"])],
            "knowledge_base": [_bundle("kb.md", ["kbbody"])],
        }
        src, up, events, has_cite, has_up = split_source_contexts(bundles)
        assert has_cite and has_up
        assert "[1] kb.md" in src
        assert "up.pdf" in up
        assert [e["source"]["name"] for e in events] == ["kb.md"]

    def test_unknown_and_url_types_are_cited(self):
        bundles = {"url": [_bundle("X", ["web"])], "unknown": [_bundle("Y", ["y"])]}
        _src, _up, events, has_cite, has_up = split_source_contexts(bundles)
        assert has_cite is True
        assert has_up is False
        assert len(events) == 2

    def test_none_and_empty(self):
        assert split_source_contexts(None) == ("", "", [], False, False)
        assert split_source_contexts({}) == ("", "", [], False, False)


class TestBundleToSplitContract:
    """Lock the producer→consumer dict contract across the react_base/prompts
    boundary — real `_bundle_sources_by_provenance` output must flow through
    `split_source_contexts` (guards silent field-rename drift)."""

    def test_real_bundles_flow_through_split(self):
        from extension_modules.react.react_base import ReactAgentBase

        sources = [
            {
                "source": {"id": "up1", "name": "up.pdf"},
                "document": ["upbody"],
                "metadata": [{"source_type": "chat_upload", "file_id": "up1"}],
            },
            {
                "source": {"id": "kb1", "name": "kb.md"},
                "document": ["kbbody"],
                "distances": [0.3],
                "metadata": [{"source_type": "knowledge_base", "file_id": "kb1"}],
            },
        ]
        bundles = ReactAgentBase._bundle_sources_by_provenance(sources)
        src, up, events, has_cite, has_up = split_source_contexts(bundles)

        assert has_cite and has_up
        assert "[1] kb.md" in src and "kbbody" in src
        assert "up.pdf" in up and "upbody" in up
        # only the KB source is emitted as a citation event, with its distance
        assert [e["source"]["name"] for e in events] == ["kb.md"]
        assert events[0]["distances"] == [0.3]


def _system_text(messages) -> str:
    return messages[0].content


class TestResolveCitationMode:
    def test_structured_forces_none(self):
        assert (
            resolve_citation_mode(
                has_uploaded=True, has_citation_sources=True, use_structured=True
            )
            == "none"
        )

    def test_kb_present_required(self):
        assert (
            resolve_citation_mode(
                has_uploaded=False, has_citation_sources=True, use_structured=False
            )
            == "required"
        )

    def test_upload_only_optional(self):
        assert (
            resolve_citation_mode(
                has_uploaded=True, has_citation_sources=False, use_structured=False
            )
            == "optional"
        )

    def test_kb_and_upload_is_required_not_mixed(self):
        # Deterministic: KB wins → required (cite KB section only). Never "mixed".
        assert (
            resolve_citation_mode(
                has_uploaded=True, has_citation_sources=True, use_structured=False
            )
            == "required"
        )

    def test_no_sources_none(self):
        assert (
            resolve_citation_mode(
                has_uploaded=False, has_citation_sources=False, use_structured=False
            )
            == "none"
        )


class TestUploadedFilesNoCitation:
    def test_upload_only_no_citation_machinery(self):
        # active_capabilities=[] also guards the has_data path (uploaded ctx must
        # keep the full prompt, not fall back to casual chat).
        msgs = get_unified_final_answer_prompt(
            uploaded_files_context="### manual.pdf\nsome content",
            citation_mode="optional",
            normalized_question="요약해줘",
            active_capabilities=[],
        )
        text = _system_text(msgs)
        assert "Uploaded Files" in text
        assert "manual.pdf" in text
        assert "Citation Rules" not in text
        assert "[1], [2] format" not in text
        assert "Never attach citation markers" not in text

    def test_upload_section_instructs_clean_rewrite(self):
        msgs = get_unified_final_answer_prompt(
            uploaded_files_context="### a.pdf\nbody",
            citation_mode="optional",
            normalized_question="정리",
            active_capabilities=[],
        )
        text = _system_text(msgs).lower()
        assert "summarize" in text or "rewrite" in text


class TestKbKeepsCitation:
    def test_kb_required_has_citation_rules(self):
        msgs = get_unified_final_answer_prompt(
            sources_context="[1] policy.md\n- text",
            citation_mode="required",
            normalized_question="정책 알려줘",
            active_capabilities=["kbsphere"],
        )
        text = _system_text(msgs)
        assert "Document Sources" in text
        assert "Citation Rules" in text
        assert "[1], [2]" in text
        assert "Cite sources using [1], [2] format" in text
        assert "Never attach citation markers" in text

    def test_mixed_kb_and_upload_both_sections(self):
        msgs = get_unified_final_answer_prompt(
            sources_context="[1] kb.md\n- kbtext",
            uploaded_files_context="### up.pdf\nupbody",
            citation_mode="required",
            normalized_question="q",
            active_capabilities=["kbsphere"],
        )
        text = _system_text(msgs)
        assert "Uploaded Files" in text
        assert "Document Sources" in text
        assert "Citation Rules" in text


class TestStructuredNoCitation:
    def test_structured_keeps_sources_drops_citation(self):
        msgs = get_unified_final_answer_prompt(
            sources_context="[1] policy.md\n- text",
            citation_mode="none",
            normalized_question="추출",
            active_capabilities=["kbsphere"],
        )
        text = _system_text(msgs)
        # Data still present for grounding...
        assert "Document Sources" in text
        assert "policy.md" in text
        # ...but no citation instructions.
        assert "Citation Rules" not in text
        assert "Cite sources using [1], [2] format" not in text
        assert "Never attach citation markers" not in text


class TestBackwardCompatDefault:
    def test_default_citation_mode_required_preserves_legacy(self):
        # Existing callers pass sources_context with no citation_mode → default
        # "required" must reproduce the legacy citation-on prompt.
        msgs = get_unified_final_answer_prompt(
            sources_context="[1] kb.md\n- t",
            normalized_question="q",
            active_capabilities=["kbsphere"],
        )
        text = _system_text(msgs)
        assert "Citation Rules" in text
        assert "Never attach citation markers" in text

    def test_no_data_casual_chat_unaffected(self):
        # No sources, no uploads, no caps → casual assistant prompt (unchanged).
        msgs = get_unified_final_answer_prompt(
            normalized_question="안녕",
            active_capabilities=[],
        )
        text = _system_text(msgs)
        assert "helpful assistant" in text.lower()
        assert "Document Sources" not in text
        assert "Uploaded Files" not in text

    def test_output_only_capability_keeps_casual_prompt(self):
        # document_tools is an output/utility capability (create_pptx/docx/xlsx),
        # not a grounding source. A plain model with it defaulted on must still
        # answer a general-knowledge question from general knowledge — NOT refuse
        # with the strict grounding "no data" prompt. (regression: 일반 질의가
        # "근거 자료가 없습니다" 로 거부되던 버그)
        for cap in ("document_tools", "code_interpreter"):
            msgs = get_unified_final_answer_prompt(
                normalized_question="각 나라별 사용 언어를 알려줘",
                active_capabilities=[cap],
            )
            text = _system_text(msgs)
            assert "helpful assistant" in text.lower(), cap
            assert "Grounding Rules" not in text, cap

    def test_created_document_still_uses_full_prompt(self):
        # When a file was actually created this turn (document_tool_links set), the
        # full prompt MUST render so the "Document Generation Notes" directive tells
        # the LLM the file exists — otherwise it denies its own output.
        msgs = get_unified_final_answer_prompt(
            normalized_question="PPT 만들어줘",
            active_capabilities=["document_tools"],
            document_tool_links=["http://host/files/deck.pptx"],
        )
        text = _system_text(msgs)
        assert "Document Generation Notes" in text
        assert "helpful assistant providing a comprehensive answer" in text.lower()

    def test_grounding_capability_keeps_grounding_prompt(self):
        # A grounding capability that gathered nothing must still get the strict
        # grounding prompt (say "the data does not cover this", do not invent).
        msgs = get_unified_final_answer_prompt(
            normalized_question="우리 회사 매출 알려줘",
            active_capabilities=["dbsphere"],
        )
        assert "Grounding Rules" in _system_text(msgs)

    def test_web_search_relaxes_grounding_to_general_knowledge(self):
        # web_search on = the owner enabled external/world knowledge. A general
        # question the connected sources don't cover must be answered from general
        # knowledge, NOT refused with "the data does not cover this".
        # (regression: 일반 모델(web_search ON)이 일반 지식 질문을 거부하던 버그)
        text = _system_text(
            get_unified_final_answer_prompt(
                normalized_question="각 나라별 사용 언어를 알려줘",
                active_capabilities=["kbsphere", "dbsphere", "web_search"],
            )
        )
        assert "answer from your own general knowledge" in text
        assert "Do not use external or general knowledge" not in text
        # private data must still be protected from fabrication
        assert "PRIVATE data" in text

    def test_no_web_search_keeps_strict_grounding(self):
        # Pure KB/DB bot (web_search OFF) must keep the strict contract so an
        # enterprise data agent still refuses when the data does not cover it.
        text = _system_text(
            get_unified_final_answer_prompt(
                normalized_question="각 나라별 사용 언어를 알려줘",
                active_capabilities=["kbsphere", "dbsphere"],
            )
        )
        assert "MUST be grounded in the gathered data" in text
        assert "answer from your own general knowledge" not in text

    def test_grounding_disabled_relaxes_without_web_search(self):
        # grounding 토글 off (capabilities.grounding="off") → web_search 없이도
        # 완화 모드. 연결 소스가 질문을 못 다루면 일반 지식으로 보완(거부 안 함).
        text = _system_text(
            get_unified_final_answer_prompt(
                normalized_question="각 나라별 사용 언어를 알려줘",
                active_capabilities=["kbsphere", "dbsphere"],
                grounding_enabled=False,
            )
        )
        assert "answer from your own general knowledge" in text
        assert "MUST be grounded in the gathered data" not in text
        # 완화 모드여도 PRIVATE 데이터 날조는 여전히 금지
        assert "PRIVATE data" in text

    def test_grounding_enabled_default_keeps_strict(self):
        # grounding_enabled 기본값(True)은 기존 strict 동작을 그대로 유지한다.
        text = _system_text(
            get_unified_final_answer_prompt(
                normalized_question="우리 회사 매출 알려줘",
                active_capabilities=["dbsphere"],
                grounding_enabled=True,
            )
        )
        assert "MUST be grounded in the gathered data" in text
        assert "answer from your own general knowledge" not in text


# ----------------------------------------------------------------------------
# build_sql_results_context: lossless SQL→final_answer handoff (every successful
# query's SQL body + result, paired via tool_call_id).
# ----------------------------------------------------------------------------


def _ai_sql(sql, tc_id, *, name="run_sql_read", content="", dbsphere_id=None):
    args = {"sql": sql}
    if dbsphere_id is not None:
        args["dbsphere_id"] = dbsphere_id
    return AIMessage(
        content=content, tool_calls=[{"name": name, "args": args, "id": tc_id}]
    )


def _ok(tc_id, body="**Results:** 1 rows, 1 columns\n**Preview:**\nx\n1"):
    return ToolMessage(
        content=f"Query executed successfully.\n\n{body}", tool_call_id=tc_id
    )


def _err(tc_id, msg="syntax error"):
    return ToolMessage(content=f"Error executing SQL query: {msg}", tool_call_id=tc_id)


class TestBuildSqlResultsContext:
    def test_empty_messages_returns_blank(self):
        assert build_sql_results_context([]) == ""

    def test_single_successful_query_includes_sql_and_result(self):
        sql = "SELECT product_category FROM t WHERE subsidiary='SEA'"
        out = build_sql_results_context([_ai_sql(sql, "tc1"), _ok("tc1")])
        assert "```sql" in out
        assert "WHERE subsidiary='SEA'" in out
        assert "Query executed successfully" in out
        assert "### Query 1" in out

    def test_multiple_queries_in_execution_order(self):
        msgs = [
            _ai_sql("SELECT 1 AS a", "tc1"),
            _ok("tc1"),
            _ai_sql("SELECT 2 AS b", "tc2"),
            _ok("tc2"),
        ]
        out = build_sql_results_context(msgs)
        assert out.index("### Query 1") < out.index("### Query 2")
        assert "SELECT 1 AS a" in out and "SELECT 2 AS b" in out

    def test_failed_query_skipped_with_note(self):
        msgs = [
            _ai_sql("SELECT 1", "tc1"),
            _ok("tc1"),
            _ai_sql("SELECT bad", "tcF"),
            _err("tcF", "boom"),
        ]
        out = build_sql_results_context(msgs)
        assert "boom" not in out  # error body excluded
        assert "1 SQL attempt(s) failed" in out
        assert "SELECT 1" in out

    def test_only_failures_returns_blank(self):
        assert (
            build_sql_results_context([_ai_sql("SELECT bad", "tcF"), _err("tcF")]) == ""
        )

    def test_success_without_matching_tool_call_fallback(self):
        # success ToolMessage whose tool_call_id has no originating AIMessage
        out = build_sql_results_context([_ok("orphan")])
        assert "SQL text unavailable" in out
        assert "Query executed successfully" in out

    def test_no_rows_returned_included(self):
        msgs = [
            _ai_sql("SELECT 1 WHERE 1=0", "tc1"),
            ToolMessage(
                content="Query executed successfully. No rows returned.",
                tool_call_id="tc1",
            ),
        ]
        out = build_sql_results_context(msgs)
        assert "No rows returned" in out
        assert "```sql" in out

    def test_write_statement_success_included(self):
        msgs = [
            _ai_sql("UPDATE t SET x=1", "tcW", name="run_sql_write"),
            ToolMessage(
                content="Statement executed successfully. (Driver did not return count.)",
                tool_call_id="tcW",
            ),
        ]
        out = build_sql_results_context(msgs)
        assert "Statement executed successfully" in out
        assert "UPDATE t SET x=1" in out

    def test_multi_db_label(self):
        msgs = [
            _ai_sql("SELECT 1", "tc1", dbsphere_id="db_fin"),
            _ok("tc1"),
            _ai_sql("SELECT 2", "tc2"),  # no dbsphere_id → no label
            _ok("tc2"),
        ]
        out = build_sql_results_context(msgs)
        assert "(database: db_fin)" in out
        assert out.count("(database:") == 1

    def test_validator_rejection_ignored(self):
        msgs = [
            ToolMessage(
                content="run_sql_read only executes read-only SQL ...",
                tool_call_id="tcX",
            )
        ]
        assert build_sql_results_context(msgs) == ""

    def test_robust_against_odd_inputs(self):
        # empty-args tool_call (no 'sql') → fallback; non-message junk is skipped;
        # a valid query in the same run still renders. Helper must never raise.
        odd = AIMessage(
            content="", tool_calls=[{"name": "run_sql_read", "args": {}, "id": "tcE"}]
        )
        msgs = [
            "junk-not-a-message",
            odd,
            _ok("tcE"),
            _ai_sql("SELECT ok", "tc1"),
            _ok("tc1"),
        ]
        out = build_sql_results_context(msgs)
        assert "SELECT ok" in out
        assert "SQL text unavailable" in out  # tcE had no sql

    def test_intent_included_when_ai_content_present(self):
        msgs = [
            _ai_sql("SELECT 1", "tc1", content="사용자 sea 를 subsidiary 로 해석"),
            _ok("tc1"),
        ]
        assert "사용자 sea 를 subsidiary 로 해석" in build_sql_results_context(msgs)

    def test_max_queries_caps_and_notes(self):
        msgs = []
        for i in range(3):
            msgs += [_ai_sql(f"SELECT {i}", f"tc{i}"), _ok(f"tc{i}")]
        out = build_sql_results_context(msgs, max_queries=2)
        assert "showing the last 2 of 3" in out
        assert "SELECT 0" not in out  # oldest dropped
        assert "SELECT 2" in out

    def test_default_cap_bounds_many_queries(self):
        # No explicit max_queries → default cap keeps context size bounded even
        # when the agent runs many queries (e.g. thousands of rows × 15 runs).
        msgs = []
        for i in range(15):
            msgs += [_ai_sql(f"SELECT col{i}", f"tc{i}"), _ok(f"tc{i}")]
        out = build_sql_results_context(msgs)
        assert "showing the last 12 of 15" in out
        assert "SELECT col0" not in out  # oldest dropped
        assert "SELECT col14" in out  # newest kept

    def test_long_sql_body_truncated(self):
        long_sql = "SELECT " + ", ".join(f"c{i}" for i in range(2000))  # >2000 chars
        out = build_sql_results_context([_ai_sql(long_sql, "tc1"), _ok("tc1")])
        assert "(SQL truncated)" in out

    def test_long_result_truncated(self):
        huge = "Query executed successfully.\n\n**Preview:**\n" + ("x" * 5000)
        msgs = [
            _ai_sql("SELECT 1", "tc1"),
            ToolMessage(content=huge, tool_call_id="tc1"),
        ]
        out = build_sql_results_context(msgs)
        assert "...(truncated)" in out
        assert len(out) < 5000  # result safety-capped


class TestSqlResultsSectionGrounding:
    def test_sql_results_section_has_grounding_rule(self):
        msgs = get_unified_final_answer_prompt(
            sql_results="### Query 1\n```sql\nSELECT 1\n```\nok",
            normalized_question="q",
            active_capabilities=["dbsphere"],
        )
        text = _system_text(msgs)
        assert "## SQL Query Results" in text
        assert "GROUNDING RULES" in text
        assert "WHERE" in text
        assert "source of truth" in text

    def test_no_sql_results_section_omitted(self):
        msgs = get_unified_final_answer_prompt(
            sql_results="",
            normalized_question="q",
            active_capabilities=["dbsphere"],
        )
        assert "## SQL Query Results" not in _system_text(msgs)

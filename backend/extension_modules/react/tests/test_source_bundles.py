"""
Tests for typed source aggregation (PR2).

`build_source_bundles` groups sources by provenance identity
(source_type, collection_id|file_id|id) instead of filename — preventing the
same-name chat-upload vs KB collision documented in the refactor analysis (§3.3).

`build_aggregated_sources_by_filename` is preserved as a legacy filename-grouping
path; its output must remain byte-identical after the shared-extraction refactor
(regression lock), since `_run_stream`/source-event/`_raw_sources` consumers are
unchanged until PR3.

Reference: dev/active/agent-file-context-prefetch/ (PR2)
"""

import json

from extension_modules.react.react_base import ReactAgentBase
from langchain_core.messages import HumanMessage, ToolMessage


class _StubAgent(ReactAgentBase):
    """Minimal concrete subclass — only `run` is abstract."""

    def run(self, question: str) -> str:  # pragma: no cover - not exercised
        return ""


def _agent() -> _StubAgent:
    return _StubAgent(api_config={}, base_url="", api_key="", metadata={})


def _tool_result(payload: dict) -> dict:
    """A LangGraph result with one HumanMessage + one ToolMessage carrying sources."""
    return {
        "messages": [
            HumanMessage(content="q"),
            ToolMessage(content=json.dumps(payload), tool_call_id="t1"),
        ]
    }


class TestBundleByProvenance:
    def test_same_filename_different_type_not_merged(self):
        # Core fix: identical display name but different provenance must NOT merge.
        sources = [
            {
                "source": {"id": "up1", "name": "매뉴얼.pdf"},
                "document": ["upload body"],
                "metadata": [
                    {
                        "source_type": "chat_upload",
                        "file_id": "up1",
                        "citation_policy": "optional",
                    }
                ],
            },
            {
                "source": {"id": "kb1", "name": "매뉴얼.pdf"},
                "document": ["kb chunk"],
                "metadata": [
                    {
                        "source_type": "knowledge_base",
                        "file_id": "kb1",
                        "citation_policy": "required",
                    }
                ],
            },
        ]
        bundles = ReactAgentBase._bundle_sources_by_provenance(sources)
        assert set(bundles) == {"chat_upload", "knowledge_base"}
        assert len(bundles["chat_upload"]) == 1
        assert len(bundles["knowledge_base"]) == 1
        assert bundles["chat_upload"][0]["document"] == ["upload body"]
        assert bundles["chat_upload"][0]["citation_policy"] == "optional"
        assert bundles["chat_upload"][0]["display_name"] == "매뉴얼.pdf"
        assert bundles["knowledge_base"][0]["citation_policy"] == "required"

    def test_same_type_same_id_merged(self):
        # Two KB chunks of the same document (file_id) merge into one bundle.
        sources = [
            {
                "source": {"id": "kb1", "name": "p.md"},
                "document": ["chunk A"],
                "distances": [0.1],
                "metadata": [{"source_type": "knowledge_base", "file_id": "doc-9"}],
            },
            {
                "source": {"id": "kb2", "name": "p.md"},
                "document": ["chunk B"],
                "distances": [0.2],
                "metadata": [{"source_type": "knowledge_base", "file_id": "doc-9"}],
            },
        ]
        bundles = ReactAgentBase._bundle_sources_by_provenance(sources)
        assert len(bundles["knowledge_base"]) == 1
        b = bundles["knowledge_base"][0]
        assert b["document"] == ["chunk A", "chunk B"]
        assert b["distances"] == [0.1, 0.2]
        assert b["identity"] == "doc-9"

    def test_collection_id_takes_precedence_over_file_id(self):
        sources = [
            {
                "source": {"id": "s1", "name": "a"},
                "document": ["x"],
                "metadata": [
                    {
                        "source_type": "knowledge_base",
                        "collection_id": "kb-7",
                        "file_id": "f-1",
                    }
                ],
            },
        ]
        bundles = ReactAgentBase._bundle_sources_by_provenance(sources)
        assert bundles["knowledge_base"][0]["identity"] == "kb-7"

    def test_unknown_type_falls_back_to_source_type_field(self):
        # Web sources carry no provenance metadata but have source.type == "url".
        sources = [
            {
                "source": {"type": "url", "id": "http://x", "name": "X"},
                "document": ["web body"],
                "metadata": [{}],
            }
        ]
        bundles = ReactAgentBase._bundle_sources_by_provenance(sources)
        assert "url" in bundles
        # citation defaults to 'required' for sources without explicit policy
        assert bundles["url"][0]["citation_policy"] == "required"

    def test_empty(self):
        assert ReactAgentBase._bundle_sources_by_provenance([]) == {}

    def test_non_dict_entries_skipped(self):
        sources = [
            None,
            "garbage",
            {"source": {"id": "ok", "name": "n"}, "document": ["d"], "metadata": [{}]},
        ]
        bundles = ReactAgentBase._bundle_sources_by_provenance(sources)
        assert sum(len(v) for v in bundles.values()) == 1


class TestBuildSourceBundlesFromResult:
    def test_extracts_from_tool_messages_and_sets_raw_sources(self):
        agent = _agent()
        payload = {
            "sources": [
                {
                    "source": {"id": "up1", "name": "a.pdf"},
                    "document": ["body"],
                    "metadata": [{"source_type": "chat_upload", "file_id": "up1"}],
                }
            ]
        }
        bundles = agent.build_source_bundles(_tool_result(payload))
        assert "chat_upload" in bundles
        assert bundles["chat_upload"][0]["document"] == ["body"]
        # shared-extraction side effect (consumed by auto-eval at unified_agent:3120)
        assert agent._raw_sources
        assert agent._raw_sources[0]["source"]["id"] == "up1"


class TestLegacyAggregationUnchanged:
    """Regression lock — filename grouping must be byte-identical post-refactor."""

    def test_same_filename_merged_into_one_bucket(self):
        agent = _agent()
        payload = {
            "sources": [
                {
                    "source": {"id": "a", "name": "doc.pdf"},
                    "document": ["one"],
                    "metadata": [{"source": "file:doc.pdf", "name": "doc.pdf"}],
                },
                {
                    "source": {"id": "b", "name": "doc.pdf"},
                    "document": ["two"],
                    "metadata": [{"source": "file:doc.pdf", "name": "doc.pdf"}],
                },
            ]
        }
        agg = agent.build_aggregated_sources_by_filename(_tool_result(payload))
        assert len(agg) == 1
        merged = next(iter(agg.values()))
        assert merged["document"] == ["one", "two"]
        # keyed by metadata 'source'
        assert "file:doc.pdf" in agg

    def test_raw_sources_set_by_legacy_path(self):
        agent = _agent()
        payload = {
            "sources": [
                {
                    "source": {"id": "a", "name": "doc.pdf"},
                    "document": ["one"],
                    "metadata": [{"source": "file:doc.pdf"}],
                }
            ]
        }
        agent.build_aggregated_sources_by_filename(_tool_result(payload))
        assert len(agent._raw_sources) == 1

    def test_distances_merged(self):
        agent = _agent()
        payload = {
            "sources": [
                {
                    "source": {"id": "a", "name": "kb.md"},
                    "document": ["x"],
                    "distances": [0.5],
                    "metadata": [{"source": "kb:1"}],
                }
            ]
        }
        agg = agent.build_aggregated_sources_by_filename(_tool_result(payload))
        merged = next(iter(agg.values()))
        assert merged["distances"] == [0.5]

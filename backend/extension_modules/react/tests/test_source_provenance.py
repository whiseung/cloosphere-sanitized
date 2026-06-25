"""
Tests for source provenance stamping (PR1).

`_items_to_openwebui_sources` must stamp each source's metadata with provenance
(source_type / source_scope / citation_policy / origin_tool / file_id /
collection_id) while preserving the existing OpenWebUI transport shape
(source / document / metadata / distances).

Backward-safety: a bare call (no provenance kwargs) must still work and keep the
legacy citation-on default.

Reference: dev/active/agent-file-context-prefetch/ (PR1)
"""

from extension_modules.react.tools_base import ReactToolsBase

# _items_to_openwebui_sources does not touch `self` — call unbound with a
# sentinel, mirroring the static-helper test pattern in test_knowledge_handler.py.
_SELF = object()


def _convert(items, **provenance):
    return ReactToolsBase._items_to_openwebui_sources(_SELF, items, **provenance)


class TestProvenanceStamping:
    def test_chat_upload_provenance(self):
        items = [
            {
                "id": "f1",
                "filename": "manual.pdf",
                "data": {"content": "hello body"},
                "meta": {"file_id": "f1"},
            }
        ]
        out = _convert(
            items,
            source_type="chat_upload",
            source_scope="current_chat",
            citation_policy="optional",
            origin_tool="get_file_contents",
        )
        src = out["sources"][0]
        meta = src["metadata"][0]
        assert meta["source_type"] == "chat_upload"
        assert meta["source_scope"] == "current_chat"
        assert meta["citation_policy"] == "optional"
        assert meta["origin_tool"] == "get_file_contents"
        assert meta["file_id"] == "f1"
        # Transport shape preserved
        assert src["document"] == ["hello body"]
        assert src["source"]["name"] == "manual.pdf"

    def test_knowledge_base_provenance(self):
        items = [
            {
                "id": "k1",
                "content": "policy text",
                "score": 0.42,
                "metadata": {"name": "policy.md", "collection": "kb-1"},
            }
        ]
        out = _convert(
            items,
            source_type="knowledge_base",
            source_scope="agent_knowledge",
            citation_policy="required",
            origin_tool="knowledge_handler",
        )
        src = out["sources"][0]
        meta = src["metadata"][0]
        assert meta["source_type"] == "knowledge_base"
        assert meta["source_scope"] == "agent_knowledge"
        assert meta["citation_policy"] == "required"
        assert meta["origin_tool"] == "knowledge_handler"
        # distances preserved when score present
        assert src["distances"] == [0.42]
        # pre-existing metadata (collection) untouched
        assert meta["collection"] == "kb-1"

    def test_collection_id_injected(self):
        items = [{"id": "k1", "content": "t", "metadata": {"name": "n"}}]
        out = _convert(items, source_type="knowledge_base", collection_id="kb-9")
        assert out["sources"][0]["metadata"][0]["collection_id"] == "kb-9"

    def test_file_id_falls_back_to_item_id(self):
        # No explicit file_id in meta → falls back to item id.
        items = [{"id": "only-id", "filename": "f.txt", "content": "c"}]
        out = _convert(items, source_type="chat_upload")
        assert out["sources"][0]["metadata"][0]["file_id"] == "only-id"


class TestBackwardSafety:
    def test_bare_call_keeps_legacy_citation_on(self):
        # No provenance kwargs — must not raise, neutral type, citation stays on
        # (default 'required') so the legacy Document-Sources path is unchanged.
        items = [{"id": "x", "filename": "a.txt", "content": "c"}]
        out = _convert(items)
        meta = out["sources"][0]["metadata"][0]
        assert meta["source_type"] == "unknown"
        assert meta["citation_policy"] == "required"

    def test_no_distances_key_when_no_score(self):
        items = [{"id": "x", "filename": "a.txt", "content": "c"}]
        out = _convert(items, source_type="chat_upload")
        assert "distances" not in out["sources"][0]

    def test_empty_content_still_stamped(self):
        items = [{"id": "e", "filename": "empty.txt"}]
        out = _convert(items, source_type="chat_upload", citation_policy="optional")
        src = out["sources"][0]
        assert src["document"] == [""]
        assert src["metadata"][0]["source_type"] == "chat_upload"

    def test_empty_items(self):
        assert _convert([], source_type="chat_upload") == {"sources": []}

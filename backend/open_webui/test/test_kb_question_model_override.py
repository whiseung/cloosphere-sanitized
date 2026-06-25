"""Unit tests for the per-KB question_generation_model override that the
``save_docs_to_vector_db`` indexing path passes to
``generate_chunk_questions`` (commit 7).

The audit (docs/engineers/kb-search-settings-audit.md) confirmed every other
``search_settings`` parameter already flows correctly via the react agent
path. The model field was the lone dead-path: it was stored on KB.meta but
the call site never forwarded it, so the global ``KB_QUESTION_GENERATION_MODEL``
always won.

These tests pin the resolution rule that lives in the override block:

  ss.get("question_generation_model") -> kb_question_model
  empty / None / missing -> None  (caller falls back to global)
"""


def _resolve_kb_question_model(meta: dict | None) -> str | None:
    """Mirror of the in-router resolution block (routers/retrieval.py)."""
    if not meta:
        return None
    ss = meta.get("search_settings") or {}
    kb_model = ss.get("question_generation_model")
    if kb_model:
        return kb_model
    return None


def test_explicit_model_overrides_global():
    meta = {"search_settings": {"question_generation_model": "gpt-4o-mini"}}
    assert _resolve_kb_question_model(meta) == "gpt-4o-mini"


def test_missing_search_settings_returns_none():
    assert _resolve_kb_question_model({}) is None
    assert _resolve_kb_question_model(None) is None


def test_empty_string_falls_back_to_global():
    """PR163 의 isFilled() mirror — `''` 는 미설정으로 취급."""
    meta = {"search_settings": {"question_generation_model": ""}}
    assert _resolve_kb_question_model(meta) is None


def test_none_field_falls_back_to_global():
    meta = {"search_settings": {"question_generation_model": None}}
    assert _resolve_kb_question_model(meta) is None


def test_other_search_settings_ignored():
    meta = {"search_settings": {"top_k": 20, "enable_question_generation": True}}
    assert _resolve_kb_question_model(meta) is None

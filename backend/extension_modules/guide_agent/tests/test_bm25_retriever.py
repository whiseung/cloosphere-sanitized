"""BM25 retriever 단위 테스트 — 토크나이저 + 실제 카탈로그 검색."""

from __future__ import annotations

import pytest
from extension_modules.guide_agent.bm25_retriever import _tokenize, get_index, search


def test_tokenizer_english_words():
    tokens = _tokenize("How do I create an Agent?")
    assert "how" in tokens
    assert "create" in tokens
    assert "agent" in tokens


def test_tokenizer_korean_bigrams():
    tokens = _tokenize("첫 대화 시작하는 법")
    assert "첫" in tokens
    assert "대화" in tokens
    assert "시작" in tokens
    assert "작하" in tokens  # bigram from 시작하는


def test_tokenizer_mixed():
    tokens = _tokenize("Code Gateway 설정하기")
    assert "code" in tokens
    assert "gateway" in tokens
    assert "설정" in tokens


def test_tokenizer_empty():
    assert _tokenize("") == []
    assert _tokenize(None) == []  # type: ignore[arg-type]


def test_index_builds_with_chunks():
    idx = get_index()
    assert idx.chunk_count > 0, "Index has zero chunks — catalog or content broken"
    assert idx.bm25_ko is not None
    assert idx.bm25_en is not None
    assert len(idx.chunks_ko) > 100  # 64 categories × ~10 chunks each
    assert len(idx.chunks_en) > 100


def test_search_korean_query_returns_korean_chunks():
    results = search("첫 대화 시작하는 법", role="user", lang="ko", top_k=5)
    assert results, "No results for basic query"
    top_categories = [r[0].category for r in results[:3]]
    assert "getting-started/first-chat" in top_categories


def test_search_english_query_returns_english_chunks():
    results = search("agent flow workflow", role="user", lang="en", top_k=5)
    assert results
    # workspace/flows or workspace/agents should appear
    cats = {r[0].category for r in results[:5]}
    assert cats & {"workspace/flows", "workspace/agents", "workspace/flows-nodes"}


def test_search_admin_blocked_for_user_role():
    """user role 은 admin/* 카테고리 결과 0건이어야."""
    results = search("Code Gateway 설정", role="user", lang="ko", top_k=8)
    leaked = [r for r in results if r[0].audience == "admin"]
    assert leaked == [], (
        f"User role saw admin chunks: {[r[0].category for r in leaked]}"
    )


def test_search_admin_role_sees_admin_chunks():
    results = search("Code Gateway 설정", role="admin", lang="ko", top_k=5)
    cats = [r[0].category for r in results[:3]]
    assert "admin/code-gateway" in cats


def test_search_diversity_max_3_per_category():
    """카테고리당 최대 3개 청크 제한."""
    results = search(
        "워크스페이스 에이전트 만들기 사용 방법 가이드",
        role="user",
        lang="ko",
        top_k=20,
    )
    from collections import Counter

    counts = Counter(r[0].category for r in results)
    over_limit = {c: n for c, n in counts.items() if n > 3}
    assert over_limit == {}, f"Categories exceeding max_per_category=3: {over_limit}"


def test_search_returns_chunks_in_score_order():
    results = search("Cloosphere 시작 방법", role="user", lang="ko", top_k=10)
    if len(results) > 1:
        scores = [s for _, s in results]
        assert scores == sorted(scores, reverse=True), (
            "Results not sorted by score desc"
        )


def test_search_empty_query_returns_empty():
    assert search("", role="user", lang="ko") == []
    assert search("   ", role="user", lang="ko") == []


@pytest.fixture(scope="module")
def regression_questions() -> list[dict]:
    from pathlib import Path

    import yaml

    path = Path(__file__).parent / "regression_questions.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))["questions"]


def test_regression_top3_accuracy(regression_questions):
    """회귀셋에서 expected_categories 가 top-3 안에 들어오는 비율 ≥ 70%."""
    scored = 0
    correct = 0
    for q in regression_questions:
        expected = set(q.get("expected_categories", []))
        if not expected:
            continue
        scored += 1
        results = search(
            q["question"],
            role=q.get("role", "user"),
            lang=q.get("lang", "ko"),
            top_k=3,
        )
        cats = [r[0].category for r in results]
        if any(c in expected for c in cats):
            correct += 1
    assert scored > 0
    accuracy = correct / scored
    assert accuracy >= 0.7, (
        f"Top-3 accuracy {accuracy:.1%} below 70% threshold ({correct}/{scored})"
    )


def test_regression_admin_blocked_zero_leaks(regression_questions):
    """admin-blocked 질문에 user role 로 검색 시 admin/monitoring 결과 0건."""
    leaks = []
    for q in regression_questions:
        if q.get("tag") != "admin-blocked":
            continue
        results = search(q["question"], role="user", lang=q.get("lang", "ko"), top_k=8)
        for chunk, _ in results:
            if chunk.category.startswith(("admin/", "monitoring/")):
                leaks.append((q["question"], chunk.category))
    assert leaks == [], f"Admin leaks: {leaks}"

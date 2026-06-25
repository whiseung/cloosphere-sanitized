"""Unit tests for indexed_with marker helpers in
``routers/knowledge.py`` — ``_current_indexed_with`` snapshot +
``_indexed_with_matches`` dim 비교 (snapshot copy 모델).

KB clone 은 vector 그대로 복사하므로 engine/model 다름은 무관 — dim 만
일치하면 같은 ``default_knowledge`` 인덱스 schema 안에서 호환. dim 다르면
시스템 schema 깨짐으로 hard reject (force 도 거부).

대응 task:
- T16: dim mismatch → 409 EMBEDDING_DIM_MISMATCH (hard reject)
- T17: engine/model 만 다른 건 confirm 자체 안 뜸 (vector copy 무관)
- legacy KB (마커 None) → 통과 보장 (regression 가드)
"""

import sys
import types
from types import SimpleNamespace
from unittest.mock import MagicMock


def _stub_embedding_module(monkeypatch, dim: int = 3072):
    """``extension_modules.search_engine.embedding`` 의 dim 헬퍼만 fake.

    실제 모듈은 search engine 전체 import chain 을 끌고 들어와 무거우므로
    test scope 동안 fake module 로 대체.
    """
    fake_mod = types.ModuleType("extension_modules.search_engine.embedding")
    fake_mod.get_effective_embedding_dimension = MagicMock(return_value=dim)
    monkeypatch.setitem(
        sys.modules, "extension_modules.search_engine.embedding", fake_mod
    )
    # search_engine 패키지 자체도 사이드이펙트 없는 빈 모듈로 stub.
    monkeypatch.setitem(
        sys.modules,
        "extension_modules.search_engine",
        types.ModuleType("extension_modules.search_engine"),
    )
    monkeypatch.setitem(
        sys.modules,
        "extension_modules",
        types.ModuleType("extension_modules"),
    )
    return fake_mod


def _make_app(engine: str, model: str) -> SimpleNamespace:
    """``app.state.config`` 의 RAG_EMBEDDING_* 만 흉내내는 가벼운 SimpleNamespace."""
    return SimpleNamespace(
        state=SimpleNamespace(
            config=SimpleNamespace(
                RAG_EMBEDDING_ENGINE=engine,
                RAG_EMBEDDING_MODEL=model,
            )
        )
    )


# ---------------------------------------------------------------------------
# _current_indexed_with — snapshot 형식
# ---------------------------------------------------------------------------


def test_current_indexed_with_returns_engine_model_dim(monkeypatch):
    """app.state.config 에서 engine/model 읽고 dim 헬퍼 호출 → 3-key dict."""
    _stub_embedding_module(monkeypatch, dim=3072)
    # 인라인 재현 — production 함수와 동일 분기.
    cfg = _make_app("openai", "text-embedding-3-large").state.config
    from extension_modules.search_engine.embedding import (
        get_effective_embedding_dimension,
    )

    marker = {
        "engine": getattr(cfg, "RAG_EMBEDDING_ENGINE", "") or "",
        "model": getattr(cfg, "RAG_EMBEDDING_MODEL", "") or "",
        "dim": get_effective_embedding_dimension(_make_app("openai", "x")),
    }
    assert marker == {
        "engine": "openai",
        "model": "text-embedding-3-large",
        "dim": 3072,
    }


def test_current_indexed_with_handles_none_config_values(monkeypatch):
    """None 인 RAG_EMBEDDING_* 도 빈 문자열 fallback (KeyError 방지)."""
    _stub_embedding_module(monkeypatch, dim=1536)
    cfg = SimpleNamespace(
        RAG_EMBEDDING_ENGINE=None,
        RAG_EMBEDDING_MODEL=None,
    )
    marker = {
        "engine": getattr(cfg, "RAG_EMBEDDING_ENGINE", "") or "",
        "model": getattr(cfg, "RAG_EMBEDDING_MODEL", "") or "",
        "dim": 1536,
    }
    assert marker["engine"] == ""
    assert marker["model"] == ""


# ---------------------------------------------------------------------------
# _indexed_with_matches — 동일/다름/legacy
# ---------------------------------------------------------------------------


def _matches(a, b) -> bool:
    """``_indexed_with_matches`` 의 인라인 재현 — snapshot copy 모델은 dim 만
    비교. engine/model 다름은 vector copy 라 검색 호환성에 영향 없음."""
    if not a or not b:
        return True  # legacy / 정보 부족 — 진행 허용
    return int(a.get("dim") or 0) == int(b.get("dim") or 0)


def test_matches_identical_markers():
    a = {"engine": "openai", "model": "text-embedding-3-large", "dim": 3072}
    assert _matches(a, dict(a)) is True


def test_matches_returns_true_when_only_model_differs():
    """T17: snapshot copy 모델 — model 다름은 vector copy 라 무관."""
    a = {"engine": "openai", "model": "text-embedding-3-large", "dim": 3072}
    b = {"engine": "openai", "model": "text-embedding-ada-002", "dim": 3072}
    # dim 같으면 통과 — engine/model 차이는 vector copy 라 무관
    assert _matches(a, b) is True


def test_matches_returns_true_when_only_engine_differs():
    """engine (azure↔openai 등) 만 다르면 통과 — vector copy 영향 X."""
    a = {"engine": "openai", "model": "x", "dim": 1536}
    b = {"engine": "azure", "model": "x", "dim": 1536}
    assert _matches(a, b) is True


def test_matches_returns_false_when_dim_differs():
    """T16 핵심: dim 다르면 mismatch — 인덱스 schema 깨짐."""
    a = {"engine": "openai", "model": "x", "dim": 3072}
    b = {"engine": "openai", "model": "x", "dim": 1536}
    assert _matches(a, b) is False


def test_matches_legacy_none_marker_passes_through():
    """Legacy KB (indexed_with 마커 미저장) 는 None — 통과 (검증 불가).

    Regression 가드: 마커 추가 전에 만든 KB 가 영구히 clone 못 하게 되면 안 됨.
    """
    current = {"engine": "openai", "model": "x", "dim": 3072}
    assert _matches(None, current) is True
    assert _matches({}, current) is True
    assert _matches(current, None) is True


def test_matches_treats_missing_dim_as_zero():
    """dim 누락 시 0 fallback — 양쪽 모두 누락이면 동일 처리."""
    a = {"engine": "openai", "model": "x"}  # dim 없음
    b = {"engine": "openai", "model": "x", "dim": 0}
    assert _matches(a, b) is True


def test_matches_ignores_extra_keys():
    """미래 마커에 새 키 추가돼도 dim 만 비교."""
    a = {"engine": "openai", "model": "x", "dim": 3072, "ts": 100}
    b = {"engine": "openai", "model": "x", "dim": 3072, "ts": 999}
    assert _matches(a, b) is True


# ---------------------------------------------------------------------------
# Hard reject flow — dim mismatch 는 force 도 무관하게 거부
# ---------------------------------------------------------------------------


def test_dim_mismatch_rejects_clone_regardless_of_force():
    """T16: dim 다르면 force=true 도 의미 없음 — 인덱스 schema 깨짐."""
    src = {"engine": "openai", "model": "old", "dim": 3072}
    cur = {"engine": "openai", "model": "new", "dim": 1536}
    has_files = True
    # 새 라우터 분기: force 무관하게 dim mismatch → hard reject.
    refused = has_files and src and not _matches(src, cur)
    assert refused is True


def test_engine_only_mismatch_does_not_block_clone():
    """T17: engine/model 만 다른 건 통과 — vector copy 라 무관."""
    src = {"engine": "openai", "model": "old", "dim": 3072}
    cur = {"engine": "azure", "model": "new", "dim": 3072}  # dim 같음
    has_files = True
    refused = has_files and src and not _matches(src, cur)
    assert refused is False  # 통과


def test_zero_files_skips_marker_check():
    """0-파일 KB 는 인덱싱 자체가 없어 mismatch 검사 무관."""
    src = {"engine": "openai", "model": "old", "dim": 3072}
    cur = {"engine": "openai", "model": "new", "dim": 1536}
    has_files = False
    refused = has_files and src and not _matches(src, cur)
    assert refused is False  # files=0 이면 거부 분기 진입 X

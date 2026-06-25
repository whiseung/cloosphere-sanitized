"""Guide catalog 단일 loader (DRY).

`guide_catalog.yaml` 로드 + 가이드 문서 경로 resolve 를 한 곳에서 관리한다.
- mtime 기반 lazy reload (`tools.py`/`bm25_retriever.py` 의 캐시 비일관 해소)
- path resolve 가드: `guide/docs/` 외부 경로 차단 (path traversal 방어)
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[3]
CATALOG_PATH = (
    REPO_ROOT / "backend" / "extension_modules" / "guide_agent" / "guide_catalog.yaml"
)
DOCS_ROOT = (REPO_ROOT / "guide" / "docs").resolve()

ADMIN_AUDIENCE = "admin"

_CACHE_LOCK = threading.Lock()
_CACHED: dict[str, Any] | None = None
_CACHED_MTIME: float | None = None


def _empty_catalog() -> dict[str, Any]:
    return {"categories": [], "audience_counts": {"user": 0, "admin": 0}}


def load_catalog(*, force_reload: bool = False) -> dict[str, Any]:
    """guide_catalog.yaml 을 mtime 기반 lazy reload 로 로드.

    파일 변경 시 자동 재로드 — `tools.py` 의 `@lru_cache` stale 문제 해소.
    파일 부재 시 빈 카탈로그 반환 (warning 1회).
    """
    global _CACHED, _CACHED_MTIME
    if not CATALOG_PATH.exists():
        if _CACHED is None:
            log.warning("guide_catalog.yaml not found at %s", CATALOG_PATH)
        return _empty_catalog()

    mtime = CATALOG_PATH.stat().st_mtime
    if not force_reload and _CACHED is not None and _CACHED_MTIME == mtime:
        return _CACHED

    with _CACHE_LOCK:
        if force_reload or _CACHED is None or _CACHED_MTIME != mtime:
            with CATALOG_PATH.open("r", encoding="utf-8") as f:
                _CACHED = yaml.safe_load(f) or _empty_catalog()
            _CACHED_MTIME = mtime
    return _CACHED


def accessible_entries(role: str) -> list[dict[str, Any]]:
    """role 기준 접근 가능한 카테고리. admin 이 아니면 audience=admin 제외."""
    catalog = load_catalog()
    entries = catalog.get("categories", [])
    if role == ADMIN_AUDIENCE:
        return entries
    return [c for c in entries if c.get("audience") != ADMIN_AUDIENCE]


def entry_by_id(category_id: str, role: str) -> dict[str, Any] | None:
    """카테고리 ID 로 단일 entry 조회. role 접근 권한 체크 포함."""
    for entry in accessible_entries(role):
        if entry.get("id") == category_id:
            return entry
    return None


def resolve_doc_path(file_path: str) -> Path | None:
    """카탈로그의 file_ko / file_en 값 → 검증된 절대경로.

    `guide/docs/` 트리 외부로 빠지는 경로는 거부 (path traversal 방어).
    파일 미존재 시 None.
    """
    if not file_path:
        return None
    raw = Path(file_path)
    candidate = (raw if raw.is_absolute() else REPO_ROOT / raw).resolve()
    try:
        candidate.relative_to(DOCS_ROOT)
    except ValueError:
        log.warning("Rejecting doc path outside guide/docs: %s", file_path)
        return None
    if not candidate.exists():
        return None
    return candidate


__all__ = [
    "ADMIN_AUDIENCE",
    "CATALOG_PATH",
    "DOCS_ROOT",
    "REPO_ROOT",
    "accessible_entries",
    "entry_by_id",
    "load_catalog",
    "resolve_doc_path",
]

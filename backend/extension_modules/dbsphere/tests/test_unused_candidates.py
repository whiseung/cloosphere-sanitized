"""Unit tests for unused-few-shot candidate computation (router pure helpers).

trust-window 게이트 / 벡터인덱스 anti-join / created_at 파싱·컷오프를 검증한다.
"""

from datetime import datetime, timezone

from open_webui.routers.dbsphere import _compute_unused_candidates, _iso_to_epoch

NOW = 2_000_000_000
DAY = 86400
GRACE_DAYS = 14
GRACE = GRACE_DAYS * DAY


class FakeDoc:
    def __init__(self, doc_id, content="q", metadata=None):
        self.id = doc_id
        self.content = content
        self.metadata = metadata or {}


def _iso(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _doc(doc_id, created_ts=None, **meta):
    md = dict(meta)
    if created_ts is not None:
        md["created_at"] = _iso(created_ts)
    return FakeDoc(doc_id, metadata=md)


def test_iso_to_epoch_roundtrip_and_invalid():
    ts = NOW - 100
    assert _iso_to_epoch(_iso(ts)) == ts
    assert _iso_to_epoch(None) is None
    assert _iso_to_epoch("") is None
    assert _iso_to_epoch("not-a-date") is None


def test_logging_not_active_returns_not_ready():
    docs = [_doc("m1", created_ts=NOW - 30 * DAY)]
    ready, cands = _compute_unused_candidates(docs, set(), None, NOW, GRACE_DAYS)
    assert ready is False
    assert cands == []


def test_logging_too_recent_returns_not_ready():
    docs = [_doc("m1", created_ts=NOW - 30 * DAY)]
    # 로깅이 시작된 지 grace 미만 → 신뢰 불가.
    ready, cands = _compute_unused_candidates(
        docs, set(), NOW - 5 * DAY, NOW, GRACE_DAYS
    )
    assert ready is False
    assert cands == []


def test_unused_old_doc_is_candidate():
    docs = [
        _doc("m1", created_ts=NOW - 30 * DAY, sql_query="SELECT 1", origin="llm_auto")
    ]
    ready, cands = _compute_unused_candidates(
        docs, set(), NOW - 20 * DAY, NOW, GRACE_DAYS
    )
    assert ready is True
    assert [c.memory_id for c in cands] == ["m1"]
    assert cands[0].sql == "SELECT 1"
    assert cands[0].origin == "llm_auto"


def test_used_doc_excluded_by_antijoin():
    docs = [_doc("m1", created_ts=NOW - 30 * DAY)]
    ready, cands = _compute_unused_candidates(
        docs, {"m1"}, NOW - 20 * DAY, NOW, GRACE_DAYS
    )
    assert ready is True
    assert cands == []


def test_recent_doc_excluded_by_grace_cutoff():
    # created_at 이 grace 컷오프 이후(최근) → 아직 매칭 기회 부족, 제외.
    docs = [_doc("m1", created_ts=NOW - 1 * DAY)]
    ready, cands = _compute_unused_candidates(
        docs, set(), NOW - 20 * DAY, NOW, GRACE_DAYS
    )
    assert ready is True
    assert cands == []


def test_unparseable_created_at_excluded():
    docs = [
        FakeDoc("m1", metadata={"created_at": None}),
        FakeDoc("m2", metadata={"created_at": "garbage"}),
        FakeDoc("m3", metadata={}),  # 누락
    ]
    ready, cands = _compute_unused_candidates(
        docs, set(), NOW - 20 * DAY, NOW, GRACE_DAYS
    )
    assert ready is True
    assert cands == []  # 나이 확정 불가 → 전부 제외(보수적)


def test_mixed_set():
    docs = [
        _doc("old_unused", created_ts=NOW - 30 * DAY),  # 후보
        _doc("old_used", created_ts=NOW - 30 * DAY),  # used → 제외
        _doc("recent_unused", created_ts=NOW - 2 * DAY),  # 최근 → 제외
    ]
    ready, cands = _compute_unused_candidates(
        docs, {"old_used"}, NOW - 25 * DAY, NOW, GRACE_DAYS
    )
    assert ready is True
    assert [c.memory_id for c in cands] == ["old_unused"]

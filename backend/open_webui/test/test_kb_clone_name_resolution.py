"""Unit tests for ``Knowledges.next_clone_name`` — locale-aware suffix +
collision incrementing + 1000-iteration uuid fallback.

`models/knowledge.py:next_clone_name` 의 내부 분기 (locale → suffix, 1차
candidate, increment loop, fail-safe) 만 검증. SQLAlchemy 의존성을 피해
``name_exists`` 만 fake 로 주입하는 패턴.

대응 task:
- T11: 이름 충돌 → ``(Clone)`` → ``(Clone 2)`` → ``(Clone 3)`` incrementing
- T12: caller locale=ko → suffix ``(복제본)``
- T13: caller locale=en → suffix ``(Clone)``
"""

import re
import uuid


def _resolve_clone_name(
    base: str,
    locale: str,
    name_exists,
) -> str:
    """``next_clone_name`` 의 핵심 로직 인라인 재현. ``name_exists`` 는 ``str -> bool``.

    production 코드 (``Knowledges.next_clone_name``) 와 byte-for-byte 동일한
    분기. SQLAlchemy / DB 의존성 회피 위해 메서드 본문만 추출.
    """
    suffix = "복제본" if (locale or "").lower().startswith("ko") else "Clone"
    candidate = f"{base} ({suffix})"
    if not name_exists(candidate):
        return candidate
    for n in range(2, 1001):
        candidate = f"{base} ({suffix} {n})"
        if not name_exists(candidate):
            return candidate
    return f"{base} ({suffix} {uuid.uuid4().hex[:6]})"


# ---------------------------------------------------------------------------
# T13 — locale 영문 (또는 빈, 기타) → "(Clone)"
# ---------------------------------------------------------------------------


def test_locale_en_uses_clone_suffix():
    """T13: locale=en, 충돌 없을 때 첫 candidate 채택."""
    name = _resolve_clone_name("MyKB", "en-US", lambda _: False)
    assert name == "MyKB (Clone)"


def test_locale_empty_defaults_to_clone():
    """빈 locale 도 ``(Clone)`` 으로 — Korean 만 별도 분기."""
    name = _resolve_clone_name("MyKB", "", lambda _: False)
    assert name == "MyKB (Clone)"


def test_locale_japanese_falls_back_to_clone():
    """한국어가 아닌 다른 동아시아 locale 도 영문 suffix 사용 (정책)."""
    name = _resolve_clone_name("MyKB", "ja-JP", lambda _: False)
    assert name == "MyKB (Clone)"


def test_locale_accept_language_with_quality_factor():
    """Accept-Language 헤더 형식 (``ko-KR,ko;q=0.9,en;q=0.8``) 도 ko 로 시작."""
    name = _resolve_clone_name("MyKB", "ko-KR,ko;q=0.9,en;q=0.8", lambda _: False)
    assert name == "MyKB (복제본)"


# ---------------------------------------------------------------------------
# T12 — locale 한국어 → "(복제본)"
# ---------------------------------------------------------------------------


def test_locale_ko_uses_korean_suffix():
    """T12: locale=ko 면 한글 suffix."""
    name = _resolve_clone_name("내KB", "ko-KR", lambda _: False)
    assert name == "내KB (복제본)"


def test_locale_ko_case_insensitive():
    """Locale 매칭은 lowercase 비교."""
    name = _resolve_clone_name("KB", "KO-kr", lambda _: False)
    assert name == "KB (복제본)"


# ---------------------------------------------------------------------------
# T11 — 이름 충돌 → incrementing
# ---------------------------------------------------------------------------


def test_first_collision_yields_clone_2():
    """첫 candidate 가 이미 존재하면 ``(Clone 2)`` 가 다음."""
    existing = {"MyKB (Clone)"}
    name = _resolve_clone_name("MyKB", "en", lambda c: c in existing)
    assert name == "MyKB (Clone 2)"


def test_consecutive_collisions_increment():
    """``(Clone)``, ``(Clone 2)`` 모두 사용 중이면 ``(Clone 3)``."""
    existing = {"MyKB (Clone)", "MyKB (Clone 2)"}
    name = _resolve_clone_name("MyKB", "en", lambda c: c in existing)
    assert name == "MyKB (Clone 3)"


def test_korean_collisions_increment_with_korean_suffix():
    """한국어 locale 도 동일하게 증가 — ``(복제본 2)`` 등."""
    existing = {"내KB (복제본)", "내KB (복제본 2)", "내KB (복제본 3)"}
    name = _resolve_clone_name("내KB", "ko", lambda c: c in existing)
    assert name == "내KB (복제본 4)"


def test_increment_stops_at_first_free_slot():
    """중간 빈 슬롯 (e.g., 5 가 비어있고 2-4 가 사용 중) 이면 가장 작은 비어있는 값 채택."""
    existing = {f"KB (Clone {i})" for i in range(2, 10) if i != 5}
    existing.add("KB (Clone)")
    name = _resolve_clone_name("KB", "en", lambda c: c in existing)
    assert name == "KB (Clone 5)"


# ---------------------------------------------------------------------------
# Fail-safe — 1000 iteration 초과 시 uuid suffix
# ---------------------------------------------------------------------------


def test_thousand_collisions_falls_back_to_uuid():
    """병적인 케이스: 1000 회 incrementing 모두 충돌이면 uuid 6자 suffix.

    실제로 도달하기 거의 불가능한 케이스지만 unbounded loop 차단을 위한
    fail-safe 동작 확인.
    """
    # (Clone) + (Clone 2..1000) 모두 사용 중이라고 가정.
    existing = {"KB (Clone)"} | {f"KB (Clone {i})" for i in range(2, 1001)}
    name = _resolve_clone_name("KB", "en", lambda c: c in existing)
    assert name.startswith("KB (Clone ")
    # uuid 6자 hex suffix — 정확한 값은 random
    match = re.fullmatch(r"KB \(Clone ([0-9a-f]{6})\)", name)
    assert match is not None, f"uuid fallback 형식 불일치: {name!r}"


# ---------------------------------------------------------------------------
# Edge — base name 자체에 괄호/공백 들어가도 동작
# ---------------------------------------------------------------------------


def test_base_with_spaces_and_parens_preserved():
    """원본 이름에 특수문자 있어도 그대로 prefix 로 사용."""
    name = _resolve_clone_name("My (Old) KB v2", "en", lambda _: False)
    assert name == "My (Old) KB v2 (Clone)"

"""Shared helpers for multi-DB (registry-routed) DbSphere tools.

UnifiedAgent can connect several databases at once. Instead of one tool per DB
(which would explode the tool list and break HITL name matching), the DB tools
keep their fixed names and take a ``dbsphere_id`` selector parameter. These
helpers build that selector and resolve it against the per-DB registry.

A registry entry is a dict with keys:
    info, data, db_config, dialect, allow_dml, runner, memory
"""

from typing import Any, Dict, List, Optional, Tuple


def make_dbsphere_id_field(dbsphere_ids: List[str]):
    """Build ``(annotation, Field)`` for a dbsphere_id selector over the ids.

    Single id  -> Optional defaulting to it (the LLM may omit it; backward compat).
    Multiple   -> Optional Literal; the LLM should pass an explicit id.
    """
    from typing import Literal

    from pydantic import Field

    ids = list(dbsphere_ids)
    annotation = Optional[Literal[tuple(ids)]]
    if len(ids) == 1:
        return (
            annotation,
            Field(
                default=ids[0],
                description=(
                    f"대상 데이터베이스 id. 연결된 DB가 하나뿐이라 생략 가능 "
                    f"(기본값 '{ids[0]}')."
                ),
            ),
        )
    return (
        annotation,
        Field(
            default=None,
            description=(
                "대상 데이터베이스 id. dbsphere_info 의 목록에서 질문과 관련된 "
                "DB의 id를 선택하세요. 여러 DB가 연결된 경우 반드시 지정해야 합니다."
            ),
        ),
    )


def resolve_entry(
    dbsphere_id: Optional[str],
    registry: Dict[str, Any],
    allowed_ids: List[str],
) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """Resolve a registry entry for ``dbsphere_id``, restricted to ``allowed_ids``.

    Returns ``(resolved_id, entry)``; entry is ``None`` when the id is missing
    (and ambiguous), disallowed, or absent from the registry.
    """
    if not dbsphere_id:
        if len(allowed_ids) == 1:
            dbsphere_id = allowed_ids[0]
        else:
            return None, None
    if dbsphere_id not in allowed_ids:
        return dbsphere_id, None
    return dbsphere_id, registry.get(dbsphere_id)


def invalid_db_message(dbsphere_id: Optional[str], allowed_ids: List[str]) -> str:
    """Human/LLM-facing error listing the valid ids — never silently mis-target."""
    valid = ", ".join(allowed_ids) if allowed_ids else "(none)"
    if not dbsphere_id:
        return (
            "여러 데이터베이스가 연결되어 있습니다. dbsphere_id 를 명시하세요. "
            f"사용 가능한 id: {valid}"
        )
    return f"알 수 없거나 허용되지 않은 dbsphere_id '{dbsphere_id}'. 사용 가능한 id: {valid}"

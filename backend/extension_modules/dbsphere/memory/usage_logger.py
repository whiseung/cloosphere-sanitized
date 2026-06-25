"""
DbSphere memory 참조(주입) 로깅 — fire-and-forget.

few-shot(sql_memory) 등이 프롬프트에 주입되는 핫패스에서, 쿼리 응답을 막지 않고
참조 이벤트를 dbsphere_memory_usage 테이블에 비동기 기록한다.

설계 원칙:
- 비차단: sync DB 호출을 asyncio.to_thread 로 오프로드. 호출자는 await 하지 않는다.
- best-effort: 실패는 삼킨다(쿼리 흐름 영향 0). under-count 는 cleanup 의 grace/수동검토로 방어.
- GC 안전: bare create_task 핸들을 모듈 set 에 보존(미보존 시 GC 가 중간 수거 가능).
- 동기 컨텍스트(러닝 루프 없음)에선 조용히 no-op.
"""

import asyncio
import logging
from typing import Iterable, Optional

logger = logging.getLogger(__name__)

# create_task 핸들 보존용 — task.add_done_callback 으로 완료 시 제거.
_pending_tasks: set = set()


def record_memory_references(
    *,
    dbsphere_id: str,
    memory_ids: Iterable[str],
    user_id: Optional[str] = None,
    chat_id: Optional[str] = None,
    entity_type: str = "sql_memory",
    injection_point: str = "system_prompt",
) -> None:
    """주입된 memory_id 들에 대해 참조 행을 비차단 기록한다(fire-and-forget).

    입력이 비었거나 러닝 이벤트 루프가 없으면 no-op.
    """
    ids = [m for m in (memory_ids or []) if m]
    if not ids or not dbsphere_id:
        return

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # 동기 컨텍스트 — 로깅은 best-effort 라 안전하게 스킵.
        return

    task = loop.create_task(
        _insert_async(
            dbsphere_id=dbsphere_id,
            ids=ids,
            user_id=user_id,
            chat_id=chat_id,
            entity_type=entity_type,
            injection_point=injection_point,
        )
    )
    _pending_tasks.add(task)
    task.add_done_callback(_pending_tasks.discard)


async def _insert_async(
    *,
    dbsphere_id: str,
    ids: list,
    user_id: Optional[str],
    chat_id: Optional[str],
    entity_type: str,
    injection_point: str,
) -> None:
    try:
        from open_webui.models.dbsphere_memory_usage import (
            DbsphereMemoryUsageForm,
            DbsphereMemoryUsages,
        )

        forms = [
            DbsphereMemoryUsageForm(
                memory_id=mid,
                dbsphere_id=dbsphere_id,
                user_id=user_id,
                chat_id=chat_id,
                entity_type=entity_type,
                injection_point=injection_point,
            )
            for mid in ids
        ]
        await asyncio.to_thread(DbsphereMemoryUsages.insert_usage_bulk, forms)
    except Exception as e:  # noqa: BLE001 — best-effort, 절대 호출자에 전파 금지
        logger.warning("DbSphere memory 참조 로깅 실패(무시): %s", e)

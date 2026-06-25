"""KB 파일 배치 삭제 워커.

Redis Queue (`knowledge_file_delete` task_type) 에서 호출되어 단일 파일을
KB 에서 제거하고, job_id 단위 카운터로 마지막 파일 처리 시점에 KG drift
cleanup 을 한 번만 트리거한다. 각 파일 완료 / 전체 완료는 Socket.IO 로
클라이언트에 알림.
"""

import logging
from typing import Any, Optional

log = logging.getLogger(__name__)


async def process_knowledge_file_delete_task(
    app: Any, task_id: str, payload: dict
) -> None:
    from open_webui.routers.knowledge import (
        _kg_drift_cleanup_for_kb,
        _perform_file_removal_core,
    )
    from open_webui.socket.main import send_notification_to_user

    kb_id: str = payload["kb_id"]
    file_id: str = payload["file_id"]
    user_id: str = payload["user_id"]
    job_id: str = payload["job_id"]
    total: int = int(payload.get("total") or 0)
    filename: str = payload.get("filename") or file_id

    success = False
    error_msg: Optional[str] = None
    try:
        success = await _perform_file_removal_core(
            app=app, kb_id=kb_id, file_id=file_id
        )
        if not success:
            error_msg = "File not found"
    except Exception as e:
        log.exception(f"[kb-file-delete] failed to remove file={file_id}: {e}")
        error_msg = str(e)
        success = False

    # job 카운터 — TaskQueue 의 원자적 helper 로 집계. Redis Streams 구현은
    # INCR/SETNX 로 12 worker 병렬 환경에서도 finalize 를 정확히 1회로 보장.
    # InProcess 구현은 single-worker 라 기본값(True claim) 으로 동작.
    tq = getattr(app.state, "task_queue", None)
    done_key = f"kb_file_delete:{job_id}:done"
    failed_key = f"kb_file_delete:{job_id}:failed"
    claim_key = f"kb_file_delete:{job_id}:finalized"

    done: Optional[int] = None
    failed_total = 0
    if tq is not None:
        try:
            done = await tq.batch_counter_incr(done_key)
            if not success:
                failed_total = await tq.batch_counter_incr(failed_key)
            else:
                failed_total = await tq.batch_counter_get(failed_key)
        except Exception as e:
            log.warning(f"[kb-file-delete] counter failed: {e}")
            done = None
            failed_total = 0 if success else 1

    # 파일별 progress 이벤트 (UI 진행바)
    try:
        await send_notification_to_user(
            user_id=user_id,
            event_type="file-delete-batch:progress",
            data={
                "kb_id": kb_id,
                "job_id": job_id,
                "file_id": file_id,
                "filename": filename,
                "status": "success" if success else "failed",
                "error": error_msg,
                "done": done if done is not None else 0,
                "total": total,
            },
        )
    except Exception as e:
        log.warning(f"[kb-file-delete] progress socket emit failed: {e}")

    # Finalize — 카운터가 total 에 도달한 경우에만 claim 시도. 첫 성공자만
    # complete 이벤트 + drift cleanup. 이 두 단계 조합으로 12 worker 중
    # 중복 finalize 를 원천 차단한다.
    if tq is None or done is None or done < total:
        return

    try:
        claimed = await tq.batch_claim_once(claim_key)
    except Exception as e:
        log.warning(f"[kb-file-delete] finalize claim failed: {e}")
        return
    if not claimed:
        return

    log.info(
        f"[kb-file-delete] job={job_id} complete: "
        f"done={done}/{total} failed={failed_total}"
    )
    try:
        await send_notification_to_user(
            user_id=user_id,
            event_type="file-delete-batch:complete",
            data={
                "kb_id": kb_id,
                "job_id": job_id,
                "total": total,
                "success": max(total - failed_total, 0),
                "failed": failed_total,
            },
        )
    except Exception as e:
        log.warning(f"[kb-file-delete] complete socket emit failed: {e}")

    # drift cleanup — 배치당 한 번만.
    try:
        await _kg_drift_cleanup_for_kb(app, kb_id, user_id)
    except Exception as e:
        log.warning(f"[kb-file-delete] drift cleanup failed: {e}")

"""
KB 필터 메타데이터 추출 워커.

Redis Queue (`kb_filter_extract` task_type) 에서 호출되어
단일 파일의 필터 메타데이터를 추출하고 저장합니다.

트리거 시점:
  - 사용자가 Extract 버튼 클릭 (단일/배치)
  - 파일 업로드 완료 후 자동 체이닝 (_process_file_task)
"""

import logging
import time
from typing import Any, Optional

log = logging.getLogger(__name__)

EXTRACT_TIMEOUT = 120  # seconds per file


async def process_filter_extract_task(app: Any, task_id: str, payload: dict):
    """
    Redis Queue 워커: 단일 파일 필터 메타데이터 추출.

    payload:
        kb_id, file_id, user_id, filter_schema,
        pre_resolved_model_config (optional),
        job_id (optional, 배치용)
    """
    import asyncio

    from open_webui.models.files import Files
    from open_webui.models.knowledge import Knowledges
    from open_webui.retrieval.knowledge_service import SearchEngineKnowledge

    kb_id = payload["kb_id"]
    file_id = payload["file_id"]
    user_id = payload["user_id"]
    filter_schema = payload.get("filter_schema", [])
    pre_resolved_model_config = payload.get("pre_resolved_model_config")
    job_id = payload.get("job_id")
    job_total = int(payload.get("job_total") or 0)

    file = Files.get_file_by_id(file_id)
    if not file:
        log.warning(f"[filter_extract] File not found: {file_id}")
        await _notify_file_result(
            user_id,
            kb_id,
            file_id,
            "",
            "failed",
            error="File not found",
            job_id=job_id,
        )
        await _maybe_finalize_batch(
            app=app,
            user_id=user_id,
            kb_id=kb_id,
            job_id=job_id,
            job_total=job_total,
            success=False,
        )
        await _emit_single_complete_if_solo(
            user_id=user_id,
            kb_id=kb_id,
            file_id=file_id,
            filename="",
            job_id=job_id,
            success=False,
        )
        return

    filename = file.filename or file_id
    file_content = (file.data or {}).get("content", "")
    if not file_content:
        log.info(f"[filter_extract] File has no content: {file_id}")
        await _notify_file_result(
            user_id,
            kb_id,
            file_id,
            filename,
            "skipped",
            error="No content",
            job_id=job_id,
        )
        # skipped 도 done 카운터를 증가시켜야 batch 가 finalize 된다. skipped 는
        # 실패로 치지 않고 success 로 집계 (단순 no-content 이므로).
        await _maybe_finalize_batch(
            app=app,
            user_id=user_id,
            kb_id=kb_id,
            job_id=job_id,
            job_total=job_total,
            success=True,
        )
        await _emit_single_complete_if_solo(
            user_id=user_id,
            kb_id=kb_id,
            file_id=file_id,
            filename=filename,
            job_id=job_id,
            success=True,
        )
        return

    try:
        extracted = await asyncio.wait_for(
            _extract_file_metadata(
                app,
                file_content,
                filename,
                filter_schema,
                pre_resolved_model_config,
            ),
            timeout=EXTRACT_TIMEOUT,
        )
    except asyncio.TimeoutError:
        log.error(f"[filter_extract] Timeout for file {file_id}")
        await _notify_file_result(
            user_id,
            kb_id,
            file_id,
            filename,
            "failed",
            error=f"Extraction timed out after {EXTRACT_TIMEOUT}s",
            job_id=job_id,
        )
        await _maybe_finalize_batch(
            app=app,
            user_id=user_id,
            kb_id=kb_id,
            job_id=job_id,
            job_total=job_total,
            success=False,
        )
        return
    except Exception as e:
        log.error(f"[filter_extract] Error for file {file_id}: {e}")
        await _notify_file_result(
            user_id,
            kb_id,
            file_id,
            filename,
            "failed",
            error=str(e),
            job_id=job_id,
        )
        await _maybe_finalize_batch(
            app=app,
            user_id=user_id,
            kb_id=kb_id,
            job_id=job_id,
            job_total=job_total,
            success=False,
        )
        await _emit_single_complete_if_solo(
            user_id=user_id,
            kb_id=kb_id,
            file_id=file_id,
            filename=filename,
            job_id=job_id,
            success=False,
        )
        return

    # 원자적 merge — 동일 KB 에 다른 파일 동시 추출 시 lost update 방지.
    # delta 의 slot 키 (f_*) 에 None 이 있으면 해당 slot 을 제거한다.
    patch_result = Knowledges.patch_knowledge_file_metadata(
        id=kb_id, file_id=file_id, delta=extracted
    )
    if patch_result is None:
        log.warning(
            f"[filter_extract] patch_knowledge_file_metadata failed: kb={kb_id} file={file_id}"
        )
        merged_metadata: dict = {}
    else:
        _, merged_metadata = patch_result

    # 벡터 인덱스 업데이트 — delta 안의 slot 키만 반영 (None 은 clear 로 전달)
    try:
        knowledge_svc = SearchEngineKnowledge(app=app, collection_name=kb_id)
        slot_values = {
            k: v
            for k, v in extracted.items()
            if k.startswith(("f_str_", "f_int_", "f_date_", "f_col_"))
        }
        if slot_values:
            await knowledge_svc.update_file_filter_slots(
                file_id=file_id,
                slot_values=slot_values,
            )
    except Exception as e:
        log.warning(f"[filter_extract] Vector index update failed for {file_id}: {e}")

    # 추출 통계 — LLM prompt / glossary 필터 모두 카운트 대상.
    def _is_target(f: dict) -> bool:
        if f.get("extraction_prompt", "").strip():
            return True
        if f.get("type") == "glossary" and f.get("glossary_id"):
            return True
        return False

    target_fields = [f for f in filter_schema if _is_target(f)]
    extracted_count = sum(
        1 for f in target_fields if _has_value(extracted.get(f["slot"]))
    )
    missing_required = [
        f.get("label", f["slot"])
        for f in filter_schema
        if f.get("required")
        and _is_target(f)
        and not _has_value(merged_metadata.get(f["slot"]))
    ]

    await _notify_file_result(
        user_id,
        kb_id,
        file_id,
        filename,
        "success",
        extracted_count=extracted_count,
        total_fields=len(target_fields),
        missing_required=missing_required if missing_required else None,
        job_id=job_id,
    )

    log.info(
        f"[filter_extract] Completed {file_id}: "
        f"{extracted_count}/{len(target_fields)} fields extracted"
    )

    # 배치 추출 (job_id + job_total) 일 때만 전체 완료 finalize 실행.
    # done 카운터 원자 증가 → total 에 도달한 단 한 worker 만 complete 이벤트 emit.
    await _maybe_finalize_batch(
        app=app,
        user_id=user_id,
        kb_id=kb_id,
        job_id=job_id,
        job_total=job_total,
        success=True,
    )

    # 단일 파일 추출은 batch finalize 가 no-op 이므로 별도 single-complete emit.
    # 진행 바/점등 인디케이터를 100% 로 마감하기 위함. batch 와 상호 배타.
    await _emit_single_complete_if_solo(
        user_id=user_id,
        kb_id=kb_id,
        file_id=file_id,
        filename=filename,
        job_id=job_id,
        success=True,
    )


async def _maybe_finalize_batch(
    app,
    user_id: str,
    kb_id: str,
    job_id: Optional[str],
    job_total: int,
    success: bool,
) -> None:
    """배치 Extract All 의 atomic finalize. job_id 가 없거나 단일 파일 추출이면
    no-op. 마지막 워커만 ``extraction:complete`` 이벤트를 emit 한다."""
    if not job_id or job_total <= 0:
        return
    tq = getattr(app.state, "task_queue", None)
    if tq is None:
        return
    done_key = f"kb_filter_extract:{job_id}:done"
    failed_key = f"kb_filter_extract:{job_id}:failed"
    claim_key = f"kb_filter_extract:{job_id}:finalized"
    try:
        done = await tq.batch_counter_incr(done_key)
        if not success:
            failed_total = await tq.batch_counter_incr(failed_key)
        else:
            failed_total = await tq.batch_counter_get(failed_key)
    except Exception as e:
        log.warning(f"[filter_extract] finalize counter failed: {e}")
        return
    if done < job_total:
        return
    try:
        claimed = await tq.batch_claim_once(claim_key)
    except Exception as e:
        log.warning(f"[filter_extract] finalize claim failed: {e}")
        return
    if not claimed:
        return
    log.info(
        f"[filter_extract] job={job_id} complete: "
        f"done={done}/{job_total} failed={failed_total}"
    )
    try:
        from open_webui.socket.main import send_notification_to_user

        await send_notification_to_user(
            user_id=user_id,
            event_type="extraction:complete",
            data={
                "kb_id": kb_id,
                "job_id": job_id,
                "total": job_total,
                "success": max(job_total - failed_total, 0),
                "failed": failed_total,
            },
        )
    except Exception as e:
        log.warning(f"[filter_extract] complete socket emit failed: {e}")


async def _emit_single_complete_if_solo(
    user_id: str,
    kb_id: str,
    file_id: str,
    filename: str,
    job_id: Optional[str],
    success: bool,
) -> None:
    """단일 파일 추출 완료 알림. ``job_id`` 가 없는 경로 (single extract) 에서만
    fire — batch 경로는 ``_maybe_finalize_batch`` 의 ``extraction:complete`` 와
    상호 배타다."""
    if job_id:
        return
    try:
        from open_webui.socket.main import send_notification_to_user

        await send_notification_to_user(
            user_id=user_id,
            event_type="extraction:single-complete",
            data={
                "kb_id": kb_id,
                "file_id": file_id,
                "filename": filename,
                "success": success,
            },
        )
    except Exception as e:
        log.warning(f"[filter_extract] single-complete socket emit failed: {e}")


async def _extract_file_metadata(
    app: Any,
    file_content: str,
    filename: str,
    filter_schema: list,
    pre_resolved_model_config: Optional[dict],
) -> dict:
    """필터 메타데이터 추출 — LLM + glossary 통합."""
    from open_webui.retrieval.filter_extractor import extract_file_metadata
    from open_webui.retrieval.glossary_filter_extractor import (
        extract_glossary_terms,
        extract_glossary_terms_ai,
    )

    glossary_fields = [
        f for f in filter_schema if f.get("type") == "glossary" and f.get("glossary_id")
    ]
    llm_fields = [f for f in filter_schema if f.get("type") != "glossary"]

    extracted = {}

    # LLM 추출 (일반 필터)
    has_llm_targets = any(f.get("extraction_prompt", "").strip() for f in llm_fields)
    if has_llm_targets and pre_resolved_model_config:
        llm_result = await extract_file_metadata(
            app=app,
            file_content=file_content,
            filter_schema=llm_fields,
            model_config=pre_resolved_model_config,
            filename=filename,
        )
        extracted.update(llm_result)

    # Glossary 추출: 텍스트 매칭 + AI 에이전트
    for gf in glossary_fields:
        try:
            gid = gf["glossary_id"]
            g_content = _build_glossary_search_content(gf, file_content, filename)
            # 제목 추출이 꺼져 있으면 filename을 빈 문자열로 전달
            g_filename = filename if gf.get("extract_title", True) else ""
            text_terms = await extract_glossary_terms(
                glossary_id=gid,
                file_content=g_content,
                filename=g_filename,
                category=gf.get("category"),
                include_synonyms=gf.get("include_synonyms", False),
            )
            ai_terms = []
            if (
                gf.get("use_ai")
                and gf.get("extraction_prompt", "").strip()
                and pre_resolved_model_config
            ):
                ai_terms = await extract_glossary_terms_ai(
                    app=app,
                    glossary_id=gid,
                    file_content=g_content,
                    filename=g_filename,
                    extraction_prompt=gf["extraction_prompt"],
                    category=gf.get("category"),
                    model_config=pre_resolved_model_config,
                    include_synonyms=gf.get("include_synonyms", False),
                )
            extracted[gf["slot"]] = sorted(set(text_terms + ai_terms))
        except Exception as e:
            log.warning(
                f"[filter_extract] Glossary failed for {gf.get('glossary_id')}: {e}"
            )
            extracted[gf["slot"]] = []

    return extracted


def _build_glossary_search_content(gf: dict, file_content: str, filename: str) -> str:
    """용어집 필터의 extraction_source 설정에 따라 검색 대상 텍스트를 구성."""
    extract_content = gf.get("extract_content", True)
    if not extract_content:
        # 본문 추출 비활성 — 빈 문자열 (제목은 별도 filename 파라미터로 전달)
        return ""

    content_range = gf.get("content_range", "full")
    if content_range != "partial":
        return file_content

    # partial: 앞 N자 + 뒤 N자
    prefix_chars = gf.get("content_prefix_chars") or 0
    suffix_chars = gf.get("content_suffix_chars") or 0

    if prefix_chars <= 0 and suffix_chars <= 0:
        return file_content

    total = len(file_content)
    parts = []
    if prefix_chars > 0:
        parts.append(file_content[:prefix_chars])
    if suffix_chars > 0:
        start = (
            max(prefix_chars, total - suffix_chars)
            if prefix_chars > 0
            else total - suffix_chars
        )
        if start < total:
            parts.append(file_content[start:])

    return "\n".join(parts)


def _has_value(v: Any) -> bool:
    return v is not None and v != "" and v != []


async def _notify_file_result(
    user_id: str,
    kb_id: str,
    file_id: str,
    filename: str,
    status: str,
    error: Optional[str] = None,
    extracted_count: int = 0,
    total_fields: int = 0,
    missing_required: Optional[list] = None,
    job_id: Optional[str] = None,
):
    """추출 결과를 Socket.IO로 알림."""
    from open_webui.socket.main import send_notification_to_user

    data: dict[str, Any] = {
        "kb_id": kb_id,
        "file_id": file_id,
        "filename": filename,
        "status": status,
        "extracted_count": extracted_count,
        "total_fields": total_fields,
        "timestamp": int(time.time()),
    }
    if error:
        data["error"] = error
    if missing_required:
        data["missing_required"] = missing_required
    if job_id:
        data["job_id"] = job_id

    try:
        await send_notification_to_user(
            user_id=user_id,
            event_type="extraction:file-complete",
            data=data,
        )
    except Exception as e:
        log.warning(f"[filter_extract] Socket.IO notification failed: {e}")

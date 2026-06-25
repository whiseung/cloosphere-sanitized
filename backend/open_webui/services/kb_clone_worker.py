"""KB Deep Clone 워커 — snapshot copy 방식.

POST /knowledge/{id}/clone 가 enqueue 한 작업을 받아 원본 KB 의 각 파일에
대해:
  1. Storage server-side copy (S3 ``CopyObject`` / Azure ``start_copy_from_url``
     / GCS ``copy_blob`` / Local ``shutil``) — 임베딩 비용 0
  2. 새 File row insert (content 그대로 복사)
  3. ``SearchEngineKnowledge.copy_chunks_to`` 로 vector + chunk metadata snapshot
     복제 — 임베딩 재계산 0
  4. ``patch_knowledge_file_metadata`` + ``update_file_filter_slots`` 로
     filter 추출 결과까지 그대로 snapshot
  5. 모두 끝나면 target KB 의 ``meta.clone_state = "ready"`` + Socket.IO emit

원본의 indexed_with 마커도 그대로 보존 — cloned KB 의 origin 정보 유지.
caller 가 라우터 단계에서 ``indexed_with.dim`` mismatch 를 사전 검증하므로
worker 는 차원 일치 가정 하에 동작.

부분 실패 시 meta.clone_state = "failed" + clone_error 메시지.
rollback 은 하지 않음 — 사용자가 cloned KB 를 그대로 두거나 삭제 결정.
"""

import asyncio
import logging
import time
import uuid
from typing import Any

log = logging.getLogger(__name__)

# File.meta 복사 화이트리스트.
# 제외: collection_name, pending_knowledge_id, processing_job — clone 시 새로 세팅.
ALLOWED_FILE_META_KEYS = {
    "name",
    "content_type",
    "size",
    "classification",
    "document_profile",
    "summary",
}


async def process_kb_clone_task(app: Any, task_id: str, payload: dict) -> None:
    from open_webui.models.knowledge import Knowledges
    from open_webui.socket.main import send_notification_to_user

    source_kb_id: str = payload["source_kb_id"]
    target_kb_id: str = payload["target_kb_id"]
    user_id: str = payload["user_id"]

    target = Knowledges.get_knowledge_by_id(target_kb_id)
    if not target:
        log.warning(
            f"[kb-clone] target KB {target_kb_id} disappeared before worker ran"
        )
        return

    source = Knowledges.get_knowledge_by_id(source_kb_id)
    if not source:
        log.warning(f"[kb-clone] source KB {source_kb_id} disappeared during clone")
        Knowledges.update_knowledge_meta_by_id(
            target_kb_id,
            {
                "clone_state": "failed",
                "clone_error": "source KB no longer exists",
                "clone_completed_at": int(time.time()),
            },
        )
        return

    source_data = source.data or {}
    file_ids = source_data.get("file_ids") or []
    # 시작 시점 snapshot — clone 진행 도중 source 가 갱신돼도 일관된 view 사용.
    # data.file_metadata 는 KB 단위로 file_id → {filter slots, doc props} 매핑.
    source_file_metadata: dict = source_data.get("file_metadata") or {}
    cloned = 0
    failed_files: list[dict] = []

    for src_fid in file_ids:
        try:
            await _clone_one_file(
                app=app,
                src_fid=src_fid,
                source_kb_id=source_kb_id,
                target_kb_id=target_kb_id,
                user_id=user_id,
                src_filter_meta=source_file_metadata.get(src_fid),
            )
            cloned += 1
        except Exception as e:
            log.exception(f"[kb-clone] failed to clone file {src_fid}: {e}")
            failed_files.append({"file_id": src_fid, "error": str(e)[:200]})

    if failed_files:
        Knowledges.update_knowledge_meta_by_id(
            target_kb_id,
            {
                "clone_state": "failed",
                "clone_error": f"{len(failed_files)}/{len(file_ids)} files failed",
                "clone_failed_files": failed_files,
                "clone_completed_at": int(time.time()),
            },
        )
        try:
            await send_notification_to_user(
                user_id=user_id,
                event_type="kb-clone-failed",
                data={
                    "kb_id": target_kb_id,
                    "cloned": cloned,
                    "total": len(file_ids),
                    "failed": len(failed_files),
                },
            )
        except Exception as e:
            log.warning(f"[kb-clone] failed to notify failure: {e}")
        return

    # snapshot copy 모델: cloned KB 의 indexed_with 는 source 값 그대로 보존
    # (vector 도 source 그대로 복사했으므로). source 마커가 없는 legacy 라면
    # 그대로 빈 채 — 마커 없는 상태도 시스템적으로 허용.
    meta_patch = {
        "clone_state": "ready",
        "clone_completed_at": int(time.time()),
    }
    src_marker = (source.meta or {}).get("indexed_with")
    if src_marker:
        meta_patch["indexed_with"] = src_marker
    Knowledges.update_knowledge_meta_by_id(target_kb_id, meta_patch)
    try:
        await send_notification_to_user(
            user_id=user_id,
            event_type="kb-clone-completed",
            data={
                "kb_id": target_kb_id,
                "cloned": cloned,
                "total": len(file_ids),
            },
        )
    except Exception as e:
        log.warning(f"[kb-clone] failed to notify completion: {e}")


async def _clone_one_file(
    app: Any,
    src_fid: str,
    source_kb_id: str,
    target_kb_id: str,
    user_id: str,
    src_filter_meta: dict | None = None,
) -> None:
    """파일 1개를 snapshot 복제.

    1. ``Storage.copy_file`` — server-side binary copy (Local/S3/Azure/GCS)
    2. ``Files.insert_new_file`` — 새 file row (content 보존)
    3. ``add_file_id_to_knowledge`` — target KB.data.file_ids 추가
    4. ``SearchEngineKnowledge.copy_chunks_to`` — vector + chunk snapshot
       (file_id, collection 만 새 값으로 갱신, vector 보존)
    5. ``patch_knowledge_file_metadata`` + ``update_file_filter_slots`` — 필터
       추출 결과 + 벡터 인덱스 slot 까지 그대로

    임베딩 재계산 0 — 같은 임베딩 모델/차원 가정. caller 가 라우터 단계에서
    ``_indexed_with_matches`` 로 dim mismatch 거부.

    Multi-worker 안전:
    - ``patch_knowledge_file_metadata`` 가 ``with_for_update()`` row-lock 으로
      atomic merge → 같은 target KB 의 다른 파일 동시 patch 시 lost update 없음.
    - 벡터 chunk insert / slot 갱신은 ``new_fid`` (방금 발급) 단위라 다른
      워커와 contention 없음.
    """
    from open_webui.models.files import FileForm, Files
    from open_webui.models.knowledge import Knowledges
    from open_webui.retrieval.knowledge_service import SearchEngineKnowledge
    from open_webui.storage.provider import Storage

    src_file = Files.get_file_by_id(src_fid)
    if not src_file:
        raise ValueError(f"source file {src_fid} not found")

    # 1. Storage server-side copy — 모든 provider (Local/S3/GCS/Azure) 가
    #    download/upload hop 없이 내부 복제. 큰 파일도 초 단위.
    #    Azure provider 는 copy 완료까지 sync poll (max 15s) 하므로 async event
    #    loop 를 block 하지 않도록 ``to_thread`` 로 위임. 다른 provider 도 동일
    #    경로 — 어차피 sync 함수라 to_thread 가 일관된 안전한 호출 패턴.
    new_filename = f"clone-{uuid.uuid4().hex[:8]}-{src_file.filename}"
    new_path = await asyncio.to_thread(Storage.copy_file, src_file.path, new_filename)

    new_fid = str(uuid.uuid4())
    src_meta = dict(src_file.meta or {})
    new_meta = {k: v for k, v in src_meta.items() if k in ALLOWED_FILE_META_KEYS}
    src_content = (src_file.data or {}).get("content", "")

    # 2. 새 file row.
    new_file = Files.insert_new_file(
        user_id=user_id,
        form_data=FileForm(
            id=new_fid,
            filename=src_file.filename,
            path=new_path,
            data={"content": src_content},
            meta=new_meta,
        ),
    )
    if not new_file:
        # Storage 파일은 dangling 으로 두면 누적되므로 즉시 정리.
        try:
            Storage.delete_file(new_path)
        except Exception:
            pass
        raise RuntimeError("failed to insert new file row")

    # 3. KB.data.file_ids 에 추가.
    Knowledges.add_file_id_to_knowledge(target_kb_id, new_fid)

    # 4. Vector + chunk snapshot — 임베딩 재계산 0. 원본 collection 의
    #    chunk 를 target collection 으로 그대로 복사하면서 file_id 만 갱신.
    src_svc = SearchEngineKnowledge(app=app, collection_name=source_kb_id)
    copied_chunks = await src_svc.copy_chunks_to(
        dst_collection=target_kb_id,
        src_file_id=src_fid,
        dst_file_id=new_fid,
    )
    if copied_chunks == 0:
        # 원본에 chunk 가 없는 경우 — content 자체는 복사됐으니 사용자가 수동
        # 인덱싱 가능. warning 만 남기고 진행 (비-치명적).
        log.warning(
            f"[kb-clone] source file {src_fid} has no chunks in collection "
            f"{source_kb_id} — file copied without vector data"
        )

    # 5. 필터 메타데이터 (KB-level) + 벡터 slot 복제.
    if src_filter_meta:
        Knowledges.patch_knowledge_file_metadata(
            id=target_kb_id, file_id=new_fid, delta=src_filter_meta
        )
        slot_values = {
            k: v
            for k, v in src_filter_meta.items()
            if k.startswith(("f_str_", "f_int_", "f_date_", "f_col_"))
        }
        if slot_values:
            try:
                tgt_svc = SearchEngineKnowledge(app=app, collection_name=target_kb_id)
                await tgt_svc.update_file_filter_slots(
                    file_id=new_fid, slot_values=slot_values
                )
            except Exception as e:
                log.warning(
                    f"[kb-clone] vector slot copy failed for file {new_fid} "
                    f"in kb {target_kb_id}: {e}"
                )

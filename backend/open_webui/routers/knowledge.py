import logging
import os
import time
from typing import List, Literal, Optional, Union

from extension_modules.search_engine.embedding import get_effective_embedding_dimension
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Query,
    Request,
    status,
)
from open_webui.constants import ERROR_MESSAGES
from open_webui.env import SRC_LOG_LEVELS
from open_webui.models.files import FileModel, Files
from open_webui.models.knowledge import (
    KnowledgeForm,
    KnowledgeResponse,
    Knowledges,
    KnowledgeUserResponse,
)
from open_webui.models.models import ModelForm, Models
from open_webui.models.projects import Projects
from open_webui.retrieval.knowledge_service import SearchEngineKnowledge
from open_webui.routers.retrieval import (
    BatchProcessFilesForm,
    ProcessFileForm,
    process_file,
    process_files_batch,
)
from open_webui.storage.provider import Storage
from open_webui.utils.access_control import (
    has_access,
    has_permission_min_level,
)
from open_webui.utils.audit_logger import AuditLogger
from open_webui.utils.auth import get_verified_user
from open_webui.utils.license import require_feature
from pydantic import BaseModel

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])


def _current_indexed_with(app) -> dict:
    """현재 글로벌 임베딩 설정 스냅샷 — KB ``meta.indexed_with`` 마커에 저장.

    KB clone 시 source.meta.indexed_with 와 현재 값을 비교해 mismatch 면
    사용자에게 confirm 강제. 같은 ``default_knowledge`` 인덱스를 모든 KB
    가 공유하므로 차원이 다르면 시스템 차원에서 인덱스 schema 깨짐.
    """
    cfg = app.state.config
    return {
        "engine": getattr(cfg, "RAG_EMBEDDING_ENGINE", "") or "",
        "model": getattr(cfg, "RAG_EMBEDDING_MODEL", "") or "",
        "dim": get_effective_embedding_dimension(app),
    }


def _indexed_with_matches(a: dict | None, b: dict | None) -> bool:
    """``indexed_with`` 두 마커가 호환 가능한지 — **차원(dim) 만 비교**.

    snapshot copy 모델: clone 은 source vector 를 그대로 복사하므로
    engine/model 이 다르더라도 vector 는 source 그대로 보존된다. 따라서
    검색 호환성은 dim 일치만으로 충분 — 같은 ``default_knowledge`` 인덱스
    스키마 안에 들어갈 수 있어야 함.

    ``dim`` 다르면 인덱스 schema mismatch (시스템 전체 깨짐) 라 hard reject.
    legacy 마커 (None) 는 unknown 으로 간주, force 없이 통과 (검증 불가).
    """
    if not a or not b:
        return True  # legacy / 정보 부족 — 진행 허용
    return int(a.get("dim") or 0) == int(b.get("dim") or 0)


def _mark_job_failed(file_id: str, data: dict, job: dict, error: str) -> None:
    """Mark a file's processing_job as failed and persist."""
    current_data = dict(data or {})
    current_data["processing_job"] = {
        **job,
        "status": "failed",
        "error": error,
        "completed_at": int(time.time()),
    }
    Files.update_file_data_by_id(file_id, current_data)


router = APIRouter(dependencies=[Depends(require_feature("kbsphere"))])

############################
# getKnowledgeBases
############################


@router.get("/", response_model=list[KnowledgeUserResponse])
async def get_knowledge(request: Request, user=Depends(get_verified_user)):
    if user.role != "admin" and not has_permission_min_level(
        user.id,
        "workspace.knowledge",
        "read",
        request.app.state.config.USER_PERMISSIONS,
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    knowledge_bases = []

    if user.role == "admin":
        knowledge_bases = Knowledges.get_knowledge_bases()
    else:
        knowledge_bases = Knowledges.get_knowledge_bases_by_user_id(user.id, "read")

    # Exclude project-linked knowledge bases
    project_kb_ids = Projects.get_all_project_knowledge_ids()
    knowledge_bases = [kb for kb in knowledge_bases if kb.id not in project_kb_ids]

    # Return lightweight list — only file counts, no full file metadata
    knowledge_with_files = []
    for knowledge_base in knowledge_bases:
        file_ids = (knowledge_base.data or {}).get("file_ids", []) or []
        knowledge_with_files.append(
            KnowledgeUserResponse(
                **knowledge_base.model_dump(),
                files=[],
                file_count=len(file_ids),
            )
        )

    return knowledge_with_files


@router.get("/list", response_model=list[KnowledgeUserResponse])
async def get_knowledge_list(request: Request, user=Depends(get_verified_user)):
    if user.role != "admin" and not has_permission_min_level(
        user.id,
        "workspace.knowledge",
        "read",
        request.app.state.config.USER_PERMISSIONS,
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    knowledge_bases = []

    if user.role == "admin":
        knowledge_bases = Knowledges.get_knowledge_bases()
    else:
        knowledge_bases = Knowledges.get_knowledge_bases_by_user_id(user.id, "write")

    # Exclude project-linked knowledge bases
    project_kb_ids = Projects.get_all_project_knowledge_ids()
    knowledge_bases = [kb for kb in knowledge_bases if kb.id not in project_kb_ids]

    # Return lightweight list — only file counts, no full file metadata
    knowledge_with_files = []
    for knowledge_base in knowledge_bases:
        file_ids = (knowledge_base.data or {}).get("file_ids", []) or []
        knowledge_with_files.append(
            KnowledgeUserResponse(
                **knowledge_base.model_dump(),
                files=[],
                file_count=len(file_ids),
            )
        )
    return knowledge_with_files


############################
# CreateNewKnowledge
############################


@router.post("/create", response_model=Optional[KnowledgeResponse])
async def create_new_knowledge(
    request: Request, form_data: KnowledgeForm, user=Depends(get_verified_user)
):
    if user.role != "admin" and not has_permission_min_level(
        user.id,
        "workspace.knowledge",
        "write",
        request.app.state.config.USER_PERMISSIONS,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.UNAUTHORIZED,
        )

    if Knowledges.name_exists(form_data.name):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NAME_TAKEN,
        )

    knowledge = Knowledges.insert_new_knowledge(user.id, form_data)

    if knowledge:
        return knowledge
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("Error creating knowledge"),
        )


############################
# CloneKnowledge
############################


@router.post("/{id}/clone", response_model=Optional[KnowledgeResponse])
async def clone_knowledge_by_id(
    id: str, request: Request, user=Depends(get_verified_user)
):
    """KB Deep Clone — 메타/파일/벡터 모두 독립적으로 복제 (snapshot copy).

    동기 단계: 권한 체크 + pending 가드 + ``indexed_with.dim`` 매치 검증 +
    새 KB row insert (clone_state="cloning"). 비동기 단계 (task_queue):
    Storage server-side copy + 새 File row + ``copy_chunks_to`` 로 vector +
    chunk metadata snapshot 복제. 완료/실패 시 Socket.IO
    ``kb-clone-completed`` / ``kb-clone-failed`` emit.

    snapshot copy 모델: vector 를 그대로 복사하므로 engine/model 차이는
    무관. **dim mismatch 만 hard reject** — 같은 ``default_knowledge`` 인덱스
    schema 깨짐 방지. 거부 시 409 + ``{code: "EMBEDDING_DIM_MISMATCH"}``.
    """
    # Step 1: Feature Permission (workspace.knowledge:write — 새 KB 생성)
    if user.role != "admin" and not has_permission_min_level(
        user.id,
        "workspace.knowledge",
        "write",
        request.app.state.config.USER_PERMISSIONS,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.UNAUTHORIZED,
        )

    # Step 2: 원본 조회 + Resource Permission (read on source)
    source = Knowledges.get_knowledge_by_id(id=id)
    if not source:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )
    if (
        user.role != "admin"
        and source.user_id != user.id
        and not has_access(user.id, "read", source.access_control)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.UNAUTHORIZED,
        )

    # Step 3: pending 처리 중 파일 가드 (race condition 방지)
    pending = Files.get_files_by_pending_knowledge_id(id) or []
    if pending:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=ERROR_MESSAGES.DEFAULT(
                "Source KB has files still being processed. "
                "Wait until processing completes before cloning."
            ),
        )

    # Step 3b: indexed_with 마커 검증 — snapshot copy 모델이라 dim 만 비교.
    # dim 일치 = 같은 인덱스 schema → 통과. dim mismatch = 시스템 전체 인덱스
    # schema 깨짐 → **force=true 도 거부** (의미적으로 invalid). legacy 마커
    # (None) 는 통과 (검증 불가).
    src_indexed_with = (source.meta or {}).get("indexed_with")
    current_indexed_with = _current_indexed_with(request.app)
    src_file_ids_count = len((source.data or {}).get("file_ids") or [])
    if (
        src_file_ids_count > 0
        and src_indexed_with
        and not _indexed_with_matches(src_indexed_with, current_indexed_with)
    ):
        # dim mismatch 는 hard reject — force 무관. 같은 default_knowledge
        # 인덱스 schema 가 단일 차원 가정이라 다른 차원 vector 가 들어가면
        # 시스템 전체 깨짐.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "EMBEDDING_DIM_MISMATCH",
                "message": (
                    "Source KB was indexed with a different vector dimension. "
                    "Clone is not possible — system-wide reindex required first."
                ),
                "source_indexed_with": src_indexed_with,
                "current_indexed_with": current_indexed_with,
            },
        )

    # Step 4: 이름 결정 (locale-aware suffix incrementing)
    accept_lang = request.headers.get("accept-language", "")
    new_name = Knowledges.next_clone_name(source.name, locale=accept_lang)

    # Step 5: 새 KB insert (file_ids 비어있는 상태로 시작)
    source_meta = dict(source.meta or {})
    new_meta = {
        **source_meta,
        "cloned_from": {"kb_id": source.id, "at": int(time.time())},
        "clone_state": "cloning",
    }
    new_kb_form = KnowledgeForm(
        name=new_name,
        description=source.description,
        data={"file_ids": []},
        meta=new_meta,
        access_control={},  # caller-private until user explicitly shares
    )
    new_kb = Knowledges.insert_new_knowledge(user.id, new_kb_form)
    if not new_kb:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("Error creating cloned knowledge"),
        )

    # Audit log — clone 은 데이터 복제 작업이므로 추적 필수
    AuditLogger.log_create(
        resource_type="knowledge",
        resource_id=new_kb.id,
        data={
            "id": new_kb.id,
            "name": new_kb.name,
            "source_kb_id": source.id,
        },
        resource_name=new_kb.name,
        meta={"actor": user.id, "action_kind": "clone_knowledge"},
    )

    file_ids = (source.data or {}).get("file_ids") or []

    # Step 6: 0-파일 KB → worker enqueue 생략, 즉시 ready
    # 빈 KB 는 인덱싱 자체가 없으니 indexed_with 마커는 의미 없음 — 생략.
    if not file_ids:
        Knowledges.update_knowledge_meta_by_id(
            new_kb.id,
            {"clone_state": "ready", "clone_completed_at": int(time.time())},
        )
        return Knowledges.get_knowledge_by_id(new_kb.id)

    # Step 7: task_queue 에 worker enqueue
    # InProcessQueue (Redis 미구성) 는 publish() 가 no-op 이므로 in-process task 로 처리.
    import asyncio

    from open_webui.services.task_queue import InProcessQueue, TaskMessage

    payload = {
        "source_kb_id": source.id,
        "target_kb_id": new_kb.id,
        "user_id": user.id,
    }
    task_queue = getattr(request.app.state, "task_queue", None)
    if task_queue is None or isinstance(task_queue, InProcessQueue):
        from open_webui.services.kb_clone_worker import process_kb_clone_task

        asyncio.create_task(
            process_kb_clone_task(request.app, f"inproc-{new_kb.id}", payload)
        )
    else:
        await task_queue.publish(
            TaskMessage(
                task_type="kb_clone",
                payload=payload,
            )
        )

    return Knowledges.get_knowledge_by_id(new_kb.id)


############################
# ReindexKnowledgeFiles
############################


@router.post("/reindex", response_model=bool)
async def reindex_knowledge_files(request: Request, user=Depends(get_verified_user)):
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.UNAUTHORIZED,
        )

    knowledge_bases = Knowledges.get_knowledge_bases()

    log.info(f"Starting reindexing for {len(knowledge_bases)} knowledge bases")

    for knowledge_base in knowledge_bases:
        try:
            files = Files.get_files_by_ids(knowledge_base.data.get("file_ids", []))

            try:
                knowledge_svc = SearchEngineKnowledge(
                    app=request.app, collection_name=knowledge_base.id
                )
                await knowledge_svc.delete_by_collection()
            except Exception as e:
                log.error(f"Error deleting collection {knowledge_base.id}: {str(e)}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Error deleting vector DB collection",
                )

            failed_files = []
            for file in files:
                try:
                    await process_file(
                        request,
                        ProcessFileForm(
                            file_id=file.id, collection_name=knowledge_base.id
                        ),
                        user=user,
                    )
                except Exception as e:
                    log.error(
                        f"Error processing file {file.filename} (ID: {file.id}): {str(e)}"
                    )
                    failed_files.append({"file_id": file.id, "error": str(e)})
                    continue

        except Exception as e:
            log.error(f"Error processing knowledge base {knowledge_base.id}: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error processing knowledge base",
            )

        if failed_files:
            log.warning(
                f"Failed to process {len(failed_files)} files in knowledge base {knowledge_base.id}"
            )
            for failed in failed_files:
                log.warning(f"File ID: {failed['file_id']}, Error: {failed['error']}")

    log.info("Reindexing completed successfully")
    return True


############################
# GetKnowledgeById
############################


class KnowledgeFilesResponse(KnowledgeResponse):
    files: list[FileModel]
    pending_files: Optional[list[FileModel]] = None


@router.get("/{id}", response_model=Optional[KnowledgeFilesResponse])
async def get_knowledge_by_id(
    id: str,
    include_files: bool = True,
    user=Depends(get_verified_user),
):
    knowledge = Knowledges.get_knowledge_by_id(id=id)

    if knowledge:
        if (
            user.role == "admin"
            or knowledge.user_id == user.id
            or has_access(user.id, "read", knowledge.access_control)
        ):
            file_ids = knowledge.data.get("file_ids", []) if knowledge.data else []
            files = Files.get_files_by_ids(file_ids) if include_files else []

            # Get files that are still being processed
            # failed/stale/completed 상태 파일은 정리하고 목록에서 제외
            raw_pending = Files.get_files_by_pending_knowledge_id(id)
            pending_files = []
            now = int(time.time())
            # DI(수백 페이지) 추출은 10분 이상 걸릴 수 있어 기존 600초 'processing'
            # 폐기는 정상 작업을 오탐(false-positive)으로 failed 처리했다. 기본 1시간으로
            # 상향(env KB_STALE_PROCESSING_TIMEOUT 로 조정 가능). 'queued' 등 미지정 상태도
            # 아래 unknown-status 분기에서 이 값을 사용한다.
            _stale_timeouts = {
                "pending": 300,
                "processing": int(
                    os.environ.get("KB_STALE_PROCESSING_TIMEOUT", "3600")
                ),
                "completed": 1800,
            }
            for pf in raw_pending:
                try:
                    job = (pf.data or {}).get("processing_job", {})
                    job_status = job.get("status")
                    started_at = job.get("started_at")

                    # processing_job 누락 방어 — job이 없거나 status가 None
                    if not job_status:
                        if not started_at or (
                            now - started_at > _stale_timeouts["pending"]
                        ):
                            Files.update_file_metadata_by_id(
                                pf.id, {"pending_knowledge_id": None}
                            )
                        else:
                            pending_files.append(pf)
                        continue

                    # stale 감지 — pending(300초) / processing(600초) / completed(1800초)
                    stale_timeout = _stale_timeouts.get(job_status)
                    if (
                        stale_timeout
                        and started_at
                        and (now - started_at > stale_timeout)
                    ):
                        _mark_job_failed(
                            pf.id,
                            pf.data,
                            job,
                            f"Stale {job_status} state detected "
                            f"(>{stale_timeout}s, backend may have restarted)",
                        )
                        job_status = "failed"

                    # unknown status 방어 — 알려진 상태가 아니면 stale 처리
                    if job_status not in _stale_timeouts and job_status not in (
                        "failed",
                        "completed",
                    ):
                        if not started_at or (
                            now - started_at > _stale_timeouts["processing"]
                        ):
                            _mark_job_failed(
                                pf.id,
                                pf.data,
                                job,
                                f"Unknown status '{job_status}' detected as stale",
                            )
                            job_status = "failed"

                    # terminal state → pending 해제
                    if job_status in ("completed", "failed"):
                        if job_status == "completed" and pf.id not in file_ids:
                            result = Knowledges.add_file_id_to_knowledge(
                                id=id, file_id=pf.id
                            )
                            if not result:
                                log.error(
                                    f"Failed to add completed file {pf.id} to knowledge {id}"
                                )
                                _mark_job_failed(
                                    pf.id,
                                    pf.data,
                                    job,
                                    "Failed to link to knowledge (DB error)",
                                )
                            else:
                                file_ids.append(pf.id)
                                files.append(pf)
                        Files.update_file_metadata_by_id(
                            pf.id, {"pending_knowledge_id": None}
                        )
                    else:
                        pending_files.append(pf)
                except Exception as e:
                    log.warning(f"Failed to process pending file {pf.id}: {e}")
                    pending_files.append(pf)

            return KnowledgeFilesResponse(
                **knowledge.model_dump(),
                files=files,
                pending_files=pending_files if pending_files else None,
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )


############################
# GetKnowledgeFilesPaged
############################


class KnowledgeFilesPageResponse(BaseModel):
    files: list[FileModel]
    total: int
    skip: int
    limit: int


@router.get("/{id}/files", response_model=KnowledgeFilesPageResponse)
async def get_knowledge_files_paginated(
    id: str,
    skip: int = 0,
    limit: int = 50,
    search: Optional[str] = None,
    sort: str = "newest",
    user=Depends(get_verified_user),
):
    knowledge = Knowledges.get_knowledge_by_id(id=id)
    if not knowledge:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )
    if not (
        user.role == "admin"
        or knowledge.user_id == user.id
        or has_access(user.id, "read", knowledge.access_control)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.UNAUTHORIZED,
        )

    file_ids = (knowledge.data or {}).get("file_ids", []) or []
    if sort not in ("newest", "oldest", "name"):
        sort = "newest"
    if limit <= 0 or limit > 500:
        limit = 50
    if skip < 0:
        skip = 0

    files, total = Files.get_files_by_ids_paginated(
        file_ids, skip=skip, limit=limit, search=search, sort=sort
    )

    # ── auto-heal: knowledge.data.file_ids 에 orphan/중복이 남아있으면 조용히
    # compact. search 필터가 없을 때만 수행 (search 중이면 total 은 검색 결과 수라
    # 전체 file_ids 길이와 비교하는 의미가 없다). file_ids 의 distinct 유효
    # 항목 수가 total 과 다르면 정리 대상.
    if not search and len(file_ids) != total:
        try:
            existing_ids = {f.id for f in Files.get_files_by_ids(file_ids)}
            dedup_count = len({fid for fid in file_ids if fid in existing_ids})
            if dedup_count != len(file_ids):
                result = Knowledges.compact_file_ids(id=id, valid_ids=existing_ids)
                if result is not None:
                    _, before, after = result
                    if before != after:
                        log.info(
                            f"[kb auto-heal] kb={id} compacted file_ids "
                            f"{before}→{after}"
                        )
        except Exception as e:
            log.warning(f"[kb auto-heal] compact failed for kb={id}: {e}")

    return KnowledgeFilesPageResponse(files=files, total=total, skip=skip, limit=limit)


############################
# GetKnowledgeFileIds (lightweight — for select-all)
############################


class KnowledgeFileIdsResponse(BaseModel):
    ids: list[str]
    total: int


@router.get("/{id}/file-ids", response_model=KnowledgeFileIdsResponse)
async def get_knowledge_file_ids(
    id: str,
    search: Optional[str] = None,
    status_filter: Optional[str] = Query(default=None, alias="status"),
    user=Depends(get_verified_user),
):
    """파일 메타데이터 없이 ID 목록만 반환 — 페이지네이션과 무관하게
    전체 파일 선택 UX 를 위한 경량 조회.

    search 가 주어지면 filename 에 대해 ilike 매칭. orphan (DB 에 없는 ID) 은
    자동으로 제외되며, 결과는 filename 기반 정렬이 아닌 단순 File.id 순서.
    status (예: "failed") 가 주어지면 processing_job.status 가 일치하는 파일만
    반환 — "실패한 파일만" 선택/일괄 재시도 UX 용.
    """
    knowledge = Knowledges.get_knowledge_by_id(id=id)
    if not knowledge:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )
    if not (
        user.role == "admin"
        or knowledge.user_id == user.id
        or has_access(user.id, "read", knowledge.access_control)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.UNAUTHORIZED,
        )

    file_ids = (knowledge.data or {}).get("file_ids", []) or []
    if not file_ids:
        return KnowledgeFileIdsResponse(ids=[], total=0)

    ids = Files.get_existing_file_ids(file_ids, search=search)
    if status_filter:
        files = Files.get_files_by_ids(ids)
        ids = [
            f.id
            for f in files
            if ((f.data or {}).get("processing_job") or {}).get("status")
            == status_filter
        ]
    return KnowledgeFileIdsResponse(ids=ids, total=len(ids))


############################
# UpdateKnowledgeById
############################


@router.post("/{id}/update", response_model=Optional[KnowledgeFilesResponse])
async def update_knowledge_by_id(
    id: str,
    form_data: KnowledgeForm,
    user=Depends(get_verified_user),
):
    knowledge = Knowledges.get_knowledge_by_id(id=id)
    if not knowledge:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )
    # Is the user the original creator, in a group with write access, or an admin
    if (
        knowledge.user_id != user.id
        and not has_access(user.id, "write", knowledge.access_control)
        and user.role != "admin"
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    if form_data.name and Knowledges.name_exists(form_data.name, exclude_id=id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NAME_TAKEN,
        )

    knowledge = Knowledges.update_knowledge_by_id(id=id, form_data=form_data)
    if knowledge:
        file_ids = knowledge.data.get("file_ids", []) if knowledge.data else []
        files = Files.get_files_by_ids(file_ids)

        return KnowledgeFilesResponse(
            **knowledge.model_dump(),
            files=files,
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("Error updating knowledge"),
        )


############################
# AddFileToKnowledge
############################


class KnowledgeFileIdForm(BaseModel):
    file_id: str
    # 동일 filename이 KB에 이미 있을 때 처리 방법.
    # - "overwrite": 기존 파일 레코드/청크 삭제 후 신규 파일로 교체 (기본)
    # - "skip":      신규 파일 레코드/디스크 파일 즉시 삭제, 기존 파일 유지
    duplicate_policy: Optional[Literal["overwrite", "skip"]] = "overwrite"
    # 배치 업로드 추적 — file-processing 알림에 그대로 echo 된다 (벨 전용 진행률 + 발신 세션 식별).
    batch_id: Optional[str] = None
    client_session_id: Optional[str] = None


class FileProcessingStatusResponse(BaseModel):
    status: str
    message: str
    file_id: str


class CheckDuplicateFilenamesForm(BaseModel):
    filenames: list[str]


class CheckDuplicateFilenamesResponse(BaseModel):
    duplicates: list[str]


@router.post(
    "/{id}/files/check-duplicates",
    response_model=CheckDuplicateFilenamesResponse,
)
async def check_duplicate_filenames(
    id: str,
    form_data: CheckDuplicateFilenamesForm,
    user=Depends(get_verified_user),
):
    """KB 내 기존 파일 중 요청한 filename과 일치하는 항목만 반환.

    배치 업로드 시 선제 중복 스캔용. 대량 업로드 전에 사용자에게
    '덮어쓸지/건너뛸지'를 물어보기 위해 프론트가 호출한다.
    """
    knowledge = Knowledges.get_knowledge_by_id(id=id)
    if not knowledge:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )
    if not (
        user.role == "admin"
        or knowledge.user_id == user.id
        or has_access(user.id, "read", knowledge.access_control)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.UNAUTHORIZED,
        )

    if not form_data.filenames:
        return CheckDuplicateFilenamesResponse(duplicates=[])

    file_ids = (knowledge.data or {}).get("file_ids", []) or []
    if not file_ids:
        return CheckDuplicateFilenamesResponse(duplicates=[])

    # 요청된 filename 집합에 해당하는 항목만 뽑기 — O(files × 1)
    requested = set(form_data.filenames)
    existing_files = Files.get_files_by_ids(file_ids)
    existing_names = {f.filename for f in existing_files if f.filename in requested}
    return CheckDuplicateFilenamesResponse(duplicates=sorted(existing_names))


@router.post(
    "/{id}/file/add",
    response_model=Union[KnowledgeFilesResponse, FileProcessingStatusResponse],
)
async def add_file_to_knowledge_by_id(
    request: Request,
    id: str,
    form_data: KnowledgeFileIdForm,
    user=Depends(get_verified_user),
):
    knowledge = Knowledges.get_knowledge_by_id(id=id)

    if not knowledge:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    if (
        knowledge.user_id != user.id
        and not has_access(user.id, "write", knowledge.access_control)
        and user.role != "admin"
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    file = Files.get_file_by_id(form_data.file_id)
    if not file:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    # 동일 파일명 처리: duplicate_policy 에 따라 교체/건너뛰기/정상 추가
    existing_file_ids = (knowledge.data or {}).get("file_ids", [])
    duplicate_ef = None
    if existing_file_ids:
        existing_files = Files.get_files_by_ids(existing_file_ids)
        for ef in existing_files:
            if ef.filename == file.filename and ef.id != file.id:
                duplicate_ef = ef
                break  # 같은 이름은 1개만 있다고 가정

    if duplicate_ef is not None:
        if form_data.duplicate_policy == "skip":
            # 신규로 업로드된 파일 레코드 + 디스크 파일을 즉시 정리하고 skipped 반환
            log.info(
                f"skip duplicate '{file.filename}' in KB {id}: "
                f"keeping existing {duplicate_ef.id}, discarding new {file.id}"
            )
            try:
                if file.path:
                    Storage.delete_file(file.path)
            except Exception as e:
                log.warning(f"Failed to remove disk file on skip: {e}")
            try:
                Files.delete_file_by_id(file.id)
            except Exception as e:
                log.warning(f"Failed to delete file record on skip: {e}")
            return FileProcessingStatusResponse(
                status="skipped",
                message=f"'{file.filename}' already exists in the knowledge base.",
                file_id=duplicate_ef.id,
            )

        # 기본 overwrite 경로: 기존 파일 청크 + 레코드 삭제 후 신규 파일로 교체
        log.info(
            f"Replacing duplicate filename '{file.filename}': "
            f"old={duplicate_ef.id} → new={file.id}"
        )
        try:
            vec_dim = get_effective_embedding_dimension(request.app)
            ks = SearchEngineKnowledge(
                app=request.app,
                collection_name=knowledge.id,
                vector_dim=vec_dim,
            )
            await ks.delete_by_file_id(duplicate_ef.id)
        except Exception as e:
            log.warning(f"Failed to delete old file vectors: {e}")
        data = knowledge.data or {}
        fids = data.get("file_ids", [])
        if duplicate_ef.id in fids:
            fids.remove(duplicate_ef.id)
            data["file_ids"] = fids
            Knowledges.update_knowledge_data_by_id(id=id, data=data)
        try:
            if duplicate_ef.path:
                Storage.delete_file(duplicate_ef.path)
        except Exception as e:
            log.warning(f"Failed to remove old disk file on overwrite: {e}")
        Files.delete_file_by_id(duplicate_ef.id)

    # Check file processing status
    file_data = file.data or {}
    processing_job = file_data.get("processing_job", {})
    processing_status = processing_job.get("status")

    # If file is still being processed, return processing status
    if processing_status in ["pending", "processing"]:
        # Store pending knowledge_id so file will be auto-added when processing completes
        log.info(
            f"File {form_data.file_id} is processing, storing pending_knowledge_id: {id}"
        )
        Files.update_file_metadata_by_id(
            form_data.file_id,
            {"pending_knowledge_id": id},
        )
        return FileProcessingStatusResponse(
            status="processing",
            message="파일을 처리 중입니다. 완료되면 자동으로 추가됩니다.",
            file_id=form_data.file_id,
        )

    # If file has no content and not processed, start processing
    if not file_data.get("content"):
        log.info(f"File {form_data.file_id} has no content, starting processing...")
        # 먼저 file_ids에 추가 (목록에 즉시 표시, 처리 상태는 processing_job으로 표시)
        Knowledges.add_file_id_to_knowledge(id=id, file_id=form_data.file_id)
        # Process directly into KB collection (skip file-{id} intermediate step)
        try:
            # Start background processing — collection_name=KB id 직접 전달
            await process_file(
                request,
                ProcessFileForm(
                    file_id=form_data.file_id,
                    collection_name=id,
                    background=True,
                    batch_id=form_data.batch_id,
                    client_session_id=form_data.client_session_id,
                ),
                user=user,
            )
            return FileProcessingStatusResponse(
                status="processing_started",
                message="파일을 처리 중입니다. 완료되면 자동으로 추가됩니다.",
                file_id=form_data.file_id,
            )
        except Exception as e:
            log.debug(e)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e),
            )

    # Add content to the vector database
    try:
        await process_file(
            request,
            ProcessFileForm(file_id=form_data.file_id, collection_name=id),
            user=user,
        )
    except Exception as e:
        log.debug(e)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    if knowledge:
        # Use atomic operation to prevent race condition
        knowledge = Knowledges.add_file_id_to_knowledge(
            id=id, file_id=form_data.file_id
        )

        if knowledge:
            # 동기 경로: 파일 처리 완료 후 필터 추출 자동 체이닝
            from open_webui.services.task_queue import _chain_filter_extract

            try:
                await _chain_filter_extract(request.app, id, form_data.file_id, user.id)
            except Exception as e:
                log.warning(f"Filter extract chain failed: {e}")

            file_ids = knowledge.data.get("file_ids", []) if knowledge.data else []
            files = Files.get_files_by_ids(file_ids)

            return KnowledgeFilesResponse(
                **knowledge.model_dump(),
                files=files,
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ERROR_MESSAGES.DEFAULT("file_id"),
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )


@router.post("/{id}/file/retry")
async def retry_file_in_knowledge(
    request: Request,
    id: str,
    form_data: KnowledgeFileIdForm,
    user=Depends(get_verified_user),
):
    """실패한 파일의 처리를 재시도."""
    knowledge = Knowledges.get_knowledge_by_id(id=id)
    if not knowledge:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    if (
        knowledge.user_id != user.id
        and not has_access(user.id, "write", knowledge.access_control)
        and user.role != "admin"
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    file = Files.get_file_by_id(form_data.file_id)
    if not file:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    # processing_job 초기화
    current_data = file.data or {}
    current_data.pop("processing_job", None)
    current_data.pop("content", None)
    Files.update_file_data_by_id(form_data.file_id, current_data)

    # pending_knowledge_id 설정 후 재처리
    Files.update_file_metadata_by_id(
        form_data.file_id,
        {"pending_knowledge_id": id},
    )

    try:
        await process_file(
            request,
            ProcessFileForm(file_id=form_data.file_id, background=True),
            user=user,
        )
        return FileProcessingStatusResponse(
            status="processing_started",
            message="파일 재처리가 시작되었습니다.",
            file_id=form_data.file_id,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


class RetryFailedFilesForm(BaseModel):
    # 명시되면 그 중 실패 상태인 것만, 없으면 KB 내 실패 파일 전체를 재시도.
    file_ids: Optional[list[str]] = None
    # 하나의 배치로 묶어 추적 — file-processing 알림에 echo (벨 전용 진행률 + 발신 세션 식별).
    batch_id: Optional[str] = None
    client_session_id: Optional[str] = None


@router.post("/{id}/files/retry-failed")
async def retry_failed_files_in_knowledge(
    request: Request,
    id: str,
    form_data: RetryFailedFilesForm,
    user=Depends(get_verified_user),
):
    """KB 내 처리 실패(processing_job.status=='failed') 파일을 일괄 재처리.
    하나의 batch_id 로 묶어 조용한 배치로 추적되도록 알림에 echo 한다."""
    knowledge = Knowledges.get_knowledge_by_id(id=id)
    if not knowledge:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )
    if (
        knowledge.user_id != user.id
        and not has_access(user.id, "write", knowledge.access_control)
        and user.role != "admin"
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    kb_file_ids = (knowledge.data or {}).get("file_ids", []) or []
    candidate_ids = (
        [fid for fid in form_data.file_ids if fid in kb_file_ids]
        if form_data.file_ids
        else kb_file_ids
    )
    if not candidate_ids:
        return {"batch_id": form_data.batch_id, "total": 0, "file_ids": []}

    files = Files.get_files_by_ids(candidate_ids)
    failed = [
        f
        for f in files
        if ((f.data or {}).get("processing_job") or {}).get("status") == "failed"
    ]

    retried_ids: list[str] = []
    for f in failed:
        # processing_job / content 초기화 후 pending_knowledge_id 설정 → 재처리 큐 등록
        current_data = f.data or {}
        current_data.pop("processing_job", None)
        current_data.pop("content", None)
        Files.update_file_data_by_id(f.id, current_data)
        Files.update_file_metadata_by_id(f.id, {"pending_knowledge_id": id})
        try:
            await process_file(
                request,
                ProcessFileForm(
                    file_id=f.id,
                    background=True,
                    batch_id=form_data.batch_id,
                    client_session_id=form_data.client_session_id,
                ),
                user=user,
            )
            retried_ids.append(f.id)
        except Exception as e:
            log.warning(f"retry-failed: failed to re-enqueue {f.id}: {e}")

    return {
        "batch_id": form_data.batch_id,
        "total": len(retried_ids),
        "file_ids": retried_ids,
    }


@router.post("/{id}/file/update", response_model=Optional[KnowledgeFilesResponse])
async def update_file_from_knowledge_by_id(
    request: Request,
    id: str,
    form_data: KnowledgeFileIdForm,
    user=Depends(get_verified_user),
):
    knowledge = Knowledges.get_knowledge_by_id(id=id)
    if not knowledge:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    if (
        knowledge.user_id != user.id
        and not has_access(user.id, "write", knowledge.access_control)
        and user.role != "admin"
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    file = Files.get_file_by_id(form_data.file_id)
    if not file:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    # Remove content from the vector database (search_engine based)
    try:
        knowledge_svc = SearchEngineKnowledge(
            app=request.app, collection_name=knowledge.id
        )
        deleted = await knowledge_svc.delete_by_metadata({"file_id": form_data.file_id})
        if deleted:
            log.info(
                f"Deleted {deleted} existing chunks before re-indexing file {form_data.file_id}"
            )
    except Exception as e:
        log.warning(f"Failed to delete existing file vectors before re-index: {e}")

    # Add content to the vector database
    try:
        await process_file(
            request,
            ProcessFileForm(file_id=form_data.file_id, collection_name=id),
            user=user,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    if knowledge:
        data = knowledge.data or {}
        file_ids = data.get("file_ids", [])

        files = Files.get_files_by_ids(file_ids)

        return KnowledgeFilesResponse(
            **knowledge.model_dump(),
            files=files,
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )


############################
# SetKnowledgeFileMetadata
############################


class KnowledgeFileMetadataForm(BaseModel):
    file_id: str
    metadata: dict


@router.post("/{id}/file/metadata", response_model=Optional[KnowledgeFilesResponse])
async def set_knowledge_file_metadata(
    request: Request,
    id: str,
    form_data: KnowledgeFileMetadataForm,
    user=Depends(get_verified_user),
):
    """파일별 필터 메타데이터 저장 및 벡터 인덱스 in-place 업데이트"""
    knowledge = Knowledges.get_knowledge_by_id(id=id)
    if not knowledge:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    if (
        knowledge.user_id != user.id
        and not has_access(user.id, "write", knowledge.access_control)
        and user.role != "admin"
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    file_ids = knowledge.data.get("file_ids", []) if knowledge.data else []
    if form_data.file_id not in file_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    # Store file metadata in knowledge.data.file_metadata
    knowledge = Knowledges.update_knowledge_file_metadata(
        id=id, file_id=form_data.file_id, metadata=form_data.metadata
    )
    if not knowledge:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("metadata"),
        )

    # 벡터 인덱스: 재임베딩 없이 필터 슬롯 값만 in-place 업데이트 (merge)
    # 삭제+재인덱싱 시 Azure Search eventual consistency로 인한 중복 오류 방지
    try:
        knowledge_svc = SearchEngineKnowledge(app=request.app, collection_name=id)
        # filter schema slot 값만 추출 (f_str_*, f_int_*, f_date_*, f_col_*)
        slot_values = {
            k: v
            for k, v in form_data.metadata.items()
            if k.startswith(("f_str_", "f_int_", "f_date_", "f_col_"))
        }
        if slot_values:
            updated = await knowledge_svc.update_file_filter_slots(
                file_id=form_data.file_id,
                slot_values=slot_values,
            )
            log.info(
                f"Updated {updated} chunks with filter slots for file {form_data.file_id}: {slot_values}"
            )
        else:
            log.debug(f"No filter slot values to update for file {form_data.file_id}")
    except Exception as e:
        log.warning(f"Failed to update filter slots in vector index: {e}")
        # 메타데이터는 이미 DB에 저장됨 — 벡터 업데이트 실패는 치명적 오류 아님

    file_ids = knowledge.data.get("file_ids", []) if knowledge.data else []
    files = Files.get_files_by_ids(file_ids)
    return KnowledgeFilesResponse(**knowledge.model_dump(), files=files)


############################
# ExtractFileMetadata (AI)
############################


class KnowledgeExtractMetadataForm(BaseModel):
    file_id: str
    model_id: str = ""


class KnowledgeExtractResponse(KnowledgeFilesResponse):
    extracted_count: int = 0
    total_fields: int = 0
    missing_required: Optional[List[str]] = None


class KnowledgeExtractAcceptedResponse(BaseModel):
    status: str = "accepted"
    file_id: str = ""


@router.post(
    "/{id}/file/extract-metadata", response_model=KnowledgeExtractAcceptedResponse
)
async def extract_file_metadata_endpoint(
    request: Request,
    id: str,
    form_data: KnowledgeExtractMetadataForm,
    user=Depends(get_verified_user),
):
    """단일 파일의 필터 메타데이터 추출을 큐에 등록"""
    from open_webui.services.task_queue import TaskMessage

    knowledge = Knowledges.get_knowledge_by_id(id=id)
    if not knowledge:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    if (
        knowledge.user_id != user.id
        and not has_access(user.id, "write", knowledge.access_control)
        and user.role != "admin"
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    file_ids = knowledge.data.get("file_ids", []) if knowledge.data else []
    if form_data.file_id not in file_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    filter_schema = (knowledge.meta or {}).get("filter_schema", [])
    if not filter_schema:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No filter schema defined",
        )

    # LLM 필요 시 model config 미리 resolve (Model Not Found 방지)
    pre_resolved = None
    has_llm_fields = any(f.get("extraction_prompt", "").strip() for f in filter_schema)
    if has_llm_fields and form_data.model_id:
        from extension_modules.utils.llm import get_model_config_from_app

        pre_resolved = get_model_config_from_app(request.app, form_data.model_id)

    # 큐에 등록
    task_queue = getattr(request.app.state, "task_queue", None)
    if task_queue:
        await task_queue.publish(
            TaskMessage(
                task_type="kb_filter_extract",
                payload={
                    "kb_id": id,
                    "file_id": form_data.file_id,
                    "user_id": user.id,
                    "filter_schema": filter_schema,
                    "pre_resolved_model_config": pre_resolved,
                },
            )
        )

    return KnowledgeExtractAcceptedResponse(
        status="accepted", file_id=form_data.file_id
    )


############################
# ExtractAllMetadata (AI)
############################


class KnowledgeExtractAllForm(BaseModel):
    model_id: str = ""
    file_ids: Optional[List[str]] = None


class ExtractAllResultItem(BaseModel):
    file_id: str
    file_name: Optional[str] = None
    metadata: Optional[dict] = None
    status: str  # "success" | "failed" | "skipped"
    error: Optional[str] = None


class ExtractAllAcceptedResponse(BaseModel):
    status: str = "accepted"
    total: int


EXTRACT_BATCH_SIZE = 5
EXTRACT_FILE_TIMEOUT = 120  # seconds per file


@router.post("/{id}/extract-all-metadata", response_model=ExtractAllAcceptedResponse)
async def extract_all_metadata_endpoint(
    request: Request,
    id: str,
    form_data: KnowledgeExtractAllForm,
    user=Depends(get_verified_user),
):
    """모든 파일의 필터 메타데이터 추출을 큐에 일괄 등록"""
    from open_webui.services.task_queue import TaskMessage

    knowledge = Knowledges.get_knowledge_by_id(id=id)
    if not knowledge:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    if (
        knowledge.user_id != user.id
        and not has_access(user.id, "write", knowledge.access_control)
        and user.role != "admin"
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    filter_schema = (knowledge.meta or {}).get("filter_schema", [])
    if not filter_schema:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No filter schema defined",
        )

    all_file_ids = knowledge.data.get("file_ids", []) if knowledge.data else []
    if form_data.file_ids:
        file_ids = [fid for fid in form_data.file_ids if fid in all_file_ids]
    else:
        file_ids = all_file_ids

    if not file_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("No valid files to process"),
        )

    # LLM 필요 시 model config 미리 resolve (Model Not Found 방지)
    pre_resolved = None
    has_llm_fields = any(f.get("extraction_prompt", "").strip() for f in filter_schema)
    if has_llm_fields:
        if not form_data.model_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ERROR_MESSAGES.DEFAULT("Model ID required for AI extraction"),
            )
        from extension_modules.utils.llm import get_model_config_from_app

        pre_resolved = get_model_config_from_app(request.app, form_data.model_id)
        if not pre_resolved:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ERROR_MESSAGES.DEFAULT(f"Model not found: {form_data.model_id}"),
            )

    # 파일별 큐 등록
    task_queue = getattr(request.app.state, "task_queue", None)
    if task_queue:
        job_id = f"extract-all-{id}-{int(time.time())}"
        total = len(file_ids)
        for fid in file_ids:
            await task_queue.publish(
                TaskMessage(
                    task_type="kb_filter_extract",
                    payload={
                        "kb_id": id,
                        "file_id": fid,
                        "user_id": user.id,
                        "filter_schema": filter_schema,
                        "pre_resolved_model_config": pre_resolved,
                        "job_id": job_id,
                        "job_total": total,
                    },
                )
            )

    return {"status": "accepted", "total": len(file_ids)}


# _extract_single_file, _extract_all_background 삭제됨
# → filter_extract_worker.py (Redis Queue 워커) 로 이동


############################
# File removal helpers
############################


async def _perform_file_removal_core(app, kb_id: str, file_id: str) -> bool:
    """단일 파일을 KB 에서 제거 — 검색엔진 청크 삭제 + files 레코드 삭제 +
    knowledge.data.file_ids 에서 제거. KG drift cleanup 은 포함하지 않으므로
    호출자가 별도 트리거해야 한다.

    Returns True 성공, False 파일이 이미 없거나 제거 실패.
    """
    file = Files.get_file_by_id(file_id)
    if not file:
        log.info(f"[file-remove] file not found (already removed?): {file_id}")
        return False

    # 처리 중/대기 중이면 먼저 취소
    if file.meta and file.meta.get("pending_knowledge_id") == kb_id:
        job = (file.data or {}).get("processing_job", {})
        job_status = job.get("status")
        if job_status in ("pending", "processing"):
            log.info(
                f"[file-remove] cancel processing for {file_id} (status={job_status})"
            )
            _mark_job_failed(
                file_id, file.data, job, "Cancelled by user (file removed)"
            )
        Files.update_file_metadata_by_id(file_id, {"pending_knowledge_id": None})

    vec_dim = get_effective_embedding_dimension(app)
    try:
        knowledge_svc = SearchEngineKnowledge(
            app=app, collection_name=kb_id, vector_dim=vec_dim
        )
        deleted = await knowledge_svc.delete_by_file_id(file_id)
        log.info(
            f"[file-remove] deleted {deleted} chunks from kb={kb_id} for file={file_id}"
        )
    except Exception as e:
        log.error(f"[file-remove] failed to delete chunks (kb={kb_id}): {e}")

    try:
        file_svc = SearchEngineKnowledge(
            app=app, collection_name=f"file-{file_id}", vector_dim=vec_dim
        )
        deleted = await file_svc.delete_by_collection()
        log.info(
            f"[file-remove] deleted {deleted} chunks from file-{file_id} collection"
        )
    except Exception as e:
        log.error(f"[file-remove] failed to delete file collection: {e}")

    Files.delete_file_by_id(file_id)

    knowledge = Knowledges.get_knowledge_by_id(id=kb_id)
    if knowledge:
        data = knowledge.data or {}
        file_ids = list(data.get("file_ids", []) or [])
        if file_id in file_ids:
            file_ids.remove(file_id)
            data["file_ids"] = file_ids
            Knowledges.update_knowledge_data_by_id(id=kb_id, data=data)
    return True


async def _kg_drift_cleanup_for_kb(app, kb_id: str, user_id: str) -> None:
    """이 KB 를 참조하는 KG 들에 대해 drift cleanup 을 백그라운드로 트리거.

    단일/배치 삭제 공용 — 배치는 모든 파일 삭제 완료 후 한 번만 호출한다.
    """
    try:
        from open_webui.models.knowledge_graph import KnowledgeGraphs

        for kg in KnowledgeGraphs.get_kgs():
            sources = (kg.data or {}).get("sources") or {}
            if kb_id not in (sources.get("knowledge_ids") or []):
                continue
            from extension_modules.knowledge_graph import sync_kb_to_kg

            try:
                await sync_kb_to_kg(
                    app=app,
                    kg_id=kg.id,
                    knowledge_id=kb_id,
                    user_id=user_id,
                    cleanup_only=True,
                )
                log.info(
                    f"[KG drift] cleanup triggered for kg={kg.id} after file "
                    f"removal from kb={kb_id}"
                )
            except Exception as exc:
                log.warning(f"[KG drift] cleanup failed for kg={kg.id}: {exc}")
    except Exception as e:
        log.warning(f"[KG drift] hook failed (non-fatal): {e}")


############################
# RemoveFileFromKnowledge
############################


@router.post("/{id}/file/remove", response_model=Optional[KnowledgeFilesResponse])
async def remove_file_from_knowledge_by_id(
    request: Request,
    id: str,
    form_data: KnowledgeFileIdForm,
    background_tasks: BackgroundTasks,
    user=Depends(get_verified_user),
):
    knowledge = Knowledges.get_knowledge_by_id(id=id)
    if not knowledge:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    if (
        knowledge.user_id != user.id
        and not has_access(user.id, "write", knowledge.access_control)
        and user.role != "admin"
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    removed = await _perform_file_removal_core(
        app=request.app, kb_id=id, file_id=form_data.file_id
    )
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    # KG drift cleanup 은 파일 제거가 실제로 수행된 경우에만 백그라운드 트리거.
    background_tasks.add_task(_kg_drift_cleanup_for_kb, request.app, id, user.id)

    knowledge = Knowledges.get_knowledge_by_id(id=id)
    if not knowledge:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("knowledge"),
        )
    updated_file_ids = (knowledge.data or {}).get("file_ids", []) or []
    files = Files.get_files_by_ids(updated_file_ids)
    return KnowledgeFilesResponse(**knowledge.model_dump(), files=files)


############################
# Batch remove files
############################


class KnowledgeBatchRemoveForm(BaseModel):
    file_ids: List[str]


class KnowledgeBatchRemoveAcceptedResponse(BaseModel):
    status: str = "accepted"
    job_id: str
    total: int


@router.post(
    "/{id}/files/batch/remove",
    response_model=KnowledgeBatchRemoveAcceptedResponse,
)
async def batch_remove_files_from_knowledge(
    request: Request,
    id: str,
    form_data: KnowledgeBatchRemoveForm,
    user=Depends(get_verified_user),
):
    """선택된 파일 목록을 백그라운드로 일괄 삭제. 각 파일별 진행은 Socket.IO
    `file-delete-batch:progress` 이벤트로, 전체 완료는 `file-delete-batch:complete`
    이벤트로 클라이언트에 전송된다. KG drift cleanup 은 배치 끝에 한 번만 트리거.
    """
    from open_webui.services.task_queue import TaskMessage

    knowledge = Knowledges.get_knowledge_by_id(id=id)
    if not knowledge:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )
    if (
        knowledge.user_id != user.id
        and not has_access(user.id, "write", knowledge.access_control)
        and user.role != "admin"
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    file_ids = [fid for fid in (form_data.file_ids or []) if fid]
    if not file_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("No files selected"),
        )

    job_id = f"kb-delete-{id}-{int(time.time())}"
    total = len(file_ids)
    task_queue = getattr(request.app.state, "task_queue", None)
    if task_queue is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=ERROR_MESSAGES.DEFAULT("Task queue unavailable"),
        )

    # 파일명 캐시 — 워커에서 알림 메시지에 사용
    files_map = {f.id: f.filename for f in Files.get_files_by_ids(file_ids)}

    for fid in file_ids:
        await task_queue.publish(
            TaskMessage(
                task_type="knowledge_file_delete",
                payload={
                    "kb_id": id,
                    "file_id": fid,
                    "filename": files_map.get(fid, fid),
                    "user_id": user.id,
                    "job_id": job_id,
                    "total": total,
                },
            )
        )

    return KnowledgeBatchRemoveAcceptedResponse(
        status="accepted", job_id=job_id, total=total
    )


############################
# BatchClearFilterMetadata
############################


class FilterMetadataBatchClearForm(BaseModel):
    file_ids: List[str]


class FilterMetadataBatchClearResponse(BaseModel):
    cleared: int
    files: List[str]


@router.post(
    "/{id}/filter-metadata/batch/clear",
    response_model=FilterMetadataBatchClearResponse,
)
async def batch_clear_filter_metadata(
    request: Request,
    id: str,
    form_data: FilterMetadataBatchClearForm,
    user=Depends(get_verified_user),
):
    """선택된 파일들의 filter slot (``f_str_*``/``f_int_*``/``f_date_*``/
    ``f_col_*``) 만 비운다. 파일 자체와 chunk / embedding 은 보존되므로
    "문서 삭제" 버튼과 명확히 분리된 경량 액션. 인덱싱된 벡터의 slot 도 함께
    None 으로 동기화한다.
    """
    # Step 1: workspace 카테고리 게이트
    if user.role != "admin" and not has_permission_min_level(
        user.id,
        "workspace.knowledge",
        "write",
        request.app.state.config.USER_PERMISSIONS,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.UNAUTHORIZED,
        )

    knowledge = Knowledges.get_knowledge_by_id(id=id)
    if not knowledge:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    # Step 2: 리소스 row-level 권한 (소유자 / admin / write 그룹)
    if (
        knowledge.user_id != user.id
        and not has_access(user.id, "write", knowledge.access_control)
        and user.role != "admin"
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    file_ids = [fid for fid in (form_data.file_ids or []) if fid]
    if not file_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("No files selected"),
        )

    result = Knowledges.clear_knowledge_file_metadata_slots(id=id, file_ids=file_ids)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("Failed to clear filter metadata"),
        )

    _, cleared_per_file = result

    # 벡터 인덱스의 filter slot 도 None 동기화 — chunk/embedding 자체는 보존.
    if cleared_per_file:
        try:
            knowledge_svc = SearchEngineKnowledge(app=request.app, collection_name=id)
            for fid, slot_keys in cleared_per_file.items():
                if not slot_keys:
                    continue
                await knowledge_svc.update_file_filter_slots(
                    file_id=fid,
                    slot_values={k: None for k in slot_keys},
                )
        except Exception as e:
            log.warning(f"[clear_filter_metadata] vector slot sync failed: {e}")

    return FilterMetadataBatchClearResponse(
        cleared=len(cleared_per_file),
        files=list(cleared_per_file.keys()),
    )


############################
# GetLinkedAgentsByKnowledgeId
############################


@router.get("/{id}/linked-agents")
async def get_linked_agents_by_knowledge_id(id: str, _user=Depends(get_verified_user)):
    """Return agents (models) that have this knowledge base connected."""
    knowledge = Knowledges.get_knowledge_by_id(id=id)
    if not knowledge:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    models = Models.get_all_models()
    linked = []
    for model in models:
        if not model.meta:
            continue
        meta = model.meta.model_dump() if hasattr(model.meta, "model_dump") else {}
        knowledge_list = meta.get("knowledge", []) or []
        for kb in knowledge_list:
            if isinstance(kb, dict) and kb.get("id") == id:
                linked.append({"id": model.id, "name": model.name})
                break
            elif isinstance(kb, str) and kb == id:
                linked.append({"id": model.id, "name": model.name})
                break
    return linked


############################
# CleanupOrphanFileIds
############################


class CleanupOrphansResponse(BaseModel):
    before: int
    after: int
    dropped: int


@router.post("/{id}/cleanup-orphans", response_model=CleanupOrphansResponse)
async def cleanup_orphan_file_ids(id: str, user=Depends(get_verified_user)):
    """knowledge.data.file_ids 에서 실제 DB 에 존재하지 않는 파일 ID 와 중복을
    제거. 일반적으로 파일 목록 조회 시 auto-heal 이 수행되지만, 명시적으로
    실행하고 싶을 때 사용.
    """
    knowledge = Knowledges.get_knowledge_by_id(id=id)
    if not knowledge:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )
    if not (
        user.role == "admin"
        or knowledge.user_id == user.id
        or has_access(user.id, "write", knowledge.access_control)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.UNAUTHORIZED,
        )

    file_ids = (knowledge.data or {}).get("file_ids", []) or []
    existing_ids = {f.id for f in Files.get_files_by_ids(file_ids)}
    result = Knowledges.compact_file_ids(id=id, valid_ids=existing_ids)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("Failed to compact file_ids"),
        )
    _, before, after = result
    return CleanupOrphansResponse(before=before, after=after, dropped=before - after)


############################
# DeleteKnowledgeById
############################


@router.delete("/{id}/delete", response_model=bool)
async def delete_knowledge_by_id(
    request: Request, id: str, user=Depends(get_verified_user)
):
    knowledge = Knowledges.get_knowledge_by_id(id=id)
    if not knowledge:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    if (
        knowledge.user_id != user.id
        and not has_access(user.id, "write", knowledge.access_control)
        and user.role != "admin"
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    log.info(f"Deleting knowledge base: {id} (name: {knowledge.name})")

    # Get all models
    models = Models.get_all_models()
    log.info(f"Found {len(models)} models to check for knowledge base {id}")

    # Update models that reference this knowledge base
    for model in models:
        if model.meta and hasattr(model.meta, "knowledge"):
            knowledge_list = model.meta.knowledge or []
            # Filter out the deleted knowledge base
            updated_knowledge = [k for k in knowledge_list if k.get("id") != id]

            # If the knowledge list changed, update the model
            if len(updated_knowledge) != len(knowledge_list):
                log.info(f"Updating model {model.id} to remove knowledge base {id}")
                model.meta.knowledge = updated_knowledge
                # Create a ModelForm for the update
                model_form = ModelForm(
                    id=model.id,
                    name=model.name,
                    base_model_id=model.base_model_id,
                    meta=model.meta,
                    params=model.params,
                    access_control=model.access_control,
                    is_active=model.is_active,
                )
                Models.update_model_by_id(model.id, model_form)

    # Clean up vector DB (search_engine based)
    vec_dim = get_effective_embedding_dimension(request.app)

    # 1) Delete the knowledge base collection
    try:
        knowledge_svc = SearchEngineKnowledge(
            app=request.app, collection_name=id, vector_dim=vec_dim
        )
        deleted = await knowledge_svc.delete_by_collection()
        log.info(f"Deleted {deleted} chunks from search index for knowledge base {id}")
    except Exception as e:
        log.error(f"Failed to delete knowledge base chunks from search index: {e}")

    # 2) Clean up orphan pending files (files waiting to be added to this knowledge)
    orphan_pending = Files.get_files_by_pending_knowledge_id(id)
    for opf in orphan_pending:
        job = (opf.data or {}).get("processing_job", {})
        if job.get("status") in ("pending", "processing", "completed"):
            _mark_job_failed(
                opf.id,
                opf.data,
                job,
                "Cancelled (knowledge base deleted)",
            )
        Files.update_file_metadata_by_id(opf.id, {"pending_knowledge_id": None})
    if orphan_pending:
        log.info(
            f"Cleaned up {len(orphan_pending)} orphan pending files for knowledge {id}"
        )

    # 3) Bulk delete file DB records
    # KB 파일 청크는 위의 delete_by_collection()에서 이미 전부 제거됨
    # (파일은 KB id 컬렉션에 직접 저장되며 file-{id} 중간 컬렉션을 사용하지 않음)
    data = knowledge.data or {}
    file_ids = data.get("file_ids", []) or []
    if file_ids:
        try:
            deleted_files = Files.delete_files_by_ids(file_ids)
            log.info(
                f"Deleted {deleted_files}/{len(file_ids)} file records for knowledge base {id}"
            )
        except Exception as e:
            log.error(f"Failed to bulk delete file records for knowledge {id}: {e}")

    result = Knowledges.delete_knowledge_by_id(id=id)
    return result


############################
# ResetKnowledgeById
############################


@router.post("/{id}/reset", response_model=Optional[KnowledgeResponse])
async def reset_knowledge_by_id(
    request: Request, id: str, user=Depends(get_verified_user)
):
    knowledge = Knowledges.get_knowledge_by_id(id=id)
    if not knowledge:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    if (
        knowledge.user_id != user.id
        and not has_access(user.id, "write", knowledge.access_control)
        and user.role != "admin"
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    try:
        knowledge_svc = SearchEngineKnowledge(app=request.app, collection_name=id)
        deleted = await knowledge_svc.delete_by_collection()
        log.info(
            f"Reset: deleted {deleted} chunks from search index for knowledge base {id}"
        )
    except Exception as e:
        log.error(
            f"Failed to delete knowledge base chunks from search index during reset: {e}"
        )

    knowledge = Knowledges.update_knowledge_data_by_id(id=id, data={"file_ids": []})

    return knowledge


############################
# AddFilesToKnowledge
############################


@router.post("/{id}/files/batch/add", response_model=Optional[KnowledgeFilesResponse])
def add_files_to_knowledge_batch(
    request: Request,
    id: str,
    form_data: list[KnowledgeFileIdForm],
    user=Depends(get_verified_user),
):
    """
    Add multiple files to a knowledge base
    """
    knowledge = Knowledges.get_knowledge_by_id(id=id)
    if not knowledge:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    if (
        knowledge.user_id != user.id
        and not has_access(user.id, "write", knowledge.access_control)
        and user.role != "admin"
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    # Get files content
    log.info(f"files/batch/add - {len(form_data)} files")
    files: List[FileModel] = []
    for form in form_data:
        file = Files.get_file_by_id(form.file_id)
        if not file:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"File {form.file_id} not found",
            )
        files.append(file)

    # Process files
    try:
        result = process_files_batch(
            request=request,
            form_data=BatchProcessFilesForm(files=files, collection_name=id),
            user=user,
        )
    except Exception as e:
        log.error(
            f"add_files_to_knowledge_batch: Exception occurred: {e}", exc_info=True
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    # Add successful files to knowledge base using atomic operations
    successful_file_ids = [r.file_id for r in result.results if r.status == "completed"]
    for file_id in successful_file_ids:
        knowledge = Knowledges.add_file_id_to_knowledge(id=id, file_id=file_id)

    # Get final file_ids list
    existing_file_ids = (
        knowledge.data.get("file_ids", []) if knowledge and knowledge.data else []
    )

    # If there were any errors, include them in the response
    if result.errors:
        error_details = [f"{err.file_id}: {err.error}" for err in result.errors]
        return KnowledgeFilesResponse(
            **knowledge.model_dump(),
            files=Files.get_files_by_ids(existing_file_ids),
            warnings={
                "message": "Some files failed to process",
                "errors": error_details,
            },
        )

    return KnowledgeFilesResponse(
        **knowledge.model_dump(), files=Files.get_files_by_ids(existing_file_ids)
    )

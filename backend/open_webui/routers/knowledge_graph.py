"""Knowledge Graph 라우터.

Phase 0 슬라이스 — CRUD + Glossary 동기화 + 노드/이웃 조회.
"""

import logging
import time
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from open_webui.constants import ERROR_MESSAGES
from open_webui.env import SRC_LOG_LEVELS
from open_webui.models.knowledge_graph import (
    CandidateStatus,
    EdgeSource,
    EdgeType,
    JobKind,
    KGCandidateModel,
    KGEdgeModel,
    KGExtractJobModel,
    KGNeighborhoodNode,
    KGNodeModel,
    KnowledgeGraphForm,
    KnowledgeGraphResponse,
    KnowledgeGraphs,
    KnowledgeGraphUserResponse,
)
from open_webui.utils.access_control import (
    has_access,
    has_permission_min_level,
)
from open_webui.utils.audit_logger import AuditLogger
from open_webui.utils.auth import get_verified_user
from pydantic import BaseModel

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])

router = APIRouter()


############################
# Watchdog
############################


async def kg_job_watchdog():
    """장시간 무응답 running job을 failed 처리.

    - sync_all / candidate_extract: 5분 타임아웃 (heartbeat 기반)
    - kb_extract: 2시간 타임아웃 (LLM 호출이 많아 장시간 소요)
    """
    from open_webui.internal.db import get_db
    from open_webui.models.knowledge_graph import KGExtractJob

    now = int(time.time())
    short_threshold = now - 300  # 5 minutes
    long_threshold = now - 7200  # 2 hours

    try:
        with get_db() as db:
            running_jobs = (
                db.query(KGExtractJob).filter(KGExtractJob.status == "running").all()
            )
            for job in running_jobs:
                # KB extract는 장시간 LLM 작업이므로 2시간 타임아웃
                if job.kind in ("kb_extract",):
                    threshold = long_threshold
                else:
                    threshold = short_threshold

                is_stale = (
                    job.started_at
                    and job.started_at < threshold
                    and (
                        job.last_heartbeat_at is None
                        or job.last_heartbeat_at < threshold
                    )
                )
                if is_stale:
                    job.status = "failed"
                    job.finished_at = now
                    job.errors = [
                        f"Job timed out — no activity for "
                        f"{'2+ hours' if job.kind == 'kb_extract' else '5+ minutes'}"
                    ]
                    log.warning(
                        f"[KG watchdog] Marked stale job {job.id} "
                        f"(kind={job.kind}) as failed"
                    )
            db.commit()
    except Exception as e:
        log.exception(f"[KG watchdog] Error: {e}")


############################
# Sync helpers (background)
############################


async def _sync_all_sources(
    app,
    kg_id: str,
    user_id: str,
    pre_resolved_kb_model_config: Optional[dict] = None,
    job_id: Optional[str] = None,
) -> None:
    """KG의 모든 등록 소스를 동기화 + 검색 인덱싱 (백그라운드 잡).

    흐름:
    1. PG에 그래프 노드/엣지 동기화 (Glossary, DbSphere)
    2. KB 문서 → LLM 엔티티/관계 추출 (llm_model_id 설정 시)
    3. PG의 모든 노드를 search engine에 인덱싱 (graceful: 미설정 시 skip)
    4. 통계 갱신

    지원 소스:
    - Glossary (sync, 임베딩 불필요)
    - DbSphere (async, search engine memory의 DDL 메모리 사용)
    - KB (async, LLM 호출 — llm_model_id 가 options에 설정돼 있어야 함)
    """
    from extension_modules.knowledge_graph import (
        KGNodeIndexService,
        KGService,
        sync_dbsphere_to_kg,
        sync_glossary_to_kg,
        sync_kb_to_kg,
    )
    from open_webui.models.knowledge_graph import KnowledgeGraphs

    service = KGService.load(kg_id)
    if not service:
        log.warning(f"KG not found for sync: {kg_id}")
        return

    # 0. 분리된(detached) 소스 정리: 이전 sync에서 만든 노드 중
    #    현재 sources 목록에 없는 source_id의 노드를 제거.
    #    이게 없으면 사용자가 KG에서 용어집/DbSphere/KB를 떼어내도
    #    이전 노드가 그대로 남아 KG가 영원히 stale 상태가 된다.
    current_glossary_ids = set(service.glossary_ids)
    current_dbsphere_ids = set(service.dbsphere_ids)
    current_knowledge_ids = set(service.knowledge_ids)
    for kind, current_set in (
        ("glossary", current_glossary_ids),
        ("dbsphere", current_dbsphere_ids),
        ("knowledge", current_knowledge_ids),
    ):
        try:
            existing = KnowledgeGraphs.get_distinct_source_ids(kg_id, kind)
        except Exception as e:
            log.exception(f"Failed to enumerate existing {kind} sources: {e}")
            continue
        for src_id in existing:
            if src_id not in current_set:
                try:
                    # detach: manual 엣지까지 같이 제거 (dangling 방지)
                    removed = KnowledgeGraphs.delete_nodes_by_source(
                        kg_id, kind, src_id, include_manual_edges=True
                    )
                    log.info(
                        f"[KG sync] cleaned up detached {kind}={src_id} "
                        f"({removed} nodes)"
                    )
                except Exception as e:
                    log.exception(f"Failed to clean up detached {kind} {src_id}: {e}")

                # KB의 경우 추가로 incremental 처리 이력도 정리
                # (다음에 다시 attach되면 처음부터 새로 추출돼야 함)
                if kind == "knowledge":
                    try:
                        KnowledgeGraphs.delete_extract_state(kg_id, src_id)
                        log.info(
                            f"[KG sync] cleared kb_extract_state for "
                            f"detached kb={src_id}"
                        )
                    except Exception as e:
                        log.exception(
                            f"Failed to clear kb_extract_state for {src_id}: {e}"
                        )

    sync_errors: list[str] = []
    sync_stats: dict = {
        "glossaries_synced": 0,
        "dbspheres_synced": 0,
        "kbs_synced": 0,
    }

    # 1. 그래프 구조 동기화 (Glossary + DbSphere)
    if job_id:
        KnowledgeGraphs.update_job_progress(
            job_id, progress_label="Syncing glossaries..."
        )
        KnowledgeGraphs.heartbeat_job(job_id)
    for glossary_id in service.glossary_ids:
        try:
            sync_glossary_to_kg(kg_id, glossary_id, user_id)
            sync_stats["glossaries_synced"] += 1
        except Exception as e:
            log.exception(f"Failed to sync glossary {glossary_id}: {e}")
            sync_errors.append(f"glossary {glossary_id[:8]}: {e}")

    if job_id:
        KnowledgeGraphs.update_job_progress(
            job_id, progress_label="Syncing databases..."
        )
        KnowledgeGraphs.heartbeat_job(job_id)
    for dbsphere_id in service.dbsphere_ids:
        try:
            await sync_dbsphere_to_kg(app, kg_id, dbsphere_id, user_id)
            sync_stats["dbspheres_synced"] += 1
        except Exception as e:
            log.exception(f"Failed to sync dbsphere {dbsphere_id}: {e}")
            sync_errors.append(f"dbsphere {dbsphere_id[:8]}: {e}")

    # 2. KB 추출 (llm_model_id 가 설정돼 있고 pre_resolved model config 가
    # 준비돼 있을 때만). KG의 entity/엣지를 만드는 유일한 경로이므로 플래그
    # 없이 항상 시도한다. llm_model_id 미설정은 /sync 엔드포인트에서 400 으로
    # 이미 차단됨.
    # incremental: kb_extract_state에서 처리 이력 로드 → 미처리분만 LLM 호출
    options = (service.kg.data or {}).get("options") or {}
    if service.knowledge_ids:
        if not pre_resolved_kb_model_config:
            log.warning(
                "[KG sync] no pre-resolved model config; skipping KB extraction"
            )
        else:
            sync_model_id = options.get("llm_model_id") or "unknown"
            if job_id:
                KnowledgeGraphs.update_job_progress(
                    job_id, progress_label="Extracting from KBs..."
                )
                KnowledgeGraphs.heartbeat_job(job_id)
            for kb_id in service.knowledge_ids:
                try:
                    already = _load_kb_processed_chunks(kg_id, kb_id)
                    result = await sync_kb_to_kg(
                        app=app,
                        kg_id=kg_id,
                        knowledge_id=kb_id,
                        user_id=user_id,
                        pre_resolved_model_config=pre_resolved_kb_model_config,
                        # max_chunks=None → 미처리분 전체 처리
                        max_chunks=None,
                        processed_chunk_ids=already,
                    )
                    if result:
                        newly = result.get("processed_chunk_ids") or set()
                        removed = result.get("removed_chunk_ids") or set()
                        if isinstance(newly, (list, tuple)):
                            newly = set(newly)
                        if isinstance(removed, (list, tuple)):
                            removed = set(removed)
                        merged = (already | newly) - removed
                        if newly or removed:
                            try:
                                _save_kb_processed_chunks(
                                    kg_id, kb_id, merged, sync_model_id
                                )
                            except Exception as e:
                                log.exception(
                                    f"[KG sync] failed to save processed_chunks "
                                    f"for kb={kb_id}: {e}"
                                )
                        sync_stats["kbs_synced"] += 1
                except Exception as e:
                    log.exception(f"Failed to sync KB {kb_id}: {e}")
                    sync_errors.append(f"kb {kb_id[:8]}: {e}")

    # 2. 검색 인덱싱 (search engine 미설정이면 graceful no-op)
    if job_id:
        KnowledgeGraphs.update_job_progress(
            job_id, progress_label="Reindexing search engine..."
        )
        KnowledgeGraphs.heartbeat_job(job_id)
    try:
        index_service = KGNodeIndexService(app)
        # 기존 KG 인덱스 항목 모두 제거 후 재구축 (Phase 0 단순 전략)
        await index_service.delete_by_kg(kg_id)

        # PG에서 모든 노드 fetch (배치)
        all_nodes = []
        offset = 0
        batch_size = 500
        while True:
            batch = KnowledgeGraphs.get_nodes(kg_id, limit=batch_size, offset=offset)
            if not batch:
                break
            all_nodes.extend(batch)
            if len(batch) < batch_size:
                break
            offset += batch_size

        if all_nodes:
            # 임베딩 호출이 비싸므로 배치별로 분할 인덱싱
            for i in range(0, len(all_nodes), batch_size):
                chunk = all_nodes[i : i + batch_size]
                await index_service.index_nodes(kg_id, chunk)
    except Exception as e:
        log.exception(f"KG indexing step failed: {e}")
        sync_errors.append(f"indexing: {e}")

    # 3. 통계 갱신
    service.refresh_stats()

    # 4. Job 마감 + Socket 알림
    if job_id:
        try:
            # 부분 실패 판단: 전체 소스 중 50% 이상 실패 시 failed 처리
            total_sources = (
                len(service.glossary_ids)
                + len(service.dbsphere_ids)
                + len(service.knowledge_ids)
            )
            total_succeeded = (
                sync_stats.get("glossaries_synced", 0)
                + sync_stats.get("dbspheres_synced", 0)
                + sync_stats.get("kbs_synced", 0)
            )
            if total_sources > 0 and total_succeeded < total_sources * 0.5:
                KnowledgeGraphs.fail_job(
                    job_id, errors=sync_errors[:20] or ["Majority of sources failed"]
                )
            else:
                KnowledgeGraphs.complete_job(
                    job_id, stats=sync_stats, errors=sync_errors[:20] or None
                )
        except Exception as e:
            log.exception(f"[KG sync] failed to complete job {job_id}: {e}")

        # 실시간 알림 (사용자에게 즉시 갱신 표시)
        try:
            from open_webui.socket.main import send_notification_to_user

            await send_notification_to_user(
                user_id=user_id,
                event_type="kg-job-completed",
                data={
                    "job_id": job_id,
                    "kg_id": kg_id,
                    "kind": "sync_all",
                    "status": "completed",
                    "stats": sync_stats,
                },
            )
        except Exception as e:
            log.warning(f"[KG sync] socket notification failed (non-fatal): {e}")


############################
# List
############################


@router.get("/", response_model=list[KnowledgeGraphUserResponse])
async def get_knowledge_graphs(request: Request, user=Depends(get_verified_user)):
    if user.role != "admin" and not has_permission_min_level(
        user.id,
        "workspace.knowledge_graphs",
        "read",
        request.app.state.config.USER_PERMISSIONS,
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    if user.role == "admin":
        kgs = KnowledgeGraphs.get_kgs()
    else:
        kgs = KnowledgeGraphs.get_kgs_by_user_id(user.id, "read")

    return [KnowledgeGraphUserResponse(**kg.model_dump()) for kg in kgs]


@router.get("/list", response_model=list[KnowledgeGraphUserResponse])
async def get_knowledge_graph_list(request: Request, user=Depends(get_verified_user)):
    """편집 가능한(write 권한) KG 목록."""
    if user.role != "admin" and not has_permission_min_level(
        user.id,
        "workspace.knowledge_graphs",
        "read",
        request.app.state.config.USER_PERMISSIONS,
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    if user.role == "admin":
        kgs = KnowledgeGraphs.get_kgs()
    else:
        kgs = KnowledgeGraphs.get_kgs_by_user_id(user.id, "write")

    return [KnowledgeGraphUserResponse(**kg.model_dump()) for kg in kgs]


############################
# Create
############################


_KG_NAME_MAX_LEN = 200


def _assert_user_can_attach_sources(user, sources: Optional[dict]) -> None:
    """KG `data.sources` 에 포함되는 KB/DbSphere/Glossary id 들에 대해
    호출자가 read 권한을 가지는지 검증.

    이 검증이 없으면 다음 권한 우회가 가능하다:
        1) 사용자 A 가 자기 KG 의 sources 에 자신은 read 권한이 없는 KB id 를
           직접 API 로 넣는다.
        2) sync 가 그 KB 의 청크를 LLM 으로 추출해 KG 노드(label 에 KB 내용
           스니펫 포함) 로 만든다.
        3) 사용자 A 는 KG 페이지에서 그 노드들을 그대로 열람한다 → 권한 세탁.

    sources 가 dict 가 아니거나 비어 있으면 no-op. admin 은 통과.
    """
    if user.role == "admin":
        return
    if not isinstance(sources, dict):
        return

    # Local imports — 순환 의존 회피 + 모듈 로드 지연.
    from open_webui.models.dbsphere import DbSpheres
    from open_webui.models.glossary import Glossaries
    from open_webui.models.knowledge import Knowledges

    def _check(label: str, ids: list, get_by_id) -> None:
        for rid in ids or []:
            if not rid:
                continue
            try:
                resource = get_by_id(rid) if get_by_id else None
            except TypeError:
                # get_by_id 의 signature 가 keyword 전용일 수 있음
                resource = get_by_id(id=rid)
            except Exception:
                resource = None
            if not resource:
                # 존재하지 않는 id → 굳이 막지 않는다 (sync 시점에 자연 정리됨)
                continue
            if getattr(resource, "user_id", None) == user.id:
                continue
            if has_access(user.id, "read", getattr(resource, "access_control", None)):
                continue
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=ERROR_MESSAGES.DEFAULT(
                    f"You do not have read access to {label} {rid[:8]}"
                ),
            )

    _check(
        "knowledge base",
        list(sources.get("knowledge_ids") or []),
        Knowledges.get_knowledge_by_id,
    )
    _check(
        "dbsphere",
        list(sources.get("dbsphere_ids") or []),
        DbSpheres.get_dbsphere_by_id,
    )
    _check(
        "glossary",
        list(sources.get("glossary_ids") or []),
        Glossaries.get_glossary_by_id,
    )


def _validate_kg_name(name: Optional[str]) -> str:
    """KG name 정규화 + 검증.

    `KnowledgeGraphModel.name`이 required이므로 None/빈/공백은 모두 거절.
    또한 1000자 이상 이름이 들어오면 DB / UI 양쪽이 망가지므로 길이 제한.
    """
    if name is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("name is required"),
        )
    stripped = name.strip()
    if not stripped:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("name must not be empty"),
        )
    if len(stripped) > _KG_NAME_MAX_LEN:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT(
                f"name must be {_KG_NAME_MAX_LEN} characters or fewer"
            ),
        )
    return stripped


@router.post("/create", response_model=Optional[KnowledgeGraphResponse])
async def create_knowledge_graph(
    request: Request,
    form_data: KnowledgeGraphForm,
    user=Depends(get_verified_user),
):
    if user.role != "admin" and not has_permission_min_level(
        user.id,
        "workspace.knowledge_graphs",
        "write",
        request.app.state.config.USER_PERMISSIONS,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.UNAUTHORIZED,
        )

    form_data.name = _validate_kg_name(form_data.name)

    if KnowledgeGraphs.name_exists(form_data.name):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NAME_TAKEN,
        )

    # 권한 세탁 방지 — sources 에 들어있는 KB/DbSphere/Glossary 에 대해
    # 호출자가 read 권한을 가지는지 검증.
    if form_data.data and isinstance(form_data.data, dict):
        _assert_user_can_attach_sources(user, form_data.data.get("sources"))

    kg = KnowledgeGraphs.insert_new_kg(user.id, form_data)
    if kg:
        AuditLogger.log_create(
            resource_type="knowledge_graph",
            resource_id=kg.id,
            data=kg.model_dump(),
            resource_name=kg.name,
        )
        return kg

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=ERROR_MESSAGES.DEFAULT("Failed to create knowledge graph"),
    )


############################
# Get / Update / Delete
############################


class KGActiveJob(BaseModel):
    """user 접근 가능한 모든 KG 의 pending/running 잡 단일 엔트리."""

    id: str
    kg_id: str
    kg_name: Optional[str] = None
    user_id: str
    kind: str
    target_id: Optional[str] = None
    status: str
    progress_current: Optional[int] = None
    progress_total: Optional[int] = None
    progress_label: Optional[str] = None
    params: Optional[dict] = None
    stats: Optional[dict] = None
    created_at: Optional[int] = None
    updated_at: Optional[int] = None


@router.get("/active-jobs", response_model=list[KGActiveJob])
async def list_active_kg_jobs(
    request: Request,
    user=Depends(get_verified_user),
):
    """현재 사용자에게 보이는 모든 KG 의 pending/running 잡을 한 번에 반환.

    글로벌 진행률 indicator 에서 앱 로드/새로고침 시 실행 중인 sync 를
    복원하는 용도. admin 은 전체 KG 대상, 그 외 사용자는 read 권한
    있는 KG 로 제한.
    """
    if user.role == "admin":
        kgs = KnowledgeGraphs.get_kgs()
    else:
        kgs = KnowledgeGraphs.get_kgs_by_user_id(user.id, "read")

    kg_name_by_id = {kg.id: kg.name for kg in kgs}
    kg_ids = list(kg_name_by_id.keys())
    if not kg_ids:
        return []

    from open_webui.internal.db import get_db
    from open_webui.models.knowledge_graph import KGExtractJob

    try:
        with get_db() as db:
            rows = (
                db.query(KGExtractJob)
                .filter(KGExtractJob.kg_id.in_(kg_ids))
                .filter(KGExtractJob.status.in_(["pending", "running"]))
                .order_by(KGExtractJob.created_at.desc())
                .limit(200)
                .all()
            )
    except Exception as e:
        log.exception(f"[kg] list_active_kg_jobs failed: {e}")
        return []

    result: list[KGActiveJob] = []
    for r in rows:
        # KGExtractJob 은 updated_at 컬럼이 없어서 heartbeat / started /
        # created 중 최근값을 "최근 활동 시각"으로 사용.
        effective_updated = (
            getattr(r, "last_heartbeat_at", None)
            or getattr(r, "started_at", None)
            or r.created_at
        )
        result.append(
            KGActiveJob(
                id=r.id,
                kg_id=r.kg_id,
                kg_name=kg_name_by_id.get(r.kg_id),
                user_id=r.user_id,
                kind=r.kind,
                target_id=r.target_id,
                status=r.status,
                progress_current=r.progress_current,
                progress_total=r.progress_total,
                progress_label=r.progress_label,
                params=_sanitize_job_params(r.params),
                stats=r.stats,
                created_at=r.created_at,
                updated_at=effective_updated,
            )
        )
    return result


@router.get("/{id}", response_model=Optional[KnowledgeGraphResponse])
async def get_knowledge_graph_by_id(
    id: str,
    request: Request,
    user=Depends(get_verified_user),
):
    kg = KnowledgeGraphs.get_kg_by_id(id=id)
    _require_kg_read(kg, user, request)
    return KnowledgeGraphResponse(**kg.model_dump())


@router.post("/{id}/update", response_model=Optional[KnowledgeGraphResponse])
async def update_knowledge_graph_by_id(
    id: str,
    request: Request,
    form_data: KnowledgeGraphForm,
    user=Depends(get_verified_user),
):
    kg = KnowledgeGraphs.get_kg_by_id(id=id)
    _require_kg_write(kg, user, request)

    # update에서 name이 명시적으로 들어왔으면 검증 (None은 부분 업데이트 의미라 통과)
    if form_data.name is not None:
        form_data.name = _validate_kg_name(form_data.name)

    if form_data.name and KnowledgeGraphs.name_exists(form_data.name, exclude_id=id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NAME_TAKEN,
        )

    # 권한 세탁 방지 — sources 에 새로 추가되는 KB/DbSphere/Glossary id 에
    # 대해 호출자가 read 권한을 가지는지 검증. 기존 KG 에 이미 있던 id 는 sync
    # 로 콘텐츠가 이미 노출된 상태이므로 새로 추가된 항목만 체크하면 충분하다.
    if form_data.data and isinstance(form_data.data, dict):
        new_sources = form_data.data.get("sources")
        if isinstance(new_sources, dict):
            existing_sources = (kg.data or {}).get("sources") or {}
            diff_sources = {
                key: [
                    rid
                    for rid in (new_sources.get(key) or [])
                    if rid not in (existing_sources.get(key) or [])
                ]
                for key in ("knowledge_ids", "dbsphere_ids", "glossary_ids")
            }
            _assert_user_can_attach_sources(user, diff_sources)

    # 용어집/DB 노드 orphan cleanup 은 이제 링크 삭제 시점(`delete_knowledge_link`)
    # 에서 처리된다. KG update 는 메타데이터만 수정하면 된다.

    kg = KnowledgeGraphs.update_kg_by_id(id=id, form_data=form_data)
    if kg:
        return KnowledgeGraphResponse(**kg.model_dump())

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=ERROR_MESSAGES.DEFAULT("Failed to update knowledge graph"),
    )


async def _cleanup_kg_index(app, kg_id: str) -> None:
    """삭제된 KG의 검색 인덱스 정리 (백그라운드, graceful)."""
    from extension_modules.knowledge_graph import KGNodeIndexService

    try:
        await KGNodeIndexService(app).delete_by_kg(kg_id)
    except Exception as e:
        log.exception(f"KG index cleanup failed for {kg_id}: {e}")


@router.delete("/{id}/delete", response_model=bool)
async def delete_knowledge_graph_by_id(
    id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    user=Depends(get_verified_user),
):
    kg = KnowledgeGraphs.get_kg_by_id(id=id)
    _require_kg_write(kg, user, request)

    result = KnowledgeGraphs.delete_kg_by_id(id=id)
    if result:
        # AGE 그래프 삭제 (AGE 미설치 시 graceful no-op)
        try:
            from extension_modules.knowledge_graph.age_service import AGEService

            age_svc = AGEService(id)
            if age_svc.graph_exists():
                age_svc.drop_graph()
        except Exception as e:
            log.warning(f"AGE graph cleanup failed for {id}: {e}")
        # 백그라운드로 검색 인덱스 정리 (search engine 미설정 시 graceful no-op)
        background_tasks.add_task(_cleanup_kg_index, request.app, id)
        AuditLogger.log_delete(
            resource_type="knowledge_graph",
            resource_id=id,
            data=kg.model_dump() if kg else {},
            resource_name=kg.name if kg else id,
        )
    return result


############################
# Sync
############################


@router.post("/{id}/sync")
async def sync_knowledge_graph(
    id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    user=Depends(get_verified_user),
):
    """KG 의 모든 knowledge_link 를 각각 link sync 로 트리거 (전체 동기화).

    엔티티 동기화 LLM 은 KG 상단의 `options.llm_model_id` 단일 소스를 쓴다.
    (엣지 카탈로그 "Suggest from LLM" 은 `link.config.recommend_model_id` 로
    별개 경로 — 이 함수와 무관.) 모델이 설정되어 있지 않으면 400.

    각 link 마다 독립적인 sync job 이 생성돼 병렬 실행되며, 응답에는 생성된
    job_id 목록을 반환한다.
    """
    kg = KnowledgeGraphs.get_kg_by_id(id=id)
    _require_kg_write(kg, user, request)

    from extension_modules.utils.llm import (
        get_model_config_from_app,
        model_config_has_credentials,
    )

    options = (kg.data or {}).get("options") or {}
    kg_default_model = options.get("llm_model_id")

    links = KnowledgeGraphs.get_knowledge_links(id) or []
    syncable = [link for link in links if link.glossary_id and link.knowledge_ids]
    if not syncable:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("No knowledge links to sync."),
        )

    if not kg_default_model:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT(
                "LLM model is not configured. Select a model at the top of the KG page."
            ),
        )

    # 단일 모델 validation + pre-resolve (한 번만 — 모든 링크가 같은 모델 사용)
    cfg = get_model_config_from_app(request.app, kg_default_model)
    if not cfg:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT(
                f"Model '{kg_default_model}' is not registered."
            ),
        )
    if not model_config_has_credentials(cfg):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT(
                f"Model '{kg_default_model}' has no credentials configured"
            ),
        )

    link_payloads: list[dict] = [
        {"link": link, "model_id": kg_default_model, "pre_resolved": cfg}
        for link in syncable
    ]

    # 각 link 별로 link sync task 를 publish (sync_knowledge_link 와 동일 흐름)
    from extension_modules.knowledge_graph.source_sync_worker import (
        _publish_or_inline,
    )

    job_ids: list[str] = []
    for entry in link_payloads:
        link = entry["link"]
        model_id = entry["model_id"]
        pre_resolved = entry["pre_resolved"]

        link_job = KnowledgeGraphs.start_job(
            kg_id=id,
            user_id=user.id,
            kind=JobKind.GLOSSARY_SYNC,
            target_id=link.id,
            params={"link_id": link.id, "glossary_id": link.glossary_id},
            progress_total=1,
            progress_label="Queued",
        )
        link_job_id = link_job.id if link_job else None
        if link_job_id:
            job_ids.append(link_job_id)

        payload = {
            "kg_id": id,
            "link_id": link.id,
            "user_id": user.id,
            "job_id": link_job_id,
            "pre_resolved_model_config": pre_resolved,
            "model_id": model_id,
        }
        await _publish_or_inline(
            request.app,
            "kg_link_sync",
            payload,
            task_id=link_job_id or f"sync_all:{link.id}",
        )

    return {
        "status": True,
        "message": f"Full sync started — {len(job_ids)} link(s) queued",
        "job_ids": job_ids,
    }


############################
# Nodes
############################


class KGNodesPage(BaseModel):
    items: list[KGNodeModel]
    total: int
    limit: int
    offset: int


@router.get("/{id}/nodes", response_model=KGNodesPage)
async def get_kg_nodes(
    id: str,
    request: Request,
    node_type: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    user=Depends(get_verified_user),
):
    """KG 노드 페이징 — node_type / q (라벨 LIKE) 서버 사이드 필터.

    응답에 `total` 을 포함해 클라이언트 페이지네이션 UI 가 정확한 페이지 수를
    계산할 수 있게 한다. `total` 은 동일 필터 조건으로 카운트된다.
    """
    kg = KnowledgeGraphs.get_kg_by_id(id=id)
    _require_kg_read(kg, user, request)

    # max_limit 강제 — DoS 방지
    limit = min(max(limit, 1), 10000)
    offset = max(offset, 0)

    items = KnowledgeGraphs.get_nodes(
        kg_id=id,
        node_type=node_type,
        q=q,
        limit=limit,
        offset=offset,
    )
    total = KnowledgeGraphs.count_nodes(kg_id=id, node_type=node_type, q=q)
    return KGNodesPage(items=items, total=total, limit=limit, offset=offset)


class KGEdgesPage(BaseModel):
    items: list[KGEdgeModel]
    total: int
    limit: int
    offset: int


@router.get("/{id}/edge-types")
async def list_kg_edge_types(
    id: str,
    request: Request,
    user=Depends(get_verified_user),
):
    """KG 에 존재하는 edge_type 목록 (distinct + 사용 빈도)."""
    kg = KnowledgeGraphs.get_kg_by_id(id=id)
    _require_kg_read(kg, user, request)
    pairs = KnowledgeGraphs.get_distinct_edge_types(id)
    return {"items": [{"edge_type": t, "count": c} for t, c in pairs]}


############################
# Per-link edge type catalog
############################


class EdgeTypeCatalogItem(BaseModel):
    key: str
    display_name: Optional[str] = None
    description: Optional[str] = ""
    examples: Optional[list[str]] = None
    source: Optional[str] = None
    recommendation_reason: Optional[str] = None
    category: Optional[str] = None
    src_category: Optional[str] = None
    dst_category: Optional[str] = None


class EdgeTypeCatalogPutForm(BaseModel):
    items: list[EdgeTypeCatalogItem]
    locked: bool = False
    recommend_model_id: Optional[str] = None


class ExtraPreserveItem(BaseModel):
    """LLM 에게 '이미 존재하므로 변형도 제안 금지' 로 알릴 추가 항목.

    주로 프론트엔드 seed(기본 엣지 타입)를 recommend 호출 시 함께 보내서
    LLM 이 의미상 변형을 제안하지 않도록 한다.
    """

    key: str
    display_name: Optional[str] = None
    description: Optional[str] = None


class EdgeTypeRecommendForm(BaseModel):
    model_id: Optional[str] = None
    max_candidates: Optional[int] = 12
    extra_preserve: Optional[list[ExtraPreserveItem]] = None


class EdgeTypeAutoGenerateForm(BaseModel):
    model_id: Optional[str] = None
    max_candidates: Optional[int] = 12
    replace_existing: Optional[bool] = False
    locked: Optional[bool] = None
    extra_preserve: Optional[list[ExtraPreserveItem]] = None


def _resolve_link_or_404(kg_id: str, link_id: str):
    link = KnowledgeGraphs.get_knowledge_link_by_id(link_id)
    if not link or link.kg_id != kg_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )
    return link


@router.get("/{id}/links/{link_id}/edge-types/catalog")
async def get_kg_link_edge_type_catalog(
    id: str,
    link_id: str,
    request: Request,
    user=Depends(get_verified_user),
):
    """링크 단위 엣지 타입 카탈로그 + locked 플래그 조회."""
    kg = KnowledgeGraphs.get_kg_by_id(id=id)
    _require_kg_read(kg, user, request)
    _resolve_link_or_404(id, link_id)
    return KnowledgeGraphs.get_link_edge_type_catalog(link_id)


@router.put("/{id}/links/{link_id}/edge-types/catalog")
async def put_kg_link_edge_type_catalog(
    id: str,
    link_id: str,
    request: Request,
    form_data: EdgeTypeCatalogPutForm,
    user=Depends(get_verified_user),
):
    """링크 단위 엣지 타입 카탈로그 전체 교체."""
    kg = KnowledgeGraphs.get_kg_by_id(id=id)
    _require_kg_write(kg, user, request)
    _resolve_link_or_404(id, link_id)
    items_payload = [item.model_dump(exclude_none=False) for item in form_data.items]
    result = KnowledgeGraphs.replace_link_edge_type_catalog(
        link_id=link_id,
        items=items_payload,
        locked=form_data.locked,
        recommend_model_id=form_data.recommend_model_id,
    )
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("Failed to save edge type catalog"),
        )
    return result


class NodeFilterSlot(BaseModel):
    kb_id: str
    slot: str


class NodeFilterPutForm(BaseModel):
    slots: list[NodeFilterSlot]


@router.get("/{id}/links/{link_id}/node-filters")
async def get_kg_link_node_filters(
    id: str,
    link_id: str,
    request: Request,
    user=Depends(get_verified_user),
):
    """링크에서 노드로 추출할 KB 필터 slot 목록 조회."""
    kg = KnowledgeGraphs.get_kg_by_id(id=id)
    _require_kg_read(kg, user, request)
    _resolve_link_or_404(id, link_id)
    return KnowledgeGraphs.get_link_node_filters(link_id)


@router.put("/{id}/links/{link_id}/node-filters")
async def put_kg_link_node_filters(
    id: str,
    link_id: str,
    request: Request,
    form_data: NodeFilterPutForm,
    user=Depends(get_verified_user),
):
    """링크의 노드 추출용 KB 필터 slot 목록 교체 + 엣지 이름 캐시 생성.

    각 slot 에 대해 엣지 이름을 결정:
      1. filter label 을 ASCII snake 로 직접 변환 가능하면 즉시 사용
      2. 한글 등으로 실패한 것만 LLM 배치 호출로 영어 snake 이름 제안
    결과는 ``config.filter_edge_names: {"kb_id::slot": "has_xxx"}`` 에 캐시.
    """
    from extension_modules.knowledge_graph.sync.kb_sync import (
        _filter_edge_type,
        _label_to_snake,
        suggest_filter_edge_names,
    )
    from open_webui.models.knowledge import Knowledges

    kg = KnowledgeGraphs.get_kg_by_id(id=id)
    _require_kg_write(kg, user, request)
    _resolve_link_or_404(id, link_id)
    payload = [s.model_dump() for s in form_data.slots]

    # KB 별 filter_schema 를 한 번씩 로드 → slot → (label, type, allowed_values)
    kb_ids = {p["kb_id"] for p in payload if p.get("kb_id")}
    kb_filter_info: dict[str, dict[str, dict]] = {}
    for kb_id in kb_ids:
        kb = Knowledges.get_knowledge_by_id(kb_id)
        if not kb:
            continue
        schema = (kb.meta or {}).get("filter_schema") or []
        by_slot: dict[str, dict] = {}
        for f in schema:
            if not isinstance(f, dict):
                continue
            sl = f.get("slot")
            if not sl:
                continue
            by_slot[sl] = f
        kb_filter_info[kb_id] = by_slot

    edge_names: dict[str, str] = {}
    llm_targets: list[dict] = []  # LLM 번역이 필요한 slot 들
    for p in payload:
        kb_id = p.get("kb_id")
        slot = p.get("slot")
        if not kb_id or not slot:
            continue
        finfo = kb_filter_info.get(kb_id, {}).get(slot) or {}
        label = finfo.get("label")
        key = f"{kb_id}::{slot}"
        snake = _label_to_snake(label)
        if snake:
            edge_names[key] = f"has_{snake}"
        else:
            # 규칙으로 안 되면 LLM 배치 대상에 추가
            llm_targets.append(
                {
                    "kb_id": kb_id,
                    "slot": slot,
                    "label": label or slot,
                    "type": finfo.get("type"),
                    "allowed_values": finfo.get("allowed_values") or [],
                }
            )

    # LLM 배치 호출 (필요한 것만)
    if llm_targets:
        model_id = ((kg.data or {}).get("options") or {}).get("llm_model_id")
        try:
            # slot 단위로 전달 (kb_id 는 응답에 필요 없음, 반환된 slot 을 kb_id 와 함께 key 로 복원)
            # 같은 slot 이름이 다른 KB 에 있을 경우 대비해 unique 임시 키 부여
            items_for_llm = []
            reverse_map: dict[
                str, tuple[str, str]
            ] = {}  # unique_slot_id → (kb_id, real_slot)
            for i, t in enumerate(llm_targets):
                uid = f"{t['slot']}__{i}"
                reverse_map[uid] = (t["kb_id"], t["slot"])
                items_for_llm.append(
                    {
                        "slot": uid,
                        "label": t["label"],
                        "type": t.get("type"),
                        "allowed_values": t.get("allowed_values") or [],
                    }
                )
            suggestions = await suggest_filter_edge_names(
                request.app, model_id, items_for_llm
            )
            for uid, name in suggestions.items():
                if uid in reverse_map:
                    kb_id, real_slot = reverse_map[uid]
                    edge_names[f"{kb_id}::{real_slot}"] = name
        except Exception as e:
            log.warning(f"[put node-filters] LLM name suggest failed: {e}")

        # LLM 실패/미반환 항목은 규칙 기반 fallback (slot suffix)
        for t in llm_targets:
            key = f"{t['kb_id']}::{t['slot']}"
            if key not in edge_names:
                fb = _filter_edge_type(t["slot"], None)
                if fb:
                    edge_names[key] = fb

    result = KnowledgeGraphs.replace_link_node_filters(
        link_id=link_id, slots=payload, edge_names=edge_names
    )
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("Failed to save node filter selection"),
        )
    return result


@router.post("/{id}/links/{link_id}/edge-types/recommend")
async def recommend_kg_link_edge_types(
    id: str,
    link_id: str,
    request: Request,
    form_data: EdgeTypeRecommendForm,
    user=Depends(get_verified_user),
):
    """링크의 글로서리 + KB 만 컨텍스트로 LLM 에게 엣지 타입 후보를 받는다.

    DB 에 기록하지 않고 후보만 반환. 사용자가 모달에서 편집 후 PUT 으로 저장.
    """
    kg = KnowledgeGraphs.get_kg_by_id(id=id)
    _require_kg_write(kg, user, request)
    link = _resolve_link_or_404(id, link_id)
    _require_link_glossary_read(link, user)

    from extension_modules.knowledge_graph.edge_type_recommender import (
        recommend_edge_types_for_link,
    )

    extra_preserve_dicts = (
        [p.model_dump(exclude_none=False) for p in (form_data.extra_preserve or [])]
        if form_data.extra_preserve
        else None
    )
    try:
        candidates = await recommend_edge_types_for_link(
            request=request,
            kg_id=id,
            link_id=link_id,
            user_id=user.id,
            model_id=form_data.model_id,
            max_candidates=int(form_data.max_candidates or 12),
            extra_preserve=extra_preserve_dicts,
        )
    except Exception as e:
        log.exception(f"[kg] link edge type recommend failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT(f"엣지 타입 추천에 실패했습니다: {e}"),
        )
    return {"candidates": candidates}


@router.post("/{id}/links/{link_id}/edge-types/auto-generate")
async def auto_generate_kg_link_edge_types(
    id: str,
    link_id: str,
    request: Request,
    form_data: EdgeTypeAutoGenerateForm,
    user=Depends(get_verified_user),
):
    """LLM 추천 결과를 그대로 링크 카탈로그에 반영 (one-click 자동 모드).

    ``replace_existing=False`` 이면 기존 manual 항목은 보존하고 LLM 항목만 갱신.
    ``locked`` 가 None 이면 현재 값 유지.
    """
    kg = KnowledgeGraphs.get_kg_by_id(id=id)
    _require_kg_write(kg, user, request)
    link = _resolve_link_or_404(id, link_id)
    _require_link_glossary_read(link, user)

    from extension_modules.knowledge_graph.edge_type_recommender import (
        recommend_edge_types_for_link,
    )

    extra_preserve_dicts = (
        [p.model_dump(exclude_none=False) for p in (form_data.extra_preserve or [])]
        if form_data.extra_preserve
        else None
    )
    try:
        candidates = await recommend_edge_types_for_link(
            request=request,
            kg_id=id,
            link_id=link_id,
            user_id=user.id,
            model_id=form_data.model_id,
            max_candidates=int(form_data.max_candidates or 12),
            extra_preserve=extra_preserve_dicts,
        )
    except Exception as e:
        log.exception(f"[kg] link edge type auto-generate failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT(f"엣지 타입 자동 생성에 실패했습니다: {e}"),
        )

    current = KnowledgeGraphs.get_link_edge_type_catalog(link_id)
    existing_items = current.get("items") or []
    existing_locked = bool(current.get("locked"))

    def _cand_to_item(c: dict) -> dict:
        return {
            "key": c.get("key"),
            "display_name": c.get("display_name") or c.get("key"),
            "description": c.get("description") or "",
            "examples": c.get("examples") or [],
            "source": "llm",
            "recommendation_reason": c.get("recommendation_reason"),
            "category": c.get("category"),
            "src_category": c.get("src_category"),
            "dst_category": c.get("dst_category"),
        }

    if form_data.replace_existing:
        merged: dict[str, dict] = {}
        for it in existing_items:
            if (it.get("source") or "") == "manual":
                merged[it["key"]] = it
        for c in candidates:
            key = c.get("key")
            if not key:
                continue
            merged[key] = _cand_to_item(c)
    else:
        merged = {it["key"]: it for it in existing_items}
        for c in candidates:
            key = c.get("key")
            if not key or key in merged:
                continue
            merged[key] = _cand_to_item(c)

    new_locked = existing_locked if form_data.locked is None else bool(form_data.locked)
    result = KnowledgeGraphs.replace_link_edge_type_catalog(
        link_id=link_id, items=list(merged.values()), locked=new_locked
    )
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("Failed to persist auto-generated catalog"),
        )
    return result


@router.get("/{id}/edges", response_model=KGEdgesPage)
async def list_kg_edges(
    id: str,
    request: Request,
    edge_type: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    user=Depends(get_verified_user),
):
    """KG 엣지 페이징 — edge_type 필터 + q (src/dst 라벨 또는 edge_type 부분 매치)."""
    kg = KnowledgeGraphs.get_kg_by_id(id=id)
    _require_kg_read(kg, user, request)

    limit = min(max(limit, 1), 10000)
    offset = max(offset, 0)

    items = KnowledgeGraphs.get_edges_paginated(
        kg_id=id,
        edge_type=edge_type,
        q=q,
        limit=limit,
        offset=offset,
    )
    total = KnowledgeGraphs.count_edges_filtered(kg_id=id, edge_type=edge_type, q=q)
    return KGEdgesPage(items=items, total=total, limit=limit, offset=offset)


############################
# Node CRUD (Phase 1)
############################


class NodeUpdateForm(BaseModel):
    label: Optional[str] = None
    properties: Optional[dict] = None


class NodeMergeForm(BaseModel):
    src_id: str  # 사라질 노드
    dst_id: str  # 남을 노드


@router.post("/{id}/nodes/{node_id}/update", response_model=Optional[KGNodeModel])
async def update_kg_node(
    id: str,
    node_id: str,
    request: Request,
    form_data: NodeUpdateForm,
    user=Depends(get_verified_user),
):
    """노드 라벨/properties 수정."""
    kg = KnowledgeGraphs.get_kg_by_id(id=id)
    _require_kg_write(kg, user, request)

    node = KnowledgeGraphs.get_node_by_id(node_id)
    if not node or node.kg_id != id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    new_label = form_data.label if form_data.label is not None else node.label
    new_props = (
        form_data.properties if form_data.properties is not None else node.properties
    )

    updated = KnowledgeGraphs.upsert_node(
        kg_id=id,
        user_id=node.user_id,
        node_id=node_id,
        node_type=node.node_type,
        label=new_label,
        properties=new_props,
        source_ref=node.source_ref,
    )
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("Failed to update node"),
        )

    # AGE dual-write
    from extension_modules.knowledge_graph.sync._age_helpers import (
        age_upsert_node,
        get_age_service,
    )

    age = get_age_service(id)
    if age:
        age_upsert_node(age, node.node_type, node_id, new_label, new_props, kg_id=id)

    return updated


@router.delete("/{id}/nodes/{node_id}", response_model=bool)
async def delete_kg_node(
    id: str,
    node_id: str,
    request: Request,
    user=Depends(get_verified_user),
):
    """개별 노드 삭제 (관련 엣지도 함께 삭제)."""
    kg = KnowledgeGraphs.get_kg_by_id(id=id)
    _require_kg_write(kg, user, request)

    node = KnowledgeGraphs.get_node_by_id(node_id)
    if not node or node.kg_id != id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    result = KnowledgeGraphs.delete_node_by_id(node_id)

    # AGE dual-write: 해당 노드 + 연결 엣지 삭제
    if result:
        from extension_modules.knowledge_graph.sync._age_helpers import (
            get_age_service,
        )

        age = get_age_service(id)
        if age:
            try:
                age.delete_nodes_by_property(node.node_type, "node_id", node_id)
            except Exception as e:
                log.warning(f"AGE delete_node failed ({node_id}): {e}")

    return result


@router.post("/{id}/nodes/merge", response_model=Optional[KGNodeModel])
async def merge_kg_nodes(
    id: str,
    request: Request,
    form_data: NodeMergeForm,
    user=Depends(get_verified_user),
):
    """두 노드를 병합 — src의 모든 엣지를 dst로 옮기고 src를 삭제.

    사용 시나리오: 같은 엔티티가 정규화 미스로 두 개 노드로 생성됐을 때
    수동으로 합치기.
    """
    from open_webui.models.knowledge_graph import KGEdge, make_edge_id

    kg = KnowledgeGraphs.get_kg_by_id(id=id)
    _require_kg_write(kg, user, request)

    if form_data.src_id == form_data.dst_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("src and dst must differ"),
        )

    src = KnowledgeGraphs.get_node_by_id(form_data.src_id)
    dst = KnowledgeGraphs.get_node_by_id(form_data.dst_id)
    if not src or src.kg_id != id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("src node not found in this KG"),
        )
    if not dst or dst.kg_id != id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("dst node not found in this KG"),
        )

    # src의 모든 엣지를 dst로 redirect
    from open_webui.internal.db import get_db
    from sqlalchemy import or_

    with get_db() as db:
        edges = (
            db.query(KGEdge)
            .filter(
                KGEdge.kg_id == id,
                or_(
                    KGEdge.src_id == form_data.src_id,
                    KGEdge.dst_id == form_data.src_id,
                ),
            )
            .all()
        )
        for edge in edges:
            new_src = (
                form_data.dst_id if edge.src_id == form_data.src_id else edge.src_id
            )
            new_dst = (
                form_data.dst_id if edge.dst_id == form_data.src_id else edge.dst_id
            )
            if new_src == new_dst:
                # self-loop → 삭제
                db.delete(edge)
                continue
            new_edge_id = make_edge_id(id, new_src, new_dst, edge.edge_type)
            # 같은 (src, dst, type) 조합의 엣지가 이미 있으면 중복 → 기존 것 삭제
            existing = db.query(KGEdge).filter_by(id=new_edge_id).first()
            if existing and existing.id != edge.id:
                db.delete(edge)
                continue
            edge.id = new_edge_id
            edge.src_id = new_src
            edge.dst_id = new_dst
        db.commit()

    # src 삭제
    KnowledgeGraphs.delete_node_by_id(form_data.src_id)

    # AGE dual-write: src 노드 삭제 + dst 노드로 엣지 재연결
    # AGE MERGE는 복잡하므로, src 삭제 후 전체 엣지를 재구성
    from extension_modules.knowledge_graph.sync._age_helpers import (
        age_upsert_edge,
        get_age_service,
    )

    age = get_age_service(id)
    if age:
        try:
            # src 노드 삭제 (DETACH DELETE로 연결 엣지도 함께 제거)
            age.delete_nodes_by_property(src.node_type, "node_id", form_data.src_id)
            # dst 노드의 현재 SQL 엣지를 AGE에 반영
            from open_webui.models.knowledge_graph import KGEdge

            with get_db() as db:
                dst_edges = (
                    db.query(KGEdge)
                    .filter(
                        KGEdge.kg_id == id,
                        or_(
                            KGEdge.src_id == form_data.dst_id,
                            KGEdge.dst_id == form_data.dst_id,
                        ),
                    )
                    .all()
                )
                for e in dst_edges:
                    s = KnowledgeGraphs.get_node_by_id(e.src_id)
                    d = KnowledgeGraphs.get_node_by_id(e.dst_id)
                    if s and d:
                        age_upsert_edge(
                            age,
                            e.edge_type,
                            s.node_type,
                            e.src_id,
                            d.node_type,
                            e.dst_id,
                            source=e.source or EdgeSource.MANUAL,
                            properties=e.properties,
                            kg_id=id,
                        )
        except Exception as e:
            log.warning(f"AGE merge_nodes sync failed: {e}")

    # dst 노드 최신 상태 반환
    return KnowledgeGraphs.get_node_by_id(form_data.dst_id)


@router.get("/{id}/graph")
async def get_kg_graph(
    id: str,
    request: Request,
    max_nodes: int = 500,
    offset: int = 0,
    node_types: Optional[str] = None,  # comma-separated
    edge_types: Optional[str] = None,  # comma-separated
    fields: Optional[str] = None,  # comma-separated property fields to include
    priority_node_type: Optional[str] = None,
    user=Depends(get_verified_user),
):
    """시각화용 단일 fetch — 노드 + 엣지를 한 번에 반환.

    `max_nodes` 제한으로 매우 큰 KG에서도 안전. 노드는 label 알파벳 순으로
    상위 N개를 fetch하고, 엣지는 그 노드들에 연결된 것만 반환한다.

    `offset`으로 페이지네이션이 가능하고, `fields`로 반환할 property
    필드를 제한하여 페이로드를 줄일 수 있다.

    `priority_node_type` 가 주어지면 그 타입의 노드를 max_nodes 한도 내에서
    *전부* 먼저 가져오고(anchor), 그 anchor 의 1-hop 이웃 노드들로 남은
    한도를 채운다. 라벨 알파벳 순 truncation 으로 특정 타입(예: TABLE) 이
    많은 TERM 노드에 묻혀 첫 페이지에서 누락되던 문제를 피하는 용도.

    Response shape:
    {
      "nodes": [{"id", "label", "node_type", "properties"}],
      "edges": [{"id", "src_id", "dst_id", "edge_type", "weight", "properties"}],
      "truncated": bool,
      "total_nodes": int,
      "total_edges": int,
      "offset": int,
      "has_next": bool
    }
    """
    kg = KnowledgeGraphs.get_kg_by_id(id=id)
    _require_kg_read(kg, user, request)

    if max_nodes < 1 or max_nodes > 5000:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("max_nodes must be between 1 and 5000"),
        )

    node_type_list: Optional[list[str]] = None
    if node_types:
        node_type_list = [t.strip() for t in node_types.split(",") if t.strip()]
    edge_type_list: Optional[list[str]] = None
    if edge_types:
        edge_type_list = [t.strip() for t in edge_types.split(",") if t.strip()]

    # property field 필터 준비
    field_set: Optional[set[str]] = None
    if fields:
        field_set = {f.strip() for f in fields.split(",") if f.strip()}

    # stats 캐시에서 total count 를 가져온다 (단, 캐시 미존재 시 DB count).
    # 이전에는 count_nodes + count_edges 2회 추가 쿼리가 필요했으나,
    # stats 캐시가 있으면 0-query 로 줄어든다.
    kg_stats = (kg.data or {}).get("stats") or {}
    total_nodes = int(kg_stats.get("node_count", 0))
    total_edges = int(kg_stats.get("edge_count", 0))
    if total_nodes == 0:
        total_nodes = KnowledgeGraphs.count_nodes(id)
    if total_edges == 0:
        total_edges = KnowledgeGraphs.count_edges(id)

    nodes: list = []
    if priority_node_type:
        # 1) priority 타입 노드를 anchor 로 fetch — anchor 가 budget 을 전부
        #    잡아먹으면 1-hop 이웃이 0개가 돼서 그래프가 외톨이만 보이는 문제
        #    가 있어 anchor 를 max_nodes 의 70% 로 cap 한다. 나머지 30% 는
        #    neighbor 용으로 남겨둔다 (최소 1개는 보장).
        anchor_limit = max(1, int(max_nodes * 0.7))
        anchor_nodes = KnowledgeGraphs.get_nodes(
            kg_id=id, node_type=priority_node_type, limit=anchor_limit
        )
        nodes.extend(anchor_nodes)
        anchor_ids = {n.id for n in anchor_nodes}

        # 2) anchor 와 1-hop 으로 연결된 엣지의 반대편 노드들을 수집
        budget = max(0, max_nodes - len(anchor_ids))
        if anchor_ids and budget > 0:
            touching = KnowledgeGraphs.get_edges_touching_nodes(
                kg_id=id, node_ids=anchor_ids, edge_types=edge_type_list
            )
            neighbor_ids: list[str] = []
            seen = set(anchor_ids)
            for e in touching:
                for nid in (e.src_id, e.dst_id):
                    if nid in seen:
                        continue
                    seen.add(nid)
                    neighbor_ids.append(nid)
                    if len(neighbor_ids) >= budget:
                        break
                if len(neighbor_ids) >= budget:
                    break
            if neighbor_ids:
                neighbors = KnowledgeGraphs.get_nodes_by_ids(
                    kg_id=id, node_ids=neighbor_ids, limit=budget
                )
                nodes.extend(neighbors)
    elif node_type_list:
        # node_type 필터별 fetch (기존 동작)
        per_type_limit = max(1, max_nodes // len(node_type_list))
        for nt in node_type_list:
            nodes.extend(
                KnowledgeGraphs.get_nodes(
                    kg_id=id, node_type=nt, limit=per_type_limit, offset=offset
                )
            )
    else:
        nodes = KnowledgeGraphs.get_nodes(kg_id=id, limit=max_nodes, offset=offset)

    node_id_set = {n.id for n in nodes}

    # edges — SQL 에서 양 endpoint IN 필터로 정확한 subset 만 가져온다.
    # 이전에는 전체 엣지를 5× over-fetch 후 Python 필터를 썼음.
    edges = KnowledgeGraphs.get_edges_for_node_set(
        kg_id=id, node_ids=node_id_set, edge_types=edge_type_list
    )

    graph_nodes = [
        {
            "id": n.id,
            "label": n.label,
            "node_type": n.node_type,
            "properties": n.properties,
        }
        for n in nodes
    ]

    # property field 필터 적용
    if field_set:
        for node in graph_nodes:
            if node.get("properties"):
                node["properties"] = {
                    k: v for k, v in node["properties"].items() if k in field_set
                }

    graph_edges = [
        {
            "id": e.id,
            "src_id": e.src_id,
            "dst_id": e.dst_id,
            "edge_type": e.edge_type,
            "weight": e.weight,
            "properties": e.properties,
        }
        for e in edges
    ]

    truncated = total_nodes > (offset + len(nodes))

    return {
        "nodes": graph_nodes,
        "edges": graph_edges,
        "truncated": truncated,
        "total_nodes": total_nodes,
        "total_edges": total_edges,
        "offset": offset,
        "has_next": offset + max_nodes < total_nodes,
    }


@router.get("/{id}/stats")
async def get_kg_stats(
    id: str,
    request: Request,
    user=Depends(get_verified_user),
):
    kg = KnowledgeGraphs.get_kg_by_id(id=id)
    _require_kg_read(kg, user, request)

    return {
        "node_count": KnowledgeGraphs.count_nodes(id),
        "edge_count": KnowledgeGraphs.count_edges(id),
        "stats": (kg.data or {}).get("stats") or {},
    }


############################
# Traversal
############################


@router.get("/{id}/neighbors", response_model=list[KGNeighborhoodNode])
async def get_kg_neighbors(
    id: str,
    request: Request,
    node_id: str,
    hops: int = 1,
    edge_types: Optional[str] = None,  # comma-separated
    limit: int = 200,
    user=Depends(get_verified_user),
):
    kg = KnowledgeGraphs.get_kg_by_id(id=id)
    _require_kg_read(kg, user, request)

    if hops < 1 or hops > 5:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("hops must be between 1 and 5"),
        )

    edge_type_list: Optional[list[str]] = None
    if edge_types:
        edge_type_list = [t.strip() for t in edge_types.split(",") if t.strip()]

    return KnowledgeGraphs.get_neighbors(
        kg_id=id,
        node_id=node_id,
        hops=hops,
        edge_types=edge_type_list,
        limit=limit,
    )


############################
# Semantic Search
############################


@router.get("/{id}/search")
async def search_kg_nodes(
    id: str,
    request: Request,
    q: str,
    top_k: int = 10,
    node_types: Optional[str] = None,  # comma-separated: term,concept,table,column
    user=Depends(get_verified_user),
):
    """KG 노드 시맨틱 검색.

    검색 엔진(`search_engine` 추상화)이 설정돼 있어야 동작.
    미설정 시 빈 리스트 + `available=false`.
    """
    kg = KnowledgeGraphs.get_kg_by_id(id=id)
    _require_kg_read(kg, user, request)

    if not q or not q.strip():
        return {"available": True, "results": []}

    if top_k < 1 or top_k > 100:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("top_k must be between 1 and 100"),
        )

    type_list: Optional[list[str]] = None
    if node_types:
        type_list = [t.strip() for t in node_types.split(",") if t.strip()]

    from extension_modules.knowledge_graph import KGNodeIndexService

    service = KGNodeIndexService(request.app)
    # 검색 엔진 미설정 여부를 응답에 포함 (UI가 안내 문구 표시)
    available = service._build_engine() is not None  # noqa: SLF001
    if not available:
        return {"available": False, "results": []}

    results = await service.search(
        kg_id=id,
        query=q.strip(),
        top_k=top_k,
        node_types=type_list,
    )
    return {"available": True, "results": results}


############################
# Manual Edge Curation (mappings)
############################


_ALLOWED_MANUAL_EDGE_TYPES = {
    EdgeType.MAPS_TO,
    EdgeType.RELATED_TO,
    EdgeType.BROADER_THAN,
    EdgeType.NARROWER_THAN,
    EdgeType.DEFINED_AS,
    EdgeType.SYNONYM_OF,
}


class EdgeCreateForm(BaseModel):
    src_id: str
    dst_id: str
    edge_type: str
    weight: Optional[float] = None
    properties: Optional[dict] = None


def _require_workspace_permission(request: Request, user, level: str) -> None:
    """`workspace.knowledge_graphs` 권한을 검증.

    리스트/생성 엔드포인트의 워크스페이스 권한 체크와 일관된 동작을
    상세 read/write 엔드포인트에도 적용하기 위해 별도 헬퍼로 분리.

    `access_control=None`(public) KG는 has_access가 항상 True를 반환하기
    때문에, 이 헬퍼가 없으면 워크스페이스 권한이 없는 사용자도 LIST는 막혀도
    상세는 통과되는 권한 우회가 발생한다.
    """
    if user.role == "admin":
        return
    if not has_permission_min_level(
        user.id,
        "workspace.knowledge_graphs",
        level,
        request.app.state.config.USER_PERMISSIONS,
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )


def _require_kg_write(kg, user, request: Optional[Request] = None) -> None:
    if request is not None:
        _require_workspace_permission(request, user, "write")
    if not kg:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )
    if (
        kg.user_id != user.id
        and not has_access(user.id, "write", kg.access_control)
        and user.role != "admin"
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )


def _require_kg_read(kg, user, request: Optional[Request] = None) -> None:
    if request is not None:
        _require_workspace_permission(request, user, "read")
    if not kg or not (
        user.role == "admin"
        or kg.user_id == user.id
        or has_access(user.id, "read", kg.access_control)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )


def _require_link_glossary_read(link, user) -> None:
    """링크의 glossary 가 존재하면 호출자가 그 glossary read 권한이 있는지 확인.

    KG link sync / edge-type recommend 등 glossary entries 를 LLM 에 노출하는
    경로에서 cross-resource 권한 누수를 차단한다 (User A 의 private glossary 가
    KG 링크에 묶여 있을 때 User B 가 KG write 만으로 entries 를 보는 시나리오).
    """
    if not link or not getattr(link, "glossary_id", None):
        return
    if user.role == "admin":
        return
    from open_webui.models.glossary import Glossaries

    glossary = Glossaries.get_glossary_by_id(link.glossary_id)
    if not glossary:
        # Orphan link (glossary 삭제됨) — silent bypass 대신 404 로 끊어 정합성 유지.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )
    if glossary.user_id == user.id:
        return
    if not has_access(user.id, "read", glossary.access_control):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )


# Job params 안에 워커 전달용으로 들어가는 민감 정보를 응답 직전에 제거한다.
# pre_resolved_model_config 류는 model 자격증명(api_key, base_url)이 평문으로
# 들어있고 UI 측에서는 한 번도 사용되지 않는다. 통째로 제거하고, 혹시 추가될
# 다른 자격 키도 재귀적으로 마스킹한다.
_JOB_PARAM_DROP_KEYS = {
    "pre_resolved_model_config",
    "pre_resolved_kb_model_config",
}
_JOB_PARAM_MASK_KEYS = {
    "api_key",
    "apikey",
    "secret",
    "password",
    "token",
    "access_token",
    "refresh_token",
}


def _sanitize_job_params(value):
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if k in _JOB_PARAM_DROP_KEYS:
                continue
            if k in _JOB_PARAM_MASK_KEYS and isinstance(v, str) and v:
                out[k] = "***"
            else:
                out[k] = _sanitize_job_params(v)
        return out
    if isinstance(value, list):
        return [_sanitize_job_params(v) for v in value]
    return value


def _sanitize_job(job):
    """KGExtractJob (또는 동일 shape Pydantic model)을 in-place sanitize 후 반환."""
    if job is None:
        return job
    if hasattr(job, "params"):
        job.params = _sanitize_job_params(job.params)
    return job


@router.get("/{id}/mappings")
async def get_kg_mappings(
    id: str,
    request: Request,
    edge_type: Optional[str] = None,
    user=Depends(get_verified_user),
):
    """수동으로 만든 매핑 엣지 + 양 endpoint 노드 정보 반환.

    edge_type 미지정 시 manual 엣지 전체.
    """
    kg = KnowledgeGraphs.get_kg_by_id(id=id)
    _require_kg_read(kg, user, request)

    edge_types = [edge_type] if edge_type else None
    items = KnowledgeGraphs.get_manual_edges_with_nodes(kg_id=id, edge_types=edge_types)
    # Pydantic 모델을 dict로 변환
    return [
        {
            "edge": item["edge"].model_dump() if item["edge"] else None,
            "src_node": item["src_node"].model_dump() if item["src_node"] else None,
            "dst_node": item["dst_node"].model_dump() if item["dst_node"] else None,
        }
        for item in items
    ]


@router.post("/{id}/edges", response_model=Optional[KGEdgeModel])
async def create_kg_edge(
    id: str,
    request: Request,
    form_data: EdgeCreateForm,
    user=Depends(get_verified_user),
):
    """사용자가 직접 만드는 매핑/관계 엣지 (`source='manual'`).

    검증:
    - src/dst 노드가 이 KG에 존재해야 함
    - edge_type이 허용 목록에 있어야 함
    - src_id != dst_id
    """
    kg = KnowledgeGraphs.get_kg_by_id(id=id)
    _require_kg_write(kg, user, request)

    if form_data.edge_type not in _ALLOWED_MANUAL_EDGE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT(
                f"edge_type must be one of {sorted(_ALLOWED_MANUAL_EDGE_TYPES)}"
            ),
        )
    if form_data.src_id == form_data.dst_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("src_id and dst_id must differ"),
        )

    src = KnowledgeGraphs.get_node_by_id(form_data.src_id)
    dst = KnowledgeGraphs.get_node_by_id(form_data.dst_id)
    if not src or src.kg_id != id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("src node not found in this KG"),
        )
    if not dst or dst.kg_id != id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("dst node not found in this KG"),
        )

    edge = KnowledgeGraphs.upsert_edge(
        kg_id=id,
        user_id=user.id,
        src_id=form_data.src_id,
        dst_id=form_data.dst_id,
        edge_type=form_data.edge_type,
        source=EdgeSource.MANUAL,
        weight=form_data.weight,
        properties=form_data.properties,
    )
    if not edge:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("Failed to create edge"),
        )

    # AGE dual-write
    from extension_modules.knowledge_graph.sync._age_helpers import (
        age_upsert_edge,
        get_age_service,
    )

    age = get_age_service(id)
    if age:
        age_upsert_edge(
            age,
            form_data.edge_type,
            src.node_type,
            form_data.src_id,
            dst.node_type,
            form_data.dst_id,
            source=EdgeSource.MANUAL,
            properties=form_data.properties,
            kg_id=id,
        )

    return edge


@router.delete("/{id}/edges/{edge_id}", response_model=bool)
async def delete_kg_edge(
    id: str,
    edge_id: str,
    request: Request,
    user=Depends(get_verified_user),
):
    kg = KnowledgeGraphs.get_kg_by_id(id=id)
    _require_kg_write(kg, user, request)

    # AGE dual-write: 삭제 전에 엣지 정보 조회
    edge_obj = KnowledgeGraphs.get_edge_by_id(edge_id)

    result = KnowledgeGraphs.delete_edge_by_id(edge_id)

    if result and edge_obj and edge_obj.kg_id == id:
        from extension_modules.knowledge_graph.sync._age_helpers import (
            get_age_service,
        )

        age = get_age_service(id)
        if age:
            try:
                src_node = KnowledgeGraphs.get_node_by_id(edge_obj.src_id)
                dst_node = KnowledgeGraphs.get_node_by_id(edge_obj.dst_id)
                if src_node and dst_node:
                    age.execute_cypher(
                        f"MATCH (a:{src_node.node_type} {{node_id: '{edge_obj.src_id}'}})"
                        f"-[r:{edge_obj.edge_type}]->"
                        f"(b:{dst_node.node_type} {{node_id: '{edge_obj.dst_id}'}}) "
                        f"DELETE r RETURN count(r)"
                    )
            except Exception as e:
                log.warning(f"AGE delete_edge failed ({edge_id}): {e}")

    return result


############################
# Candidate Acceptance
############################


class CandidateAcceptForm(BaseModel):
    glossary_id: str
    term: Optional[str] = None  # 사용자가 final term 수정 가능
    description: Optional[str] = None
    category: Optional[str] = None
    filter_expr: Optional[str] = None  # maps_to 엣지 filter 오버라이드
    create_mapping: bool = True  # False면 용어집만 추가하고 maps_to는 안 만듦


############################
# KB Entity Extraction (Slice 7)
############################


class KbExtractForm(BaseModel):
    knowledge_id: Optional[str] = None  # None이면 KG에 attach된 모든 KB
    # cleanup_only=True면 model_id 없이도 OK
    model_id: Optional[str] = None
    # max_chunks=None: 미처리 청크 *전체* 처리. 값을 주면 1회 호출당 안전 캡.
    max_chunks: Optional[int] = None
    min_confidence: float = 0.6
    # True면 이번 KB의 processed_chunks 이력을 비우고 처음부터 다시 추출
    reset: bool = False
    # True면 LLM 호출 없이 drift cleanup만 수행 (KB에서 사라진 청크 정리)
    cleanup_only: bool = False


class KbExtractPreviewForm(BaseModel):
    """엔티티 추출 사전 조회 (LLM 호출 없이 pending 청크 수만 계산).

    버튼 클릭 전 사용자에게 예상 LLM 호출 횟수를 경고 다이얼로그로 노출하는 용도.

    범위 우선순위: ``knowledge_ids`` (다중) > ``knowledge_id`` (단일) > KG 에
    attach 된 모든 KB. 링크 sync 는 해당 링크의 ``knowledge_ids`` 를 넘기고,
    전체 sync 는 아무것도 안 넘겨서 KG 전역을 대상으로 한다.
    """

    knowledge_id: Optional[str] = None
    knowledge_ids: Optional[list[str]] = None
    max_chunks: Optional[int] = None
    reset: bool = False


def _load_kb_processed_chunks(kg_id: str, kb_id: str) -> set[str]:
    """Load processed chunk IDs from new table (with legacy JSON fallback)."""
    state = KnowledgeGraphs.get_extract_state(kg_id, kb_id)
    if state and state.processed_chunks:
        return set(state.processed_chunks)
    return set()


def _save_kb_processed_chunks(
    kg_id: str, kb_id: str, processed_ids: set[str], model_id: str
) -> None:
    """kg_extract_state 테이블에 처리 이력 저장 (atomic per-KB update)."""
    KnowledgeGraphs.upsert_extract_state(kg_id, kb_id, sorted(processed_ids), model_id)


async def _extract_kb_via_queue(
    app,
    kg_id: str,
    form: "KbExtractForm",
    user_id: str,
    knowledge_ids: list[str],
    pre_resolved_model_config: dict,
    job_id: str,
) -> None:
    """Redis queue 기반 fan-out 추출.

    각 청크를 `kg_kb_chunk` task로 publish해서 컨슈머가 max_retries=3으로
    병렬 처리한다.

    중요(경합 방지): job의 progress_total과 params는 task를 publish 하기 *전에*
    DB에 기록한다. 그렇지 않으면 빠른 worker가 첫 increment 만으로
    `try_claim_job_finalization` 의 조건을 만족시켜 producer가 progress_total을
    설정하기 전에 job이 finalize 되는 race가 발생한다.
    """
    from open_webui.models.knowledge_graph import NodeType
    from open_webui.retrieval.knowledge_service import SearchEngineKnowledge
    from open_webui.services.task_queue import TaskMessage

    queue = app.state.task_queue
    job_errors: list[str] = []
    # kb_id → list of (chunk_id, content)
    pending_per_kb: dict[str, list[tuple[str, str]]] = {}
    # kb_id → anchor labels snapshot
    anchors_per_kb: dict[str, list[str]] = {}
    aggregated_pending_per_kb: dict[str, list[str]] = {}

    # 1단계: 각 KB의 drift cleanup + pending chunks 식별 + anchor 스냅샷
    for kb_id in knowledge_ids:
        try:
            # 드리프트 정리는 cleanup_only 모드로 sync_kb_to_kg에 위임
            from extension_modules.knowledge_graph import sync_kb_to_kg

            # reset=True 면 기존 processed_chunks 를 fan-out 전에 원자적으로 삭제.
            # (워커가 per-chunk append 방식이라 finalize 에서 폐기할 수 없음.)
            if form.reset:
                try:
                    KnowledgeGraphs.delete_extract_state(kg_id, kb_id)
                except Exception as e:
                    log.warning(
                        f"[KG kb-extract] reset: failed to clear state kb={kb_id[:8]}: {e}"
                    )
            already = set() if form.reset else _load_kb_processed_chunks(kg_id, kb_id)

            cleanup_result = await sync_kb_to_kg(
                app=app,
                kg_id=kg_id,
                knowledge_id=kb_id,
                user_id=user_id,
                pre_resolved_model_config=pre_resolved_model_config,
                model_id=form.model_id,
                processed_chunk_ids=already,
                cleanup_only=True,
            )
            removed = (cleanup_result or {}).get("removed_chunk_ids") or set()
            if isinstance(removed, (list, tuple)):
                removed = set(removed)
            already_after_cleanup = already - removed

            # 청크 fetch 후 pending 계산
            ks = SearchEngineKnowledge(app=app, collection_name=kb_id)
            all_chunks = await ks.query_by_metadata({}, limit=10000)
            pending = [c for c in all_chunks if c.id not in already_after_cleanup]
            if form.max_chunks and form.max_chunks > 0:
                pending = pending[: form.max_chunks]

            if not pending:
                log.info(f"[KG kb-extract via queue] kb={kb_id}: no pending chunks")
                continue

            # anchor labels 스냅샷 (LLM 프롬프트 가이드용 — 최대 200개)
            anchor_labels: list[str] = []
            for at in (
                NodeType.TERM,
                NodeType.CONCEPT,
                NodeType.COLUMN,
                NodeType.TABLE,
                NodeType.DOC_ENTITY,
            ):
                try:
                    nodes = KnowledgeGraphs.get_nodes(
                        kg_id=kg_id, node_type=at, limit=2000
                    )
                except Exception:
                    continue
                for n in nodes:
                    if not n.label:
                        continue
                    if n.label not in anchor_labels:
                        anchor_labels.append(n.label)
                    if len(anchor_labels) >= 200:
                        break
                if len(anchor_labels) >= 200:
                    break

            # ── Phase 2 계층 upsert — publish 전에 KB/document/chunk 노드를
            # 미리 만들어둬야 worker 의 extracted_from 엣지가 고아가 안 됨 ──
            try:
                from extension_modules.knowledge_graph.sync._age_helpers import (
                    get_age_service,
                )
                from extension_modules.knowledge_graph.sync._kb_hierarchy import (
                    upsert_kb_documents_hierarchy,
                )

                _age = get_age_service(kg_id)
                _hier_stats = upsert_kb_documents_hierarchy(
                    kg_id=kg_id,
                    knowledge_id=kb_id,
                    user_id=user_id,
                    chunks=pending,
                    age=_age,
                )
                log.info(
                    f"[KG kb-extract via queue] kb={kb_id[:8]} hierarchy upserted: "
                    f"{_hier_stats['documents']} docs"
                    + (
                        f" (skipped {_hier_stats['skipped_no_file_id']} without file_id)"
                        if _hier_stats.get("skipped_no_file_id")
                        else ""
                    )
                )
            except Exception as e:
                log.exception(
                    f"[KG kb-extract via queue] hierarchy upsert failed "
                    f"for kb={kb_id[:8]}: {e}"
                )
                job_errors.append(f"kb {kb_id[:8]} hierarchy: {e}")

            # 청크 컨텐츠 미리 정규화 (publish는 progress_total 설정 *후*에 한다)
            normalized_chunks: list[tuple[str, str]] = []
            chunk_ids_for_kb: list[str] = []
            for chunk in pending:
                content = (chunk.content or "").strip()
                if len(content) > 4000:
                    content = content[:4000]
                normalized_chunks.append((chunk.id, content))
                chunk_ids_for_kb.append(chunk.id)
            pending_per_kb[kb_id] = normalized_chunks
            anchors_per_kb[kb_id] = anchor_labels
            if chunk_ids_for_kb:
                aggregated_pending_per_kb[kb_id] = chunk_ids_for_kb

        except Exception as e:
            log.exception(f"[KG kb-extract via queue] kb={kb_id} failed: {e}")
            job_errors.append(f"kb {kb_id[:8]}: {e}")

    total_chunks_planned = sum(len(v) for v in pending_per_kb.values())

    # 0개 enqueue → finalize 즉시 (drift cleanup만 됐을 수도 있음)
    if total_chunks_planned == 0:
        try:
            KnowledgeGraphs.complete_job(
                job_id,
                stats={"chunks_enqueued": 0, "chunks_succeeded": 0, "chunks_failed": 0},
                errors=job_errors[:20] or None,
            )
            # stats 갱신 (cleanup만 일어난 경우에도 last_synced_at 반영)
            try:
                from extension_modules.knowledge_graph import KGService

                svc = KGService.load(kg_id)
                if svc:
                    svc.refresh_stats()
            except Exception as e:
                log.exception(f"[KG kb-extract via queue] stats refresh failed: {e}")
        except Exception as e:
            log.exception(f"failed to complete empty job: {e}")
        return

    # ─── progress_total / params 를 publish *전*에 기록 ───
    # 그렇지 않으면 worker 의 첫 increment 가 progress_total=0 보다 커져
    # try_claim_job_finalization 이 조기 발동된다.
    try:
        from open_webui.internal.db import get_db
        from open_webui.models.knowledge_graph import KGExtractJob

        current_job = KnowledgeGraphs.get_job_by_id(job_id)
        params = dict((current_job.params if current_job else {}) or {})
        flat_chunks: list[str] = []
        for cids in aggregated_pending_per_kb.values():
            flat_chunks.extend(cids)
        # finalize 가 KB 별로 처리 이력을 저장할 수 있도록 두 형태 모두 저장
        params["chunk_ids"] = flat_chunks
        params["chunks_per_kb"] = aggregated_pending_per_kb
        with get_db() as db:
            row = db.query(KGExtractJob).filter_by(id=job_id).first()
            if row:
                row.progress_total = total_chunks_planned
                row.params = params
                row.progress_label = f"Queued {total_chunks_planned} chunks"
                db.commit()
    except Exception as e:
        log.exception(f"failed to set progress_total before publish: {e}")

    # ─── 지식 연결에서 KB별 매칭 라벨 로드 (LLM system prompt hint 용) ───
    # knowledge_links[].status.doc_entity_map 에서 해당 KB 의 매칭 결과를 가져와
    # 각 chunk payload 에 entity_context 텍스트로 주입한다 — "이 청크는 X 라는
    # 것에 대한 문서다" hint 만 제공해서 entity linking 정확도를 높이는 용도.
    kb_entity_context: dict[str, str] = {}  # kb_id → context_str
    try:
        _kg_links = KnowledgeGraphs.get_knowledge_links(kg_id)
        for link in _kg_links:
            doc_map = (link.status or {}).get("doc_entity_map") or {}
            for _file_id, matches in doc_map.items():
                labels = [
                    m.get("entity_label", "") for m in matches if m.get("entity_label")
                ]
                if labels:
                    for _kb_id in knowledge_ids:
                        if _kb_id not in kb_entity_context:
                            kb_entity_context[_kb_id] = (
                                f"This chunk is part of a document about: "
                                f"{', '.join(labels)}."
                            )
                        else:
                            existing_ctx = kb_entity_context[_kb_id]
                            all_labels = set(
                                existing_ctx.split(": ", 1)[-1].rstrip(".").split(", ")
                            ) | set(labels)
                            kb_entity_context[_kb_id] = (
                                f"This chunk is part of a document about: "
                                f"{', '.join(all_labels)}."
                            )
    except Exception as e:
        log.warning(f"[KG kb-extract via queue] entity context load failed: {e}")

    # ─── 이제 publish ───
    total_chunks_enqueued = 0
    failed_chunks = 0
    for kb_id, items in pending_per_kb.items():
        anchor_labels = anchors_per_kb.get(kb_id) or []
        _entity_ctx_str = kb_entity_context.get(kb_id)
        for chunk_id, content in items:
            payload = {
                "kg_id": kg_id,
                "knowledge_id": kb_id,
                "user_id": user_id,
                "chunk_id": chunk_id,
                "chunk_content": content,
                "anchor_labels": anchor_labels,
                "llm_config": pre_resolved_model_config,
                "min_confidence": form.min_confidence,
                "job_id": job_id,
                "entity_context": _entity_ctx_str,
            }
            msg = TaskMessage(
                task_type="kg_kb_chunk",
                payload=payload,
                max_retries=3,
            )
            try:
                await queue.publish(msg)
                total_chunks_enqueued += 1
            except Exception as e:
                log.exception(f"failed to publish chunk task: {e}")
                job_errors.append(f"publish failed for {chunk_id[:8]}: {e}")
                failed_chunks += 1

    # publish 실패가 발생했으면 progress_current 를 그만큼 미리 증가시켜서
    # finalize 가 차단되지 않도록 한다 (worker가 도달 못할 카운트 보정).
    if failed_chunks > 0:
        try:
            KnowledgeGraphs.increment_job_progress(
                job_id, delta=failed_chunks, failure_delta=failed_chunks
            )
        except Exception as e:
            log.exception(f"failed to record publish failures on job: {e}")

    log.info(
        f"[KG kb-extract via queue] enqueued {total_chunks_enqueued}/"
        f"{total_chunks_planned} chunks across {len(aggregated_pending_per_kb)} KBs "
        f"for job {job_id}"
    )

    # 모든 publish 가 실패해 finalize 가 일어나지 않을 수 있는 케이스 보정.
    # publish 후 worker 가 즉시 모두 끝나 있을 수도 있으므로 여기서 한 번 더
    # try_claim 을 시도한다 (이미 finalize 되었으면 None 반환되며 무해).
    try:
        from extension_modules.knowledge_graph.kb_chunk_worker import _maybe_finalize

        # knowledge_id 인자는 더이상 finalize 동작에 영향을 주지 않으므로 None 으로 전달
        _maybe_finalize(app, job_id, kg_id, None)
    except Exception as e:
        log.exception(f"post-enqueue _maybe_finalize crashed: {e}")


async def _extract_kb_bg(
    app,
    kg_id: str,
    form: KbExtractForm,
    user_id: str,
    knowledge_ids: list[str],
    pre_resolved_model_config: Optional[dict] = None,
    job_id: Optional[str] = None,
) -> None:
    """백그라운드 KB 엔티티/관계 추출 잡 (job 추적 포함).

    Redis 큐가 가용하면 청크별 fan-out으로 병렬 처리, 미가용이면 inline 직렬.
    cleanup_only 모드는 항상 inline (LLM 호출 없음).
    """
    # cleanup_only는 큐 fan-out 의미 없음 — 기존 inline 경로
    if not form.cleanup_only and pre_resolved_model_config and job_id:
        try:
            from open_webui.services.task_queue import InProcessQueue

            queue = getattr(app.state, "task_queue", None)
            if queue is not None and not isinstance(queue, InProcessQueue):
                await _extract_kb_via_queue(
                    app,
                    kg_id,
                    form,
                    user_id,
                    knowledge_ids,
                    pre_resolved_model_config,
                    job_id,
                )
                return
        except Exception as e:
            log.exception(
                f"[KG kb-extract] queue path failed, falling back to inline: {e}"
            )

    from extension_modules.knowledge_graph import KGNodeIndexService, sync_kb_to_kg

    aggregated: dict = {
        "kbs_processed": 0,
        "total_chunks": 0,
        "chunks_processed": 0,
        "entities_created": 0,
        "entities_linked": 0,
        "edges_created": 0,
    }
    job_errors: list[str] = []

    for idx, kb_id in enumerate(knowledge_ids):
        if job_id:
            KnowledgeGraphs.update_job_progress(
                job_id,
                progress_current=idx,
                progress_label=f"Processing KB {idx + 1}/{len(knowledge_ids)}",
            )
            KnowledgeGraphs.heartbeat_job(job_id)
        # 이번 KB의 처리 이력 로드 (reset 시 빈 set)
        already = set() if form.reset else _load_kb_processed_chunks(kg_id, kb_id)
        try:
            result = await sync_kb_to_kg(
                app=app,
                kg_id=kg_id,
                knowledge_id=kb_id,
                user_id=user_id,
                pre_resolved_model_config=pre_resolved_model_config,
                model_id=form.model_id,
                max_chunks=form.max_chunks,
                min_confidence=form.min_confidence,
                processed_chunk_ids=already,
                cleanup_only=form.cleanup_only,
            )
            # sync 완료 후 heartbeat (장시간 LLM 호출 후 watchdog 방지)
            if job_id:
                KnowledgeGraphs.heartbeat_job(job_id)
            if result:
                aggregated["kbs_processed"] += 1
                aggregated["total_chunks"] += int(result.get("total_chunks", 0))
                aggregated["chunks_processed"] += int(result.get("chunks_processed", 0))
                aggregated["entities_created"] += int(result.get("entities_created", 0))
                aggregated["entities_linked"] += int(result.get("entities_linked", 0))
                aggregated["edges_created"] += int(result.get("edges_created", 0))
                aggregated["nodes_pruned"] = aggregated.get("nodes_pruned", 0) + int(
                    result.get("nodes_pruned", 0)
                )

                # 처리 이력 갱신:
                #   final = (already ∪ newly_processed) - removed_drift
                # KB에서 사라진 청크(removed_drift)는 final state에서도 빠져서
                # 다음 실행에는 다시 "처리되지 않은" 것으로 안 잡힌다.
                newly = result.get("processed_chunk_ids") or set()
                removed = result.get("removed_chunk_ids") or set()
                if isinstance(newly, (list, tuple)):
                    newly = set(newly)
                if isinstance(removed, (list, tuple)):
                    removed = set(removed)
                merged = (already | newly) - removed
                # newly가 있거나 drift가 감지됐거나 reset이면 저장
                if newly or removed or form.reset:
                    try:
                        # cleanup_only 인 경우 model_id 가 None 일 수 있으므로
                        # last_model 필드를 합리적인 값으로 대체.
                        save_model = form.model_id or (
                            "cleanup" if form.cleanup_only else "unknown"
                        )
                        _save_kb_processed_chunks(kg_id, kb_id, merged, save_model)
                    except Exception as e:
                        log.exception(
                            f"[KG kb-extract] failed to save processed_chunks "
                            f"for kb={kb_id}: {e}"
                        )
                # 결과의 LLM/추출 에러도 잡 errors에 누적 (앞 10개만)
                for err in (result.get("errors") or [])[:5]:
                    job_errors.append(f"[{kb_id[:8]}] {err}")
            log.info(f"[KG kb-extract] kb={kb_id} result: {result}")
        except Exception as e:
            log.exception(f"[KG kb-extract] failed for kb={kb_id}: {e}")
            job_errors.append(f"[{kb_id[:8]}] {e}")

    # 새로 만들어진 doc_entity 노드를 search 인덱스에 반영 (semantic search 동작용).
    # 미설정이면 graceful no-op.
    try:
        index_service = KGNodeIndexService(app)
        nodes = KnowledgeGraphs.get_nodes(kg_id, node_type="doc_entity", limit=2000)
        if nodes:
            await index_service.index_nodes(kg_id, nodes)
    except Exception as e:
        log.exception(f"[KG kb-extract] indexing step failed: {e}")

    log.info(f"[KG kb-extract] aggregated: {aggregated}")

    # KG stats 갱신 (frontend 의 last_synced_at + node/edge count 표시용)
    try:
        from extension_modules.knowledge_graph import KGService

        svc = KGService.load(kg_id)
        if svc:
            svc.refresh_stats()
    except Exception as e:
        log.exception(f"[KG kb-extract] stats refresh failed: {e}")

    # 잡 마감
    if job_id:
        try:
            KnowledgeGraphs.complete_job(
                job_id, stats=aggregated, errors=job_errors[:20] or None
            )
        except Exception as e:
            log.exception(f"[KG kb-extract] failed to complete job {job_id}: {e}")


@router.post("/{id}/kb/extract/preview")
async def extract_kb_entities_preview(
    id: str,
    form_data: KbExtractPreviewForm,
    request: Request,
    user=Depends(get_verified_user),
):
    """엔티티 추출을 실제 실행하지 않고 예상 LLM 호출 횟수만 계산해 반환.

    프론트엔드 "엔티티 추출" 버튼 클릭 시 사용자에게 경고 다이얼로그로
    노출하는 용도. `/kb/extract` 와 동일한 pending chunk 계산 로직을
    사용하지만 LLM 호출, 잡 생성, 큐 publish 는 수행하지 않는다.

    반환:
        knowledge_ids: 대상 KB 목록
        chunks_per_kb: {kb_id: pending_count}
        pending_total: 모든 KB 의 pending 청크 합계
        already_processed_total: 모든 KB 의 이미 처리된 청크 합계
        estimated_llm_calls: LLM 호출 예상 횟수 (1 청크 = 1 호출)
    """
    from open_webui.retrieval.knowledge_service import SearchEngineKnowledge

    kg = KnowledgeGraphs.get_kg_by_id(id=id)
    _require_kg_read(kg, user, request)

    # 실제 attach 된 KB 는 knowledge_link 테이블의 union — kg.data.sources 는
    # 레거시라 지금은 비어 있을 수 있다.
    links_all = KnowledgeGraphs.get_knowledge_links(id) or []
    attached_from_links: list[str] = []
    _seen_attach: set[str] = set()
    for _link in links_all:
        for _kb_id in _link.knowledge_ids or []:
            if _kb_id not in _seen_attach:
                _seen_attach.add(_kb_id)
                attached_from_links.append(_kb_id)
    # 레거시 경로와도 merge (혹시 sources 에만 있는 경우 대비)
    legacy_sources = list(
        ((kg.data or {}).get("sources") or {}).get("knowledge_ids") or []
    )
    for _kb_id in legacy_sources:
        if _kb_id not in _seen_attach:
            _seen_attach.add(_kb_id)
            attached_from_links.append(_kb_id)
    attached_ids = attached_from_links

    # 범위 우선순위: knowledge_ids (다중) > knowledge_id (단일) > attached 전체.
    if form_data.knowledge_ids:
        # 실제로 KG 에 attach 된 것만 유지 (silent filter — 링크가 이전 KB 를
        # 가리키고 있을 수 있어 404 대신 무시)
        requested = set(form_data.knowledge_ids)
        target_ids = [kb_id for kb_id in attached_ids if kb_id in requested]
    elif form_data.knowledge_id:
        if form_data.knowledge_id not in attached_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ERROR_MESSAGES.DEFAULT(
                    "knowledge_id is not attached to this KG"
                ),
            )
        target_ids = [form_data.knowledge_id]
    else:
        target_ids = list(attached_ids)

    chunks_per_kb: dict[str, int] = {}
    already_processed_total = 0
    pending_total = 0

    for kb_id in target_ids:
        try:
            already = set() if form_data.reset else _load_kb_processed_chunks(id, kb_id)
            ks = SearchEngineKnowledge(app=request.app, collection_name=kb_id)
            all_chunks = await ks.query_by_metadata({}, limit=10000)
            pending = [c for c in all_chunks if c.id not in already]
            if form_data.max_chunks and form_data.max_chunks > 0:
                pending = pending[: form_data.max_chunks]
            chunks_per_kb[kb_id] = len(pending)
            pending_total += len(pending)
            already_processed_total += len(already)
        except Exception as e:
            log.exception(f"[KG kb-extract preview] kb={kb_id[:8]} failed: {e}")
            chunks_per_kb[kb_id] = 0

    return {
        "knowledge_ids": target_ids,
        "chunks_per_kb": chunks_per_kb,
        "pending_total": pending_total,
        "already_processed_total": already_processed_total,
        "estimated_llm_calls": pending_total,
    }


@router.post("/{id}/kb/extract")
async def extract_kb_entities(
    id: str,
    form_data: KbExtractForm,
    request: Request,
    background_tasks: BackgroundTasks,
    user=Depends(get_verified_user),
):
    """LLM으로 첨부된 KB 문서에서 doc_entity 노드 + related_to 엣지 추출 (백그라운드).

    `knowledge_id`가 주어지면 그 KB만, 없으면 KG의 `sources.knowledge_ids` 전체.
    Sync now와 다르게 용어집/DbSphere 동기화는 건너뛰고 KB 추출만 수행하므로
    "KB 추출만 다시 돌리고 싶다" 시나리오에 사용한다.
    """
    kg = KnowledgeGraphs.get_kg_by_id(id=id)
    _require_kg_write(kg, user, request)

    # 대상 KB 목록 결정
    sources = (kg.data or {}).get("sources") or {}
    attached_ids = list(sources.get("knowledge_ids") or [])
    if form_data.knowledge_id:
        if form_data.knowledge_id not in attached_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ERROR_MESSAGES.DEFAULT(
                    "knowledge_id is not attached to this KG"
                ),
            )
        target_ids = [form_data.knowledge_id]
    else:
        # KG sources에 같은 KB id 가 중복으로 들어있을 수 있어 dedup (insertion order 보존)
        target_ids = list(dict.fromkeys(attached_ids))
    if not target_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT(
                "No knowledge bases attached. Add a KB to sources first."
            ),
        )

    # cleanup-only는 LLM 호출이 없으므로 모델 검증 skip
    pre_resolved = None
    if not form_data.cleanup_only:
        if not form_data.model_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ERROR_MESSAGES.DEFAULT(
                    "model_id is required unless cleanup_only=true"
                ),
            )
        from extension_modules.utils.llm import (
            get_model_config_from_app,
            model_config_has_credentials,
        )

        pre_resolved = get_model_config_from_app(request.app, form_data.model_id)
        if not pre_resolved:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ERROR_MESSAGES.DEFAULT(f"Model not found: {form_data.model_id}"),
            )
        if not model_config_has_credentials(pre_resolved):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ERROR_MESSAGES.DEFAULT(
                    "Selected model has no credentials configured "
                    "(api_key for openai/openrouter, service_account_key or "
                    "use_global_gcp_key for vertex)"
                ),
            )

    # Job 생성 — 진행 상황을 사용자가 폴링으로 볼 수 있도록
    job_kind = JobKind.KB_CLEANUP if form_data.cleanup_only else JobKind.KB_EXTRACT
    job = KnowledgeGraphs.start_job(
        kg_id=id,
        user_id=user.id,
        kind=job_kind,
        target_id=form_data.knowledge_id,
        params={
            "model_id": form_data.model_id,
            "max_chunks": form_data.max_chunks,
            "min_confidence": form_data.min_confidence,
            "reset": form_data.reset,
            "cleanup_only": form_data.cleanup_only,
            "knowledge_ids": target_ids,
        },
        progress_total=len(target_ids),
        progress_label=f"Queued — {len(target_ids)} KB(s)",
    )

    background_tasks.add_task(
        _extract_kb_bg,
        request.app,
        id,
        form_data,
        user.id,
        target_ids,
        pre_resolved,
        job.id if job else None,
    )
    msg = (
        f"KB cleanup started for {len(target_ids)} knowledge base(s)."
        if form_data.cleanup_only
        else f"KB extraction started for {len(target_ids)} knowledge base(s)."
    )
    return {
        "status": True,
        "message": msg,
        "knowledge_ids": target_ids,
        "job_id": job.id if job else None,
    }


@router.get("/{id}/candidates", response_model=list[KGCandidateModel])
async def get_candidates(
    id: str,
    request: Request,
    status: Optional[str] = None,  # pending | accepted | rejected
    limit: int = 200,
    user=Depends(get_verified_user),
):
    kg = KnowledgeGraphs.get_kg_by_id(id=id)
    _require_kg_read(kg, user, request)
    return KnowledgeGraphs.get_candidates(kg_id=id, status=status, limit=limit)


@router.get("/{id}/candidates/stats")
async def get_candidate_stats(
    id: str,
    request: Request,
    user=Depends(get_verified_user),
):
    kg = KnowledgeGraphs.get_kg_by_id(id=id)
    _require_kg_read(kg, user, request)
    return KnowledgeGraphs.count_candidates_by_status(kg_id=id)


@router.post("/{id}/candidates/{cid}/accept", response_model=Optional[dict])
async def accept_candidate(
    id: str,
    cid: str,
    request: Request,
    form_data: CandidateAcceptForm,
    user=Depends(get_verified_user),
):
    """후보 수락 → 용어집에 entry 추가 + maps_to 엣지 생성.

    Slice 6 핵심: 사용자가 검수해서 OK한 용어를 즉시 사용 가능한 KG 매핑으로
    변환. 용어집도 함께 채워지므로 KG가 스스로를 부트스트랩하는 효과.
    """
    import time
    import uuid

    from open_webui.models.glossary import Glossaries

    kg = KnowledgeGraphs.get_kg_by_id(id=id)
    _require_kg_write(kg, user, request)

    candidate = KnowledgeGraphs.get_candidate_by_id(cid)
    if not candidate or candidate.kg_id != id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )
    if candidate.status != CandidateStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT(f"Candidate is already {candidate.status}"),
        )

    # 1. 용어집 검증
    glossary = Glossaries.get_glossary_by_id(form_data.glossary_id)
    if not glossary:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("Glossary not found"),
        )
    if (
        glossary.user_id != user.id
        and not has_access(user.id, "write", glossary.access_control)
        and user.role != "admin"
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    # 2. 용어집에 entry 추가
    final_term = (form_data.term or candidate.suggested_label).strip()
    props = candidate.properties or {}
    description = (
        form_data.description
        or props.get("description")
        or props.get("reasoning")
        or ""
    )

    entry_id = str(uuid.uuid4())
    new_entry = {
        "id": entry_id,
        "term": final_term,
        "synonyms": props.get("synonyms", []),
        "description": description,
        "example": props.get("example", ""),
        "category": form_data.category or props.get("category") or None,
    }
    existing_entries = (glossary.data or {}).get("entries", []) or []
    new_data = {**(glossary.data or {}), "entries": existing_entries + [new_entry]}
    updated_glossary = Glossaries.update_glossary_data_by_id(
        form_data.glossary_id, new_data
    )
    if not updated_glossary:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("Failed to add entry to glossary"),
        )

    # 3. (옵션) maps_to 엣지 생성 — target_node_id가 column 노드일 때
    edge_created = False
    if form_data.create_mapping and candidate.target_node_id:
        target_node = KnowledgeGraphs.get_node_by_id(candidate.target_node_id)
        if target_node and target_node.kg_id == id:
            # 해당 용어집가 KG에 sync 돼 있어야 term 노드도 존재함.
            # 없으면 임시로 manual term 노드를 만들어 매핑한다.
            from open_webui.models.knowledge_graph import NodeType, make_node_id

            term_node_id = make_node_id(
                id, "glossary", form_data.glossary_id, "term", entry_id
            )
            term_node = KnowledgeGraphs.upsert_node(
                kg_id=id,
                user_id=user.id,
                node_id=term_node_id,
                node_type=NodeType.TERM,
                label=final_term,
                properties={
                    "description": description,
                    "from_candidate": cid,
                },
                source_ref={
                    "kind": "glossary",
                    "glossary_id": form_data.glossary_id,
                    "entry_id": entry_id,
                },
            )

            edge_props = {}
            filter_expr = form_data.filter_expr or props.get("suggested_filter")
            if filter_expr:
                edge_props["filter"] = filter_expr
            edge_props["from_candidate"] = cid

            # term_node 가 None 이면 upsert 가 실패한 것이므로 매핑 생성 스킵.
            if term_node:
                edge = KnowledgeGraphs.upsert_edge(
                    kg_id=id,
                    user_id=user.id,
                    src_id=term_node_id,
                    dst_id=candidate.target_node_id,
                    edge_type=EdgeType.MAPS_TO,
                    source=EdgeSource.MANUAL,
                    properties=edge_props,
                )
                edge_created = bool(edge)

    # 4. candidate status 업데이트
    KnowledgeGraphs.update_candidate_status(
        cid=cid,
        status=CandidateStatus.ACCEPTED,
        resolved_glossary_id=form_data.glossary_id,
        resolved_entry_id=entry_id,
    )

    return {
        "status": True,
        "candidate_id": cid,
        "glossary_id": form_data.glossary_id,
        "entry_id": entry_id,
        "term": final_term,
        "mapping_created": edge_created,
        "ts": int(time.time()),
    }


@router.post("/{id}/candidates/{cid}/reject", response_model=bool)
async def reject_candidate(
    id: str,
    cid: str,
    request: Request,
    user=Depends(get_verified_user),
):
    kg = KnowledgeGraphs.get_kg_by_id(id=id)
    _require_kg_write(kg, user, request)
    candidate = KnowledgeGraphs.get_candidate_by_id(cid)
    if not candidate or candidate.kg_id != id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )
    return KnowledgeGraphs.update_candidate_status(
        cid=cid, status=CandidateStatus.REJECTED
    )


@router.delete("/{id}/candidates/{cid}", response_model=bool)
async def delete_candidate(
    id: str,
    cid: str,
    request: Request,
    user=Depends(get_verified_user),
):
    kg = KnowledgeGraphs.get_kg_by_id(id=id)
    _require_kg_write(kg, user, request)
    return KnowledgeGraphs.delete_candidate(cid)


############################
# Background Jobs (Slice 9)
############################


@router.get("/{id}/jobs", response_model=list[KGExtractJobModel])
async def list_kg_jobs(
    id: str,
    request: Request,
    job_status: Optional[str] = None,  # 'pending'|'running'|'completed'|'failed'
    kind: Optional[
        str
    ] = None,  # 'kb_extract'|'kb_cleanup'|'candidate_extract'|'sync_all'
    limit: int = 50,
    user=Depends(get_verified_user),
):
    """KG의 백그라운드 추출/동기화 잡 목록 (최신순).

    프론트엔드가 폴링해서 진행 중 잡(`status='running'`)을 표시하거나
    최근 실행 결과를 보여주는 데 사용한다.
    """
    kg = KnowledgeGraphs.get_kg_by_id(id=id)
    _require_kg_read(kg, user, request)

    if limit < 1 or limit > 200:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("limit must be between 1 and 200"),
        )

    jobs = KnowledgeGraphs.get_jobs(kg_id=id, status=job_status, kind=kind, limit=limit)
    return [_sanitize_job(j) for j in jobs]


@router.get("/{id}/jobs/{job_id}", response_model=Optional[KGExtractJobModel])
async def get_kg_job(
    id: str,
    job_id: str,
    request: Request,
    user=Depends(get_verified_user),
):
    """단일 잡의 상세 (진행률 + 통계 + 에러)."""
    kg = KnowledgeGraphs.get_kg_by_id(id=id)
    _require_kg_read(kg, user, request)

    job = KnowledgeGraphs.get_job_by_id(job_id)
    if not job or job.kg_id != id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )
    return _sanitize_job(job)


@router.post("/{id}/jobs/{job_id}/cancel", response_model=bool)
async def cancel_kg_job(
    id: str,
    job_id: str,
    request: Request,
    user=Depends(get_verified_user),
):
    """실행 중인 백그라운드 잡을 취소.

    워커가 다음 increment_job_progress 호출 전에 status를 확인해서
    조기 종료한다. 이미 완료/실패/취소된 잡은 무시(False 반환).
    """
    kg = KnowledgeGraphs.get_kg_by_id(id=id)
    _require_kg_write(kg, user, request)

    job = KnowledgeGraphs.get_job_by_id(job_id)
    if not job or job.kg_id != id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    return KnowledgeGraphs.cancel_job(job_id)


############################
# Knowledge Links (지식 연결)
############################


class KnowledgeLinkCreateForm(BaseModel):
    """지식 연결 생성 폼 — 용어집 → KB(복수) + DbSphere(복수) 매핑."""

    glossary_id: str
    knowledge_ids: list[str] = []
    # 용어집이 extraction_sources 로 참조하는 DbSphere 중 이 링크에서 실제로
    # 활성화할 subset. 미전달/빈 배열 시 sync 는 glossary 의 extraction_sources
    # 전체를 fallback 으로 사용.
    dbsphere_ids: list[str] = []


class LinkSourceCandidate(BaseModel):
    id: str
    name: Optional[str] = None
    description: Optional[str] = None


class LinkSourceCandidatesResponse(BaseModel):
    knowledge_bases: list[LinkSourceCandidate]
    dbspheres: list[LinkSourceCandidate]


@router.get(
    "/{id}/links/source-candidates", response_model=LinkSourceCandidatesResponse
)
async def get_link_source_candidates(
    id: str,
    request: Request,
    glossary_id: str,
    user=Depends(get_verified_user),
):
    """용어집 하나가 연결 가능한 KB / DbSphere 후보를 반환.

    - **KB 후보**: ``knowledge.meta.filter_schema`` 에 해당 glossary_id 를
      쓰는 glossary 타입 필터가 있는 KB.
    - **DbSphere 후보**: ``glossary.data.extraction_sources`` 에 기록된
      dbsphere_id 의 union.

    Add Link 모달에서 체크박스로 subset 선택할 수 있도록 제공.
    """
    kg = KnowledgeGraphs.get_kg_by_id(id=id)
    _require_kg_read(kg, user, request)

    # --- DbSphere 후보 (extraction_sources) ---
    from open_webui.models.dbsphere import DbSpheres
    from open_webui.models.glossary import Glossaries
    from open_webui.models.knowledge import Knowledges

    glossary = Glossaries.get_glossary_by_id(glossary_id)
    ds_candidates: list[LinkSourceCandidate] = []
    if glossary:
        ext_sources = (glossary.data or {}).get("extraction_sources") or {}
        ds_ids: set[str] = set()
        # extraction_sources: {category: {dbsphere_id, table, column, ...}}
        for _cat, spec in (ext_sources or {}).items():
            if isinstance(spec, dict):
                dsid = spec.get("dbsphere_id")
                if dsid:
                    ds_ids.add(dsid)
        for dsid in sorted(ds_ids):
            try:
                ds = DbSpheres.get_dbsphere_by_id(dsid)
            except Exception:
                ds = None
            ds_candidates.append(
                LinkSourceCandidate(
                    id=dsid,
                    name=getattr(ds, "name", None) if ds else None,
                    description=getattr(ds, "description", None) if ds else None,
                )
            )

    # --- KB 후보 (filter_schema 에서 glossary 참조) ---
    kb_candidates: list[LinkSourceCandidate] = []
    try:
        if user.role == "admin":
            kbs = Knowledges.get_knowledge_bases()
        else:
            kbs = Knowledges.get_knowledge_bases_by_user_id(user.id, "read")
    except Exception as e:
        log.warning(f"[link candidates] kb list failed: {e}")
        kbs = []
    for kb in kbs or []:
        meta = getattr(kb, "meta", None) or {}
        schema = meta.get("filter_schema") or []
        uses = any(
            isinstance(f, dict)
            and f.get("type") == "glossary"
            and f.get("glossary_id") == glossary_id
            for f in schema
        )
        if not uses:
            continue
        kb_candidates.append(
            LinkSourceCandidate(
                id=kb.id,
                name=kb.name,
                description=getattr(kb, "description", None),
            )
        )

    return LinkSourceCandidatesResponse(
        knowledge_bases=kb_candidates, dbspheres=ds_candidates
    )


@router.get("/{id}/links")
async def get_knowledge_links(
    id: str,
    request: Request,
    user=Depends(get_verified_user),
):
    """KG의 지식 연결 목록."""
    kg = KnowledgeGraphs.get_kg_by_id(id=id)
    _require_kg_read(kg, user, request)
    return KnowledgeGraphs.get_knowledge_links(id)


@router.post("/{id}/links")
async def create_knowledge_link(
    id: str,
    request: Request,
    form_data: KnowledgeLinkCreateForm,
    user=Depends(get_verified_user),
):
    """지식 연결 추가 — 같은 용어집 중복 생성은 거부."""
    kg = KnowledgeGraphs.get_kg_by_id(id=id)
    _require_kg_write(kg, user, request)

    fd = form_data.model_dump()
    if KnowledgeGraphs.check_duplicate_link(id, fd):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=ERROR_MESSAGES.DEFAULT(
                "Duplicate link: this glossary is already linked"
            ),
        )

    link = KnowledgeGraphs.create_knowledge_link(id, user.id, fd)
    if not link:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("Failed to create knowledge link"),
        )
    # kg.data.sources 를 모든 link 기반으로 재계산 — UI / DB 조회 시 실제
    # 연결된 자원을 바로 반영.
    try:
        KnowledgeGraphs.recompute_kg_sources_from_links(id)
    except Exception as e:
        log.warning(f"[kg] recompute sources after link create failed: {e}")
    return link


@router.delete("/{id}/links/{link_id}")
async def delete_knowledge_link(
    id: str,
    link_id: str,
    request: Request,
    user=Depends(get_verified_user),
):
    """지식 연결 삭제 — 다른 링크가 참조하지 않는 용어집/DB 노드는 cleanup."""
    kg = KnowledgeGraphs.get_kg_by_id(id=id)
    _require_kg_write(kg, user, request)

    removed_link = KnowledgeGraphs.get_knowledge_link_by_id(link_id)
    if not removed_link or removed_link.kg_id != id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )
    removed_glossary_id = removed_link.glossary_id

    if not KnowledgeGraphs.delete_knowledge_link(link_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    # 다른 링크가 여전히 이 용어집을 참조하는지 확인
    if removed_glossary_id:
        remaining_links = KnowledgeGraphs.get_knowledge_links(id)
        remaining_glossary_ids = {
            link.glossary_id for link in remaining_links if link.glossary_id
        }
        if removed_glossary_id not in remaining_glossary_ids:
            try:
                from extension_modules.knowledge_graph.sync.glossary_sync import (
                    get_referenced_dbsphere_ids,
                )

                # 제거 대상 용어집 노드 삭제
                KnowledgeGraphs.delete_nodes_by_source(
                    id, "glossary", removed_glossary_id, include_manual_edges=True
                )

                # 이 용어집이 참조했던 dbsphere 중 남은 용어집이 안 쓰는 것만 삭제
                removed_db_ids = set(get_referenced_dbsphere_ids(removed_glossary_id))
                still_ref: set[str] = set()
                for gid in remaining_glossary_ids:
                    still_ref.update(get_referenced_dbsphere_ids(gid))
                for db_id in removed_db_ids - still_ref:
                    KnowledgeGraphs.delete_nodes_by_source(
                        id, "dbsphere", db_id, include_manual_edges=True
                    )
            except Exception as e:
                log.exception(f"[link delete] orphan cleanup failed: {e}")

    # KB 단위 doc_entity orphan cleanup — 삭제된 링크의 knowledge_ids 중
    # 남은 링크가 더 이상 참조하지 않는 KB 의 doc_entity 노드는 제거한다.
    # doc_entity 노드 ID 는 `{kg_id}__kb__{knowledge_id}__entity__...` 형식이므로
    # delete_nodes_by_source(kg_id, "kb", kb_id) 로 prefix 매칭 삭제 가능.
    removed_kb_ids = set(removed_link.knowledge_ids or [])
    if removed_kb_ids:
        try:
            remaining_links = KnowledgeGraphs.get_knowledge_links(id)
            still_ref_kbs: set[str] = set()
            for link in remaining_links:
                for kb_id in link.knowledge_ids or []:
                    still_ref_kbs.add(kb_id)
            orphan_kbs = removed_kb_ids - still_ref_kbs
            for kb_id in orphan_kbs:
                deleted = KnowledgeGraphs.delete_nodes_by_source(
                    id, "kb", kb_id, include_manual_edges=True
                )
                # 이 KB 의 추출 상태도 함께 정리 (다음 sync 가 clean state 로 시작)
                try:
                    KnowledgeGraphs.delete_extract_state(id, kb_id)
                except Exception:
                    pass
                log.info(
                    f"[link delete] removed {deleted} doc_entity nodes "
                    f"for orphan kb={kb_id[:8]}"
                )
        except Exception as e:
            log.exception(f"[link delete] kb orphan cleanup failed: {e}")

    if removed_glossary_id or removed_kb_ids:
        # stats 갱신
        try:
            from extension_modules.knowledge_graph import KGService

            svc = KGService.load(id)
            if svc:
                svc.refresh_stats()
        except Exception as e:
            log.exception(f"[link delete] refresh_stats failed: {e}")

    # kg.data.sources 재계산 — 삭제된 link 반영.
    try:
        KnowledgeGraphs.recompute_kg_sources_from_links(id)
    except Exception as e:
        log.warning(f"[kg] recompute sources after link delete failed: {e}")

    return True


############################
# Link sync (지식 연결 단위 통합 sync)
############################


@router.post("/{id}/links/{link_id}/sync")
async def sync_knowledge_link(
    id: str,
    link_id: str,
    request: Request,
    user=Depends(get_verified_user),
):
    """지식 연결 1개를 통합 sync — 용어집 + 참조 DB 스키마 + KB 매칭.

    링크에 매달린 glossary_id 로 참조 dbsphere 를 도출하고, 링크의
    knowledge_ids 범위에서만 KB 파일 매칭을 수행한다. `kg_link_sync`
    task 로 enqueue (Redis 없으면 InProcess 폴백).

    LLM 모델 설정은 **HTTP 요청 컨텍스트**에서 미리 resolve 해 payload 에
    `pre_resolved_model_config` 로 주입한다. 백그라운드 워커 컨텍스트는
    `app.state.MODELS` 가 비어있거나 다를 수 있어서 워커 안에서 다시
    resolve 하면 자격증명이 없는 config 가 나와 401 이 발생하기 때문
    (글로서리 `extract_worker` 와 동일 패턴).
    """
    kg = KnowledgeGraphs.get_kg_by_id(id=id)
    _require_kg_write(kg, user, request)

    link = KnowledgeGraphs.get_knowledge_link_by_id(link_id)
    if not link or link.kg_id != id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )
    if not link.glossary_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("Link has no glossary source"),
        )
    _require_link_glossary_read(link, user)

    # LLM 모델 resolve (HTTP 요청 컨텍스트)
    from extension_modules.utils.llm import (
        get_model_config_from_app,
        model_config_has_credentials,
    )

    options = (kg.data or {}).get("options") or {}
    # 엔티티 동기화 LLM 은 KG 상단의 `options.llm_model_id` 단일 소스.
    # (엣지 카탈로그 "Suggest from LLM" 은 `link.config.recommend_model_id` 로
    # 별개 경로 — 이 함수와 무관.)
    model_id = options.get("llm_model_id")
    pre_resolved_model_config: Optional[dict] = None
    link_has_kb = bool(link.knowledge_ids)
    if not model_id and link_has_kb:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT(
                "LLM model is not configured. Select a model for this link or set the KG default."
            ),
        )
    if model_id:
        pre_resolved_model_config = get_model_config_from_app(request.app, model_id)
        if not pre_resolved_model_config:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ERROR_MESSAGES.DEFAULT(
                    f"Model not found: {model_id}. Open the KG page once to warm up"
                    " model registry, or pick a different model."
                ),
            )
        if not model_config_has_credentials(pre_resolved_model_config):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ERROR_MESSAGES.DEFAULT(
                    f"Model '{model_id}' has no credentials configured"
                ),
            )

    # kg.data.sources 가 오래돼 DB/UI 에서 "연결 안 됨" 처럼 보이는 기존 KG
    # backfill: sync 트리거 시점에 link 기반으로 한 번 더 재계산.
    try:
        KnowledgeGraphs.recompute_kg_sources_from_links(id)
    except Exception as e:
        log.warning(f"[kg] recompute sources on sync failed: {e}")

    job = KnowledgeGraphs.start_job(
        kg_id=id,
        user_id=user.id,
        kind=JobKind.GLOSSARY_SYNC,
        target_id=link_id,
        params={"link_id": link_id, "glossary_id": link.glossary_id},
        progress_total=1,
        progress_label="Queued",
    )
    job_id = job.id if job else None

    payload = {
        "kg_id": id,
        "link_id": link_id,
        "user_id": user.id,
        "job_id": job_id,
        "pre_resolved_model_config": pre_resolved_model_config,
        "model_id": model_id,
    }

    from open_webui.services.task_queue import InProcessQueue, TaskMessage

    task_queue = getattr(request.app.state, "task_queue", None)
    if task_queue is None or isinstance(task_queue, InProcessQueue):
        import asyncio as _asyncio

        from extension_modules.knowledge_graph.source_sync_worker import (
            process_kg_link_sync_task,
        )

        _asyncio.create_task(
            process_kg_link_sync_task(request.app, job_id or link_id, payload)
        )
    else:
        await task_queue.publish(
            TaskMessage(
                task_type="kg_link_sync",
                payload=payload,
                task_id=job_id or link_id,
            )
        )

    return {
        "status": True,
        "message": "Link sync queued",
        "job_id": job_id,
    }


############################
# DbSphere Schema Helpers (용어집 DB 추출 UI용)
############################


@router.get("/dbsphere/{dbsphere_id}/tables")
async def get_dbsphere_tables(
    dbsphere_id: str,
    request: Request,
    user=Depends(get_verified_user),
):
    """DbSphere 테이블 목록 — 용어집 DB 추출 UI에서 호출.

    schema extraction 이 돌아가 있어야 결과가 있다. DDL 메모리에서 테이블
    이름/설명을 반환한다.
    """
    from extension_modules.dbsphere.memory.search_memory import (
        SearchEngineDbSphereMemory,
    )

    try:
        memory = SearchEngineDbSphereMemory(
            app=request.app,
            dbsphere_id=dbsphere_id,
            user_id=user.id,
            embedding_func=None,
        )
        ddl_memories = await memory.get_table_schemas()
    except Exception as e:
        log.warning(f"[kg tables] failed for dbsphere {dbsphere_id}: {e}")
        return []

    seen: set[str] = set()
    tables = []
    for ddl in ddl_memories or []:
        if not ddl.table_name or ddl.table_name in seen:
            continue
        seen.add(ddl.table_name)
        tables.append(
            {
                "table_name": ddl.table_name,
                "description": ddl.table_description or "",
                "column_count": len(ddl.columns or []),
            }
        )
    return tables


@router.get("/dbsphere/{dbsphere_id}/tables/{table_name}/columns")
async def get_dbsphere_table_columns(
    dbsphere_id: str,
    table_name: str,
    request: Request,
    user=Depends(get_verified_user),
):
    """DbSphere 컬럼 목록 — 용어집 DB 추출 UI에서 호출."""
    from extension_modules.dbsphere.memory.search_memory import (
        SearchEngineDbSphereMemory,
    )

    try:
        memory = SearchEngineDbSphereMemory(
            app=request.app,
            dbsphere_id=dbsphere_id,
            user_id=user.id,
            embedding_func=None,
        )
        ddl_memories = await memory.get_table_schemas()
    except Exception as e:
        log.warning(f"[kg columns] failed for dbsphere {dbsphere_id}: {e}")
        return []

    for ddl in ddl_memories or []:
        if ddl.table_name == table_name:
            return [
                {
                    "name": col.name,
                    "data_type": col.data_type or "",
                    "description": col.description or "",
                    "is_primary_key": col.is_primary_key,
                    "is_foreign_key": col.is_foreign_key,
                }
                for col in (ddl.columns or [])
                if col.name
            ]
    return []


############################
# KG Tool Tester (관리자용)
############################


class ToolTestForm(BaseModel):
    tool_name: str  # kg_resolve_term | kg_search_concepts | kg_explore_context | kg_neighbors | kg_find_related_tables | kg_fetch_data | kg_fetch_document
    args: dict  # 도구별 인자


@router.post("/{id}/test-tool")
async def test_kg_tool(
    id: str,
    request: Request,
    form_data: ToolTestForm,
    user=Depends(get_verified_user),
):
    """KG 도구를 직접 호출해서 결과를 확인 (관리자 테스터).

    에이전트 attach 없이 kg_resolve_term / kg_explore_context 등의
    동작을 바로 시험할 수 있다.
    """
    kg = KnowledgeGraphs.get_kg_by_id(id=id)
    _require_kg_read(kg, user, request)

    from extension_modules.knowledge_graph import KGToolManager

    mgr = KGToolManager(
        app=request.app,
        kg_ids=[id],
        user_id=user.id,
    )
    tools = mgr.get_tools()

    tool = next((t for t in tools if t.name == form_data.tool_name), None)
    if not tool:
        available = [t.name for t in tools]
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT(
                f"Tool not found: {form_data.tool_name}. Available: {available}"
            ),
        )

    try:
        result = await tool.ainvoke(form_data.args)
    except Exception as e:
        return {"tool": form_data.tool_name, "error": str(e), "result": None}

    return {"tool": form_data.tool_name, "error": None, "result": result}


############################
# Export / Import
############################


@router.post("/{id}/export")
async def export_knowledge_graph(
    id: str,
    request: Request,
    user=Depends(get_verified_user),
):
    """KG를 JSON으로 내보내기 (백업/이전용).

    POST를 사용하는 이유: GET /{id}/export는 SvelteKit 프론트엔드 라우트와
    충돌해서 HTML이 반환됨. POST는 프론트엔드에서 가로채지 않음.

    노드, 엣지, knowledge_links, glossary_ids, 후보, 통계를 포함.
    연결된 리소스(DbSphere, KB, Glossary) 자체는 포함하지 않음 — ID만 참조.
    """
    kg = KnowledgeGraphs.get_kg_by_id(id=id)
    _require_kg_read(kg, user, request)

    # 노드 전체 fetch (배치)
    all_nodes = []
    offset = 0
    while True:
        batch = KnowledgeGraphs.get_nodes(id, limit=500, offset=offset)
        if not batch:
            break
        all_nodes.extend(batch)
        if len(batch) < 500:
            break
        offset += 500

    # 엣지 전체 fetch
    all_edges = KnowledgeGraphs.get_all_edges(id, limit=50000)

    # 후보 (pending만)
    candidates = KnowledgeGraphs.get_candidates(id, limit=500)

    # 지식 연결 (새 테이블 + legacy fallback)
    knowledge_links = KnowledgeGraphs.get_knowledge_links(id)

    return {
        "version": 1,
        "kg": kg.model_dump(),
        "knowledge_links": [lnk.model_dump() for lnk in knowledge_links],
        "nodes": [n.model_dump() for n in all_nodes],
        "edges": [e.model_dump() for e in all_edges],
        "candidates": [c.model_dump() for c in candidates],
        "node_count": len(all_nodes),
        "edge_count": len(all_edges),
    }


class ImportForm(BaseModel):
    name: Optional[str] = None  # None이면 원본 이름 사용
    data: dict  # export된 JSON의 전체 내용


@router.post("/create/import", response_model=Optional[KnowledgeGraphResponse])
async def import_knowledge_graph(
    request: Request,
    form_data: ImportForm,
    user=Depends(get_verified_user),
):
    """JSON에서 KG 가져오기 (새 KG로 생성).

    export된 JSON을 받아 새 KG를 생성하고 노드/엣지를 복원한다.
    노드/엣지 ID는 새 KG ID prefix로 재생성되므로 충돌 없음.
    """
    import uuid

    if user.role != "admin" and not has_permission_min_level(
        user.id,
        "workspace.knowledge_graphs",
        "write",
        request.app.state.config.USER_PERMISSIONS,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.UNAUTHORIZED,
        )

    export_data = form_data.data
    if "kg" not in export_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("Invalid export format: missing 'kg' field"),
        )

    orig_kg = export_data["kg"]
    new_name = form_data.name or orig_kg.get("name", "Imported KG")
    new_kg_id = str(uuid.uuid4())

    # KG 생성
    kg_data = orig_kg.get("data") or {}
    new_kg = KnowledgeGraphs.insert_new_kg(
        user.id,
        KnowledgeGraphForm(
            name=new_name,
            description=orig_kg.get("description"),
            data=kg_data,
        ),
    )
    if not new_kg:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("Failed to create KG from import"),
        )

    imported_kg_id = new_kg.id
    old_kg_id = orig_kg.get("id", "")

    # 노드 ID 매핑 (old → new)
    id_map: dict[str, str] = {}

    # 노드 복원
    nodes_imported = 0
    for n in export_data.get("nodes", []):
        old_id = n.get("id", "")
        # old KG ID prefix를 새 것으로 교체
        new_node_id = (
            old_id.replace(old_kg_id, imported_kg_id, 1)
            if old_kg_id
            else f"{imported_kg_id}__{old_id}"
        )
        id_map[old_id] = new_node_id

        KnowledgeGraphs.upsert_node(
            kg_id=imported_kg_id,
            user_id=user.id,
            node_id=new_node_id,
            node_type=n.get("node_type", "doc_entity"),
            label=n.get("label", ""),
            properties=n.get("properties"),
            source_ref=n.get("source_ref"),
        )
        nodes_imported += 1

    # 엣지 복원
    edges_imported = 0
    for e in export_data.get("edges", []):
        old_src = e.get("src_id", "")
        old_dst = e.get("dst_id", "")
        new_src = id_map.get(old_src, old_src)
        new_dst = id_map.get(old_dst, old_dst)

        KnowledgeGraphs.upsert_edge(
            kg_id=imported_kg_id,
            user_id=user.id,
            src_id=new_src,
            dst_id=new_dst,
            edge_type=e.get("edge_type", "related_to"),
            source=e.get("source", "manual"),
            weight=e.get("weight"),
            properties=e.get("properties"),
        )
        edges_imported += 1

    # stats 갱신
    from extension_modules.knowledge_graph import KGService

    svc = KGService.load(imported_kg_id)
    if svc:
        svc.refresh_stats()

    log.info(
        f"[KG import] {imported_kg_id}: {nodes_imported} nodes, "
        f"{edges_imported} edges imported from {old_kg_id[:8]}"
    )

    return KnowledgeGraphs.get_kg_by_id(imported_kg_id)

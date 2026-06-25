"""KG 소스(용어집) 단일 sync — fan-out 백그라운드 워커.

본 워커는 4개의 task type 을 처리한다:

1. `kg_glossary_sync` (부모) — 가볍게 준비 작업만 수행:
   - 용어집 로드, 참조 dbsphere/entries 청크/KB 파일 목록 수집
   - 기존 소스 노드 cleanup (race 방지 차원에서 부모가 한 번만)
   - 카테고리 정의 생성 (KB 매칭용 캐시)
   - progress_total 세팅 후 자식 태스크 fan-out

2. `kg_dbsphere_sync_one` — 참조 dbsphere 스키마 1개 upsert
3. `kg_glossary_entries_chunk` — entries 묶음 1개 upsert
4. `kg_kb_match_file` — KB 파일 1개에 대해 용어집 매칭 수행 → link.status 저장

각 자식은 완료 시 `increment_job_progress` 로 카운터를 올리고
`kg-job-progress` socket 이벤트를 발송한다. 마지막 자식이
`try_claim_job_finalization` 에 성공하면 finalize (KG stats + 검색 인덱스
부분 재구축 + `kg-job-completed` 알림) 를 수행한다.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Optional

from open_webui.env import SRC_LOG_LEVELS
from open_webui.models.knowledge_graph import KnowledgeGraphs
from open_webui.socket.main import send_notification_to_user

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])


DEFAULT_CHUNK_SIZE = 50


def _chunk_size() -> int:
    try:
        return max(1, int(os.environ.get("KG_GLOSSARY_CHUNK_SIZE", DEFAULT_CHUNK_SIZE)))
    except Exception:
        return DEFAULT_CHUNK_SIZE


async def _publish_or_inline(
    app,
    task_type: str,
    payload: dict,
    task_id: str,
) -> None:
    """Redis 가 있으면 publish, 없으면 asyncio.create_task 로 같은 프로세스 실행."""
    from open_webui.services.task_queue import InProcessQueue, TaskMessage

    queue = getattr(app.state, "task_queue", None)
    if queue is None or isinstance(queue, InProcessQueue):
        import asyncio as _asyncio

        if task_type == "kg_dbsphere_sync_one":
            _asyncio.create_task(
                process_kg_dbsphere_sync_one_task(app, task_id, payload)
            )
        elif task_type == "kg_glossary_entries_chunk":
            _asyncio.create_task(
                process_kg_glossary_entries_chunk_task(app, task_id, payload)
            )
        elif task_type == "kg_link_match_phase":
            _asyncio.create_task(
                process_kg_link_match_phase_task(app, task_id, payload)
            )
        elif task_type == "kg_link_match_kb":
            _asyncio.create_task(process_kg_link_match_kb_task(app, task_id, payload))
        elif task_type == "kg_link_db_derivation":
            _asyncio.create_task(
                process_kg_link_db_derivation_task(app, task_id, payload)
            )
        elif task_type == "kg_link_doc_extract":
            _asyncio.create_task(process_kg_doc_extract_task(app, task_id, payload))
        else:
            log.warning(f"[source_sync_worker] unknown inline task: {task_type}")
        return

    await queue.publish(
        TaskMessage(task_type=task_type, payload=payload, task_id=task_id)
    )


async def _advance_progress(
    app,
    parent_job_id: Optional[str],
    user_id: str,
    kg_id: str,
    label: Optional[str] = None,
    success: bool = True,
) -> None:
    """진행률 1 증가 + socket push + fan-in finalize 시도.

    성공/실패와 무관하게 increment — 실패해도 부모가 영원히 대기하지 않도록.
    """
    if not parent_job_id:
        return
    try:
        job = KnowledgeGraphs.increment_job_progress(
            parent_job_id,
            delta=1,
            progress_label=label,
            success_delta=1 if success else 0,
            failure_delta=0 if success else 1,
        )
    except Exception as e:
        log.exception(f"[source_sync_worker] increment_job_progress failed: {e}")
        job = None

    if job:
        await _notify(
            user_id,
            "kg-job-progress",
            kg_id,
            job_id=parent_job_id,
            progress_current=job.progress_current,
            progress_total=job.progress_total,
            progress_label=job.progress_label,
        )

    # Fan-in: 마지막 자식만 성공
    try:
        claimed = KnowledgeGraphs.try_claim_job_finalization(parent_job_id)
    except Exception as e:
        log.exception(f"[source_sync_worker] try_claim_job_finalization failed: {e}")
        return

    if not claimed:
        return

    await _finalize_parent(app, claimed, kg_id, user_id)


async def _maybe_emit_kb_match_warning(
    user_id: str,
    kg_id: str,
    link_id: Optional[str],
    glossary_id: Optional[str],
    claimed_job,
    params: dict,
) -> None:
    """kb_match phase 종료 시 "조용한 실패" 감지 → 경고 소켓 이벤트.

    KB 에 파일이 있었는데 link.status.doc_entity_map 이 비어 있으면
    대부분 KB 필터에 glossary 타입이 설정되지 않았거나 필터 추출 배치가
    아직 안 돌았을 때. 사용자는 sync "성공" 토스트만 받고 KG 가 텅 빈
    상태로 남는 걸 막기 위해 별도 이벤트 발행.
    """
    kb_files_total = int(params.get("kb_files_total") or 0)
    if kb_files_total <= 0 or not link_id:
        return

    try:
        link = KnowledgeGraphs.get_knowledge_link_by_id(link_id)
    except Exception:
        link = None

    doc_map = ((link.status or {}).get("doc_entity_map") or {}) if link else {}
    total_files_matched = len(doc_map)
    total_mentions = sum(len(v or []) for v in doc_map.values())

    if total_files_matched > 0 or total_mentions > 0:
        return

    msg = (
        "KB glossary 필터 결과가 비어 있어 DOCUMENT/MENTIONS 를 생성하지 못했습니다. "
        "KB 필터 스키마에 glossary 타입이 설정돼 있는지, 필터 추출 배치가 완료됐는지 확인하세요."
    )
    log.warning(
        f"[match_phase:finalize] link={link_id[:8]} kb_match_empty: "
        f"{kb_files_total} files queued but 0 matches"
    )
    await _notify(
        user_id,
        "kg-link-sync-warning",
        kg_id,
        job_id=claimed_job.id if claimed_job else None,
        link_id=link_id,
        glossary_id=glossary_id,
        warning="kb_match_empty",
        message=msg,
        kb_files_total=kb_files_total,
    )


async def _finalize_parent(app, claimed_job, kg_id: str, user_id: str) -> None:
    """마지막 자식이 parent 를 complete 로 claim 했을 때 실행되는 마무리.

    Phase 별 chain 분기:
    - kind=glossary_sync (Phase 1) → 글로서리/DB 노드 색인 → Phase 2 (kb_match) chain
    - kind=kb_match (Phase 2) → db_derivation chain
    - kind=db_derivation → doc_extract (문서 단위 관계 추출) chain
    - kind=doc_extract → 최종 완료
    """
    log.info(
        f"[source_sync_worker] finalizing parent job {claimed_job.id} (kind={claimed_job.kind})"
    )

    params = (claimed_job.params or {}) if claimed_job else {}
    glossary_id = params.get("glossary_id")
    link_id = params.get("link_id")
    dbsphere_ids = params.get("dbsphere_ids") or []
    pre_resolved = params.get("pre_resolved_model_config")
    chain_model_id = params.get("model_id")

    # 1. KG stats 갱신
    try:
        from extension_modules.knowledge_graph import KGService

        svc = KGService.load(kg_id)
        if svc:
            svc.refresh_stats()
    except Exception as e:
        log.exception(f"[source_sync_worker] refresh_stats failed: {e}")

    # 2. Phase 1 only: glossary/dbsphere 노드 부분 재색인
    if claimed_job.kind == "glossary_sync":
        try:
            from extension_modules.knowledge_graph import KGNodeIndexService

            index_service = KGNodeIndexService(app)
            touched = []
            prefix_glossary = (
                f"{kg_id}__glossary__{glossary_id}__" if glossary_id else None
            )
            for n in KnowledgeGraphs.get_nodes(kg_id, limit=10000):
                if prefix_glossary and n.id.startswith(prefix_glossary):
                    touched.append(n)
                    continue
                for db_id in dbsphere_ids:
                    if n.id.startswith(f"{kg_id}__dbsphere__{db_id}__"):
                        touched.append(n)
                        break
            if touched:
                await index_service.index_nodes(kg_id, touched)
        except Exception as e:
            log.warning(f"[source_sync_worker] reindex failed (non-fatal): {e}")

    # 3. Chain 분기
    chained = False
    if link_id and pre_resolved and chain_model_id:
        try:
            if claimed_job.kind == "glossary_sync":
                # Phase 1 → Phase 2 (match — KB 필터 결과 기반, LLM 없음)
                kb_files_raw = params.get("kb_files") or []
                kb_files = [tuple(p) for p in kb_files_raw if p and len(p) == 2]
                await _start_match_phase(
                    app=app,
                    kg_id=kg_id,
                    link_id=link_id,
                    user_id=user_id,
                    glossary_id=glossary_id,
                    kb_files=kb_files,
                    pre_resolved_model_config=pre_resolved,
                    model_id=chain_model_id,
                )
                chained = True
            elif claimed_job.kind == "kb_match":
                # Phase 2 fan-in 완료. kb_match_empty 조건이면 별도 warning
                # socket 이벤트 발행 후 db_derivation 으로 계속 진행.
                await _maybe_emit_kb_match_warning(
                    user_id=user_id,
                    kg_id=kg_id,
                    link_id=link_id,
                    glossary_id=glossary_id,
                    claimed_job=claimed_job,
                    params=params,
                )
                await _start_db_derivation_phase(
                    app=app,
                    kg_id=kg_id,
                    link_id=link_id,
                    user_id=user_id,
                    model_id=chain_model_id,
                    pre_resolved_model_config=pre_resolved,
                )
                chained = True
            elif claimed_job.kind == "db_derivation":
                # db_derivation → doc_extract (문서 단위 관계 추출)
                await _start_doc_extract_phase(
                    app=app,
                    kg_id=kg_id,
                    link_id=link_id,
                    user_id=user_id,
                    model_id=chain_model_id,
                    pre_resolved_model_config=pre_resolved,
                )
                chained = True
            # doc_extract → 최종 완료
        except Exception as e:
            log.exception(f"[source_sync_worker] chain to next phase failed: {e}")
    elif link_id:
        log.info(
            f"[source_sync_worker] skip chain — no pre_resolved model "
            f"config on job {claimed_job.id}"
        )

    # 4. Socket 완료 알림 — chain 되지 않은 경우 (마지막 phase) 만 즉시 토스트
    if not chained:
        await _notify(
            user_id,
            "kg-link-sync-completed",
            kg_id,
            job_id=claimed_job.id,
            link_id=link_id,
            glossary_id=glossary_id,
            stats=claimed_job.stats,
        )


async def _start_match_phase(
    app,
    kg_id: str,
    link_id: str,
    user_id: str,
    glossary_id: Optional[str],
    kb_files: list[tuple[str, str]],
    pre_resolved_model_config: dict,
    model_id: str,
) -> None:
    """Phase 2 부모 task — KB 파일 매칭 단계.

    새 KGExtractJob (kind=kb_match) 생성 후 publish. 실제 fan-out 은 워커
    컨텍스트의 ``process_kg_link_match_phase_task`` 가 수행한다.
    """
    job = KnowledgeGraphs.start_job(
        kg_id=kg_id,
        user_id=user_id,
        kind="kb_match",
        target_id=link_id,
        params={
            "link_id": link_id,
            "glossary_id": glossary_id,
            "model_id": model_id,
            "phase": "kb_match",
            "kb_files": [list(p) for p in kb_files],
            "pre_resolved_model_config": pre_resolved_model_config,
        },
        progress_total=max(len(kb_files), 1),
        progress_label=f"Queued {len(kb_files)} files for matching",
    )
    job_id = job.id if job else None
    await _publish_or_inline(
        app,
        "kg_link_match_phase",
        {
            "kg_id": kg_id,
            "link_id": link_id,
            "user_id": user_id,
            "glossary_id": glossary_id,
            "model_id": model_id,
            "kb_files": [list(p) for p in kb_files],
            "pre_resolved_model_config": pre_resolved_model_config,
            "parent_job_id": job_id,
        },
        task_id=job_id or f"{link_id}:match_phase",
    )


async def process_kg_link_match_phase_task(
    app, task_id: str, payload: dict[str, Any]
) -> None:
    """Phase 2 (부모) — KB 별 자식 태스크 fan-out.

    KB 별로 ``kg_link_match_kb`` 자식 태스크를 publish. 자식이
    doc_entity_map 빌드 + DOCUMENT/MENTIONS 배치 upsert 를 수행하고
    ``_advance_progress`` 로 카운터를 올린다. 마지막 자식이
    ``try_claim_job_finalization`` 에 성공하면 ``_finalize_parent`` 가
    kb_match warning 판별 + db_derivation chain 을 돌린다.

    LLM 호출 없음. KB 수에 비례한 병렬도로 실행 (같은 KG 의 여러 링크도
    KB 교집합이 있으면 결정적 ID + ON CONFLICT 로 race-safe).
    """
    kg_id: str = payload["kg_id"]
    link_id: str = payload["link_id"]
    user_id: str = payload["user_id"]
    glossary_id: Optional[str] = payload.get("glossary_id")
    model_id: str = payload["model_id"]
    parent_job_id: Optional[str] = payload.get("parent_job_id")
    pre_resolved: dict = payload["pre_resolved_model_config"]
    kb_files_raw = payload.get("kb_files") or []
    kb_files = [tuple(p) for p in kb_files_raw if p and len(p) == 2]

    # KB ID 목록 추출 (dedupe, 순서 보존)
    kb_ids = list(dict.fromkeys(kb_id for kb_id, _ in kb_files))
    total_kb_files = len(kb_files)

    # KB 가 없으면 즉시 complete → db_derivation 체이닝 (fan-in 스킵)
    if not kb_ids:
        log.info(f"[match_phase] no kb files for link {link_id[:8]}; completing")
        if parent_job_id:
            try:
                KnowledgeGraphs.complete_job(
                    parent_job_id,
                    stats={
                        "files_matched": 0,
                        "mentions_created": 0,
                        "kb_files_total": 0,
                    },
                )
            except Exception:
                pass
            claimed = KnowledgeGraphs.get_job_by_id(parent_job_id)
            if claimed:
                await _finalize_parent(app, claimed, kg_id, user_id)
        return

    # progress_total = KB 수. 자식마다 _advance_progress 로 1씩 증가하면
    # 마지막 자식이 fan-in finalize 를 트리거.
    if parent_job_id:
        try:
            KnowledgeGraphs.update_job_progress(
                parent_job_id,
                progress_current=0,
                progress_total=len(kb_ids),
                progress_label=f"Matching {len(kb_ids)} KBs",
            )
            # kb_files_total 을 finalize 시점에 warning 판별용으로 저장
            try:
                KnowledgeGraphs.set_job_params(
                    parent_job_id,
                    {
                        **(
                            (KnowledgeGraphs.get_job_by_id(parent_job_id).params or {})
                            if KnowledgeGraphs.get_job_by_id(parent_job_id)
                            else {}
                        ),
                        "kb_files_total": total_kb_files,
                    },
                )
            except Exception:
                pass
        except Exception as e:
            log.warning(f"[match_phase] update_job_progress failed: {e}")

    # fan-out — 각 KB 별 자식 태스크
    for kb_idx, knowledge_id in enumerate(kb_ids):
        child_payload = {
            "kg_id": kg_id,
            "link_id": link_id,
            "user_id": user_id,
            "glossary_id": glossary_id,
            "knowledge_id": knowledge_id,
            "model_id": model_id,
            "parent_job_id": parent_job_id,
            "pre_resolved_model_config": pre_resolved,
        }
        child_task_id = (
            f"{parent_job_id or link_id}:match_kb:{kb_idx}:{knowledge_id[:8]}"
        )
        await _publish_or_inline(
            app, "kg_link_match_kb", child_payload, task_id=child_task_id
        )

    log.info(
        f"[match_phase] link={link_id[:8]} fan-out: "
        f"{len(kb_ids)} KB children dispatched"
    )


async def process_kg_link_match_kb_task(
    app, task_id: str, payload: dict[str, Any]
) -> None:
    """Phase 2 자식 — KB 한 개의 doc_entity_map 빌드 + DOCUMENT/MENTIONS 배치 upsert.

    배치 upsert: ``bulk_ensure_documents_and_mentions`` 한 번으로 해당 KB 의
    모든 파일에 대한 DOCUMENT 노드 + CONTAINS_DOCUMENT 엣지 + MENTIONS 엣지를
    단일 트랜잭션에 처리한다 (SQL/AGE 각 1 round-trip per 엣지 타입).

    완료 시 ``_advance_progress`` 로 카운터 증가 → 마지막 자식이 finalize
    트리거.
    """
    from extension_modules.knowledge_graph.sync._age_helpers import get_age_service
    from extension_modules.knowledge_graph.sync._kb_hierarchy import (
        bulk_ensure_documents_and_mentions,
        bulk_upsert_filter_attrs,
        ensure_kb_container_node,
    )
    from extension_modules.knowledge_graph.sync.kb_sync import (
        build_doc_entity_map_from_filter,
        build_filter_attr_map,
    )
    from open_webui.models.knowledge import Knowledges

    kg_id: str = payload["kg_id"]
    link_id: str = payload["link_id"]
    user_id: str = payload["user_id"]
    glossary_id: Optional[str] = payload.get("glossary_id")
    knowledge_id: str = payload["knowledge_id"]
    parent_job_id: Optional[str] = payload.get("parent_job_id")

    label = f"Match KB {knowledge_id[:8]}"
    success = True

    try:
        doc_entity_map = build_doc_entity_map_from_filter(
            kg_id=kg_id,
            glossary_id=glossary_id,
            knowledge_id=knowledge_id,
        )
    except Exception as e:
        log.exception(
            f"[match_kb] build_doc_entity_map failed for KB {knowledge_id[:8]}: {e}"
        )
        doc_entity_map = {}
        success = False

    # 링크 설정에서 사용자가 선택한 필터 slot 들만 doc_attr 노드로 승격.
    # link.config.extracted_filter_slots: [{"kb_id", "slot"}, ...]
    # link.config.filter_edge_names: {"kb_id::slot": "has_xxx"} — LLM/규칙으로 미리 생성
    allowed_slots: list[str] = []
    edge_name_overrides: dict[str, str] = {}
    try:
        link = KnowledgeGraphs.get_knowledge_link_by_id(link_id)
        if link:
            cfg = link.config or {}
            for entry in cfg.get("extracted_filter_slots") or []:
                if not isinstance(entry, dict):
                    continue
                if entry.get("kb_id") != knowledge_id:
                    continue
                slot = entry.get("slot")
                if isinstance(slot, str) and slot:
                    allowed_slots.append(slot)
            names_raw = cfg.get("filter_edge_names") or {}
            if isinstance(names_raw, dict):
                prefix = f"{knowledge_id}::"
                for k, v in names_raw.items():
                    if (
                        isinstance(k, str)
                        and isinstance(v, str)
                        and k.startswith(prefix)
                        and v
                    ):
                        edge_name_overrides[k[len(prefix) :]] = v
    except Exception as e:
        log.warning(
            f"[match_kb] load extracted_filter_slots failed for link={link_id[:8]}: {e}"
        )

    try:
        filter_attr_map = build_filter_attr_map(
            kg_id=kg_id,
            knowledge_id=knowledge_id,
            allowed_slots=allowed_slots,
            glossary_id=glossary_id,
            edge_name_overrides=edge_name_overrides,
        )
    except Exception as e:
        log.exception(
            f"[match_kb] build_filter_attr_map failed for KB {knowledge_id[:8]}: {e}"
        )
        filter_attr_map = {}

    # filter_attr 가 있지만 glossary 매칭이 없는 파일도 DOCUMENT 노드가 필요.
    # doc_entity_map 에 빈 매칭으로 등록 → bulk_ensure_documents_and_mentions 가
    # DOCUMENT 만 생성하고 MENTIONS 는 skip 한다.
    for fid in filter_attr_map:
        doc_entity_map.setdefault(fid, [])

    if doc_entity_map:
        # link.status 에 doc_entity_map 저장 (idempotent upsert 패턴)
        try:
            links = [
                lk
                for lk in KnowledgeGraphs.get_knowledge_links(kg_id)
                if lk.glossary_id == glossary_id
                and knowledge_id in (lk.knowledge_ids or [])
            ]
            for lk in links:
                existing = dict(lk.status or {})
                existing_map = dict(existing.get("doc_entity_map") or {})
                existing_map.update(doc_entity_map)
                existing["doc_entity_map"] = existing_map
                existing["documents_matched"] = len(existing_map)
                existing["last_matched_at"] = int(time.time())
                KnowledgeGraphs.update_knowledge_link_status(lk.id, existing)
        except Exception as e:
            log.exception(
                f"[match_kb] failed to save doc_entity_map for KB {knowledge_id[:8]}: {e}"
            )
            success = False

        # KB 컨테이너 (단일 upsert — idempotent) + 나머지는 배치
        try:
            kb_row = Knowledges.get_knowledge_by_id(knowledge_id)
        except Exception:
            kb_row = None
        age = get_age_service(kg_id)
        kb_nid = ensure_kb_container_node(
            kg_id=kg_id,
            knowledge_id=knowledge_id,
            user_id=user_id,
            age=age,
            kb_name=getattr(kb_row, "name", None) if kb_row else None,
            kb_description=(getattr(kb_row, "description", None) if kb_row else None),
        )
        try:
            stats = bulk_ensure_documents_and_mentions(
                kg_id=kg_id,
                knowledge_id=knowledge_id,
                user_id=user_id,
                doc_entity_map=doc_entity_map,
                age=age,
                kb_nid=kb_nid,
            )
            log.info(
                f"[match_kb] kb={knowledge_id[:8]}: "
                f"{stats['documents']} docs, {stats['mentions']} mentions"
            )
        except Exception as e:
            log.exception(
                f"[match_kb] bulk_ensure_documents_and_mentions failed for KB {knowledge_id[:8]}: {e}"
            )
            success = False

        # filter_attr_map 의 attr 노드 + has_{slot} 엣지 배치.
        # DOCUMENT 노드가 위에서 생성된 직후여야 엣지 MATCH 가 성공한다.
        if filter_attr_map:
            try:
                attr_stats = bulk_upsert_filter_attrs(
                    kg_id=kg_id,
                    knowledge_id=knowledge_id,
                    user_id=user_id,
                    filter_attr_map=filter_attr_map,
                    age=age,
                )
                # 사용된 엣지 타입들을 KG 레지스트리에 등록 (카탈로그에 seed 로 노출)
                for et in attr_stats.get("edge_types") or []:
                    try:
                        KnowledgeGraphs.register_edge_type(
                            kg_id=kg_id,
                            name=et,
                            description=None,
                            source="filter",
                        )
                    except Exception as e:
                        log.warning(f"[match_kb] register_edge_type({et}) failed: {e}")
                log.info(
                    f"[match_kb] kb={knowledge_id[:8]} filter_attrs: "
                    f"{attr_stats['attr_nodes']} nodes, "
                    f"{attr_stats['attr_edges']} edges, "
                    f"types={attr_stats['edge_types']}"
                )
            except Exception as e:
                log.exception(
                    f"[match_kb] bulk_upsert_filter_attrs failed for KB {knowledge_id[:8]}: {e}"
                )
                success = False
    else:
        log.info(f"[match_kb] kb={knowledge_id[:8]}: doc_entity_map empty — skipped")

    await _advance_progress(app, parent_job_id, user_id, kg_id, label, success=success)


async def _start_db_derivation_phase(
    app,
    kg_id: str,
    link_id: str,
    user_id: str,
    model_id: str,
    pre_resolved_model_config: dict,
) -> None:
    """Phase 4 부모 task 시작 — DB 기반 cross-category 엣지 파생.

    Phase 3 (kb_extract) 종료 후 `_finalize_parent` 에서 chain 으로 호출.
    """
    job = KnowledgeGraphs.start_job(
        kg_id=kg_id,
        user_id=user_id,
        kind="db_derivation",
        target_id=link_id,
        params={
            "link_id": link_id,
            "model_id": model_id,
            "phase": "db_derivation",
            "pre_resolved_model_config": pre_resolved_model_config,
        },
        progress_total=1,
        progress_label="Queued DB derivation",
    )
    job_id = job.id if job else None
    await _publish_or_inline(
        app,
        "kg_link_db_derivation",
        {
            "kg_id": kg_id,
            "link_id": link_id,
            "user_id": user_id,
            "model_id": model_id,
            "pre_resolved_model_config": pre_resolved_model_config,
            "parent_job_id": job_id,
        },
        task_id=job_id or f"{link_id}:db_derivation",
    )


async def process_kg_link_db_derivation_task(
    app, task_id: str, payload: dict[str, Any]
) -> None:
    """Phase 4 — DB 기반 cross-category 엣지 파생 실행.

    자식 fan-out 없이 부모 혼자 plan → cleanup → execute 순으로 처리.
    각 plan 이 끝날 때마다 progress 를 increment 하고, 모든 plan 이 끝나면
    `_advance_progress` 로 fan-in finalize 트리거 → `_finalize_parent` 가
    chain 없음 → 최종 완료 알림.
    """
    from extension_modules.knowledge_graph.sync.db_derivation import (
        run_db_derivation_for_link,
    )

    kg_id: str = payload["kg_id"]
    link_id: str = payload["link_id"]
    user_id: str = payload["user_id"]
    parent_job_id: Optional[str] = payload.get("parent_job_id")
    pre_resolved: dict = payload.get("pre_resolved_model_config") or {}

    if not pre_resolved:
        log.warning(
            f"[db_derivation_phase] link={link_id[:8]} no pre_resolved model config"
        )
        if parent_job_id:
            KnowledgeGraphs.fail_job(parent_job_id, errors=["no LLM model config"])
        await _notify(
            user_id,
            "kg-link-sync-completed",
            kg_id,
            job_id=parent_job_id,
            link_id=link_id,
            stats={"plans_total": 0},
        )
        return

    try:
        stats = await run_db_derivation_for_link(
            app=app,
            kg_id=kg_id,
            link_id=link_id,
            user_id=user_id,
            pre_resolved_model_config=pre_resolved,
        )
    except Exception as e:
        log.exception(f"[db_derivation_phase] run failed: {e}")
        if parent_job_id:
            KnowledgeGraphs.fail_job(parent_job_id, errors=[str(e)])
        await _notify(
            user_id,
            "kg-link-sync-completed",
            kg_id,
            job_id=parent_job_id,
            link_id=link_id,
            error=str(e),
        )
        return

    log.info(
        f"[db_derivation_phase] link={link_id[:8]} done: "
        f"plans={stats.get('plans_total', 0)} "
        f"edges={stats.get('edges_created', 0)} "
        f"rows={stats.get('rows_scanned', 0)} "
        f"unmatched={stats.get('unmatched_rows', 0)}"
    )

    # job 완료 마크 + _finalize_parent 직접 호출 → Phase 3 로 chain
    # (single-worker phase 라 fan-in claim 없이 바로 finalize 가능)
    if parent_job_id:
        try:
            KnowledgeGraphs.complete_job(parent_job_id, stats=stats)
        except Exception as e:
            log.warning(f"[db_derivation_phase] complete_job failed: {e}")
        claimed = KnowledgeGraphs.get_job_by_id(parent_job_id)
        if claimed:
            await _finalize_parent(app, claimed, kg_id, user_id)
    else:
        # parent_job_id 없으면 KG stats 만 refresh
        try:
            from extension_modules.knowledge_graph import KGService

            svc = KGService.load(kg_id)
            if svc:
                svc.refresh_stats()
        except Exception as e:
            log.warning(f"[db_derivation_phase] refresh_stats failed: {e}")


# ─────────────────────────────────────────────
# 부모: kg_link_sync
# ─────────────────────────────────────────────


async def process_kg_link_sync_task(app, task_id: str, payload: dict[str, Any]) -> None:
    """부모 태스크 — 지식 연결 1개를 통합 sync.

    링크는 (glossary_id, knowledge_ids[]) 쌍을 담으며, 이 함수는
      1) 링크에 매달린 용어집의 참조 dbsphere 스키마 추출
      2) 용어집 entries → TERM/CONCEPT 노드 + MAPS_TO 엣지 추출
      3) 링크의 knowledge_ids 범위 안에서만 KB 파일 → TERM 매칭
    을 한 묶음으로 fan-out 한다.

    payload: {
      kg_id, link_id, user_id, job_id,
      pre_resolved_model_config (optional, HTTP 요청 컨텍스트에서 주입),
      model_id (optional, fallback resolve 용)
    }
    """
    kg_id: str = payload["kg_id"]
    link_id: str = payload["link_id"]
    user_id: str = payload["user_id"]
    job_id: Optional[str] = payload.get("job_id")
    payload_pre_resolved: Optional[dict] = payload.get("pre_resolved_model_config")
    payload_model_id: Optional[str] = payload.get("model_id")

    from extension_modules.knowledge_graph.sync.glossary_sync import (
        cleanup_glossary_nodes,
        get_referenced_dbsphere_ids,
    )
    from extension_modules.knowledge_graph.sync.kb_sync import (
        ensure_glossary_category_definitions,
    )
    from extension_modules.utils.llm import get_model_config_from_app
    from open_webui.models.glossary import Glossaries
    from open_webui.models.knowledge import Knowledges

    link = KnowledgeGraphs.get_knowledge_link_by_id(link_id)
    if not link or link.kg_id != kg_id:
        msg = f"Knowledge link not found: {link_id}"
        log.warning(f"[source_sync_worker] {msg}")
        if job_id:
            KnowledgeGraphs.fail_job(job_id, errors=[msg])
        return

    glossary_id = link.glossary_id
    if not glossary_id:
        msg = f"Link {link_id[:8]} has no glossary_id"
        log.warning(f"[source_sync_worker] {msg}")
        if job_id:
            KnowledgeGraphs.fail_job(job_id, errors=[msg])
        return

    glossary = Glossaries.get_glossary_by_id(glossary_id)
    if not glossary:
        msg = f"Glossary not found: {glossary_id}"
        log.warning(f"[source_sync_worker] {msg}")
        if job_id:
            KnowledgeGraphs.fail_job(job_id, errors=[msg])
        return

    # 1. 참조 dbsphere 수집.
    #    link.config.dbsphere_ids 가 명시적으로 주어졌으면 그 subset 만 쓰고,
    #    없으면 glossary.extraction_sources 전체(fallback).
    link_config = dict(link.config or {})
    configured_dbs = link_config.get("dbsphere_ids")
    if isinstance(configured_dbs, list) and configured_dbs:
        dbsphere_ids = [ds for ds in configured_dbs if ds]
    else:
        dbsphere_ids = get_referenced_dbsphere_ids(glossary_id)

    # 2. entries → 청크 분할
    entries = (glossary.data or {}).get("entries") or []
    entry_ids = [e.get("id") for e in entries if e.get("id")]
    N = _chunk_size()
    entry_chunks: list[list[str]] = [
        entry_ids[i : i + N] for i in range(0, len(entry_ids), N)
    ]

    # 3. KB 파일 목록 — 이 링크의 knowledge_ids 범위에서만
    link_kb_ids = list(link.knowledge_ids or [])
    kb_files: list[tuple[str, str]] = []
    for kb_id in link_kb_ids:
        try:
            kb = Knowledges.get_knowledge_by_id(id=kb_id)
        except Exception:
            kb = None
        if not kb:
            continue
        for file_id in (kb.data or {}).get("file_ids") or []:
            if file_id:
                kb_files.append((kb_id, file_id))

    # Phase 1 은 db + entries 만 (LLM 미사용, 빠름).
    # Match phase 는 chain 으로 _start_match_phase 에서 별도 부모 job 으로 시작.
    total = len(dbsphere_ids) + len(entry_chunks)

    # 4. 기존 소스 cleanup — 자식이 돌기 전에 부모가 한 번만
    #    이 링크가 참조하는 용어집/dbsphere prefix 노드를 정리한다.
    #    같은 용어집을 참조하는 다른 링크가 있어도 결정적 node_id 라 문제 없음.
    cleanup_glossary_nodes(kg_id, glossary_id)
    for db_id in dbsphere_ids:
        try:
            KnowledgeGraphs.delete_nodes_by_source(kg_id, "dbsphere", db_id)
        except Exception as e:
            log.exception(
                f"[source_sync_worker] dbsphere cleanup {db_id[:8]} failed: {e}"
            )

    # 5. 카테고리 정의 캐시 확보 (KB 매칭 자식들이 공유)
    # HTTP 요청 컨텍스트에서 주입된 pre_resolved 를 우선 사용, 없으면 fallback
    kg = KnowledgeGraphs.get_kg_by_id(kg_id)
    options = ((kg.data or {}).get("options") or {}) if kg else {}
    model_id = payload_model_id or options.get("llm_model_id")
    pre_resolved = payload_pre_resolved
    if not pre_resolved and model_id:
        pre_resolved = get_model_config_from_app(app, model_id)
    if kb_files:
        if pre_resolved:
            try:
                await ensure_glossary_category_definitions(app, glossary, pre_resolved)
            except Exception as e:
                log.warning(
                    f"[source_sync_worker] category definition generation failed: {e}"
                )
        else:
            log.info(
                f"[source_sync_worker] no llm model configured for kg={kg_id[:8]}; "
                f"KB matching may skip"
            )

    # 6. progress_total 세팅 + finalize 에 필요한 컨텍스트 저장
    # pre_resolved_model_config 를 job.params 에 함께 저장해서 finalize 단계
    # (백그라운드 워커 컨텍스트) 가 Phase 3 chain 할 때 자격증명 손실 없이 전달.
    if job_id:
        try:
            KnowledgeGraphs.set_job_params(
                job_id,
                {
                    "link_id": link_id,
                    "glossary_id": glossary_id,
                    "dbsphere_ids": list(dbsphere_ids),
                    "chunk_size": N,
                    "entry_chunk_count": len(entry_chunks),
                    # Phase 2 (match phase) 가 chain 시 사용. 페어 list 는 JSON
                    # 직렬화 가능하도록 list of [kb_id, file_id] 형식.
                    "kb_files": [[kb_id, file_id] for kb_id, file_id in kb_files],
                    "kb_file_count": len(kb_files),
                    "pre_resolved_model_config": pre_resolved,
                    "model_id": model_id,
                },
            )
        except Exception:
            pass
        try:
            KnowledgeGraphs.update_job_progress(
                job_id,
                progress_current=0,
                progress_total=max(total, 0),
                progress_label="Dispatching..." if total else "Nothing to do",
            )
        except Exception as e:
            log.exception(f"[source_sync_worker] update_job_progress failed: {e}")

    if total == 0:
        if job_id:
            try:
                KnowledgeGraphs.complete_job(
                    job_id,
                    stats={
                        "dbspheres_synced": 0,
                        "entries_synced": 0,
                        "files_matched": 0,
                    },
                )
            except Exception:
                pass
        await _notify(
            user_id,
            "kg-link-sync-completed",
            kg_id,
            job_id=job_id,
            link_id=link_id,
            glossary_id=glossary_id,
            stats={"dbspheres_synced": 0, "entries_synced": 0, "files_matched": 0},
        )
        return

    # 7. fan-out — dbsphere 자식
    for i, db_id in enumerate(dbsphere_ids):
        await _publish_or_inline(
            app,
            "kg_dbsphere_sync_one",
            {
                "kg_id": kg_id,
                "dbsphere_id": db_id,
                "user_id": user_id,
                "parent_job_id": job_id,
            },
            task_id=f"{job_id or link_id}:db:{i}",
        )

    # 8. fan-out — entries 청크 자식
    for i, chunk in enumerate(entry_chunks):
        await _publish_or_inline(
            app,
            "kg_glossary_entries_chunk",
            {
                "kg_id": kg_id,
                "glossary_id": glossary_id,
                "entry_ids": chunk,
                "chunk_index": i,
                "chunk_total": len(entry_chunks),
                "user_id": user_id,
                "parent_job_id": job_id,
            },
            task_id=f"{job_id or link_id}:entries:{i}",
        )

    # match_file 자식은 Phase 2 (kb_match) 에서 별도 부모로 시작 — 여기서 fan-out 안 함

    log.info(
        f"[source_sync_worker] Phase 1 fan-out complete for link {link_id[:8]} "
        f"(glossary {glossary_id[:8]}): "
        f"{len(dbsphere_ids)} dbspheres, {len(entry_chunks)} entry chunks "
        f"(match phase will be chained after fan-in)"
    )


# ─────────────────────────────────────────────
# 자식: kg_dbsphere_sync_one
# ─────────────────────────────────────────────


async def process_kg_dbsphere_sync_one_task(
    app, task_id: str, payload: dict[str, Any]
) -> None:
    """dbsphere 스키마 1개 upsert 후 진행률 증가."""
    from extension_modules.knowledge_graph import sync_dbsphere_to_kg

    kg_id: str = payload["kg_id"]
    dbsphere_id: str = payload["dbsphere_id"]
    user_id: str = payload["user_id"]
    parent_job_id: Optional[str] = payload.get("parent_job_id")

    label = f"Database schema: {dbsphere_id[:8]}"
    success = True
    try:
        await sync_dbsphere_to_kg(app, kg_id, dbsphere_id, user_id)
    except Exception as e:
        log.exception(
            f"[source_sync_worker] dbsphere sync failed {dbsphere_id[:8]}: {e}"
        )
        success = False

    await _advance_progress(app, parent_job_id, user_id, kg_id, label, success=success)


# ─────────────────────────────────────────────
# 자식: kg_glossary_entries_chunk
# ─────────────────────────────────────────────


async def process_kg_glossary_entries_chunk_task(
    app, task_id: str, payload: dict[str, Any]
) -> None:
    """entries 청크 1개 upsert 후 진행률 증가."""
    from extension_modules.knowledge_graph.sync.glossary_sync import (
        sync_glossary_entries_chunk,
    )

    kg_id: str = payload["kg_id"]
    glossary_id: str = payload["glossary_id"]
    user_id: str = payload["user_id"]
    entry_ids: list[str] = payload.get("entry_ids") or []
    chunk_index: int = int(payload.get("chunk_index", 0))
    chunk_total: int = int(payload.get("chunk_total", 1))
    parent_job_id: Optional[str] = payload.get("parent_job_id")

    label = f"Glossary chunk {chunk_index + 1}/{chunk_total}"
    success = True
    try:
        # 동기 SQL 블록을 스레드로 offload 해 이벤트 루프 블로킹 최소화
        import asyncio as _asyncio

        await _asyncio.to_thread(
            sync_glossary_entries_chunk, kg_id, glossary_id, user_id, entry_ids
        )
    except Exception as e:
        log.exception(
            f"[source_sync_worker] entries chunk failed "
            f"({chunk_index + 1}/{chunk_total}): {e}"
        )
        success = False

    await _advance_progress(app, parent_job_id, user_id, kg_id, label, success=success)


# ─────────────────────────────────────────────
# Socket helper
# ─────────────────────────────────────────────


async def _notify(user_id: str, event_type: str, kg_id: str, **extra) -> None:
    try:
        await send_notification_to_user(
            user_id=user_id,
            event_type=event_type,
            data={"kg_id": kg_id, **extra},
        )
    except Exception as e:
        log.warning(f"[source_sync_worker] notify failed: {e}")


# ─────────────────────────────────────────────
# doc_extract phase (문서 단위 관계 추출)
# ─────────────────────────────────────────────


async def _start_doc_extract_phase(
    app,
    kg_id: str,
    link_id: str,
    user_id: str,
    model_id: str,
    pre_resolved_model_config: dict,
) -> None:
    """문서 단위 관계 추출 Phase 시작.

    db_derivation 완료 후 `_finalize_parent` 에서 chain 으로 호출.
    """
    job = KnowledgeGraphs.start_job(
        kg_id=kg_id,
        user_id=user_id,
        kind="doc_extract",
        target_id=link_id,
        params={
            "link_id": link_id,
            "model_id": model_id,
            "phase": "doc_extract",
            "pre_resolved_model_config": pre_resolved_model_config,
        },
        progress_total=1,
        progress_label="Queued document-level extraction",
    )
    job_id = job.id if job else None
    await _publish_or_inline(
        app,
        "kg_link_doc_extract",
        {
            "kg_id": kg_id,
            "link_id": link_id,
            "user_id": user_id,
            "model_id": model_id,
            "pre_resolved_model_config": pre_resolved_model_config,
            "parent_job_id": job_id,
        },
        task_id=job_id or f"{link_id}:doc_extract",
    )


async def process_kg_doc_extract_task(
    app, task_id: str, payload: dict[str, Any]
) -> None:
    """문서 단위 관계 추출 — 청크 fan-out 방식.

    doc_entity_map 에 있는 각 파일의 청크들을 수집하고 기존
    ``kg_kb_chunk`` 태스크로 fan-out 한다. 기존 Phase 3 와 동일한 병렬
    처리이지만 ``provenance_node_id`` 를 통해 DOCUMENT 에 귀속된다.
    """
    from extension_modules.knowledge_graph.sync._age_helpers import get_age_service
    from extension_modules.knowledge_graph.sync._node_ids import (
        document_node_id as _document_node_id,
    )
    from open_webui.models.knowledge import Knowledges
    from open_webui.retrieval.knowledge_service import SearchEngineKnowledge
    from open_webui.services.task_queue import InProcessQueue, TaskMessage

    kg_id: str = payload["kg_id"]
    link_id: str = payload["link_id"]
    user_id: str = payload["user_id"]
    parent_job_id: Optional[str] = payload.get("parent_job_id")
    pre_resolved = payload.get("pre_resolved_model_config")

    link = KnowledgeGraphs.get_knowledge_link_by_id(link_id)
    if not link or link.kg_id != kg_id:
        log.warning(f"[doc_extract] link not found: {link_id}")
        if parent_job_id:
            KnowledgeGraphs.fail_job(parent_job_id, errors=["link not found"])
        return

    if not pre_resolved:
        log.warning("[doc_extract] no pre_resolved model config")
        if parent_job_id:
            KnowledgeGraphs.fail_job(parent_job_id, errors=["no model config"])
        return

    kg_row = KnowledgeGraphs.get_kg_by_id(kg_id)
    kg_name = (kg_row.name if kg_row else None) or None
    kg_description = (kg_row.description if kg_row else None) or None

    # 엣지 카탈로그 — cross-category 제외 (db_derivation 에서 처리됨)
    link_config = dict(link.config or {})
    edge_types = link_config.get("edge_types") or {}
    edge_types_locked = bool(link_config.get("edge_types_locked"))
    filtered_edge_types: dict[str, dict] = {}
    for key, entry in edge_types.items():
        if not isinstance(entry, dict):
            continue
        src_cat = entry.get("src_category")
        dst_cat = entry.get("dst_category")
        # cross-category(두 term category 사이) 엣지는 Phase 3 db_derivation 전용.
        # dst_category="doc_entity" 는 "문서/청크 속성" 엣지라 cross 가 아님 — 유지.
        if src_cat and dst_cat and src_cat != dst_cat and dst_cat != "doc_entity":
            continue
        filtered_edge_types[key] = entry

    link_status = link.status or {}
    doc_entity_map = link_status.get("doc_entity_map") or {}
    glossary_id = link.glossary_id or ""
    knowledge_ids = list(link.knowledge_ids or [])

    if not doc_entity_map:
        log.info(f"[doc_extract] link {link_id[:8]} has no doc_entity_map")
        if parent_job_id:
            KnowledgeGraphs.complete_job(parent_job_id, stats={"chunks_enqueued": 0})
            claimed = KnowledgeGraphs.get_job_by_id(parent_job_id)
            if claimed:
                await _finalize_parent(app, claimed, kg_id, user_id)
        return

    # ── 청크 수집 + fan-out ──
    age = get_age_service(kg_id)
    queue = getattr(app.state, "task_queue", None)
    inline = queue is None or isinstance(queue, InProcessQueue)

    # file_anchors 구축 (doc_entity_map → 파일별 앵커)
    file_anchors_global: dict[str, list[dict]] = {}
    for file_id, matches in doc_entity_map.items():
        file_anchors_global[file_id] = [
            {
                "node_id": m["entity_node_id"],
                "label": m["entity_label"],
                "glossary_id": glossary_id,
                "category": m.get("category"),
            }
            for m in matches
        ]

    enqueued = 0
    failed = 0
    job_errors: list[str] = []

    # 1. 청크 수집 — publish 전에 전체 량을 먼저 파악해야 progress_total 을
    #    race-safe 하게 먼저 기록할 수 있다. 이전엔 publish → 첫 자식 완료가
    #    progress_total 업데이트보다 먼저 일어나 "15/1" 같은 이상한 비율이
    #    UI 에 노출되는 cosmetic bug 가 있었다.
    pending_payloads: list[tuple[str, dict]] = []  # [(chunk_id, payload), ...]

    for kb_id in knowledge_ids:
        try:
            kb = Knowledges.get_knowledge_by_id(kb_id)
            kb_data = (kb.data or {}) if kb else {}
            kb_file_ids = set(kb_data.get("file_ids") or [])
        except Exception:
            kb = None
            kb_data = {}
            kb_file_ids = set()

        ks = SearchEngineKnowledge(app=app, collection_name=kb_id)

        for file_id in kb_file_ids:
            if file_id not in file_anchors_global:
                continue

            file_anchors = file_anchors_global[file_id]
            doc_nid = _document_node_id(kg_id, kb_id, file_id)

            try:
                chunks = await ks.query_by_metadata({"file_id": file_id}, limit=10000)
            except Exception as e:
                job_errors.append(f"file {file_id[:8]} chunks: {e}")
                continue

            for ch in chunks:
                content = (ch.content or "").strip()
                if not content or len(content) < 50:
                    continue
                if len(content) > 4000:
                    content = content[:4000]

                chunk_payload = {
                    "kg_id": kg_id,
                    "knowledge_id": kb_id,
                    "user_id": user_id,
                    "chunk_id": ch.id,
                    "chunk_content": content,
                    "file_anchors": file_anchors,
                    "edge_types": filtered_edge_types,
                    "edge_types_locked": edge_types_locked,
                    "llm_config": pre_resolved,
                    "min_confidence": 0.6,
                    "job_id": parent_job_id,
                    "kg_name": kg_name,
                    "kg_description": kg_description,
                    "provenance_node_id": doc_nid,
                }
                pending_payloads.append((ch.id, chunk_payload))

    planned_total = len(pending_payloads)

    # 2. progress_total 을 publish 이전에 설정 — 첫 자식의 increment 가
    #    parent 의 total 보다 먼저 오는 race 를 방지.
    if parent_job_id:
        try:
            from open_webui.internal.db import get_db
            from open_webui.models.knowledge_graph import KGExtractJob

            with get_db() as db:
                row = db.query(KGExtractJob).filter_by(id=parent_job_id).first()
                if row:
                    row.progress_total = max(planned_total, 1)
                    row.progress_label = f"Queued {planned_total} chunks for extraction"
                    db.commit()
        except Exception as e:
            log.warning(f"[doc_extract] set progress_total failed: {e}")

    # 3. 실제 publish — 이제 progress_total 이 확정됐으므로 race 없음.
    for chunk_id, chunk_payload in pending_payloads:
        try:
            if inline:
                import asyncio as _asyncio

                from extension_modules.knowledge_graph.kb_chunk_worker import (
                    process_kb_chunk_task,
                )

                _asyncio.create_task(
                    process_kb_chunk_task(app, chunk_id, chunk_payload)
                )
            else:
                await queue.publish(
                    TaskMessage(
                        task_type="kg_kb_chunk",
                        payload=chunk_payload,
                        max_retries=3,
                    )
                )
            enqueued += 1
        except Exception as e:
            log.exception(f"[doc_extract] publish failed: {e}")
            failed += 1

    if failed > 0 and parent_job_id:
        try:
            KnowledgeGraphs.increment_job_progress(
                parent_job_id, delta=failed, failure_delta=failed
            )
        except Exception:
            pass

    log.info(
        f"[doc_extract] link={link_id[:8]}: "
        f"enqueued {enqueued} chunks across {len(knowledge_ids)} KBs"
    )

    # enqueued=0 이면 fan-in 이 안 일어나므로 직접 완료 처리
    if enqueued == 0 and parent_job_id:
        try:
            KnowledgeGraphs.complete_job(
                parent_job_id,
                stats={"chunks_enqueued": 0},
                errors=job_errors[:20] or None,
            )
        except Exception:
            pass
        claimed = KnowledgeGraphs.get_job_by_id(parent_job_id)
        if claimed:
            await _finalize_parent(app, claimed, kg_id, user_id)

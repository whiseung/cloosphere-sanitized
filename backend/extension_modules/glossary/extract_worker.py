"""용어집 DB 값 추출 — 백그라운드 워커.

`task_queue` 의 `glossary_extract_values` task type 을 처리한다. 흐름:

1. router(`POST /glossary/{id}/extract-values`) 가 즉시 잡 메타데이터를
   `glossary.meta.extract_job` 에 기록(status=queued) 후 Redis Stream 에
   발행하고 응답한다.
2. 컨슈머가 본 워커를 호출 → SQL 추출 → LLM enrichment → preview entries
   를 다시 `meta.extract_job.result` 에 저장(status=succeeded).
3. 사용자는 용어집 상세에서 단건/전체 accept 또는 discard 한다.

진행률은 LLM 배치마다 `meta.extract_job.progress.{current,total}` 로
업데이트되며, 각 배치 시작 전 사용자가 `cancel` 했는지(`status==canceled`)
재조회해서 즉시 중단한다.
"""

from __future__ import annotations

import copy
import logging
import time
import uuid
from typing import Any, Optional

from extension_modules.glossary.value_enrich import generate_entries_batch
from extension_modules.utils.llm import get_model_config_from_app
from open_webui.env import SRC_LOG_LEVELS
from open_webui.models.dbsphere import DbSpheres
from open_webui.models.glossary import Glossaries
from open_webui.socket.main import send_notification_to_user

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])


# ───────────────────────── 헬퍼 ─────────────────────────


def _now() -> int:
    return int(time.time())


def _get_runner(db_config):
    """DBType → SQL Runner 인스턴스."""
    from extension_modules.dbsphere.dbsphere_state import DBType
    from extension_modules.dbsphere.sql_runners.databricks import DatabricksRunner
    from extension_modules.dbsphere.sql_runners.fabric import FabricRunner
    from extension_modules.dbsphere.sql_runners.mssql import MSSQLRunner
    from extension_modules.dbsphere.sql_runners.mysql import MySQLRunner
    from extension_modules.dbsphere.sql_runners.oracle import OracleRunner
    from extension_modules.dbsphere.sql_runners.postgres import PostgresRunner
    from extension_modules.dbsphere.sql_runners.snowflake import SnowflakeRunner
    from extension_modules.dbsphere.sql_runners.synapse import SynapseRunner

    runner_map = {
        DBType.POSTGRES: PostgresRunner,
        DBType.MYSQL: MySQLRunner,
        DBType.MSSQL: MSSQLRunner,
        DBType.ORACLE: OracleRunner,
        DBType.SNOWFLAKE: SnowflakeRunner,
        DBType.DATABRICKS: DatabricksRunner,
        DBType.SYNAPSE: SynapseRunner,
        DBType.FABRIC: FabricRunner,
    }
    db_type = db_config.get_db_type_enum()
    runner_cls = runner_map.get(db_type)
    if not runner_cls:
        raise ValueError(f"Unsupported database type: {db_type}")
    return runner_cls(db_config), db_type


async def _run_sql_extraction(
    glossary_id: str,
    params: dict,
) -> dict:
    """SQL 실행 + 행 파싱. 반환: dict with `values`, `db_synonyms`, `db_descriptions`,
    `value_contexts`, `context_cols_list`, `total_values`, `new_values`, `skipped`."""
    from extension_modules.dbsphere.dbsphere_state import DBConfig, DBType
    from open_webui.routers.dbsphere import decrypt_connection_password

    dbsphere_id = params["dbsphere_id"]
    table_name = params["table_name"]
    column_name = params["column_name"]
    synonym_column = params.get("synonym_column") or ""
    description_column = params.get("description_column") or ""
    raw_context_columns = params.get("context_columns") or []

    dbsphere = DbSpheres.get_dbsphere_by_id(dbsphere_id)
    if not dbsphere or not dbsphere.data:
        raise ValueError(f"DbSphere not found: {dbsphere_id}")

    data = decrypt_connection_password(copy.deepcopy(dbsphere.data))
    db_config = DBConfig.from_dbsphere_data(data)
    runner, db_type = _get_runner(db_config)

    q = "`" if db_type in (DBType.MYSQL, DBType.DATABRICKS) else '"'
    col = f"{q}{column_name}{q}"
    tbl = f"{q}{table_name}{q}"

    has_synonym_col = bool(synonym_column)
    has_desc_col = bool(description_column)
    select_cols = [col]
    if has_synonym_col:
        select_cols.append(f"{q}{synonym_column}{q}")
    if has_desc_col:
        select_cols.append(f"{q}{description_column}{q}")

    reserved_cols = {column_name, synonym_column, description_column}
    seen_ctx: set[str] = set()
    context_cols_list: list[str] = []
    for c in raw_context_columns:
        if not c or c in reserved_cols or c in seen_ctx:
            continue
        seen_ctx.add(c)
        context_cols_list.append(c)
    for cc in context_cols_list:
        select_cols.append(f"{q}{cc}{q}")

    if has_synonym_col or has_desc_col or context_cols_list:
        sql = (
            f"SELECT DISTINCT {', '.join(select_cols)} "
            f"FROM {tbl} "
            f"WHERE {col} IS NOT NULL "
            f"ORDER BY {col}"
        )
    else:
        sql = f"SELECT DISTINCT {col} FROM {tbl} WHERE {col} IS NOT NULL ORDER BY {col}"

    df = await runner.run_sql(sql)
    if df.empty:
        return {
            "values": [],
            "db_synonyms": {},
            "db_descriptions": {},
            "value_contexts": {},
            "context_cols_list": context_cols_list,
            "total_values": 0,
            "new_values": [],
            "skipped": 0,
        }

    db_synonyms: dict[str, list[str]] = {}
    db_descriptions: dict[str, str] = {}
    value_contexts: dict[str, dict] = {}
    values: list[str] = []
    seen: set[str] = set()
    ctx_start_idx = 1 + (1 if has_synonym_col else 0) + (1 if has_desc_col else 0)

    for _, row in df.iterrows():
        val = str(row.iloc[0]) if row.iloc[0] is not None else None
        if not val or val.lower() in seen:
            if val and has_synonym_col:
                syn_val = row.iloc[1] if len(row) > 1 else None
                if syn_val and str(syn_val).strip():
                    db_synonyms.setdefault(val, []).append(str(syn_val).strip())
            continue
        seen.add(val.lower())
        values.append(val)
        if has_synonym_col and len(row) > 1:
            syn_val = row.iloc[1]
            if syn_val and str(syn_val).strip():
                db_synonyms.setdefault(val, []).append(str(syn_val).strip())
        if has_desc_col:
            desc_idx = 2 if has_synonym_col else 1
            if len(row) > desc_idx:
                desc_val = row.iloc[desc_idx]
                if desc_val and str(desc_val).strip():
                    db_descriptions[val] = str(desc_val).strip()
        if context_cols_list:
            ctx: dict = {}
            for offset, cc_name in enumerate(context_cols_list):
                ci = ctx_start_idx + offset
                if ci < len(row):
                    cv = row.iloc[ci]
                    if cv is not None and str(cv).strip():
                        ctx[cc_name] = str(cv).strip()
            if ctx:
                value_contexts[val] = ctx

    glossary = Glossaries.get_glossary_by_id(glossary_id)
    existing_terms = {
        e.get("term", "").lower()
        for e in ((glossary.data or {}).get("entries", []) if glossary else [])
    }
    new_values = [v for v in values if v.lower() not in existing_terms]
    skipped = len(values) - len(new_values)

    return {
        "values": values,
        "db_synonyms": db_synonyms,
        "db_descriptions": db_descriptions,
        "value_contexts": value_contexts,
        "context_cols_list": context_cols_list,
        "total_values": len(values),
        "new_values": new_values,
        "skipped": skipped,
    }


async def _build_llm_context(
    app,
    user_id: str,
    params: dict,
    context_cols_list: list[str],
    has_synonym_col: bool,
    has_desc_col: bool,
) -> str:
    """DbSphere DDL 메모리에서 테이블/컬럼 설명을 가져와 LLM 프롬프트용 컨텍스트 문자열 생성."""
    table_description = ""
    column_meta: dict[str, dict] = {}
    try:
        from extension_modules.dbsphere.memory.search_memory import (
            SearchEngineDbSphereMemory,
        )

        schema_memory = SearchEngineDbSphereMemory(
            app=app,
            dbsphere_id=params["dbsphere_id"],
            user_id=user_id,
            embedding_func=None,
        )
        ddl_memories = await schema_memory.get_table_schemas()
        for ddl in ddl_memories or []:
            if ddl.table_name == params["table_name"]:
                table_description = ddl.table_description or ""
                for c in ddl.columns or []:
                    if c.name:
                        column_meta[c.name] = {
                            "data_type": c.data_type or "",
                            "description": c.description or "",
                        }
                break
    except Exception as e:
        log.warning(f"[glossary extract] schema fetch failed: {e}")

    relevant_cols: list[str] = [params["column_name"]]
    if has_synonym_col:
        relevant_cols.append(params["synonym_column"])
    if has_desc_col:
        relevant_cols.append(params["description_column"])
    relevant_cols.extend(context_cols_list)

    schema_lines: list[str] = []
    for cn in relevant_cols:
        meta = column_meta.get(cn)
        if meta:
            desc = meta["description"] or "(설명 없음)"
            dtype = meta["data_type"] or "?"
            schema_lines.append(f"- `{cn}` ({dtype}): {desc}")
        else:
            schema_lines.append(f"- `{cn}`")

    parts = [f"테이블 `{params['table_name']}`의 `{params['column_name']}` 컬럼 값"]
    if table_description:
        parts.append(f"테이블 설명: {table_description}")
    if schema_lines:
        parts.append("관련 컬럼 스키마:\n" + "\n".join(schema_lines))
    if context_cols_list:
        parts.append(
            "각 항목에는 동일 행의 다음 컬럼 값이 context로 함께 제공됩니다: "
            + ", ".join(f"`{c}`" for c in context_cols_list)
        )
    if params.get("category"):
        parts.append(f"분류: {params['category']}")
    return "\n\n".join(parts)


def _build_preview_entries(
    new_values: list[str],
    db_synonyms: dict[str, list[str]],
    db_descriptions: dict[str, str],
    entries_map: dict[str, dict],
    use_llm: set[str],
    category: Optional[str],
) -> list[dict]:
    now = _now()
    out: list[dict] = []
    for val in new_values:
        llm_info = entries_map.get(val, {})
        synonyms = db_synonyms.get(val, []) or (
            llm_info.get("synonyms", []) if "synonyms" in use_llm else []
        )
        description = db_descriptions.get(val, "") or (
            llm_info.get("description", "") if "description" in use_llm else ""
        )
        example = llm_info.get("example", "") if "example" in use_llm else ""
        out.append(
            {
                "id": str(uuid.uuid4()),
                "term": val,
                "synonyms": synonyms,
                "description": description,
                "example": example,
                "category": category or None,
                "created_at": now,
                "updated_at": now,
            }
        )
    return out


# ───────────────────────── 메인 핸들러 ─────────────────────────


async def process_glossary_extract_task(
    app, task_id: str, payload: dict[str, Any]
) -> None:
    """glossary_extract_values task 처리."""
    glossary_id: str = payload["glossary_id"]
    user_id: str = payload["user_id"]
    params: dict = payload["params"]

    job = Glossaries.get_extract_job(glossary_id)
    if not job or job.get("status") == "canceled":
        log.info(f"[glossary_extract] {glossary_id} skipped — no job or canceled")
        return

    Glossaries.patch_extract_job(
        glossary_id,
        {"status": "running", "phase": "sql", "started_at": _now()},
    )

    try:
        sql_result = await _run_sql_extraction(glossary_id, params)
    except Exception as e:
        log.exception(f"[glossary_extract] SQL failed for {glossary_id}: {e}")
        Glossaries.patch_extract_job(
            glossary_id,
            {
                "status": "failed",
                "error": f"SQL 실행 오류: {e}",
                "completed_at": _now(),
            },
        )
        await _notify(user_id, "glossary-extract-failed", glossary_id, error=str(e))
        return

    new_values = sql_result["new_values"]
    total_values = sql_result["total_values"]

    Glossaries.patch_extract_job(
        glossary_id,
        {
            "phase": "llm",
            "progress.current": 0,
            "progress.total": len(new_values),
        },
    )

    entries_map: dict = {}
    use_llm = set(params.get("llm_fields") or [])
    if params.get("generate_enrichment") and params.get("model_id") and new_values:
        # 1) 라우터에서 HTTP 요청 컨텍스트에 pre-resolve 한 config 를 우선 사용
        # 2) 없으면(legacy payload) 컨슈머 컨텍스트에서 다시 시도
        model_config = payload.get("pre_resolved_model_config")
        if not model_config:
            try:
                model_config = get_model_config_from_app(app, params["model_id"])
            except Exception as e:
                log.warning(f"[glossary_extract] model_config failed: {e}")
                model_config = None

        if not model_config:
            err_msg = (
                f"모델 설정을 resolve 할 수 없습니다: {params.get('model_id')}. "
                "사용자 세션에서 /api/models 가 먼저 호출되지 않았거나 "
                "provider 설정이 누락된 상태입니다."
            )
            log.error(f"[glossary_extract] {glossary_id}: {err_msg}")
            Glossaries.patch_extract_job(
                glossary_id,
                {"status": "failed", "error": err_msg, "completed_at": _now()},
            )
            await _notify(
                user_id, "glossary-extract-failed", glossary_id, error=err_msg
            )
            return

        if model_config:
            context_str = await _build_llm_context(
                app=app,
                user_id=user_id,
                params=params,
                context_cols_list=sql_result["context_cols_list"],
                has_synonym_col=bool(params.get("synonym_column")),
                has_desc_col=bool(params.get("description_column")),
            )

            def _is_canceled() -> bool:
                cur = Glossaries.get_extract_job(glossary_id)
                return bool(cur and cur.get("status") == "canceled")

            # glossary 이름은 미리 캐시해두고 progress event 에 그대로 전달
            _glossary_cached = Glossaries.get_glossary_by_id(glossary_id)
            _glossary_name_cached = _glossary_cached.name if _glossary_cached else None

            async def _on_progress(done: int, total: int) -> None:
                Glossaries.patch_extract_job(
                    glossary_id, {"progress.current": done, "progress.total": total}
                )
                # socket 로 진행률 발행 — 알림 센터의 엔트리가 실시간 갱신됨.
                # 실패해도 추출 자체를 막지 않도록 try/except.
                try:
                    await _notify(
                        user_id,
                        "glossary-extract-progress",
                        glossary_id,
                        glossary_name=_glossary_name_cached,
                        current=done,
                        total=total,
                    )
                except Exception:
                    pass

            llm_stats: dict = {}
            try:
                vc = sql_result["value_contexts"] or None
                if vc:
                    vc = {v: vc[v] for v in new_values if v in vc}
                entries_map = await generate_entries_batch(
                    app=app,
                    values=new_values,
                    context=context_str,
                    pre_resolved_model_config=model_config,
                    batch_size=params.get("batch_size", 10),
                    value_contexts=vc,
                    progress_cb=_on_progress,
                    cancel_check=_is_canceled,
                    stats_out=llm_stats,
                    custom_instructions=params.get("custom_instructions"),
                    concurrency=params.get("llm_concurrency", 8),
                )
            except Exception as e:
                # CancelledError 도 여기로 옴
                msg = str(e) or e.__class__.__name__
                if "cancel" in msg.lower():
                    log.info(f"[glossary_extract] {glossary_id} canceled")
                    Glossaries.patch_extract_job(
                        glossary_id,
                        {"status": "canceled", "completed_at": _now()},
                    )
                    return
                log.exception(f"[glossary_extract] LLM failed for {glossary_id}: {e}")
                Glossaries.patch_extract_job(
                    glossary_id,
                    {
                        "status": "failed",
                        "error": f"LLM 호출 오류: {msg}",
                        "completed_at": _now(),
                    },
                )
                await _notify(
                    user_id, "glossary-extract-failed", glossary_id, error=msg
                )
                return

            # LLM 실행 결과 진단: 매핑이 0건이면 잡을 실패로 마킹
            total_b = int(llm_stats.get("total_batches") or 0)
            failed_b = int(llm_stats.get("failed_batches") or 0)
            mapped = int(llm_stats.get("mapped_values") or 0)
            if total_b > 0 and mapped == 0:
                first_err = llm_stats.get("first_error")
                first_bad = llm_stats.get("first_bad_response")
                reason_parts = [
                    f"LLM 응답이 파싱되지 않아 값 매핑이 0건입니다 "
                    f"({failed_b}/{total_b} 배치 실패)."
                ]
                if first_err:
                    reason_parts.append(f"첫 오류: {first_err}")
                if first_bad:
                    reason_parts.append(f"첫 응답 snippet: {first_bad[:200]}")
                err_msg = " | ".join(reason_parts)
                log.error(f"[glossary_extract] {glossary_id}: {err_msg}")
                Glossaries.patch_extract_job(
                    glossary_id,
                    {
                        "status": "failed",
                        "error": err_msg,
                        "completed_at": _now(),
                    },
                )
                await _notify(
                    user_id,
                    "glossary-extract-failed",
                    glossary_id,
                    error="LLM 응답 매핑 실패 — 모델/프롬프트 확인 필요",
                )
                return
            elif failed_b > 0:
                log.warning(
                    f"[glossary_extract] {glossary_id}: partial LLM failures "
                    f"({failed_b}/{total_b} batches failed, mapped={mapped})"
                )

    preview_entries = _build_preview_entries(
        new_values=new_values,
        db_synonyms=sql_result["db_synonyms"],
        db_descriptions=sql_result["db_descriptions"],
        entries_map=entries_map,
        use_llm=use_llm,
        category=params.get("category"),
    )

    # 카테고리 → 출처(dbsphere/table/column) 매핑을 glossary.meta.extraction_sources
    # 에 기록. 같은 카테고리를 재추출하면 덮어써서 "카테고리 = 단일 출처" 원칙 유지.
    # KG sync 등 후속 단계에서 TERM↔COLUMN 엣지 생성 근거로 사용.
    category = params.get("category")
    if category:
        Glossaries.set_extraction_source(
            glossary_id,
            category,
            {
                "dbsphere_id": params["dbsphere_id"],
                "table": params["table_name"],
                "column": params["column_name"],
                "extracted_at": _now(),
            },
        )

    Glossaries.patch_extract_job(
        glossary_id,
        {
            "status": "succeeded",
            "phase": "done",
            "completed_at": _now(),
            "result": {
                "entries": preview_entries,
                "total_values": total_values,
                "skipped": sql_result["skipped"],
            },
            "progress.current": len(new_values),
            "progress.total": len(new_values),
        },
    )

    glossary = Glossaries.get_glossary_by_id(glossary_id)
    await _notify(
        user_id,
        "glossary-extract-completed",
        glossary_id,
        glossary_name=glossary.name if glossary else None,
        new_count=len(preview_entries),
        skipped=sql_result["skipped"],
    )


async def _notify(
    user_id: str,
    event_type: str,
    glossary_id: str,
    **extra,
) -> None:
    try:
        await send_notification_to_user(
            user_id=user_id,
            event_type=event_type,
            data={"glossary_id": glossary_id, **extra},
        )
    except Exception as e:
        log.warning(f"[glossary_extract] notify failed: {e}")

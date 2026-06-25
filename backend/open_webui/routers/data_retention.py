import logging
import time
from typing import Optional

from fastapi import APIRouter, Depends, Request
from open_webui.env import DATABASE_SCHEMA, SRC_LOG_LEVELS
from open_webui.internal.db import SQLALCHEMY_DATABASE_URL, get_db
from open_webui.models.audit_log import AuditLog, AuditLogs
from open_webui.models.auto_evaluations import AutoEvaluation, AutoEvaluations
from open_webui.models.guardrail_log import GuardrailLog, GuardrailLogs
from open_webui.models.message_trace import MessageTrace, MessageTraces
from open_webui.models.trace_analysis import TraceAnalyses, TraceAnalysis
from open_webui.models.usage import Usage, Usages
from open_webui.utils.audit_logger import AuditLogger
from open_webui.utils.auth import (
    get_admin_settings_read_access,
    get_admin_settings_write_access,
)
from pydantic import BaseModel
from sqlalchemy import func, text

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])

router = APIRouter()


############################
# Models
############################


class DataRetentionConfigForm(BaseModel):
    ENABLE_DATA_RETENTION: bool
    DATA_RETENTION_CLEANUP_HOUR: int
    RETENTION_DAYS_USAGE: int
    RETENTION_DAYS_AUDIT_LOG: int
    RETENTION_DAYS_GUARDRAIL_LOG: int
    RETENTION_DAYS_TRACE: int
    RETENTION_DAYS_TRACE_ANALYSIS: int
    RETENTION_DAYS_AUTO_EVALUATION: int


class WorkerCleanupConfigForm(BaseModel):
    ENABLE_WORKER_AUTO_CLEANUP: bool
    WORKER_ZOMBIE_IDLE_HOURS: int
    WORKER_STUCK_IDLE_HOURS: int
    WORKER_CLEANUP_INTERVAL_MINUTES: int


class TableStatsItem(BaseModel):
    table_name: str
    label: str
    row_count: int
    total_size: Optional[str] = None
    data_size: Optional[str] = None
    index_size: Optional[str] = None
    retention_days: int


class DataRetentionStatsResponse(BaseModel):
    tables: list[TableStatsItem]


class CleanupResult(BaseModel):
    table_name: str
    deleted_count: int


class CleanupResponse(BaseModel):
    results: list[CleanupResult]
    total_deleted: int


############################
# Helpers
############################

LOG_TABLES = [
    ("log_usage", "Usage Logs", Usage),
    ("audit_log", "Audit Logs", AuditLog),
    ("log_guardrail", "Guardrail Logs", GuardrailLog),
    ("message_trace", "Traces", MessageTrace),
    ("trace_analysis", "Trace Analysis", TraceAnalysis),
    ("auto_evaluation", "Auto Evaluations", AutoEvaluation),
]


def _get_retention_days_map(config) -> dict[str, int]:
    return {
        "log_usage": config.RETENTION_DAYS_USAGE,
        "audit_log": config.RETENTION_DAYS_AUDIT_LOG,
        "log_guardrail": config.RETENTION_DAYS_GUARDRAIL_LOG,
        "message_trace": config.RETENTION_DAYS_TRACE,
        "trace_analysis": config.RETENTION_DAYS_TRACE_ANALYSIS,
        "auto_evaluation": config.RETENTION_DAYS_AUTO_EVALUATION,
    }


def _get_table_sizes_pg() -> dict[str, dict]:
    """PostgreSQL 테이블 크기 조회"""
    table_names = [t[0] for t in LOG_TABLES]
    schema = DATABASE_SCHEMA or "public"
    try:
        with get_db() as db:
            results = {}
            for table_name in table_names:
                row = db.execute(
                    text(
                        "SELECT "
                        "pg_size_pretty(pg_total_relation_size(:tbl)) AS total, "
                        "pg_size_pretty(pg_relation_size(:tbl)) AS data, "
                        "pg_size_pretty(pg_indexes_size(:tbl)) AS indexes"
                    ),
                    {"tbl": f'"{schema}".{table_name}'},
                ).fetchone()
                if row:
                    results[table_name] = {
                        "total_size": row[0],
                        "data_size": row[1],
                        "index_size": row[2],
                    }
            return results
    except Exception as e:
        log.warning(f"Failed to get table sizes: {e}")
        return {}


def _get_row_counts() -> dict[str, int]:
    """각 로그 테이블의 행 수 조회"""
    try:
        with get_db() as db:
            counts = {}
            for table_name, _, model_class in LOG_TABLES:
                counts[table_name] = db.query(func.count(model_class.id)).scalar() or 0
            return counts
    except Exception as e:
        log.warning(f"Failed to get row counts: {e}")
        return {}


def execute_cleanup(config) -> list[CleanupResult]:
    """보존 기간 기반 로그 정리 실행"""
    retention_map = _get_retention_days_map(config)
    results = []

    cleanup_funcs = {
        "log_usage": Usages.delete_usage_logs_before,
        "audit_log": AuditLogs.delete_audit_logs_before,
        "log_guardrail": GuardrailLogs.delete_guardrail_logs_before,
        "message_trace": lambda ts: MessageTraces.delete_traces_before(ts * 1000),
        "trace_analysis": TraceAnalyses.delete_analyses_before,
        "auto_evaluation": AutoEvaluations.delete_auto_evaluations_before,
    }

    now = int(time.time())

    for table_name, cleanup_func in cleanup_funcs.items():
        days = retention_map.get(table_name, 0)
        if days <= 0:
            continue

        cutoff = now - (days * 86400)
        deleted = cleanup_func(cutoff)
        if deleted > 0:
            log.info(
                f"Data retention: deleted {deleted} rows from {table_name} (older than {days} days)"
            )
        results.append(CleanupResult(table_name=table_name, deleted_count=deleted))

    return results


############################
# Endpoints
############################


@router.get("/", response_model=DataRetentionConfigForm)
async def get_data_retention_config(
    request: Request, user=Depends(get_admin_settings_read_access)
):
    return {
        "ENABLE_DATA_RETENTION": request.app.state.config.ENABLE_DATA_RETENTION,
        "DATA_RETENTION_CLEANUP_HOUR": request.app.state.config.DATA_RETENTION_CLEANUP_HOUR,
        "RETENTION_DAYS_USAGE": request.app.state.config.RETENTION_DAYS_USAGE,
        "RETENTION_DAYS_AUDIT_LOG": request.app.state.config.RETENTION_DAYS_AUDIT_LOG,
        "RETENTION_DAYS_GUARDRAIL_LOG": request.app.state.config.RETENTION_DAYS_GUARDRAIL_LOG,
        "RETENTION_DAYS_TRACE": request.app.state.config.RETENTION_DAYS_TRACE,
        "RETENTION_DAYS_TRACE_ANALYSIS": request.app.state.config.RETENTION_DAYS_TRACE_ANALYSIS,
        "RETENTION_DAYS_AUTO_EVALUATION": request.app.state.config.RETENTION_DAYS_AUTO_EVALUATION,
    }


@router.post("/", response_model=DataRetentionConfigForm)
async def set_data_retention_config(
    request: Request,
    form_data: DataRetentionConfigForm,
    user=Depends(get_admin_settings_write_access),
):
    request.app.state.config.ENABLE_DATA_RETENTION = form_data.ENABLE_DATA_RETENTION
    request.app.state.config.DATA_RETENTION_CLEANUP_HOUR = (
        form_data.DATA_RETENTION_CLEANUP_HOUR
    )
    request.app.state.config.RETENTION_DAYS_USAGE = form_data.RETENTION_DAYS_USAGE
    request.app.state.config.RETENTION_DAYS_AUDIT_LOG = (
        form_data.RETENTION_DAYS_AUDIT_LOG
    )
    request.app.state.config.RETENTION_DAYS_GUARDRAIL_LOG = (
        form_data.RETENTION_DAYS_GUARDRAIL_LOG
    )
    request.app.state.config.RETENTION_DAYS_TRACE = form_data.RETENTION_DAYS_TRACE
    request.app.state.config.RETENTION_DAYS_TRACE_ANALYSIS = (
        form_data.RETENTION_DAYS_TRACE_ANALYSIS
    )
    request.app.state.config.RETENTION_DAYS_AUTO_EVALUATION = (
        form_data.RETENTION_DAYS_AUTO_EVALUATION
    )

    AuditLogger.log_settings_change(
        "data_retention/config", after_data=form_data.model_dump()
    )
    return {
        "ENABLE_DATA_RETENTION": request.app.state.config.ENABLE_DATA_RETENTION,
        "DATA_RETENTION_CLEANUP_HOUR": request.app.state.config.DATA_RETENTION_CLEANUP_HOUR,
        "RETENTION_DAYS_USAGE": request.app.state.config.RETENTION_DAYS_USAGE,
        "RETENTION_DAYS_AUDIT_LOG": request.app.state.config.RETENTION_DAYS_AUDIT_LOG,
        "RETENTION_DAYS_GUARDRAIL_LOG": request.app.state.config.RETENTION_DAYS_GUARDRAIL_LOG,
        "RETENTION_DAYS_TRACE": request.app.state.config.RETENTION_DAYS_TRACE,
        "RETENTION_DAYS_TRACE_ANALYSIS": request.app.state.config.RETENTION_DAYS_TRACE_ANALYSIS,
        "RETENTION_DAYS_AUTO_EVALUATION": request.app.state.config.RETENTION_DAYS_AUTO_EVALUATION,
    }


@router.get("/stats", response_model=DataRetentionStatsResponse)
async def get_data_retention_stats(
    request: Request, user=Depends(get_admin_settings_read_access)
):
    retention_map = _get_retention_days_map(request.app.state.config)
    row_counts = _get_row_counts()

    # PostgreSQL인 경우에만 크기 정보 조회
    is_pg = "sqlite" not in SQLALCHEMY_DATABASE_URL
    sizes = _get_table_sizes_pg() if is_pg else {}

    tables = []
    for table_name, label, _ in LOG_TABLES:
        size_info = sizes.get(table_name, {})
        tables.append(
            TableStatsItem(
                table_name=table_name,
                label=label,
                row_count=row_counts.get(table_name, 0),
                total_size=size_info.get("total_size"),
                data_size=size_info.get("data_size"),
                index_size=size_info.get("index_size"),
                retention_days=retention_map.get(table_name, 0),
            )
        )

    return DataRetentionStatsResponse(tables=tables)


@router.post("/cleanup", response_model=CleanupResponse)
async def execute_data_retention_cleanup(
    request: Request, user=Depends(get_admin_settings_write_access)
):
    results = execute_cleanup(request.app.state.config)
    total = sum(r.deleted_count for r in results)

    AuditLogger.log_settings_change(
        "data_retention/cleanup",
        after_data={
            "results": [r.model_dump() for r in results],
            "total_deleted": total,
        },
    )

    return CleanupResponse(results=results, total_deleted=total)


############################
# Worker Auto Cleanup
############################


@router.get("/worker-cleanup", response_model=WorkerCleanupConfigForm)
async def get_worker_cleanup_config(
    request: Request, user=Depends(get_admin_settings_read_access)
):
    return {
        "ENABLE_WORKER_AUTO_CLEANUP": request.app.state.config.ENABLE_WORKER_AUTO_CLEANUP,
        "WORKER_ZOMBIE_IDLE_HOURS": request.app.state.config.WORKER_ZOMBIE_IDLE_HOURS,
        "WORKER_STUCK_IDLE_HOURS": request.app.state.config.WORKER_STUCK_IDLE_HOURS,
        "WORKER_CLEANUP_INTERVAL_MINUTES": request.app.state.config.WORKER_CLEANUP_INTERVAL_MINUTES,
    }


@router.post("/worker-cleanup", response_model=WorkerCleanupConfigForm)
async def set_worker_cleanup_config(
    request: Request,
    form_data: WorkerCleanupConfigForm,
    user=Depends(get_admin_settings_write_access),
):
    request.app.state.config.ENABLE_WORKER_AUTO_CLEANUP = (
        form_data.ENABLE_WORKER_AUTO_CLEANUP
    )
    request.app.state.config.WORKER_ZOMBIE_IDLE_HOURS = max(
        1, form_data.WORKER_ZOMBIE_IDLE_HOURS
    )
    request.app.state.config.WORKER_STUCK_IDLE_HOURS = max(
        1, form_data.WORKER_STUCK_IDLE_HOURS
    )
    request.app.state.config.WORKER_CLEANUP_INTERVAL_MINUTES = max(
        1, form_data.WORKER_CLEANUP_INTERVAL_MINUTES
    )

    AuditLogger.log_settings_change(
        "data_retention/worker_cleanup", after_data=form_data.model_dump()
    )
    return {
        "ENABLE_WORKER_AUTO_CLEANUP": request.app.state.config.ENABLE_WORKER_AUTO_CLEANUP,
        "WORKER_ZOMBIE_IDLE_HOURS": request.app.state.config.WORKER_ZOMBIE_IDLE_HOURS,
        "WORKER_STUCK_IDLE_HOURS": request.app.state.config.WORKER_STUCK_IDLE_HOURS,
        "WORKER_CLEANUP_INTERVAL_MINUTES": request.app.state.config.WORKER_CLEANUP_INTERVAL_MINUTES,
    }

"""
BI Dashboard Router

관리자 모니터링 대시보드 — DbSphere 연결 DB 데이터를 Plotly로 시각화.
패널 생성 시 DBSphereAgent로 NL→SQL 생성+검증, 이후 갱신은 저장된 SQL 실행.
"""

import copy
import logging
import time
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from open_webui.constants import ERROR_MESSAGES
from open_webui.env import SRC_LOG_LEVELS
from open_webui.models.bi_dashboard import (
    BiDashboardForm,
    BiDashboards,
    BiPanelForm,
    BiPanels,
)
from open_webui.utils.access_control import has_access
from open_webui.utils.auth import (
    get_admin_monitoring_read_access,
    get_admin_monitoring_write_access,
    get_verified_user,
)
from open_webui.utils.license import require_feature
from pydantic import BaseModel

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])

router = APIRouter(dependencies=[Depends(require_feature("ai_dashboard"))])


############################
# Request Models
############################


class DashboardFilter(BaseModel):
    label: str
    type: str = "text"  # date_range, select, text
    field: str  # column name
    value: Optional[str] = None
    from_value: Optional[str] = None  # date_range용
    to_value: Optional[str] = None  # date_range용


class AutoBuildForm(BaseModel):
    name: str
    dbsphere_ids: list[str]
    model_id: str
    prompt: Optional[str] = None  # 사용자 목적/지시 (예: "매출 분석용 대시보드")


class GenerateSqlForm(BaseModel):
    dbsphere_id: str
    nl_query: str
    model_id: str
    filters: Optional[list[dict]] = None


class ExecuteSqlForm(BaseModel):
    dbsphere_id: str
    sql: str
    sql_template: Optional[str] = None  # $st/$ed 플레이스홀더 포함 SQL
    from_value: Optional[str] = None  # 시작일 (YYYY-MM-DD)
    to_value: Optional[str] = None  # 종료일 (YYYY-MM-DD)
    filters: Optional[list[dict]] = None


############################
# Dashboard CRUD
############################


@router.get("/")
async def get_dashboards(user=Depends(get_admin_monitoring_read_access)):
    """대시보드 목록 (관리자)."""
    dashboards = BiDashboards.get_dashboards()
    result = []
    for d in dashboards:
        panels = BiPanels.get_panels_by_dashboard_id(d.id)
        result.append({**d.model_dump(), "panel_count": len(panels)})
    return result


@router.get("/accessible")
async def get_accessible_dashboards(user=Depends(get_verified_user)):
    """접근 가능한 대시보드 목록 (일반 사용자 — 소유 + 공유받은 대시보드)."""
    dashboards = BiDashboards.get_dashboards()
    result = []
    for d in dashboards:
        if (
            user.role == "admin"
            or d.user_id == user.id
            or d.access_control is None  # 공개
            or has_access(user.id, "read", d.access_control)
        ):
            panels = BiPanels.get_panels_by_dashboard_id(d.id)
            result.append({**d.model_dump(), "panel_count": len(panels)})
    return result


@router.post("/create")
async def create_dashboard(
    form_data: BiDashboardForm,
    user=Depends(get_admin_monitoring_write_access),
):
    """대시보드 생성."""
    if BiDashboards.name_exists(form_data.name):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NAME_TAKEN,
        )

    dashboard = BiDashboards.insert_new_dashboard(user.id, form_data)
    if dashboard:
        return dashboard
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=ERROR_MESSAGES.DEFAULT("Error creating dashboard"),
    )


@router.get("/{dashboard_id}")
async def get_dashboard(
    dashboard_id: str,
    user=Depends(get_admin_monitoring_read_access),
):
    """대시보드 상세 (패널 포함)."""
    dashboard = BiDashboards.get_dashboard_by_id(dashboard_id)
    if not dashboard:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )
    panels = BiPanels.get_panels_by_dashboard_id(dashboard_id)
    return {**dashboard.model_dump(), "panels": [p.model_dump() for p in panels]}


@router.post("/{dashboard_id}/update")
async def update_dashboard(
    dashboard_id: str,
    form_data: BiDashboardForm,
    user=Depends(get_admin_monitoring_write_access),
):
    """대시보드 수정."""
    if BiDashboards.name_exists(form_data.name, exclude_id=dashboard_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NAME_TAKEN,
        )

    dashboard = BiDashboards.update_dashboard_by_id(dashboard_id, form_data)
    if dashboard:
        return dashboard
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=ERROR_MESSAGES.NOT_FOUND,
    )


@router.delete("/{dashboard_id}/delete")
async def delete_dashboard(
    dashboard_id: str,
    user=Depends(get_admin_monitoring_write_access),
):
    """대시보드 삭제 (패널도 함께 삭제)."""
    result = BiDashboards.delete_dashboard_by_id(dashboard_id)
    if result:
        return {"success": True}
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=ERROR_MESSAGES.NOT_FOUND,
    )


############################
# Auto Build (AI Agent)
############################


@router.post("/auto-build")
async def auto_build_dashboard(
    request: Request,
    form_data: AutoBuildForm,
    user=Depends(get_admin_monitoring_write_access),
):
    """AI가 DbSphere 스키마를 분석하여 대시보드를 자동 생성."""
    from extension_modules.dbsphere.dashboard_builder_agent import (
        DashboardBuilderAgent,
    )
    from extension_modules.utils.llm import get_model_config_from_app

    # MODELS가 비어있으면 먼저 로드 (서버 재시작 직후 등)
    if not request.app.state.MODELS:
        from open_webui.utils.models import get_all_models

        await get_all_models(request, user=user)

    model_config = get_model_config_from_app(request.app, form_data.model_id)
    if not model_config:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Model not found: {form_data.model_id}",
        )

    metadata = {
        "user_id": user.id,
        "chat_id": f"dashboard-builder-{int(time.time())}",
    }

    agent = DashboardBuilderAgent(
        api_config=model_config.get("api_config", {}),
        base_url=model_config.get("base_url", ""),
        api_key=model_config.get("api_key", ""),
        metadata=metadata,
        request=request,
        dbsphere_ids=form_data.dbsphere_ids,
    )

    # 데이터 소스 로드
    await agent.load_data_sources()

    if not agent.sql_runners:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No valid database connections found",
        )

    # 에이전트 실행
    try:
        result = await agent.run(
            model_id=form_data.model_id,
            dashboard_name=form_data.name,
            user_prompt=form_data.prompt,
        )
    except Exception as e:
        log.error(f"Dashboard auto-build failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Dashboard generation failed: {str(e)}",
        )

    # 저장
    try:
        dashboard_id = await agent.save_dashboard(
            user_id=user.id,
            dashboard_name=form_data.name,
            panel_definitions=result.get("panel_definitions", []),
        )
    except Exception as e:
        log.error(f"Dashboard save failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Dashboard save failed: {str(e)}",
        )

    return {"success": True, "dashboard_id": dashboard_id}


############################
# Auto Build Chat (Multi-turn AI)
############################


class AutoBuildChatForm(BaseModel):
    messages: List[dict]
    model_id: Optional[str] = None
    dashboard_id: Optional[str] = None  # Existing dashboard to add panels to
    dbsphere_ids: Optional[List[str]] = None  # Explicitly selected DbSpheres


@router.post("/auto-build/chat")
async def auto_build_dashboard_chat(
    request: Request,
    form_data: AutoBuildChatForm,
    user=Depends(get_admin_monitoring_write_access),
):
    """Multi-turn conversational dashboard building with Human-in-the-Loop."""
    from extension_modules.dbsphere.dashboard_builder_agent import (
        DashboardBuilderAgent,
    )
    from extension_modules.utils.llm import get_model_config_from_app

    if not form_data.messages or len(form_data.messages) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("At least one message is required"),
        )

    if not form_data.model_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("model_id is required"),
        )

    # Load models if needed
    if not request.app.state.MODELS:
        from open_webui.utils.models import get_all_models

        await get_all_models(request, user=user)

    model_config = get_model_config_from_app(request.app, form_data.model_id)
    if not model_config:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Model not found: {form_data.model_id}",
        )

    metadata = {
        "user_id": user.id,
        "user_role": user.role,
        "chat_id": f"dashboard-builder-{int(time.time())}",
    }

    # Create agent — dbsphere_ids empty initially, schemas loaded on demand
    agent = DashboardBuilderAgent(
        api_config=model_config.get("api_config", {}),
        base_url=model_config.get("base_url", ""),
        api_key=model_config.get("api_key", ""),
        metadata=metadata,
        request=request,
        dbsphere_ids=[],
    )

    # If dashboard exists, load existing panels and their DbSphere schemas
    existing_panels = None
    dashboard_id = form_data.dashboard_id

    if dashboard_id:
        dashboard = BiDashboards.get_dashboard_by_id(dashboard_id)
        if dashboard:
            panels = BiPanels.get_panels_by_dashboard_id(dashboard_id)
            if panels:
                existing_panels = []
                dbsphere_ids_to_load = set()
                for p in panels:
                    panel_data = p.data or {}
                    existing_panels.append(
                        {
                            "id": p.id,
                            "name": p.name,
                            "type": panel_data.get("panel_type", "chart"),
                            "panel_type": panel_data.get("panel_type", "chart"),
                            "chart_type": panel_data.get("chart_type", ""),
                            "dbsphere_id": p.dbsphere_id,
                            "sql": panel_data.get("sql", ""),
                            "layout": panel_data.get(
                                "layout", {"x": 0, "y": 0, "w": 6, "h": 4}
                            ),
                        }
                    )
                    if p.dbsphere_id:
                        dbsphere_ids_to_load.add(p.dbsphere_id)

                # Load schemas for existing DbSpheres
                if dbsphere_ids_to_load:
                    agent.dbsphere_ids = list(dbsphere_ids_to_load)
                    try:
                        await agent.load_data_sources()
                    except Exception as e:
                        log.warning(f"Failed to load existing schemas: {e}")

    # Load explicitly selected DbSpheres from form data
    if form_data.dbsphere_ids:
        for dbid in form_data.dbsphere_ids:
            if dbid not in agent.dbsphere_ids:
                agent.dbsphere_ids.append(dbid)
        if agent.dbsphere_ids:
            try:
                await agent.load_data_sources()
            except Exception as e:
                log.warning(f"Failed to load selected data sources: {e}")

    # Scan conversation for user-selected DbSphere IDs to load schemas
    # The AI might have asked which DB to use; user's reply may contain a DB name
    if not agent.sql_runners:
        import re

        from open_webui.models.dbsphere import DbSpheres

        all_dbs = DbSpheres.get_dbspheres()
        # Build multiple match keys per DB (full name, name without brackets, etc.)
        db_match_keys: list[tuple[str, str]] = []
        for db in all_dbs:
            name_lower = db.name.lower()
            db_match_keys.append((name_lower, db.id))
            # Also match without brackets: "[Oracle] 판매 분석" → "oracle 판매 분석"
            clean = re.sub(r"\[.*?\]\s*", "", name_lower).strip()
            if clean:
                db_match_keys.append((clean, db.id))

        # Check all messages for mentions of DB names
        for msg in form_data.messages:
            content = msg.get("content", "").lower()
            for db_name, db_id in db_match_keys:
                if db_name in content and db_id not in agent.dbsphere_ids:
                    agent.dbsphere_ids.append(db_id)

        if agent.dbsphere_ids:
            try:
                await agent.load_data_sources()
            except Exception as e:
                log.warning(f"Failed to load data sources: {e}")

    try:
        result = await agent.run_chat(
            messages=form_data.messages,
            model_id=form_data.model_id,
            existing_panels=existing_panels,
        )

        # Handle DELETE_PANEL / REPOSITION_EXISTING markers from agent
        if dashboard_id:
            # Collect all message contents (handle both str and list content)
            raw_contents = []
            for m in result.get("_raw_messages", []):
                c = getattr(m, "content", "") if hasattr(m, "content") else ""
                if isinstance(c, list):
                    # Some LangChain messages have content as list of dicts
                    for item in c:
                        if isinstance(item, dict):
                            raw_contents.append(item.get("text", ""))
                        elif isinstance(item, str):
                            raw_contents.append(item)
                elif isinstance(c, str):
                    raw_contents.append(c)

            for msg_content in raw_contents:
                if "DELETE_PANEL:" in str(msg_content):
                    try:
                        target_name = msg_content.split("DELETE_PANEL:")[1].strip()
                        panels = BiPanels.get_panels_by_dashboard_id(dashboard_id)
                        for p in panels:
                            if target_name.lower() in p.name.lower():
                                BiPanels.delete_panel_by_id(p.id)
                                log.info(f"Deleted panel '{p.name}'")
                                break
                    except Exception as e:
                        log.warning(f"Failed to process DELETE_PANEL: {e}")

                if "REPOSITION_EXISTING:" in str(msg_content):
                    try:
                        import ast

                        raw = msg_content.split("REPOSITION_EXISTING:")[1].strip()
                        repositions = ast.literal_eval(raw)
                        if existing_panels and isinstance(repositions, list):
                            for repo in repositions:
                                idx = repo.get("existing_index", -1)
                                if 0 <= idx < len(existing_panels):
                                    panel_id = existing_panels[idx].get("id")
                                    if panel_id:
                                        panel = BiPanels.get_panel_by_id(panel_id)
                                        if panel:
                                            new_data = dict(panel.data or {})
                                            new_data["layout"] = {
                                                "x": repo.get("x", 0),
                                                "y": repo.get("y", 0),
                                                "w": repo.get("w", 6),
                                                "h": repo.get("h", 4),
                                            }
                                            BiPanels.update_panel_by_id(
                                                panel_id,
                                                BiPanelForm(
                                                    name=panel.name,
                                                    dbsphere_id=panel.dbsphere_id,
                                                    data=new_data,
                                                ),
                                            )
                                            log.info(
                                                f"Repositioned panel '{panel.name}' "
                                                f"to ({repo.get('x')},{repo.get('y')})"
                                            )
                    except Exception as e:
                        log.warning(f"Failed to process REPOSITION_EXISTING: {e}")

        # Save panels if generated
        if result.get("panel_definitions"):
            panel_defs = result["panel_definitions"]

            if not dashboard_id:
                # Create new dashboard
                dashboard = BiDashboards.insert_new_dashboard(
                    user.id,
                    BiDashboardForm(name="AI Dashboard"),
                )
                if dashboard:
                    dashboard_id = dashboard.id

            if dashboard_id:
                # Fix overlapping layouts before saving
                _fix_panel_overlaps(dashboard_id, panel_defs)

                panel_ids = await agent.save_panels(
                    user_id=user.id,
                    dashboard_id=dashboard_id,
                    panel_definitions=panel_defs,
                )
                result["dashboard_id"] = dashboard_id
                result["panel_ids"] = panel_ids

        # Save chat history to dashboard meta (always, not just when panels are generated)
        if dashboard_id:
            try:
                db_dashboard = BiDashboards.get_dashboard_by_id(dashboard_id)
                if db_dashboard:
                    current_meta = db_dashboard.meta or {}
                    current_meta["ai_chat_history"] = form_data.messages + [
                        {
                            "role": "assistant",
                            "content": result.get("assistant_message", ""),
                        }
                    ]
                    BiDashboards.update_dashboard_by_id(
                        dashboard_id,
                        BiDashboardForm(
                            name=db_dashboard.name,
                            description=db_dashboard.description,
                            data=db_dashboard.data,
                            meta=current_meta,
                            access_control=db_dashboard.access_control,
                        ),
                    )
                    result["dashboard_id"] = dashboard_id
            except Exception as e:
                log.warning(f"Failed to save chat history: {e}")

        return result

    except Exception as e:
        log.exception(f"Dashboard auto-build chat failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=ERROR_MESSAGES.DEFAULT(f"Chat failed: {str(e)}"),
        )


############################
# Share & Export
############################


class ShareDashboardForm(BaseModel):
    access_control: Optional[dict] = None


def _check_shared_dashboard_access(share_id: str, user):
    """공유 대시보드 접근 권한 확인. 대시보드 반환."""

    dashboard = BiDashboards.get_dashboard_by_share_id(share_id)
    if not dashboard:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    # 소유자 또는 admin은 항상 접근 가능
    if user.role == "admin" or dashboard.user_id == user.id:
        return dashboard

    # access_control이 None이면 전체 공개 (로그인 사용자)
    if dashboard.access_control is None:
        return dashboard

    # access_control이 빈 dict이면 비공개 (소유자만)
    if dashboard.access_control == {}:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.UNAUTHORIZED,
        )

    # 그룹/사용자/조직 접근 제어
    if has_access(user.id, "read", dashboard.access_control):
        return dashboard

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=ERROR_MESSAGES.UNAUTHORIZED,
    )


@router.post("/{dashboard_id}/share")
async def share_dashboard(
    dashboard_id: str,
    form_data: ShareDashboardForm,
    user=Depends(get_admin_monitoring_write_access),
):
    """대시보드 공유 링크 생성/업데이트."""
    import uuid as _uuid

    dashboard = BiDashboards.get_dashboard_by_id(dashboard_id)
    if not dashboard:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    share_id = dashboard.share_id or str(_uuid.uuid4())[:8]
    updated = BiDashboards.update_dashboard_share(
        dashboard_id, share_id, form_data.access_control
    )
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=ERROR_MESSAGES.DEFAULT("Failed to share dashboard"),
        )

    return {"share_id": updated.share_id, "share_url": f"/dashboard/{updated.share_id}"}


@router.delete("/{dashboard_id}/share")
async def unshare_dashboard(
    dashboard_id: str,
    user=Depends(get_admin_monitoring_write_access),
):
    """대시보드 공유 해제."""
    dashboard = BiDashboards.get_dashboard_by_id(dashboard_id)
    if not dashboard:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    BiDashboards.update_dashboard_share(dashboard_id, None, None)
    return {"success": True}


@router.get("/shared/{share_id}")
async def get_shared_dashboard(
    share_id: str,
    user=Depends(get_verified_user),
):
    """공유 대시보드 조회 (읽기 전용)."""
    dashboard = _check_shared_dashboard_access(share_id, user)
    panels = BiPanels.get_panels_by_dashboard_id(dashboard.id)
    return {**dashboard.model_dump(), "panels": [p.model_dump() for p in panels]}


@router.post("/shared/{share_id}/execute-sql")
async def execute_shared_dashboard_sql(
    share_id: str,
    form_data: ExecuteSqlForm,
    user=Depends(get_verified_user),
):
    """공유 대시보드 SQL 실행 (필터 적용)."""
    _check_shared_dashboard_access(share_id, user)

    # execute_sql 로직 재사용
    if (
        form_data.sql_template
        and ("$st" in form_data.sql_template or "$ed" in form_data.sql_template)
        and (form_data.from_value or form_data.to_value)
    ):
        sql = _replace_date_placeholders(
            form_data.sql_template,
            form_data.from_value or "1900-01-01",
            form_data.to_value or "2099-12-31",
            form_data.dbsphere_id,
        )
    else:
        sql = form_data.sql

    sql = sql.strip().rstrip(";")
    if not sql.upper().startswith("SELECT"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only SELECT queries are allowed",
        )

    if form_data.filters:
        where_clauses = _build_filter_where_clauses(form_data.filters)
        if where_clauses:
            sql = _inject_where_into_sql(sql, where_clauses)

    runner = _create_sql_runner(form_data.dbsphere_id)
    try:
        df = await runner.run_sql(sql)
        return {
            "columns": list(df.columns),
            "data": df.where(df.notnull(), None).to_dict(orient="records"),
            "row_count": len(df),
        }
    except Exception as e:
        log.error(f"Shared SQL execution failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"SQL execution failed: {str(e)}",
        )


class ExportHtmlForm(BaseModel):
    from_value: Optional[str] = None
    to_value: Optional[str] = None
    filters: Optional[list[dict]] = None


def compute_date_range(time_range: str) -> tuple[str, str]:
    """기간 프리셋을 실행 시점 기준 (from, to) YYYY-MM-DD로 변환."""
    from datetime import datetime, timedelta

    now = datetime.now()
    fmt = "%Y-%m-%d"

    if time_range == "today":
        d = now.strftime(fmt)
        return d, d
    elif time_range == "yesterday":
        d = (now - timedelta(days=1)).strftime(fmt)
        return d, d
    elif time_range == "this_week":
        dow = now.weekday()  # 0=Mon
        start = now - timedelta(days=dow)
        return start.strftime(fmt), now.strftime(fmt)
    elif time_range == "last_week":
        dow = now.weekday()
        end = now - timedelta(days=dow + 1)
        start = end - timedelta(days=6)
        return start.strftime(fmt), end.strftime(fmt)
    elif time_range == "this_month":
        return now.replace(day=1).strftime(fmt), now.strftime(fmt)
    elif time_range == "last_month":
        first_this = now.replace(day=1)
        last_prev = first_this - timedelta(days=1)
        first_prev = last_prev.replace(day=1)
        return first_prev.strftime(fmt), last_prev.strftime(fmt)
    elif time_range == "7d":
        return (now - timedelta(days=7)).strftime(fmt), now.strftime(fmt)
    elif time_range == "30d":
        return (now - timedelta(days=30)).strftime(fmt), now.strftime(fmt)
    else:  # "all" or unknown
        return "", ""


async def generate_dashboard_export(
    dashboard_id: str,
    from_value: str = "",
    to_value: str = "",
    filters: Optional[list[dict]] = None,
) -> tuple[str, list[dict]]:
    """대시보드 전체 패널 SQL 실행 + HTML 생성. (html, panel_results) 반환."""
    dashboard = BiDashboards.get_dashboard_by_id(dashboard_id)
    if not dashboard:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    panels = BiPanels.get_panels_by_dashboard_id(dashboard_id)

    panel_results = []
    for panel in panels:
        panel_data = panel.data or {}
        result_data = None

        if not panel_data.get("sql"):
            result_data = panel_data.get("cached_result")
        else:
            try:
                sql = panel_data["sql"]
                if (
                    panel_data.get("use_time_filter")
                    and panel_data.get("sql_template")
                    and (from_value or to_value)
                ):
                    sql_template = panel_data["sql_template"]
                    if "$st" in sql_template or "$ed" in sql_template:
                        sql = _replace_date_placeholders(
                            sql_template,
                            from_value or "1900-01-01",
                            to_value or "2099-12-31",
                            panel.dbsphere_id,
                        )

                sql = sql.strip().rstrip(";")

                if filters:
                    where_clauses = _build_filter_where_clauses(filters)
                    if where_clauses:
                        sql = _inject_where_into_sql(sql, where_clauses)

                runner = _create_sql_runner(panel.dbsphere_id)
                df = await runner.run_sql(sql)
                result_data = {
                    "columns": list(df.columns),
                    "data": df.where(df.notnull(), None).to_dict(orient="records"),
                    "row_count": len(df),
                }
            except Exception as e:
                log.warning(f"Panel {panel.id} export failed: {e}")
                result_data = panel_data.get("cached_result")

        panel_results.append(
            {
                "panel": panel.model_dump(),
                "result": result_data,
            }
        )

    # form_data 호환 객체 생성
    form_compat = ExportHtmlForm(
        from_value=from_value or None,
        to_value=to_value or None,
        filters=filters,
    )
    html = _build_export_html(dashboard, panel_results, form_compat)
    return html, panel_results


@router.post("/{dashboard_id}/export-html")
async def export_dashboard_html(
    dashboard_id: str,
    form_data: ExportHtmlForm,
    user=Depends(get_admin_monitoring_read_access),
):
    """대시보드를 정적 HTML로 내보내기 (Plotly 인터랙티브)."""
    from urllib.parse import quote

    from fastapi.responses import Response

    html, _ = await generate_dashboard_export(
        dashboard_id,
        form_data.from_value or "",
        form_data.to_value or "",
        form_data.filters,
    )

    dashboard = BiDashboards.get_dashboard_by_id(dashboard_id)
    ascii_name = (
        dashboard.name.encode("ascii", "replace").decode("ascii").replace('"', "'")
    )
    utf8_name = quote(dashboard.name + ".html")
    return Response(
        content=html,
        media_type="text/html",
        headers={
            "Content-Disposition": f"attachment; filename=\"{ascii_name}.html\"; filename*=UTF-8''{utf8_name}"
        },
    )


def _build_export_html(dashboard, panel_results, form_data) -> str:
    """대시보드를 self-contained HTML로 렌더링."""
    import html as html_mod

    COLORS = [
        "#636EFA",
        "#EF553B",
        "#00CC96",
        "#AB63FA",
        "#FFA15A",
        "#19D3F3",
        "#FF6692",
        "#B6E880",
        "#FF97FF",
        "#FECB52",
        "#1f77b4",
        "#ff7f0e",
        "#2ca02c",
        "#d62728",
        "#9467bd",
        "#8c564b",
        "#e377c2",
        "#7f7f7f",
        "#bcbd22",
        "#17becf",
    ]

    title = html_mod.escape(dashboard.name)
    from_val = form_data.from_value or ""
    to_val = form_data.to_value or ""
    filter_desc = f"{from_val} ~ {to_val}" if from_val or to_val else "All"

    panel_divs = []
    plot_scripts = []

    for idx, pr in enumerate(panel_results):
        panel = pr["panel"]
        result = pr["result"]
        p_data = panel.get("data", {}) or {}
        layout = p_data.get("layout", {"x": 0, "y": idx * 4, "w": 6, "h": 4})
        chart_type = p_data.get("chart_type", "bar")
        panel_name = html_mod.escape(panel.get("name", ""))
        card_bg = p_data.get("card_bg_color", "")
        show_title = p_data.get("show_title", True)
        title_position = p_data.get("title_position", "inside")
        div_id = f"panel-{idx}"

        x, y, w, h = (
            layout.get("x", 0),
            layout.get("y", 0),
            layout.get("w", 6),
            layout.get("h", 4),
        )

        if not result or not result.get("data"):
            # 데이터 없는 패널
            style = f"grid-column: {x + 1} / span {w}; grid-row: {y + 1} / span {h};"
            panel_divs.append(
                f'<div class="panel" style="{style}">'
                f'<div class="panel-header">{panel_name}</div>'
                f'<div class="no-data">No data</div></div>'
            )
            continue

        columns = result["columns"]
        rows = result["data"]

        # 카드 타입
        if chart_type == "card":
            col = columns[-1]
            val = rows[0].get(col, "") if rows else ""
            if isinstance(val, (int, float)):
                val = f"{val:,.0f}" if val == int(val) else f"{val:,.2f}"
            bg_style = (
                f"background-color: {card_bg};"
                if card_bg
                else "background-color: var(--card-bg);"
            )
            text_class = "color: white;" if card_bg else ""
            style = f"grid-column: {x + 1} / span {w}; grid-row: {y + 1} / span {h}; {bg_style}"
            label = (
                columns[0] + ": " + str(rows[0].get(columns[0], ""))
                if len(columns) > 1
                else panel_name
            )
            panel_divs.append(
                f'<div class="panel card-panel" style="{style}">'
                f'<div class="card-value" style="{text_class}">{html_mod.escape(str(val))}</div>'
                f'<div class="card-label" style="{text_class}">{html_mod.escape(str(label))}</div>'
                f"{'<div class=panel-header style=' + chr(34) + text_class + chr(34) + '>' + panel_name + '</div>' if show_title and title_position == 'top' else ''}"
                f"</div>"
            )
            continue

        # Plotly 차트
        style = f"grid-column: {x + 1} / span {w}; grid-row: {y + 1} / span {h};"
        header_html = (
            f'<div class="panel-header">{panel_name}</div>'
            if show_title and title_position == "top"
            else ""
        )
        panel_divs.append(
            f'<div class="panel" style="{style}">'
            f"{header_html}"
            f'<div id="{div_id}" class="chart-container"></div></div>'
        )

        # 차트 trace 빌드 (PanelChart.svelte 로직 포팅)
        traces_json, layout_json = _build_plotly_chart_json(
            columns,
            rows,
            chart_type,
            panel_name if show_title and title_position == "inside" else "",
            COLORS,
        )
        plot_scripts.append(
            f"Plotly.newPlot('{div_id}', {traces_json}, {layout_json}, {{responsive:true, displayModeBar:false}});"
        )

    plots_js = "\n".join(plot_scripts)

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
  :root {{ --bg: #ffffff; --text: #333; --card-bg: #f9fafb; --border: #e5e7eb; --muted: #6b7280; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg: #111827; --text: #e5e7eb; --card-bg: #1f2937; --border: #374151; --muted: #9ca3af; }}
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ background: var(--bg); color: var(--text); font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; padding: 24px; }}
  .header {{ margin-bottom: 20px; }}
  .header h1 {{ font-size: 1.5rem; font-weight: 600; }}
  .header .meta {{ color: var(--muted); font-size: 0.85rem; margin-top: 4px; }}
  .grid {{ display: grid; grid-template-columns: repeat(12, 1fr); grid-auto-rows: 80px; gap: 16px; }}
  .panel {{ background: var(--card-bg); border: 1px solid var(--border); border-radius: 12px; overflow: hidden; display: flex; flex-direction: column; }}
  .panel-header {{ padding: 8px 12px; font-size: 0.875rem; font-weight: 500; border-bottom: 1px solid var(--border); }}
  .chart-container {{ flex: 1; min-height: 0; }}
  .no-data {{ display: flex; align-items: center; justify-content: center; flex: 1; color: var(--muted); font-size: 0.875rem; }}
  .card-panel {{ display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center; padding: 16px; }}
  .card-value {{ font-size: 2rem; font-weight: 700; }}
  .card-label {{ font-size: 0.85rem; opacity: 0.7; margin-top: 4px; }}
</style>
</head>
<body>
<div class="header">
  <h1>{title}</h1>
  <div class="meta">Exported at {time.strftime("%Y-%m-%d %H:%M")} &middot; Filter: {html_mod.escape(filter_desc)}</div>
</div>
<div class="grid">
  {"".join(panel_divs)}
</div>
<script>
{plots_js}
// 리사이즈 대응
window.addEventListener('resize', function() {{
  document.querySelectorAll('.chart-container').forEach(function(el) {{
    if (el.data) Plotly.Plots.resize(el);
  }});
}});
</script>
</body>
</html>"""


def _build_plotly_chart_json(columns, rows, chart_type, title, colors):
    """PanelChart.svelte의 렌더링 로직을 Python으로 포팅. (traces, layout) JSON 문자열 반환."""
    import json

    # 컬럼 타입 추론
    numeric_cols = []
    for col in columns:
        samples = [
            r.get(col) for r in rows[:5] if r.get(col) is not None and r.get(col) != ""
        ]
        if (
            samples
            and sum(1 for v in samples if isinstance(v, (int, float)))
            >= len(samples) * 0.8
        ):
            numeric_cols.append(col)

    date_cols = []
    for col in columns:
        if col in numeric_cols:
            continue
        sample = str(rows[0].get(col, "") if rows else "")
        if len(sample) >= 7 and sample[:4].isdigit() and sample[4] == "-":
            date_cols.append(col)

    categorical_cols = [
        c for c in columns if c not in numeric_cols and c not in date_cols
    ]

    # x축 선택
    if chart_type in ("line", "area"):
        x_col = (date_cols + categorical_cols + columns)[:1]
        x_col = x_col[0] if x_col else columns[0]
    elif chart_type in ("bar", "pie"):
        x_col = (categorical_cols + date_cols + columns)[:1]
        x_col = x_col[0] if x_col else columns[0]
    else:
        x_col = (categorical_cols + date_cols + columns)[:1]
        x_col = x_col[0] if x_col else columns[0]

    y_cols = numeric_cols if numeric_cols else [c for c in columns if c != x_col]

    # x 값 truncate
    x_values = [str(r.get(x_col, ""))[:20] for r in rows]
    max_label_len = max((len(v) for v in x_values), default=0)
    needs_angle = max_label_len > 8 and chart_type not in ("pie", "table")

    layout = {
        "title": title or None,
        "paper_bgcolor": "transparent",
        "plot_bgcolor": "transparent",
        "font": {"color": "#888", "size": 12},
        "margin": {
            "t": 40 if title else 20,
            "r": 20,
            "b": 80 if needs_angle else 40,
            "l": 50,
        },
        "autosize": True,
        "showlegend": len(y_cols) > 1 or chart_type == "pie",
        "legend": {"orientation": "h", "y": -0.2},
    }
    if needs_angle:
        layout["xaxis"] = {"tickangle": -30}
    if (len(y_cols) > 1 and chart_type == "bar") or chart_type == "grouped_bar":
        layout["barmode"] = "group"

    traces = []

    if chart_type == "pie":
        y_col = (
            y_cols[0] if y_cols else (columns[1] if len(columns) > 1 else columns[0])
        )
        traces = [
            {
                "type": "pie",
                "labels": x_values,
                "values": [float(r.get(y_col, 0) or 0) for r in rows],
                "marker": {"colors": colors[: len(rows)]},
                "textinfo": "label+percent",
                "hole": 0.3,
            }
        ]
    elif chart_type == "histogram":
        # Histogram: 숫자 컬럼별 분포
        for i, yc in enumerate(y_cols):
            traces.append(
                {
                    "type": "histogram",
                    "x": [float(r.get(yc, 0) or 0) for r in rows],
                    "name": yc,
                    "marker": {"color": colors[i % len(colors)]},
                    "opacity": 0.7,
                }
            )
        if len(y_cols) > 1:
            layout["barmode"] = "overlay"
    elif chart_type == "heatmap":
        # Heatmap: x축(카테고리/날짜) × y축(두번째 카테고리) → z축(숫자 값)
        all_cats = categorical_cols + date_cols
        y_col_hm = next(
            (c for c in all_cats if c != x_col),
            y_cols[1] if len(y_cols) >= 2 else (y_cols[0] if y_cols else columns[-1]),
        )
        z_col = y_cols[0] if y_cols else columns[-1]

        if len(all_cats) >= 2:
            x_labels = list(dict.fromkeys(str(r.get(x_col, "")) for r in rows))
            y_labels = list(dict.fromkeys(str(r.get(y_col_hm, "")) for r in rows))
            z_values = []
            for yl in y_labels:
                row_vals = []
                for xl in x_labels:
                    matched = next(
                        (
                            r
                            for r in rows
                            if str(r.get(x_col)) == xl and str(r.get(y_col_hm)) == yl
                        ),
                        None,
                    )
                    row_vals.append(float(matched.get(z_col, 0) or 0) if matched else 0)
                z_values.append(row_vals)
            traces.append(
                {
                    "type": "heatmap",
                    "x": x_labels,
                    "y": y_labels,
                    "z": z_values,
                    "colorscale": "YlOrRd",
                }
            )
        else:
            z_values = [[float(r.get(yc, 0) or 0) for r in rows] for yc in numeric_cols]
            traces.append(
                {
                    "type": "heatmap",
                    "x": x_values,
                    "y": numeric_cols,
                    "z": z_values,
                    "colorscale": "YlOrRd",
                }
            )
        layout["margin"] = {"t": 40 if title else 20, "r": 20, "b": 60, "l": 80}
    elif chart_type == "table":
        traces = [
            {
                "type": "table",
                "header": {
                    "values": [f"<b>{c}</b>" for c in columns],
                    "fill": {"color": "#1f77b4"},
                    "font": {"color": "white", "size": 12},
                    "align": "left",
                },
                "cells": {
                    "values": [[r.get(col) for r in rows] for col in columns],
                    "fill": {"color": ["#f9fafb", "white"]},
                    "align": "left",
                    "font": {"size": 11},
                },
            }
        ]
        layout["margin"] = {"t": 10, "r": 10, "b": 10, "l": 10}
    else:
        plot_type = (
            "scatter"
            if chart_type in ("line", "area")
            else ("bar" if chart_type == "grouped_bar" else chart_type)
        )

        # 그룹 컬럼 감지
        group_col = next((c for c in categorical_cols + date_cols if c != x_col), None)
        y_col = y_cols[0] if y_cols else columns[-1]

        if group_col and len(y_cols) == 1:
            groups = list(dict.fromkeys(str(r.get(group_col, "unknown")) for r in rows))
            for i, gv in enumerate(groups):
                group_rows = [r for r in rows if str(r.get(group_col, "unknown")) == gv]
                trace = {
                    "x": [r.get(x_col) for r in group_rows],
                    "y": [float(r.get(y_col, 0) or 0) for r in group_rows],
                    "name": gv,
                    "marker": {"color": colors[i % len(colors)]},
                }
                if chart_type == "line":
                    trace.update({"type": "scatter", "mode": "lines+markers"})
                elif chart_type == "area":
                    trace.update(
                        {"type": "scatter", "mode": "lines", "fill": "tozeroy"}
                    )
                elif chart_type == "scatter":
                    trace.update({"type": "scatter", "mode": "markers"})
                else:
                    trace["type"] = plot_type
                traces.append(trace)
            layout["showlegend"] = len(groups) > 1
        else:
            for i, yc in enumerate(y_cols):
                trace = {
                    "x": x_values,
                    "y": [float(r.get(yc, 0) or 0) for r in rows],
                    "name": yc,
                    "marker": {"color": colors[i % len(colors)]},
                }
                if chart_type == "line":
                    trace.update({"type": "scatter", "mode": "lines+markers"})
                elif chart_type == "area":
                    trace.update(
                        {"type": "scatter", "mode": "lines", "fill": "tozeroy"}
                    )
                elif chart_type == "scatter":
                    trace.update({"type": "scatter", "mode": "markers"})
                else:
                    trace["type"] = plot_type
                traces.append(trace)

    return json.dumps(traces, ensure_ascii=False), json.dumps(
        layout, ensure_ascii=False
    )


############################
# Panel CRUD
############################


@router.post("/{dashboard_id}/panels/create")
async def create_panel(
    dashboard_id: str,
    form_data: BiPanelForm,
    user=Depends(get_admin_monitoring_write_access),
):
    """패널 생성."""
    dashboard = BiDashboards.get_dashboard_by_id(dashboard_id)
    if not dashboard:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dashboard not found",
        )

    panel = BiPanels.insert_new_panel(user.id, dashboard_id, form_data)
    if panel:
        return panel
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=ERROR_MESSAGES.DEFAULT("Error creating panel"),
    )


@router.post("/{dashboard_id}/panels/{panel_id}/update")
async def update_panel(
    dashboard_id: str,
    panel_id: str,
    form_data: BiPanelForm,
    user=Depends(get_admin_monitoring_write_access),
):
    """패널 수정."""
    panel = BiPanels.update_panel_by_id(panel_id, form_data)
    if panel:
        return panel
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=ERROR_MESSAGES.NOT_FOUND,
    )


@router.delete("/{dashboard_id}/panels/{panel_id}/delete")
async def delete_panel(
    dashboard_id: str,
    panel_id: str,
    user=Depends(get_admin_monitoring_write_access),
):
    """패널 삭제."""
    result = BiPanels.delete_panel_by_id(panel_id)
    if result:
        return {"success": True}
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=ERROR_MESSAGES.NOT_FOUND,
    )


############################
# Filter Helpers
############################


def _fix_panel_overlaps(dashboard_id: str, new_panel_defs: list[dict]):
    """Fix overlapping layouts by finding available grid positions.

    Checks each new panel's layout against existing panels in the dashboard.
    If overlap detected, finds the next available position.
    Grid: 12 columns, auto rows.
    """
    existing_panels = BiPanels.get_panels_by_dashboard_id(dashboard_id)

    # Build occupied grid: set of (x, y) cells
    occupied: set[tuple[int, int]] = set()
    for p in existing_panels:
        layout = (p.data or {}).get("layout", {})
        px, py = layout.get("x", 0), layout.get("y", 0)
        pw, ph = layout.get("w", 6), layout.get("h", 4)
        for dx in range(pw):
            for dy in range(ph):
                occupied.add((px + dx, py + dy))

    def fits(x: int, y: int, w: int, h: int) -> bool:
        if x + w > 12:
            return False
        for dx in range(w):
            for dy in range(h):
                if (x + dx, y + dy) in occupied:
                    return False
        return True

    def place(x: int, y: int, w: int, h: int):
        for dx in range(w):
            for dy in range(h):
                occupied.add((x + dx, y + dy))

    max_y = max((y for _, y in occupied), default=-1) + 1 if occupied else 0

    for panel_def in new_panel_defs:
        layout = panel_def.get("layout", {})
        w = layout.get("w", 3 if panel_def.get("type") == "card" else 6)
        h = layout.get("h", 1 if panel_def.get("type") == "card" else 4)
        x = layout.get("x", 0)
        y = layout.get("y", 0)

        if fits(x, y, w, h):
            place(x, y, w, h)
            continue

        # Find next available position
        found = False
        for try_y in range(max_y + 20):
            for try_x in range(12 - w + 1):
                if fits(try_x, try_y, w, h):
                    panel_def["layout"] = {"x": try_x, "y": try_y, "w": w, "h": h}
                    place(try_x, try_y, w, h)
                    found = True
                    break
            if found:
                break

        if not found:
            # Fallback: place at bottom
            panel_def["layout"] = {"x": 0, "y": max_y, "w": w, "h": h}
            place(0, max_y, w, h)
            max_y += h


def _build_filter_context(filters: list[dict]) -> str:
    """필터 목록을 LLM 프롬프트용 텍스트로 변환."""
    lines = []
    for f in filters:
        f_type = f.get("type", "text")
        field = f.get("field", "")
        label = f.get("label", field)

        if not field:
            continue

        if f_type == "date_range":
            from_val = f.get("from_value", "")
            to_val = f.get("to_value", "")
            if from_val and to_val:
                lines.append(f"- {label}: {field} BETWEEN '{from_val}' AND '{to_val}'")
            elif from_val:
                lines.append(f"- {label}: {field} >= '{from_val}'")
            elif to_val:
                lines.append(f"- {label}: {field} <= '{to_val}'")
        elif f_type == "select":
            value = f.get("value", "")
            if value:
                lines.append(f"- {label}: {field} = '{value}'")
        else:  # text
            value = f.get("value", "")
            if value:
                lines.append(f"- {label}: {field} LIKE '%{value}%'")

    return "\n".join(lines)


async def _extract_sql_template(request: Request, model_id: str, sql: str) -> dict:
    """LLM으로 SQL에서 날짜/시간 WHERE 조건을 $st, $ed 플레이스홀더로 치환한 템플릿 생성."""
    from extension_modules.utils.llm import create_llm, get_model_config_from_app
    from langchain_core.messages import HumanMessage, SystemMessage

    model_config = get_model_config_from_app(request.app, model_id)
    if not model_config:
        return {"sql_template": sql, "date_column": ""}

    llm = create_llm(model_config)

    prompt = f"""Analyze the following SQL query and do two things:

1. Identify the date/time/timestamp column used in WHERE clause (if any)
2. Replace the date/time filter values in WHERE clause with placeholders $st (start) and $ed (end)

Rules:
- Only modify the WHERE clause date/time conditions
- Keep everything else unchanged
- If there's no date/time filter, return the SQL as-is with empty date_column
- Use the database's native date format with the placeholders
- Return ONLY a JSON object, no other text

Example input:
SELECT * FROM orders WHERE order_date BETWEEN '2024-01-01' AND '2024-03-31' AND status = 'active'

Example output:
{{"sql_template": "SELECT * FROM orders WHERE order_date BETWEEN '$st' AND '$ed' AND status = 'active'", "date_column": "order_date"}}

SQL to analyze:
{sql}"""

    try:
        response = await llm.ainvoke(
            [
                SystemMessage(
                    content="You are a SQL analyzer. Return only valid JSON."
                ),
                HumanMessage(content=prompt),
            ]
        )

        import json

        content = response.content.strip()
        # JSON 블록 추출
        if "```" in content:
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
            content = content.strip()

        result = json.loads(content)
        return {
            "sql_template": result.get("sql_template", sql),
            "date_column": result.get("date_column", ""),
        }
    except Exception as e:
        log.warning(f"SQL template extraction failed: {e}")
        return {"sql_template": sql, "date_column": ""}


def _detect_date_column(df) -> str:
    """DataFrame에서 날짜/시간 컬럼을 자동 감지."""
    import pandas as pd

    # 1. datetime 타입 컬럼
    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            return col

    # 2. 컬럼명으로 추론
    date_keywords = [
        "date",
        "time",
        "created",
        "updated",
        "timestamp",
        "일자",
        "날짜",
        "기간",
    ]
    for col in df.columns:
        col_lower = col.lower()
        for kw in date_keywords:
            if kw in col_lower:
                return col

    # 3. 값 파싱 시도 (첫 번째 non-null 값)
    for col in df.columns:
        if df[col].dtype == object:
            sample = df[col].dropna().head(5)
            parsed = 0
            for val in sample:
                try:
                    pd.to_datetime(str(val))
                    parsed += 1
                except Exception:
                    pass
            if parsed >= 3:
                return col

    return ""


def _extract_main_table(sql: str) -> str:
    """SQL에서 메인 테이블명/별칭 추출."""
    import re

    # FROM 테이블명 [AS] 별칭 패턴
    match = re.search(
        r"\bFROM\s+(\w+(?:\.\w+)?)\s*(?:AS\s+)?(\w+)?",
        sql,
        re.IGNORECASE,
    )
    if match:
        return match.group(2) or match.group(1)
    return ""


def _inject_where_into_sql(sql: str, where_clauses: list[str]) -> str:
    """원본 SQL에 WHERE 조건을 주입.

    기존 WHERE가 있으면 AND로 추가, 없으면 GROUP BY/ORDER BY/LIMIT 앞에 삽입.
    JOIN이 있으면 컬럼에 메인 테이블 한정자를 추가하여 ambiguous 에러 방지.
    """
    import re

    # JOIN이 있으면 컬럼에 테이블 한정자 추가
    has_join = bool(re.search(r"\bJOIN\b", sql, re.IGNORECASE))
    if has_join:
        table_prefix = _extract_main_table(sql)
        if table_prefix:
            where_clauses = [
                re.sub(
                    r"^(\w+)(\s)",
                    rf"{table_prefix}.\1\2",
                    clause,
                )
                for clause in where_clauses
            ]

    where_str = " AND ".join(where_clauses)
    sql_upper = sql.upper()

    # 기존 WHERE 절이 있는지 확인
    where_match = re.search(r"\bWHERE\b", sql_upper)
    if where_match:
        # GROUP BY/ORDER BY/HAVING/LIMIT 중 WHERE 뒤에 오는 첫 번째 키워드 찾기
        after_where = sql_upper[where_match.end() :]
        keyword_match = re.search(
            r"\b(GROUP\s+BY|ORDER\s+BY|HAVING|LIMIT)\b", after_where
        )
        if keyword_match:
            insert_pos = where_match.end() + keyword_match.start()
            return sql[:insert_pos] + f" AND {where_str} " + sql[insert_pos:]
        else:
            return sql + f" AND {where_str}"
    else:
        # WHERE 없음 → GROUP BY/ORDER BY/HAVING/LIMIT 앞에 삽입
        keyword_match = re.search(
            r"\b(GROUP\s+BY|ORDER\s+BY|HAVING|LIMIT)\b", sql_upper
        )
        if keyword_match:
            insert_pos = keyword_match.start()
            return sql[:insert_pos] + f"WHERE {where_str} " + sql[insert_pos:]
        else:
            return sql + f" WHERE {where_str}"


def _build_filter_where_clauses(filters: list[dict]) -> list[str]:
    """필터 목록을 SQL WHERE 절 조건으로 변환. CAST AS DATE로 DBMS 범용 대응."""
    clauses = []
    for f in filters:
        f_type = f.get("type", "text")
        field = f.get("field", "")
        if not field:
            continue

        # SQL injection 방지: 필드명에 알파벳, 숫자, _, . 만 허용
        if not all(c.isalnum() or c in ("_", ".") for c in field):
            continue

        if f_type == "date_range":
            # 날짜 필터는 SQL 템플릿($st/$ed)으로 처리.
            # 여기서는 스킵 — 컬럼 타입(정수/문자열/timestamp)을 모르므로 범용 CAST 불가.
            pass
        elif f_type == "select":
            value = f.get("value", "")
            if value:
                safe_val = value.replace("'", "''")
                clauses.append(f"{field} = '{safe_val}'")
        else:  # text
            value = f.get("value", "")
            if value:
                safe_val = value.replace("'", "''")
                clauses.append(f"{field} LIKE '%{safe_val}%'")

    return clauses


def _replace_date_placeholders(
    sql_template: str,
    from_value: str,
    to_value: str,
    dbsphere_id: str,
) -> str:
    """$st/$ed를 DB 타입별 날짜 리터럴로 치환."""
    from open_webui.models.dbsphere import DbSpheres

    db_type = ""
    dbsphere = DbSpheres.get_dbsphere_by_id(dbsphere_id)
    if dbsphere and dbsphere.data:
        conn = dbsphere.data.get("connection", {})
        db_type = conn.get("db_type", "").upper()

    def _date_literal(val: str) -> str:
        """YYYY-MM-DD 문자열을 DB별 날짜 리터럴로 변환."""
        safe = val.replace("'", "")
        if db_type == "ORACLE":
            return f"TO_DATE('{safe}', 'YYYY-MM-DD')"
        # PostgreSQL, MySQL, MSSQL, Snowflake 등은 문자열 리터럴 자동 변환 지원
        return f"'{safe}'"

    st_literal = _date_literal(from_value)
    ed_literal = _date_literal(to_value)

    # 템플릿이 '$st'(따옴표 포함)이면 따옴표째 치환, 아니면 $st만 치환
    result = sql_template
    if "'$st'" in result:
        result = result.replace("'$st'", st_literal)
    else:
        result = result.replace("$st", st_literal)
    if "'$ed'" in result:
        result = result.replace("'$ed'", ed_literal)
    else:
        result = result.replace("$ed", ed_literal)
    return result


############################
# SQL Generation & Execution
############################


def _create_sql_runner(dbsphere_id: str):
    """DbSphere에서 SQL runner 생성."""
    from open_webui.models.dbsphere import DbSpheres
    from open_webui.routers.dbsphere import decrypt_connection_password

    dbsphere = DbSpheres.get_dbsphere_by_id(dbsphere_id)
    if not dbsphere:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="DbSphere not found",
        )

    data = dbsphere.data
    if not data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="DbSphere has no connection data",
        )

    data = decrypt_connection_password(copy.deepcopy(data))

    from extension_modules.dbsphere.dbsphere_state import DBConfig

    db_config = DBConfig.from_dbsphere_data(data)

    from extension_modules.dbsphere.dbsphere_state import DBType
    from extension_modules.dbsphere.sql_runners import (
        BigQueryRunner,
        DatabricksRunner,
        FabricRunner,
        MSSQLRunner,
        MySQLRunner,
        OracleRunner,
        PostgresRunner,
        SnowflakeRunner,
        SynapseRunner,
    )

    db_type = db_config.get_db_type_enum()
    runners = {
        DBType.POSTGRES: PostgresRunner,
        DBType.MYSQL: MySQLRunner,
        DBType.MSSQL: MSSQLRunner,
        DBType.ORACLE: OracleRunner,
        DBType.SNOWFLAKE: SnowflakeRunner,
        DBType.DATABRICKS: DatabricksRunner,
        DBType.SYNAPSE: SynapseRunner,
        DBType.FABRIC: FabricRunner,
        DBType.BIGQUERY: BigQueryRunner,
    }
    runner_cls = runners.get(db_type)
    if not runner_cls:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported database type: {db_config.db_type}",
        )
    return runner_cls(db_config)


@router.post("/generate-sql")
async def generate_sql(
    request: Request,
    form_data: GenerateSqlForm,
    user=Depends(get_admin_monitoring_write_access),
):
    """DBSphereAgent로 NL→SQL 생성 + 실행 + 검증.

    visualize_data 도구 없이 run_sql만 사용.
    검증된 SQL과 실행 결과를 반환.
    """
    from extension_modules.dbsphere.dbsphere_agent import DBSphereAgent
    from extension_modules.dbsphere.tools.run_sql import create_run_sql_tool

    # DBSphereAgent에 필요한 최소 metadata 구성
    metadata = {
        "user_id": user.id,
        "chat_id": f"bi-dashboard-{int(time.time())}",
        "model": {
            "id": form_data.model_id,
            "info": {
                "meta": {
                    "dbspheres": [{"id": form_data.dbsphere_id}],
                }
            },
        },
    }

    # LLM 설정 가져오기
    from extension_modules.utils.llm import get_model_config_from_app

    model_config = get_model_config_from_app(request.app, form_data.model_id)
    if not model_config:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Model not found: {form_data.model_id}",
        )

    # Agent 생성 (visualize_data 제외)
    agent = DBSphereAgent(
        api_config=model_config.get("api_config", {}),
        base_url=model_config.get("base_url", ""),
        api_key=model_config.get("api_key", ""),
        metadata=metadata,
        request=request,
    )

    # DB 설정 로드
    agent.db_config = agent._load_dbsphere_config()
    if not agent.db_config:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to load database configuration",
        )

    agent.sql_runner = agent._create_sql_runner()
    agent.memory = agent._create_memory()

    if not agent.sql_runner:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported database type: {agent.db_config.db_type}",
        )

    # run_sql 도구만 사용 (visualize_data 제외)
    tools = [
        create_run_sql_tool(
            sql_runner=agent.sql_runner,
            working_directory=agent.working_directory,
        )
    ]

    # 스키마 + 메모리 컨텍스트 가져오기
    schema_info = await agent._get_schema_info()

    # 필터 조건을 질문에 추가
    user_query = form_data.nl_query
    if form_data.filters:
        filter_lines = _build_filter_context(form_data.filters)
        if filter_lines:
            user_query = f"{form_data.nl_query}\n\n[필터 조건 - 반드시 SQL WHERE 절에 반영하세요]\n{filter_lines}"

    messages = [{"role": "user", "content": user_query}]
    memory_context = await agent._get_memory_context(messages)

    # 에이전트용 payload 구성
    payload = {
        "model": form_data.model_id,
        "messages": [{"role": "user", "content": user_query}],
    }

    # noop event emitter (대시보드에서는 채팅 이벤트 불필요)
    async def noop_emitter(event):
        pass

    async def noop_call(event):
        return ""

    agent.event_emitter = noop_emitter
    agent.event_call = noop_call

    # 에이전트 실행
    try:
        result = await agent._run_agent(
            payload=payload,
            tools=tools,
            schema_info=schema_info,
            memory_context=memory_context,
        )
    except Exception as e:
        log.error(f"Agent execution failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"SQL generation failed: {str(e)}",
        )

    # 결과에서 SQL과 응답 추출
    executed_sql = result.get("executed_sql", "")
    query_result_file = result.get("query_result_file", "")

    # LLM 최종 응답 추출
    llm_response = ""
    for msg in reversed(result.get("messages", [])):
        if hasattr(msg, "type") and msg.type == "ai" and msg.content:
            llm_response = msg.content
            break

    # 결과 파일에서 데이터 로드
    result_data = None
    if query_result_file:
        import os

        import pandas as pd

        filepath = os.path.join(agent.working_directory, query_result_file)
        if os.path.exists(filepath):
            try:
                df = pd.read_csv(filepath)
                result_data = {
                    "columns": list(df.columns),
                    "data": df.where(df.notnull(), None).to_dict(orient="records"),
                    "row_count": len(df),
                }
            except Exception as e:
                log.warning(f"Failed to load result file: {e}")

    # LLM으로 SQL 템플릿 생성 (날짜/시간 WHERE → $st, $ed 치환)
    sql_template = executed_sql
    date_column = ""
    if executed_sql:
        try:
            template_result = await _extract_sql_template(
                request, form_data.model_id, executed_sql
            )
            sql_template = template_result.get("sql_template", executed_sql)
            date_column = template_result.get("date_column", "")
        except Exception as e:
            log.warning(f"Failed to extract SQL template: {e}")

    return {
        "sql": executed_sql,
        "sql_template": sql_template,
        "date_column": date_column,
        "explanation": llm_response,
        "result": result_data,
    }


@router.post("/execute-sql")
async def execute_sql(
    form_data: ExecuteSqlForm,
    user=Depends(get_admin_monitoring_write_access),
):
    """저장된 SQL 직접 실행 (대시보드 갱신용). 필터가 있으면 WHERE 조건 추가."""
    # 기간 필터: sql_template의 $st/$ed를 DB 타입별 날짜 리터럴로 치환
    if (
        form_data.sql_template
        and ("$st" in form_data.sql_template or "$ed" in form_data.sql_template)
        and (form_data.from_value or form_data.to_value)
    ):
        sql = _replace_date_placeholders(
            form_data.sql_template,
            form_data.from_value or "1900-01-01",
            form_data.to_value or "2099-12-31",
            form_data.dbsphere_id,
        )
    else:
        sql = form_data.sql

    sql = sql.strip().rstrip(";")
    if not sql.upper().startswith("SELECT"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only SELECT queries are allowed",
        )

    # 필터가 있으면 원본 SQL에 WHERE 조건 주입
    if form_data.filters:
        where_clauses = _build_filter_where_clauses(form_data.filters)
        if where_clauses:
            sql = _inject_where_into_sql(sql, where_clauses)

    runner = _create_sql_runner(form_data.dbsphere_id)

    try:
        df = await runner.run_sql(sql)
        return {
            "columns": list(df.columns),
            "data": df.where(df.notnull(), None).to_dict(orient="records"),
            "row_count": len(df),
        }
    except Exception as e:
        log.error(f"SQL execution failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"SQL execution failed: {str(e)}",
        )


@router.post("/{dashboard_id}/panels/{panel_id}/execute")
async def execute_panel(
    dashboard_id: str,
    panel_id: str,
    user=Depends(get_admin_monitoring_read_access),
):
    """패널의 저장된 SQL 실행 + 결과 캐시."""
    panel = BiPanels.get_panel_by_id(panel_id)
    if not panel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Panel not found",
        )

    panel_data = panel.data or {}
    sql = panel_data.get("sql", "").strip().rstrip(";")
    if not sql:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Panel has no SQL query",
        )

    runner = _create_sql_runner(panel.dbsphere_id)

    try:
        df = await runner.run_sql(sql)
        result_data = {
            "columns": list(df.columns),
            "data": df.where(df.notnull(), None).to_dict(orient="records"),
            "row_count": len(df),
        }

        # 캐시 저장
        BiPanels.update_panel_data_by_id(
            panel_id,
            {
                "cached_result": result_data,
                "cached_at": int(time.time()),
            },
        )

        return result_data
    except Exception as e:
        log.error(f"Panel execution failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Panel execution failed: {str(e)}",
        )

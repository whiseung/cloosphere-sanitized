from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from open_webui.config import publish_models_invalidate
from open_webui.constants import ERROR_MESSAGES
from open_webui.models.agent_version import (
    AgentVersionLabelForm,
    AgentVersionModel,
    AgentVersionResponse,
    AgentVersions,
)
from open_webui.models.guardrails import Guardrails
from open_webui.models.models import (
    ModelForm,
    ModelModel,
    ModelResponse,
    Models,
    ModelUserResponse,
)
from open_webui.utils.access_control import (
    has_access,
    has_permission_min_level,
)
from open_webui.utils.auth import (
    get_admin_settings_read_access,
    get_admin_settings_write_access,
    get_verified_user,
)
from pydantic import BaseModel

router = APIRouter()


def _invalidate_models_cache(request: Request) -> None:
    """로컬 워커의 in-memory MODELS 캐시를 비우고 다른 워커에 신호 발행.

    모델 CRUD/toggle/delete 직후 항상 두 동작을 짝으로 수행해야 한다.
    하나라도 빠지면 멀티워커 환경에서 stale 캐시로 인한 ``Model not found``
    간헐 에러가 다시 살아난다.
    """
    request.app.state.MODELS = {}
    publish_models_invalidate()


def _agent_snapshot(model: ModelModel) -> dict:
    """버전 스냅샷용 에이전트 설정 전체 추출."""
    params = model.params
    meta = model.meta
    return {
        "name": model.name,
        "base_model_id": model.base_model_id,
        "params": params.model_dump()
        if hasattr(params, "model_dump")
        else (params or {}),
        "meta": meta.model_dump() if hasattr(meta, "model_dump") else (meta or {}),
        "access_control": model.access_control,
    }


def _build_restore_form(model: ModelModel, snapshot: dict) -> ModelForm:
    """복원용 ModelForm — '프롬프트 버전관리' 취지에 따라 params(작업/답변 프롬프트
    및 LLM 파라미터)만 그 버전으로 되돌리고, name·base_model_id·meta(연결 리소스)·
    access_control·is_active 는 현재 행 값을 유지한다. (복원으로 연결 리소스가
    사라지거나, 제거된 그룹에 재노출되지 않도록)"""
    return ModelForm(
        id=model.id,
        base_model_id=model.base_model_id,
        name=model.name,
        meta=model.meta,
        params=snapshot.get("params") or {},
        access_control=model.access_control,
        is_active=model.is_active,
    )


###########################
# GetModels
###########################


@router.get("/", response_model=list[ModelUserResponse])
async def get_models(
    request: Request, id: Optional[str] = None, user=Depends(get_verified_user)
):
    if user.role != "admin" and not has_permission_min_level(
        user.id, "workspace.agents", "read", request.app.state.config.USER_PERMISSIONS
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    if user.role == "admin":
        return Models.get_models()
    else:
        return Models.get_models_by_user_id(user.id, "read")


###########################
# GetBaseModels
###########################


@router.get("/base", response_model=list[ModelResponse])
async def get_base_models(user=Depends(get_admin_settings_read_access)):
    return Models.get_base_models()


############################
# CreateNewModel
############################


@router.post("/create", response_model=Optional[ModelModel])
async def create_new_model(
    request: Request,
    form_data: ModelForm,
    user=Depends(get_verified_user),
):
    if user.role != "admin" and not has_permission_min_level(
        user.id, "workspace.agents", "write", request.app.state.config.USER_PERMISSIONS
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.UNAUTHORIZED,
        )

    model = Models.get_model_by_id(form_data.id)
    if model:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.MODEL_ID_TAKEN,
        )

    if Models.name_exists(form_data.name):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NAME_TAKEN,
        )

    else:
        model = Models.insert_new_model(form_data, user.id)
        if model:
            _invalidate_models_cache(request)
            # 에이전트면 최초 버전(v1) 기록 (base 모델은 내부 게이트로 skip)
            AgentVersions.create_version(
                agent_id=model.id,
                snapshot=_agent_snapshot(model),
                user_id=model.user_id,
                created_by=user.id,
            )
            return model
        else:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=ERROR_MESSAGES.DEFAULT(),
            )


###########################
# GetModelById
###########################


# Note: We're not using the typical url path param here, but instead using a query parameter to allow '/' in the id
@router.get("/connection/linked-usages")
async def get_connection_linked_usages(ids: str, _user=Depends(get_verified_user)):
    """Check if any of the given model IDs (comma-separated) are in use. Returns {in_use: bool}."""
    model_id_list = [mid.strip() for mid in ids.split(",") if mid.strip()]

    all_models = Models.get_all_models()
    all_guardrails = Guardrails.get_guardrails()

    for mid in model_id_list:
        for m in all_models:
            if m.base_model_id == mid:
                return {"in_use": True}
        for g in all_guardrails:
            if g.llm_judge_enabled and g.llm_judge_model == mid:
                return {"in_use": True}

    return {"in_use": False}


@router.get("/model/linked-usages")
async def get_model_linked_usages(id: str, _user=Depends(get_verified_user)):
    """Return agents, guardrails, and auto-evaluations that use this model ID."""
    result = {"agents": [], "guardrails": []}

    # 1. Agents using this model as base_model_id
    all_models = Models.get_all_models()
    for m in all_models:
        if m.base_model_id == id:
            result["agents"].append({"id": m.id, "name": m.name})

    # 2. Guardrails using this model as LLM judge
    all_guardrails = Guardrails.get_guardrails()
    for g in all_guardrails:
        if g.llm_judge_enabled and g.llm_judge_model == id:
            result["guardrails"].append({"id": g.id, "name": g.name})

    return result


def _meta_dict(meta) -> dict:
    if meta is None:
        return {}
    if isinstance(meta, dict):
        return meta
    if hasattr(meta, "model_dump"):
        return meta.model_dump()
    return {}


def _auto_eval_judge_for(meta: dict) -> Optional[str]:
    """Return judgeModelId from meta.autoEvaluation if and only if it is enabled.

    Auto-eval mapping lives on the agent row; only ``enabled`` rows count as
    live mappings — disabled config is just historical baggage from earlier
    setups.
    """
    raw = meta.get("autoEvaluation") or meta.get("auto_evaluation")
    if not isinstance(raw, dict):
        return None
    if not raw.get("enabled"):
        return None
    judge = raw.get("judgeModelId") or raw.get("judge_model_id")
    if not isinstance(judge, str) or not judge:
        return None
    return judge


def _flow_uses_model(meta: dict, model_id: str, agent_base: dict[str, str]) -> bool:
    """Whether a flow's node graph references ``model_id`` directly or via an
    agent node whose underlying base model is ``model_id``.

    Convenience predicate for callers (counts loop) that only need a boolean;
    detail responses use :func:`_flow_reference_kind` instead to surface both
    paths when they coexist in the same flow.
    """
    return _flow_reference_kind(meta, model_id, agent_base)[0] != "none"


def _flow_reference_kind(
    meta: dict, model_id: str, agent_base: dict[str, str]
) -> tuple[str, list[str]]:
    """Inspect a flow and report how it references ``model_id``.

    Returns ``(kind, via_agent_ids)`` where ``kind`` is one of:

    * ``"none"`` — the flow does not reference this model at all.
    * ``"direct"`` — referenced only through ``model`` nodes (or ``agent``
      nodes pointing at the model itself when the viewed row is an agent).
    * ``"via"`` — referenced only through agent nodes whose base model is
      ``model_id``.
    * ``"both"`` — referenced through both paths in the same flow.

    ``via_agent_ids`` lists distinct agent IDs from the indirect path in
    first-seen order; empty for ``direct`` / ``none``.
    """
    nodes = (meta.get("flow_data") or {}).get("nodes") or []
    if not isinstance(nodes, list):
        return "none", []
    direct = False
    seen: set[str] = set()
    via: list[str] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_type = node.get("type")
        data = node.get("data") or {}
        if node_type == "model":
            if (data.get("config") or {}).get("modelId") == model_id:
                direct = True
        elif node_type == "agent":
            res_id = data.get("resourceId")
            if not res_id:
                continue
            if res_id == model_id:
                direct = True
            elif agent_base.get(res_id) == model_id and res_id not in seen:
                seen.add(res_id)
                via.append(res_id)
    if direct and via:
        return "both", via
    if direct:
        return "direct", []
    if via:
        return "via", via
    return "none", []


@router.get("/model/usages/detail")
async def get_model_usages_detail(
    id: str, request: Request, _user=Depends(get_admin_settings_read_access)
):
    """Full list of items that depend on a single model: agents, flows, evaluations."""
    agents: list[dict] = []
    flows: list[dict] = []
    evaluations: list[dict] = []

    all_models = Models.get_all_models()
    agent_base: dict[str, str] = {
        m.id: m.base_model_id for m in all_models if m.base_model_id
    }
    name_for: dict[str, str] = {m.id: m.name for m in all_models}

    for m in all_models:
        meta = _meta_dict(m.meta)
        if meta.get("type") == "agent_flow":
            kind, via_ids = _flow_reference_kind(meta, id, agent_base)
            if kind == "none":
                continue
            entry: dict = {
                "id": m.id,
                "name": m.name,
                "direct": kind in ("direct", "both"),
            }
            if via_ids:
                entry["via"] = [
                    {"id": aid, "name": name_for.get(aid, aid)} for aid in via_ids
                ]
            flows.append(entry)
        elif m.base_model_id == id:
            agents.append({"id": m.id, "name": m.name})

    arena_models = (
        getattr(request.app.state.config, "EVALUATION_ARENA_MODELS", None) or []
    )
    for arena in arena_models:
        if not isinstance(arena, dict):
            continue
        ids = (arena.get("meta") or {}).get("model_ids") or []
        if isinstance(ids, list) and id in ids:
            evaluations.append(
                {
                    "id": arena.get("id") or "",
                    "name": arena.get("name")
                    or (arena.get("meta") or {}).get("name")
                    or arena.get("id")
                    or "",
                    "kind": "arena",
                }
            )

    # Live auto-evaluation mapping — agents that currently set this model as
    # their judge. Historical run counts intentionally excluded.
    for m in all_models:
        judge = _auto_eval_judge_for(_meta_dict(m.meta))
        if judge == id:
            evaluations.append(
                {
                    "id": m.id,
                    "name": m.name,
                    "kind": "auto_eval_judge",
                }
            )

    return {"agents": agents, "flows": flows, "evaluations": evaluations}


@router.get("/usages/counts")
async def get_models_usage_counts(
    request: Request, _user=Depends(get_admin_settings_read_access)
):
    """Per-model dependency counts for the admin Models page.

    Returns: {model_id: {agents, flows, evaluations}}. Models with no
    dependencies are omitted; the frontend treats absence as zero.
    """
    result: dict[str, dict[str, int]] = {}

    def bump(model_id: str, key: str) -> None:
        if not model_id:
            return
        bucket = result.setdefault(
            model_id, {"agents": 0, "flows": 0, "evaluations": 0}
        )
        bucket[key] += 1

    all_models = Models.get_all_models()
    agent_base: dict[str, str] = {
        m.id: m.base_model_id for m in all_models if m.base_model_id
    }

    # Agents: rows with base_model_id, excluding agent_flow rows
    for m in all_models:
        if not m.base_model_id:
            continue
        if _meta_dict(m.meta).get("type") == "agent_flow":
            continue
        bump(m.base_model_id, "agents")

    # Agent Flows: each flow contributes +1 to every distinct model it touches
    # — either directly via a model node, or indirectly through an agent node
    # whose base model is that model.
    for m in all_models:
        meta = _meta_dict(m.meta)
        if meta.get("type") != "agent_flow":
            continue
        nodes = (meta.get("flow_data") or {}).get("nodes") or []
        if not isinstance(nodes, list):
            continue
        seen: set[str] = set()

        def add_ref(mid: Optional[str]) -> None:
            if mid and mid not in seen:
                seen.add(mid)
                bump(mid, "flows")

        for node in nodes:
            if not isinstance(node, dict):
                continue
            node_type = node.get("type")
            data = node.get("data") or {}
            if node_type == "model":
                add_ref((data.get("config") or {}).get("modelId"))
            elif node_type == "agent":
                res_id = data.get("resourceId")
                # The flow uses the agent directly + the agent's base model.
                add_ref(res_id)
                add_ref(agent_base.get(res_id or ""))

    # Arena evaluation models: each entry has meta.model_ids[]
    arena_models = (
        getattr(request.app.state.config, "EVALUATION_ARENA_MODELS", None) or []
    )
    for arena in arena_models:
        if not isinstance(arena, dict):
            continue
        ids = (arena.get("meta") or {}).get("model_ids") or []
        if not isinstance(ids, list):
            continue
        for mid in set(filter(None, ids)):
            bump(mid, "evaluations")

    # Live auto-evaluation mapping — each agent contributes +1 to its judge.
    for m in all_models:
        judge = _auto_eval_judge_for(_meta_dict(m.meta))
        if judge:
            bump(judge, "evaluations")

    return result


@router.get("/model", response_model=Optional[ModelResponse])
async def get_model_by_id(id: str, user=Depends(get_verified_user)):
    model = Models.get_model_by_id(id)
    if model:
        if (
            user.role == "admin"
            or model.user_id == user.id
            or has_access(user.id, "read", model.access_control)
        ):
            return model
    else:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )


############################
# ToggelModelById
############################


@router.post("/model/toggle", response_model=Optional[ModelResponse])
async def toggle_model_by_id(
    request: Request, id: str, user=Depends(get_verified_user)
):
    model = Models.get_model_by_id(id)
    if model:
        if (
            user.role == "admin"
            or model.user_id == user.id
            or has_access(user.id, "write", model.access_control)
        ):
            model = Models.toggle_model_by_id(id)

            if model:
                _invalidate_models_cache(request)
                return model
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=ERROR_MESSAGES.DEFAULT("Error updating function"),
                )
        else:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=ERROR_MESSAGES.UNAUTHORIZED,
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )


############################
# UpdateModelById
############################


@router.post("/model/update", response_model=Optional[ModelModel])
async def update_model_by_id(
    request: Request,
    id: str,
    form_data: ModelForm,
    user=Depends(get_verified_user),
):
    model = Models.get_model_by_id(id)

    if not model:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    if (
        model.user_id != user.id
        and not has_access(user.id, "write", model.access_control)
        and user.role != "admin"
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    if Models.name_exists(form_data.name, exclude_id=id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NAME_TAKEN,
        )

    model = Models.update_model_by_id(id, form_data)
    if model:
        _invalidate_models_cache(request)
        # 변경분을 새 버전으로 기록 (no-op·base 모델은 create_version 내부에서 skip)
        AgentVersions.create_version(
            agent_id=model.id,
            snapshot=_agent_snapshot(model),
            user_id=model.user_id,
            created_by=user.id,
        )
    return model


############################
# DeleteModelById
############################


@router.delete("/model/delete", response_model=bool)
async def delete_model_by_id(
    request: Request, id: str, user=Depends(get_verified_user)
):
    model = Models.get_model_by_id(id)
    if not model:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    if (
        user.role != "admin"
        and model.user_id != user.id
        and not has_access(user.id, "write", model.access_control)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.UNAUTHORIZED,
        )

    result = Models.delete_model_by_id(id)
    if result:
        _invalidate_models_cache(request)
        AgentVersions.delete_versions_by_agent_id(id)
    return result


############################
# Agent Version History
############################


def _require_agent_read(model: ModelModel, user) -> None:
    if not (
        user.role == "admin"
        or model.user_id == user.id
        or has_access(user.id, "read", model.access_control)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.UNAUTHORIZED,
        )


def _require_agent_write(model: ModelModel, user) -> None:
    if (
        model.user_id != user.id
        and not has_access(user.id, "write", model.access_control)
        and user.role != "admin"
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )


@router.get("/model/versions", response_model=list[AgentVersionResponse])
async def get_agent_versions(id: str, user=Depends(get_verified_user)):
    model = Models.get_model_by_id(id)
    if not model:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=ERROR_MESSAGES.NOT_FOUND
        )
    _require_agent_read(model, user)
    return AgentVersions.get_versions_by_agent_id(id)


@router.get("/model/version", response_model=Optional[AgentVersionModel])
async def get_agent_version(id: str, version: int, user=Depends(get_verified_user)):
    model = Models.get_model_by_id(id)
    if not model:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=ERROR_MESSAGES.NOT_FOUND
        )
    _require_agent_read(model, user)
    ver = AgentVersions.get_version(id, version)
    if not ver:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=ERROR_MESSAGES.NOT_FOUND
        )
    return ver


@router.post("/model/version/label", response_model=Optional[AgentVersionModel])
async def update_agent_version_label(
    id: str,
    version: int,
    form_data: AgentVersionLabelForm,
    user=Depends(get_verified_user),
):
    model = Models.get_model_by_id(id)
    if not model:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=ERROR_MESSAGES.NOT_FOUND
        )
    _require_agent_write(model, user)
    return AgentVersions.update_label(id, version, form_data.label)


@router.post("/model/version/restore", response_model=Optional[ModelModel])
async def restore_agent_version(
    request: Request, id: str, version: int, user=Depends(get_verified_user)
):
    model = Models.get_model_by_id(id)
    if not model:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=ERROR_MESSAGES.NOT_FOUND
        )
    _require_agent_write(model, user)

    ver = AgentVersions.get_version(id, version)
    if not ver:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=ERROR_MESSAGES.NOT_FOUND
        )

    snap = ver.snapshot or {}
    form_data = _build_restore_form(model, snap)
    updated = Models.update_model_by_id(id, form_data)
    if updated:
        _invalidate_models_cache(request)
        # 복원도 새 버전으로 기록 (router 훅 방식이라 명시 호출 필요)
        AgentVersions.create_version(
            agent_id=updated.id,
            snapshot=_agent_snapshot(updated),
            user_id=updated.user_id,
            created_by=user.id,
            label=f"Restored from v{version}",
        )
    return updated


###########################
# Per-model Usage-Limit Overrides Aggregator
###########################


class OverrideEntry(BaseModel):
    id: str
    name: str
    tokens: int
    used_today: Optional[int] = None  # users tier 한정. groups/org_units = None.


class OverrideCounts(BaseModel):
    users: int
    groups: int
    org_units: int


def _model_per_limit(payload, model_id: str) -> Optional[int]:
    if not isinstance(payload, dict):
        return None
    usage_limit = payload.get("usage_limit") or {}
    per_model = usage_limit.get("per_model") if isinstance(usage_limit, dict) else None
    if not isinstance(per_model, dict):
        return None
    val = per_model.get(model_id)
    if val is None:
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def _collect_user_override_rows(model_id: str) -> list[tuple[str, str, int]]:
    """model_id 에 per-model override 가 설정된 사용자만 (id, name, tokens).

    사용량(`used_today`) 은 포함하지 않음 — 카운트/목록 양쪽에서 공유.
    """
    from open_webui.internal.db import get_db
    from open_webui.models.users import User

    rows: list[tuple[str, str, int]] = []
    with get_db() as db:
        for u in db.query(User).all():
            v = _model_per_limit(u.info or {}, model_id)
            if v is None:
                continue
            rows.append((u.id, u.name or u.email or u.id, v))
    return rows


def _gather_user_overrides(model_id: str) -> list[OverrideEntry]:
    """users tier 오버라이드 + 각 사용자의 today 사용량(`used_today`).

    today 사용량은 해당 model_id 한정 (base 모델이면 model_id 일치, agent
    이면 agent_id 일치). 매칭 사용자들의 사용량은 단일 GROUP BY 쿼리로
    배치 조회 (N+1 → 1).
    """
    from open_webui.models.models import Models
    from open_webui.models.usage import USER_QUOTA_MESSAGE_TYPES, Usages

    rows = _collect_user_override_rows(model_id)
    if not rows:
        return []

    model_row = Models.get_model_by_id(model_id)
    used_by_user: dict[str, int] = (
        Usages.get_users_daily_token_usage_for_model_row(
            [r[0] for r in rows], model_row, message_types=USER_QUOTA_MESSAGE_TYPES
        )
        if model_row is not None
        else {}
    )
    return [
        OverrideEntry(
            id=uid, name=name, tokens=tokens, used_today=used_by_user.get(uid, 0)
        )
        for uid, name, tokens in rows
    ]


def _gather_group_overrides(model_id: str) -> list[OverrideEntry]:
    from open_webui.models.groups import Groups

    out: list[OverrideEntry] = []
    for g in Groups.get_groups():
        v = _model_per_limit(g.meta or {}, model_id)
        if v is not None:
            out.append(OverrideEntry(id=g.id, name=g.name or g.id, tokens=v))
    return out


def _gather_org_unit_overrides(model_id: str) -> list[OverrideEntry]:
    from open_webui.internal.db import get_db
    from open_webui.models.organization import OrganizationalUnit

    out: list[OverrideEntry] = []
    with get_db() as db:
        for u in db.query(OrganizationalUnit).all():
            v = _model_per_limit(u.meta or {}, model_id)
            if v is not None:
                out.append(
                    OverrideEntry(
                        id=u.id, name=u.display_name or u.name or u.id, tokens=v
                    )
                )
    return out


_TIER_GATHERERS = {
    "users": _gather_user_overrides,
    "groups": _gather_group_overrides,
    "org_units": _gather_org_unit_overrides,
}


@router.get("/usage-limit/overrides/counts", response_model=OverrideCounts)
async def get_usage_limit_override_counts(
    id: str, user=Depends(get_admin_settings_read_access)
):
    """주어진 model_id 에 대해 user/group/org_unit override 행 개수.

    카운트만 필요하므로 사용량 배치 쿼리는 생략 (List 뷰와 분리).
    """
    return OverrideCounts(
        users=len(_collect_user_override_rows(id)),
        groups=len(_gather_group_overrides(id)),
        org_units=len(_gather_org_unit_overrides(id)),
    )


@router.get("/usage-limit/overrides/list", response_model=list[OverrideEntry])
async def list_usage_limit_overrides(
    id: str,
    tier: str,
    q: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
    user=Depends(get_admin_settings_read_access),
):
    """주어진 model_id 의 한 계층(users/groups/org_units) 오버라이드 페이징 조회."""
    gather = _TIER_GATHERERS.get(tier)
    if gather is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT(f"Unknown tier: {tier}"),
        )
    rows = gather(id)
    if q:
        needle = q.lower()
        rows = [r for r in rows if needle in r.name.lower() or needle in r.id.lower()]
    rows.sort(key=lambda r: r.name.lower())
    return rows[max(0, skip) : max(0, skip) + max(1, limit)]


@router.delete("/delete/all", response_model=bool)
async def delete_all_models(
    request: Request, user=Depends(get_admin_settings_write_access)
):
    result = Models.delete_all_models()
    if result:
        _invalidate_models_cache(request)
    return result

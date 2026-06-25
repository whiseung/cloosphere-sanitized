import logging
import re
import time
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from open_webui.constants import ERROR_MESSAGES
from open_webui.env import SRC_LOG_LEVELS
from open_webui.models.models import ModelForm, ModelMeta, ModelParams, Models
from open_webui.utils.access_control import (
    has_access,
    has_permission_min_level,
)
from open_webui.utils.auth import get_verified_user
from open_webui.utils.license import require_feature
from pydantic import BaseModel

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])

router = APIRouter(dependencies=[Depends(require_feature("agent_flow"))])

# Flow model ID prefix
FLOW_MODEL_PREFIX = "flow_"
FLOW_MODEL_PREFIX_LEGACY = "flow."  # 기존 데이터 하위 호환


def _has_flow_prefix(model_id: str) -> bool:
    """Check if model ID has flow prefix (current or legacy)."""
    return model_id.startswith(FLOW_MODEL_PREFIX) or model_id.startswith(
        FLOW_MODEL_PREFIX_LEGACY
    )


def _strip_flow_prefix(model_id: str) -> str:
    """Strip flow prefix (current or legacy) from model ID."""
    if model_id.startswith(FLOW_MODEL_PREFIX):
        return model_id[len(FLOW_MODEL_PREFIX) :]
    if model_id.startswith(FLOW_MODEL_PREFIX_LEGACY):
        return model_id[len(FLOW_MODEL_PREFIX_LEGACY) :]
    return model_id


def _resolve_flow_model_id(flow_id: str) -> str:
    """Resolve flow ID to model ID, checking both current and legacy prefix."""
    if _has_flow_prefix(flow_id):
        return flow_id

    # 새 접두사 우선
    model = Models.get_model_by_id(f"{FLOW_MODEL_PREFIX}{flow_id}")
    if model:
        return f"{FLOW_MODEL_PREFIX}{flow_id}"

    # 레거시 접두사 fallback
    model = Models.get_model_by_id(f"{FLOW_MODEL_PREFIX_LEGACY}{flow_id}")
    if model:
        return f"{FLOW_MODEL_PREFIX_LEGACY}{flow_id}"

    return f"{FLOW_MODEL_PREFIX}{flow_id}"


def is_flow_model(model) -> bool:
    """Check if a model is an agent flow."""
    if not model:
        return False
    if _has_flow_prefix(model.id):
        return True
    if model.meta:
        meta = (
            model.meta.model_dump() if hasattr(model.meta, "model_dump") else model.meta
        )
        return meta.get("type") == "agent_flow"
    return False


def flow_model_to_response(model) -> dict:
    """Convert a Model to a flow response format."""
    from open_webui.models.users import Users

    meta = (
        model.meta.model_dump()
        if hasattr(model.meta, "model_dump")
        else (model.meta or {})
    )
    user = Users.get_user_by_id(model.user_id)
    return {
        "id": _strip_flow_prefix(model.id),
        "user_id": model.user_id,
        "name": model.name,
        "description": meta.get("description"),
        "flow_data": meta.get("flow_data"),
        "meta": {
            k: v
            for k, v in meta.items()
            if k not in ["type", "flow_data", "description"]
        },
        "access_control": model.access_control,
        "is_active": model.is_active,
        "created_at": model.created_at,
        "updated_at": model.updated_at,
        "user": {
            "id": user.id,
            "name": user.name,
            "email": user.email,
        }
        if user
        else None,
    }


############################
# Forms
############################


class AgentFlowForm(BaseModel):
    id: str  # 사용자 지정 Flow ID (필수)
    name: str
    description: Optional[str] = None
    flow_data: Optional[dict] = None
    meta: Optional[dict] = None
    access_control: Optional[dict] = None
    is_active: bool = True


class AgentFlowUpdateForm(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    flow_data: Optional[dict] = None
    meta: Optional[dict] = None
    access_control: Optional[dict] = None
    is_active: Optional[bool] = None


class AgentFlowValidateForm(BaseModel):
    flow_data: dict


class AgentFlowValidateResponse(BaseModel):
    valid: bool
    errors: List[dict] = []
    warnings: List[dict] = []


def _validate_flow_data(flow_data) -> None:
    """Validate flow_data structure. Raises HTTPException on invalid data."""
    if flow_data is None:
        return  # Allow None (draft flows)

    if not isinstance(flow_data, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("flow_data must be a dictionary"),
        )

    nodes = flow_data.get("nodes")
    edges = flow_data.get("edges")

    if nodes is not None and not isinstance(nodes, list):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("flow_data.nodes must be a list"),
        )

    if edges is not None and not isinstance(edges, list):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("flow_data.edges must be a list"),
        )

    for node in nodes or []:
        if not isinstance(node, dict) or not node.get("id") or not node.get("type"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ERROR_MESSAGES.DEFAULT(
                    "Each node must have 'id' and 'type' fields"
                ),
            )


############################
# getAgentFlows
############################


@router.get("/")
async def get_agent_flows(request: Request, user=Depends(get_verified_user)):
    """Get all agent flows accessible to the user."""
    if user.role != "admin" and not has_permission_min_level(
        user.id,
        "workspace.agent_flows",
        "read",
        request.app.state.config.USER_PERMISSIONS,
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    all_models = Models.get_all_models()
    flows = []

    for model in all_models:
        if not is_flow_model(model):
            continue

        if not model.is_active:
            continue

        # Check access
        if user.role != "admin":
            if model.user_id != user.id and not has_access(
                user.id, "read", model.access_control
            ):
                continue

        flows.append(flow_model_to_response(model))

    return flows


@router.get("/list")
async def get_agent_flows_list(request: Request, user=Depends(get_verified_user)):
    """Get agent flows list with write permission check."""
    if user.role != "admin" and not has_permission_min_level(
        user.id,
        "workspace.agent_flows",
        "write",
        request.app.state.config.USER_PERMISSIONS,
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )
    all_models = Models.get_all_models()
    flows = []

    for model in all_models:
        if not is_flow_model(model):
            continue

        # Check write access
        if user.role != "admin":
            if model.user_id != user.id and not has_access(
                user.id, "write", model.access_control
            ):
                continue

        flows.append(flow_model_to_response(model))

    return flows


############################
# CheckFlowIdAvailable
############################


@router.get("/check/{flow_id}")
async def check_flow_id_available(flow_id: str, user=Depends(get_verified_user)):
    """Check if a flow ID is available."""
    # 새 접두사 + 레거시 접두사 모두 확인
    existing_new = Models.get_model_by_id(f"{FLOW_MODEL_PREFIX}{flow_id}")
    existing_legacy = Models.get_model_by_id(f"{FLOW_MODEL_PREFIX_LEGACY}{flow_id}")
    return {"available": existing_new is None and existing_legacy is None}


############################
# CreateNewAgentFlow
############################


@router.post("/create")
async def create_new_agent_flow(
    request: Request, form_data: AgentFlowForm, user=Depends(get_verified_user)
):
    """Create a new agent flow."""
    if user.role != "admin" and not has_permission_min_level(
        user.id,
        "workspace.agent_flows",
        "write",
        request.app.state.config.USER_PERMISSIONS,
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    # Flow ID 검증
    flow_id = form_data.id.strip().lower()

    if not flow_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("Flow ID is required"),
        )

    # ID 형식 검증: 영문 소문자, 숫자, 하이픈, 언더스코어만 허용
    if not re.match(r"^[a-z0-9][a-z0-9_-]*$", flow_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT(
                "Flow ID must start with a letter or number and contain only lowercase letters, numbers, and hyphens"
            ),
        )
    if len(flow_id) < 2 or len(flow_id) > 50:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT(
                "Flow ID must be between 2 and 50 characters"
            ),
        )

    model_id = f"{FLOW_MODEL_PREFIX}{flow_id}"

    # 중복 체크 (새 접두사 + 레거시 접두사)
    existing = Models.get_model_by_id(model_id) or Models.get_model_by_id(
        f"{FLOW_MODEL_PREFIX_LEGACY}{flow_id}"
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT(f"Flow ID already in use: {flow_id}"),
        )

    if Models.name_exists(form_data.name):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NAME_TAKEN,
        )

    _validate_flow_data(form_data.flow_data)

    # Build meta with flow data
    meta_dict = {
        "profile_image_url": "/static/favicon.png",
        "description": form_data.description,
        "type": "agent_flow",
        "flow_data": form_data.flow_data,
        **(form_data.meta or {}),
    }

    model_form = ModelForm(
        id=model_id,
        base_model_id=None,
        name=form_data.name,
        meta=ModelMeta(**meta_dict),
        params=ModelParams(),
        access_control=form_data.access_control,
        is_active=form_data.is_active,
    )

    model = Models.insert_new_model(model_form, user.id)

    if model:
        return flow_model_to_response(model)
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("Error creating agent flow"),
        )


############################
# GetAgentFlowById
############################


@router.get("/{id}")
async def get_agent_flow_by_id(id: str, user=Depends(get_verified_user)):
    """Get an agent flow by ID."""
    model_id = _resolve_flow_model_id(id)
    model = Models.get_model_by_id(model_id)

    if model and is_flow_model(model):
        if (
            user.role == "admin"
            or model.user_id == user.id
            or has_access(user.id, "read", model.access_control)
        ):
            return flow_model_to_response(model)

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=ERROR_MESSAGES.NOT_FOUND,
    )


############################
# UpdateAgentFlowById
############################


@router.post("/{id}/update")
async def update_agent_flow_by_id(
    id: str,
    request: Request,
    form_data: AgentFlowUpdateForm,
    user=Depends(get_verified_user),
):
    """Update an agent flow by ID."""
    model_id = _resolve_flow_model_id(id)
    model = Models.get_model_by_id(model_id)

    if not model or not is_flow_model(model):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    if model.user_id != user.id and user.role != "admin":
        if not has_access(user.id, "write", model.access_control):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
            )

    if form_data.name is not None and Models.name_exists(
        form_data.name, exclude_id=model_id
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NAME_TAKEN,
        )

    if form_data.flow_data is not None:
        _validate_flow_data(form_data.flow_data)

    # Build updated meta
    current_meta = (
        model.meta.model_dump()
        if hasattr(model.meta, "model_dump")
        else (model.meta or {})
    )

    updated_meta_dict = {
        "profile_image_url": current_meta.get(
            "profile_image_url", "/static/favicon.png"
        ),
        "description": form_data.description
        if form_data.description is not None
        else current_meta.get("description"),
        "type": "agent_flow",
        "flow_data": form_data.flow_data
        if form_data.flow_data is not None
        else current_meta.get("flow_data"),
        **(
            form_data.meta
            if form_data.meta
            else {
                k: v
                for k, v in current_meta.items()
                if k not in ["type", "flow_data", "description", "profile_image_url"]
            }
        ),
    }

    model_form = ModelForm(
        id=model_id,
        base_model_id=None,
        name=form_data.name if form_data.name is not None else model.name,
        meta=ModelMeta(**updated_meta_dict),
        params=model.params if hasattr(model, "params") else ModelParams(),
        access_control=form_data.access_control
        if form_data.access_control is not None
        else model.access_control,
        is_active=form_data.is_active
        if form_data.is_active is not None
        else model.is_active,
    )

    updated_model = Models.update_model_by_id(model_id, model_form)

    if updated_model:
        return flow_model_to_response(updated_model)
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("Error updating agent flow"),
        )


############################
# DeleteAgentFlowById
############################


@router.delete("/{id}/delete", response_model=bool)
async def delete_agent_flow_by_id(id: str, user=Depends(get_verified_user)):
    """Delete an agent flow by ID."""
    model_id = _resolve_flow_model_id(id)
    model = Models.get_model_by_id(model_id)

    if not model or not is_flow_model(model):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    if model.user_id != user.id and user.role != "admin":
        if not has_access(user.id, "write", model.access_control):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
            )

    result = Models.delete_model_by_id(model_id)

    if result:
        return True
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("Error deleting agent flow"),
        )


############################
# ValidateAgentFlow
############################


@router.post("/validate", response_model=AgentFlowValidateResponse)
async def validate_agent_flow(
    request: Request, form_data: AgentFlowValidateForm, user=Depends(get_verified_user)
):
    """Validate agent flow configuration."""
    if user.role != "admin" and not has_permission_min_level(
        user.id,
        "workspace.agent_flows",
        "read",
        request.app.state.config.USER_PERMISSIONS,
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )
    errors = []
    warnings = []
    flow_data = form_data.flow_data

    nodes = flow_data.get("nodes", [])
    edges = flow_data.get("edges", [])

    # Check for input/output nodes (optional since implicit entry/exit is supported)
    input_types = {"input", "flowInput"}
    output_types = {"output", "flowOutput"}
    input_nodes = [n for n in nodes if n.get("type") in input_types]
    output_nodes = [n for n in nodes if n.get("type") in output_types]

    if not input_nodes:
        warnings.append(
            {
                "type": "no_input_node",
                "message": "No Input node found. The first node in the flow will be used as the entry point.",
            }
        )

    if not output_nodes:
        warnings.append(
            {
                "type": "no_output_node",
                "message": "No Output node found. Leaf nodes will automatically connect to the flow end.",
            }
        )

    # Check for unsupported node types
    supported_types = {
        "input",
        "flowInput",
        "output",
        "flowOutput",
        "agent",
        "model",
        "guardrail",
        "condition",
        "router",
        "merge",
        "glossary",
        "transform",
    }
    for node in nodes:
        node_type = node.get("type")
        if node_type and node_type not in supported_types:
            errors.append(
                {
                    "type": "unsupported_node",
                    "nodeId": node.get("id"),
                    "message": f"Unsupported node type: '{node_type}'",
                }
            )

    # Check for orphan nodes (not connected)
    node_ids = {n.get("id") for n in nodes}
    connected_nodes = set()
    for edge in edges:
        connected_nodes.add(edge.get("source"))
        connected_nodes.add(edge.get("target"))

    orphan_nodes = node_ids - connected_nodes
    for node_id in orphan_nodes:
        node = next((n for n in nodes if n.get("id") == node_id), None)
        # Single-node flows are valid (entry + exit in one node)
        if node and len(nodes) > 1:
            warnings.append(
                {
                    "type": "orphan_node",
                    "nodeId": node_id,
                    "message": f"Node {node_id} is not connected to any other node",
                }
            )

    # Check for cycles (simple DFS)
    adjacency = {n.get("id"): [] for n in nodes}
    for edge in edges:
        source = edge.get("source")
        target = edge.get("target")
        if source in adjacency:
            adjacency[source].append(target)

    def has_cycle(node, visited, rec_stack):
        visited.add(node)
        rec_stack.add(node)
        for neighbor in adjacency.get(node, []):
            if neighbor not in visited:
                if has_cycle(neighbor, visited, rec_stack):
                    return True
            elif neighbor in rec_stack:
                return True
        rec_stack.remove(node)
        return False

    visited = set()
    for node_id in node_ids:
        if node_id not in visited:
            if has_cycle(node_id, visited, set()):
                errors.append(
                    {
                        "type": "cycle_detected",
                        "message": "Flow contains a cycle which may cause infinite loops",
                    }
                )
                break

    # Validate node configurations
    for node in nodes:
        node_type = node.get("type")
        node_data = node.get("data", {})

        if node_type in ["agent", "model"]:
            if not node_data.get("resourceId"):
                errors.append(
                    {
                        "type": "missing_config",
                        "nodeId": node.get("id"),
                        "message": f"Agent/Model node {node.get('id')} has no agent selected",
                    }
                )

        elif node_type == "guardrail":
            if not node_data.get("resourceId"):
                errors.append(
                    {
                        "type": "missing_config",
                        "nodeId": node.get("id"),
                        "message": f"Guardrail node {node.get('id')} has no guardrail selected",
                    }
                )

    return AgentFlowValidateResponse(
        valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
    )


############################
# Import/Export
############################


@router.get("/{id}/export")
async def export_agent_flow(id: str, user=Depends(get_verified_user)):
    """Export an agent flow as JSON."""
    model_id = _resolve_flow_model_id(id)
    model = Models.get_model_by_id(model_id)

    if not model or not is_flow_model(model):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    if model.user_id != user.id and user.role != "admin":
        if not has_access(user.id, "read", model.access_control):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
            )

    meta = (
        model.meta.model_dump()
        if hasattr(model.meta, "model_dump")
        else (model.meta or {})
    )

    export_data = {
        "version": "1.0",
        "type": "agent_flow",
        "name": model.name,
        "description": meta.get("description"),
        "flow_data": meta.get("flow_data"),
        "meta": {
            k: v
            for k, v in meta.items()
            if k not in ["type", "flow_data", "description", "profile_image_url"]
        },
    }

    return export_data


class FlowImportForm(BaseModel):
    data: dict
    name: Optional[str] = None


@router.post("/import")
async def import_agent_flow(
    request: Request, form_data: FlowImportForm, user=Depends(get_verified_user)
):
    """Import an agent flow from JSON."""
    if user.role != "admin" and not has_permission_min_level(
        user.id,
        "workspace.agent_flows",
        "write",
        request.app.state.config.USER_PERMISSIONS,
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    data = form_data.data

    if data.get("type") != "agent_flow":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid import data: not an agent flow",
        )

    _validate_flow_data(data.get("flow_data"))

    # Generate flow ID
    flow_id = str(uuid.uuid4())
    model_id = f"{FLOW_MODEL_PREFIX}{flow_id}"

    meta_dict = {
        "profile_image_url": "/static/favicon.png",
        "description": data.get("description"),
        "type": "agent_flow",
        "flow_data": data.get("flow_data"),
        **(data.get("meta") or {}),
    }

    model_form = ModelForm(
        id=model_id,
        base_model_id=None,
        name=form_data.name or data.get("name", "Imported Flow"),
        meta=ModelMeta(**meta_dict),
        params=ModelParams(),
        access_control=None,
        is_active=True,
    )

    model = Models.insert_new_model(model_form, user.id)

    if model:
        return flow_model_to_response(model)
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("Error importing agent flow"),
        )


############################
# AutoBuildAgentFlow
############################


class AutoBuildFlowForm(BaseModel):
    name: str = ""
    intent: str
    model_id: Optional[str] = None


class AutoBuildChatForm(BaseModel):
    messages: List[dict]
    model_id: Optional[str] = None
    flow_name: str = ""
    flow_id: Optional[str] = None  # Existing flow to update


@router.post("/auto-build/chat")
async def auto_build_flow_chat(
    request: Request,
    form_data: AutoBuildChatForm,
    user=Depends(get_verified_user),
):
    """Multi-turn conversational flow building with Human-in-the-Loop."""
    if user.role != "admin" and not has_permission_min_level(
        user.id,
        "workspace.agent_flows",
        "write",
        request.app.state.config.USER_PERMISSIONS,
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

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

    try:
        from extension_modules.agent_flow.flow_builder_agent import FlowBuilderAgent
        from extension_modules.utils.llm import get_model_config_from_app

        model_config = get_model_config_from_app(request.app, form_data.model_id)
        if not model_config:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ERROR_MESSAGES.DEFAULT(
                    f"Model '{form_data.model_id}' not found"
                ),
            )

        agent = FlowBuilderAgent(
            api_config=model_config.get("api_config", {}),
            base_url=model_config.get("base_url", ""),
            api_key=model_config.get("api_key", ""),
            metadata={
                "user_id": user.id,
                "user_role": user.role,
                "chat_id": f"flow-builder-{int(time.time())}",
            },
            request=request,
        )

        result = await agent.run_chat(
            messages=form_data.messages,
            model_id=form_data.model_id,
        )

        # Auto-save flow if generated
        if result.get("flow_data") and result["flow_data"].get("nodes"):
            if form_data.flow_id:
                # Update existing flow
                model_id = _resolve_flow_model_id(form_data.flow_id)
                model = Models.get_model_by_id(model_id)
                if model:
                    current_meta = (
                        model.meta.model_dump()
                        if hasattr(model.meta, "model_dump")
                        else (model.meta or {})
                    )
                    current_meta["flow_data"] = result["flow_data"]
                    model_form = ModelForm(
                        id=model_id,
                        base_model_id=None,
                        name=result.get("flow_name") or model.name,
                        meta=ModelMeta(**current_meta),
                        params=model.params
                        if hasattr(model, "params")
                        else ModelParams(),
                        access_control=model.access_control,
                        is_active=model.is_active,
                    )
                    Models.update_model_by_id(model_id, model_form)
                    result["flow_id"] = form_data.flow_id
            else:
                # Create new flow
                flow_id = await agent.save_flow(
                    user_id=user.id,
                    flow_data=result["flow_data"],
                    flow_name=result.get("flow_name")
                    or form_data.flow_name
                    or "AI Flow",
                    flow_description=result.get("flow_description", ""),
                )
                result["flow_id"] = flow_id

        # Save chat history to flow meta (always, not just when flow_data is generated)
        save_history_flow_id = result.get("flow_id") or form_data.flow_id
        if save_history_flow_id:
            try:
                mid = _resolve_flow_model_id(save_history_flow_id)
                m = Models.get_model_by_id(mid)
                if m:
                    meta = (
                        m.meta.model_dump()
                        if hasattr(m.meta, "model_dump")
                        else (m.meta or {})
                    )
                    meta["ai_chat_history"] = form_data.messages + [
                        {
                            "role": "assistant",
                            "content": result.get("assistant_message", ""),
                        }
                    ]
                    uf = ModelForm(
                        id=mid,
                        base_model_id=None,
                        name=m.name,
                        meta=ModelMeta(**meta),
                        params=m.params if hasattr(m, "params") else ModelParams(),
                        access_control=m.access_control,
                        is_active=m.is_active,
                    )
                    Models.update_model_by_id(mid, uf)
            except Exception as e:
                log.warning(f"Failed to save chat history: {e}")

        return result

    except Exception as e:
        log.exception(f"Auto-build chat failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=ERROR_MESSAGES.DEFAULT(f"Chat failed: {str(e)}"),
        )


@router.post("/auto-build")
async def auto_build_agent_flow(
    request: Request,
    form_data: AutoBuildFlowForm,
    user=Depends(get_verified_user),
):
    """AI auto-generates a flow from natural language intent."""
    if user.role != "admin" and not has_permission_min_level(
        user.id,
        "workspace.agent_flows",
        "write",
        request.app.state.config.USER_PERMISSIONS,
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    if not form_data.intent or len(form_data.intent.strip()) < 10:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("Intent must be at least 10 characters"),
        )

    if not form_data.model_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("model_id is required"),
        )

    try:
        from extension_modules.agent_flow.flow_builder_agent import FlowBuilderAgent
        from extension_modules.utils.llm import get_model_config_from_app

        # Get API config for the builder LLM
        model_config = get_model_config_from_app(request.app, form_data.model_id)
        if not model_config:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ERROR_MESSAGES.DEFAULT(
                    f"Model '{form_data.model_id}' not found"
                ),
            )

        agent = FlowBuilderAgent(
            api_config=model_config.get("api_config", {}),
            base_url=model_config.get("base_url", ""),
            api_key=model_config.get("api_key", ""),
            metadata={
                "user_id": user.id,
                "user_role": user.role,
                "chat_id": f"flow-builder-{int(time.time())}",
            },
            request=request,
        )

        # Run builder agent
        result = await agent.run(
            intent=form_data.intent,
            model_id=form_data.model_id,
            flow_name=form_data.name,
        )

        # Save flow
        flow_id = await agent.save_flow(
            user_id=user.id,
            flow_data=result["flow_data"],
            flow_name=result["flow_name"],
            flow_description=result["flow_description"],
        )

        # Return the saved flow
        model_id = f"flow_{flow_id}"
        model = Models.get_model_by_id(model_id)
        if model:
            return flow_model_to_response(model)
        else:
            return {
                "id": flow_id,
                "name": result["flow_name"],
                "description": result["flow_description"],
                "flow_data": result["flow_data"],
            }

    except Exception as e:
        log.exception(f"Auto-build flow failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=ERROR_MESSAGES.DEFAULT(f"Failed to auto-build flow: {str(e)}"),
        )

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from open_webui.constants import ERROR_MESSAGES
from open_webui.env import SRC_LOG_LEVELS
from open_webui.models.guardrails import (
    GuardrailForm,
    GuardrailModel,
    Guardrails,
    GuardrailTestForm,
    GuardrailTestResponse,
    GuardrailUserModel,
)
from open_webui.models.models import Models
from open_webui.utils.access_control import (
    has_access,
    has_permission_min_level,
)
from open_webui.utils.auth import get_verified_user
from open_webui.utils.guardrails import GuardrailEngine
from open_webui.utils.license import require_feature

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])

router = APIRouter(dependencies=[Depends(require_feature("guardrail"))])


############################
# getGuardrails
############################


@router.get("/", response_model=list[GuardrailUserModel])
async def get_guardrails(request: Request, user=Depends(get_verified_user)):
    """Get all guardrails accessible to the user."""
    if user.role != "admin" and not has_permission_min_level(
        user.id,
        "workspace.guardrails",
        "read",
        request.app.state.config.USER_PERMISSIONS,
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    if user.role == "admin":
        guardrails = Guardrails.get_guardrails()
    else:
        guardrails = Guardrails.get_guardrails_by_user_id(user.id, "read")

    return guardrails


@router.get("/list", response_model=list[GuardrailUserModel])
async def get_guardrails_list(request: Request, user=Depends(get_verified_user)):
    """Get guardrails list with write permission check."""
    if user.role != "admin" and not has_permission_min_level(
        user.id,
        "workspace.guardrails",
        "read",
        request.app.state.config.USER_PERMISSIONS,
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    if user.role == "admin":
        guardrails = Guardrails.get_guardrails()
    else:
        guardrails = Guardrails.get_guardrails_by_user_id(user.id, "write")

    return guardrails


############################
# CreateNewGuardrail
############################


@router.post("/create", response_model=Optional[GuardrailModel])
async def create_new_guardrail(
    request: Request, form_data: GuardrailForm, user=Depends(get_verified_user)
):
    """Create a new guardrail."""
    if user.role != "admin" and not has_permission_min_level(
        user.id,
        "workspace.guardrails",
        "write",
        request.app.state.config.USER_PERMISSIONS,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.UNAUTHORIZED,
        )

    if Guardrails.name_exists(form_data.name):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NAME_TAKEN,
        )

    guardrail = Guardrails.insert_new_guardrail(user.id, form_data)

    if guardrail:
        return guardrail
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("Error creating guardrail"),
        )


############################
# GetGuardrailById
############################


@router.get("/{id}", response_model=Optional[GuardrailModel])
async def get_guardrail_by_id(id: str, user=Depends(get_verified_user)):
    """Get a guardrail by ID."""
    guardrail = Guardrails.get_guardrail_by_id(id)

    if guardrail:
        if (
            user.role == "admin"
            or guardrail.user_id == user.id
            or has_access(user.id, "read", guardrail.access_control)
        ):
            return guardrail

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=ERROR_MESSAGES.NOT_FOUND,
    )


############################
# UpdateGuardrailById
############################


@router.post("/{id}/update", response_model=Optional[GuardrailModel])
async def update_guardrail_by_id(
    id: str, request: Request, form_data: GuardrailForm, user=Depends(get_verified_user)
):
    """Update a guardrail by ID."""
    guardrail = Guardrails.get_guardrail_by_id(id)

    if not guardrail:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    if guardrail.user_id != user.id and user.role != "admin":
        if not has_access(user.id, "write", guardrail.access_control):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=ERROR_MESSAGES.UNAUTHORIZED,
            )

    if Guardrails.name_exists(form_data.name, exclude_id=id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NAME_TAKEN,
        )

    updated_guardrail = Guardrails.update_guardrail_by_id(id, form_data)

    if updated_guardrail:
        return updated_guardrail
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("Error updating guardrail"),
        )


############################
# DeleteGuardrailById
############################


@router.get("/{id}/linked-agents")
async def get_linked_agents_by_guardrail_id(id: str, _user=Depends(get_verified_user)):
    """Return agents (models) that have this guardrail connected."""
    guardrail = Guardrails.get_guardrail_by_id(id=id)
    if not guardrail:
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
        guardrails_list = meta.get("guardrails", []) or []
        if isinstance(guardrails_list, str):
            guardrails_list = [guardrails_list]
        for g in guardrails_list:
            if isinstance(g, dict) and g.get("id") == id:
                linked.append({"id": model.id, "name": model.name})
                break
            elif isinstance(g, str) and g == id:
                linked.append({"id": model.id, "name": model.name})
                break
    return linked


@router.delete("/{id}/delete", response_model=bool)
async def delete_guardrail_by_id(id: str, user=Depends(get_verified_user)):
    """Delete a guardrail by ID."""
    guardrail = Guardrails.get_guardrail_by_id(id)

    if not guardrail:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    if guardrail.user_id != user.id and user.role != "admin":
        if not has_access(user.id, "write", guardrail.access_control):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=ERROR_MESSAGES.UNAUTHORIZED,
            )

    result = Guardrails.delete_guardrail_by_id(id)

    if result:
        return True
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("Error deleting guardrail"),
        )


############################
# TestGuardrail
############################


@router.post("/test", response_model=GuardrailTestResponse)
async def test_guardrail(
    request: Request, form_data: GuardrailTestForm, user=Depends(get_verified_user)
):
    """Test guardrail with sample text."""
    config = None

    # Get config from guardrail_id or use provided config
    if form_data.guardrail_id:
        guardrail = Guardrails.get_guardrail_by_id(form_data.guardrail_id)
        if not guardrail:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=ERROR_MESSAGES.NOT_FOUND,
            )
        config = guardrail.model_dump()
    elif form_data.config:
        config = form_data.config.model_dump()
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either guardrail_id or config must be provided",
        )

    # Process the text
    engine = GuardrailEngine(config)
    processed_text, violations, blocked = engine.process_text(
        form_data.text, is_input=True
    )

    return GuardrailTestResponse(
        processed_text=processed_text,
        violations=violations,
        blocked=blocked,
        message="Content blocked by guardrail" if blocked else None,
    )

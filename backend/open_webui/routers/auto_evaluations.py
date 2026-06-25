import csv
import io
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from open_webui.constants import ERROR_MESSAGES
from open_webui.models.auto_evaluations import (
    AutoEvaluationForm,
    AutoEvaluationListResponse,
    AutoEvaluationResponse,
    AutoEvaluations,
    AutoEvaluationStatsResponse,
    AutoEvaluationUpdateForm,
)
from open_webui.models.users import Users
from open_webui.utils.auth import (
    get_admin_evaluations_read_access,
    get_admin_evaluations_write_access,
    get_verified_user,
)
from open_webui.utils.license import require_feature
from pydantic import BaseModel

router = APIRouter(dependencies=[Depends(require_feature("evaluation"))])


####################
# Auto Evaluation User Response Model
####################


class AutoEvaluationUserInfo(BaseModel):
    id: str
    name: str
    email: str
    role: str = "pending"


class AutoEvaluationWithUserResponse(AutoEvaluationResponse):
    user: Optional[AutoEvaluationUserInfo] = None


####################
# List Auto Evaluations (Admin)
####################


@router.get("/", response_model=AutoEvaluationListResponse)
async def get_auto_evaluations(
    model_id: Optional[str] = Query(None, description="Filter by model ID"),
    evaluation_type: Optional[str] = Query(
        None, description="Filter by evaluation type (retrieval, faithfulness, quality)"
    ),
    status_filter: Optional[str] = Query(
        None,
        alias="status",
        description="Filter by status (pending, completed, failed)",
    ),
    score_min: Optional[float] = Query(
        None, ge=0.0, le=1.0, description="Minimum score"
    ),
    score_max: Optional[float] = Query(
        None, ge=0.0, le=1.0, description="Maximum score"
    ),
    date_from: Optional[int] = Query(None, description="Start date (epoch timestamp)"),
    date_to: Optional[int] = Query(None, description="End date (epoch timestamp)"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(50, ge=1, le=100, description="Items per page"),
    sort_by: str = Query("created_at", description="Sort field"),
    order: str = Query("desc", description="Sort order (asc or desc)"),
    user=Depends(get_admin_evaluations_read_access),
):
    """
    Get list of auto evaluations with filtering, sorting, and pagination.
    """
    items, total = AutoEvaluations.get_auto_evaluations(
        model_id=model_id,
        evaluation_type=evaluation_type,
        status=status_filter,
        score_min=score_min,
        score_max=score_max,
        date_from=date_from,
        date_to=date_to,
        page=page,
        limit=limit,
        sort_by=sort_by,
        order=order,
    )

    return AutoEvaluationListResponse(
        items=[AutoEvaluationResponse(**item.model_dump()) for item in items],
        total=total,
        page=page,
        limit=limit,
    )


####################
# Get Stats (Admin)
####################


@router.get("/stats", response_model=AutoEvaluationStatsResponse)
async def get_auto_evaluation_stats(user=Depends(get_admin_evaluations_read_access)):
    """
    Get statistics for auto evaluations.
    """
    stats = AutoEvaluations.get_stats()
    return AutoEvaluationStatsResponse(**stats)


####################
# Export Auto Evaluations (Admin)
####################


@router.get("/export")
async def export_auto_evaluations(
    format: str = Query("csv", description="Export format (csv or json)"),
    user=Depends(get_admin_evaluations_read_access),
):
    """
    Export all auto evaluations.
    """
    auto_evals = AutoEvaluations.get_all_auto_evaluations()

    if format == "json":
        return [ae.model_dump() for ae in auto_evals]

    # Default to CSV
    output = io.StringIO()
    writer = csv.writer(output)

    # Write header
    writer.writerow(
        [
            "id",
            "chat_id",
            "message_id",
            "user_id",
            "model_id",
            "judge_model_id",
            "evaluation_type",
            "score",
            "status",
            "reasoning",
            "error_message",
            "created_at",
            "completed_at",
        ]
    )

    # Write data
    for ae in auto_evals:
        writer.writerow(
            [
                ae.id,
                ae.chat_id,
                ae.message_id,
                ae.user_id,
                ae.model_id,
                ae.judge_model_id,
                ae.evaluation_type,
                ae.score,
                ae.status,
                ae.reasoning,
                ae.error_message,
                ae.created_at,
                ae.completed_at,
            ]
        )

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=auto_evaluations.csv"},
    )


####################
# Get Single Auto Evaluation
####################


@router.get("/{id}", response_model=AutoEvaluationWithUserResponse)
async def get_auto_evaluation_by_id(
    id: str, user=Depends(get_admin_evaluations_read_access)
):
    """
    Get a single auto evaluation by ID.
    """
    auto_eval = AutoEvaluations.get_auto_evaluation_by_id(id)
    if not auto_eval:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    # Get user info
    eval_user = Users.get_user_by_id(auto_eval.user_id)
    user_info = None
    if eval_user:
        user_info = AutoEvaluationUserInfo(
            id=eval_user.id,
            name=eval_user.name,
            email=eval_user.email,
            role=eval_user.role,
        )

    return AutoEvaluationWithUserResponse(**auto_eval.model_dump(), user=user_info)


####################
# Create Auto Evaluation (For testing/manual trigger)
####################


@router.post("/", response_model=AutoEvaluationResponse)
async def create_auto_evaluation(
    form_data: AutoEvaluationForm,
    user=Depends(get_verified_user),
):
    """
    Create a new auto evaluation.
    This is primarily for testing or manual triggering.
    """
    auto_eval = AutoEvaluations.insert_new_auto_evaluation(
        user_id=user.id, form_data=form_data
    )
    if not auto_eval:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT(),
        )

    return AutoEvaluationResponse(**auto_eval.model_dump())


####################
# Update Auto Evaluation (Admin - for completing evaluations)
####################


@router.put("/{id}", response_model=AutoEvaluationResponse)
async def update_auto_evaluation(
    id: str,
    form_data: AutoEvaluationUpdateForm,
    user=Depends(get_admin_evaluations_write_access),
):
    """
    Update an auto evaluation (e.g., to mark it as completed with results).
    """
    auto_eval = AutoEvaluations.update_auto_evaluation_by_id(id, form_data)
    if not auto_eval:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    return AutoEvaluationResponse(**auto_eval.model_dump())


####################
# Delete Auto Evaluation (Admin)
####################


@router.delete("/{id}")
async def delete_auto_evaluation(
    id: str, user=Depends(get_admin_evaluations_write_access)
):
    """
    Delete an auto evaluation.
    """
    success = AutoEvaluations.delete_auto_evaluation_by_id(id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    return {"success": True}


####################
# Delete All Auto Evaluations (Admin)
####################


@router.delete("/")
async def delete_all_auto_evaluations(user=Depends(get_admin_evaluations_write_access)):
    """
    Delete all auto evaluations.
    """
    # Get all and delete each (could be optimized with a bulk delete)
    auto_evals = AutoEvaluations.get_all_auto_evaluations()
    deleted_count = 0
    for ae in auto_evals:
        if AutoEvaluations.delete_auto_evaluation_by_id(ae.id):
            deleted_count += 1

    return {"success": True, "deleted_count": deleted_count}


####################
# Get Auto Evaluations by Chat ID
####################


@router.get("/chat/{chat_id}", response_model=list[AutoEvaluationResponse])
async def get_auto_evaluations_by_chat(chat_id: str, user=Depends(get_verified_user)):
    """
    Get auto evaluations for a specific chat.
    Users can access evaluations for their own chats.
    """
    auto_evals = AutoEvaluations.get_auto_evaluations_by_chat_id(chat_id)
    # TODO: Add permission check - verify user owns the chat or is admin
    return [AutoEvaluationResponse(**ae.model_dump()) for ae in auto_evals]


####################
# Get Auto Evaluations by Message ID
####################


@router.get("/message/{message_id}", response_model=list[AutoEvaluationResponse])
async def get_auto_evaluations_by_message(
    message_id: str, user=Depends(get_verified_user)
):
    """
    Get auto evaluations for a specific message.
    Users can access evaluations for their own messages.
    """
    auto_evals = AutoEvaluations.get_auto_evaluations_by_message_id(message_id)
    # TODO: Add permission check - verify user owns the message or is admin
    return [AutoEvaluationResponse(**ae.model_dump()) for ae in auto_evals]

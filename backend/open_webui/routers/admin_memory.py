"""Admin Memory Governance API."""

import logging
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from open_webui.constants import ERROR_MESSAGES
from open_webui.env import SRC_LOG_LEVELS
from open_webui.internal.db import get_db
from open_webui.models.audit_log import AuditLogQueryParams, AuditLogs
from open_webui.models.memories import Memories, Memory
from open_webui.models.memory_entity import EntityTypes, MemoryEntities
from open_webui.models.memory_retention_policy import RetentionPolicies
from open_webui.utils.audit_logger import AuditLogger
from open_webui.utils.auth import get_admin_user
from pydantic import BaseModel

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])

router = APIRouter()


############################
# Retention Policies
############################


@router.get("/retention-policies")
async def get_retention_policies(user=Depends(get_admin_user)):
    return RetentionPolicies.get_all_policies()


class UpdateRetentionPolicyForm(BaseModel):
    ttl_days: Optional[int] = None


@router.put("/retention-policies/{policy_id}")
async def update_retention_policy(
    policy_id: str,
    form_data: UpdateRetentionPolicyForm,
    user=Depends(get_admin_user),
):
    policy = RetentionPolicies.update_policy(policy_id, form_data.ttl_days)
    if policy is None:
        raise HTTPException(status_code=404, detail=ERROR_MESSAGES.NOT_FOUND)

    AuditLogger.log_settings_change(
        "memory/retention",
        after_data={"policy_id": policy_id, "ttl_days": form_data.ttl_days},
    )

    return policy


############################
# Audit Logs
############################


@router.get("/audit-logs")
async def get_audit_logs(
    event_type: Optional[str] = None,
    user_id: Optional[str] = None,
    page: int = 1,
    limit: int = 100,
    include_system: bool = True,
    user=Depends(get_admin_user),
):
    if limit > 500:
        limit = 500
    logs, total = AuditLogs.get_audit_logs(
        AuditLogQueryParams(
            resource_type="memory",
            action=event_type,
            user_id=user_id,
            page=page,
            limit=limit,
            exclude_system=not include_system,
        )
    )
    return {"items": logs, "total": total}


def _resolve_org_id(user_id: str) -> Optional[str]:
    """Resolve user's organization ID from OrganizationalUnit membership."""
    from open_webui.models.organization import OrganizationalUnit
    from sqlalchemy import String, cast

    with get_db() as db:
        unit = (
            db.query(OrganizationalUnit)
            .filter(cast(OrganizationalUnit.member_ids, String).like(f'%"{user_id}"%'))
            .first()
        )
        return unit.organization_id if unit else None


############################
# Organization Memory
############################


class OrgMemoryForm(BaseModel):
    content: str


@router.get("/org")
async def get_org_memories(user=Depends(get_admin_user)):
    org_id = _resolve_org_id(user.id)
    if not org_id:
        raise HTTPException(status_code=400, detail="User not in any organization")
    return Memories.get_org_memories(org_id)


@router.post("/org")
async def create_org_memory(
    form_data: OrgMemoryForm,
    user=Depends(get_admin_user),
):
    org_id = _resolve_org_id(user.id)
    if not org_id:
        raise HTTPException(status_code=400, detail="User not in any organization")

    memory = Memories.insert_org_memory(org_id, form_data.content, user.id)
    if memory:
        AuditLogger.log_create(
            resource_type="memory",
            resource_id=memory.id,
            data={"source": "manual", "scope": "org", "retention_class": "permanent"},
            resource_name=form_data.content[:50],
            meta={"actor": f"admin:{user.id}", "scope": "org", "org_id": org_id},
        )
    return memory


@router.delete("/org/{memory_id}")
async def delete_org_memory(memory_id: str, user=Depends(get_admin_user)):
    org_id = _resolve_org_id(user.id)
    if not org_id:
        raise HTTPException(status_code=400, detail="User not in any organization")

    with get_db() as db:
        updated = (
            db.query(Memory)
            .filter_by(id=memory_id, scope="org", org_id=org_id)
            .filter(Memory.deleted_at.is_(None))
            .update({"deleted_at": int(time.time())})
        )
        db.commit()

    if updated > 0:
        AuditLogger.log_delete(
            resource_type="memory",
            resource_id=memory_id,
            data={"scope": "org"},
            meta={"actor": f"admin:{user.id}", "scope": "org", "org_id": org_id},
        )
        return True
    return False


############################
# Admin User Memory Management
############################


@router.get("/users/{user_id}/memories")
async def get_user_memories(user_id: str, user=Depends(get_admin_user)):
    return Memories.get_memories_by_user_id_for_admin(user_id)


@router.delete("/users/{user_id}/memories/{memory_id}")
async def delete_user_memory(
    user_id: str, memory_id: str, user=Depends(get_admin_user)
):
    from open_webui.retrieval.vector.connector import VECTOR_DB_CLIENT

    result = Memories.soft_delete_memory_by_id_and_user_id(memory_id, user_id)
    if result:
        try:
            VECTOR_DB_CLIENT.delete(
                collection_name=f"user-memory-{user_id}", ids=[memory_id]
            )
        except Exception:
            pass

        AuditLogger.log_delete(
            resource_type="memory",
            resource_id=memory_id,
            data={"target_user_id": user_id},
            meta={"actor": f"admin:{user.id}", "admin_action": True},
        )
        return True
    return False


############################
# Entity Types
############################


class EntityTypeForm(BaseModel):
    name: str
    description: Optional[str] = None


@router.get("/entity-types")
async def get_entity_types(user=Depends(get_admin_user)):
    return EntityTypes.get_all_types()


@router.post("/entity-types")
async def add_entity_type(
    form_data: EntityTypeForm,
    user=Depends(get_admin_user),
):
    result = EntityTypes.add_type(form_data.name, form_data.description)
    if result is None:
        raise HTTPException(
            status_code=400, detail="Entity type already exists or creation failed"
        )
    return result


@router.delete("/entity-types/{type_id}")
async def delete_entity_type(type_id: str, user=Depends(get_admin_user)):
    return EntityTypes.delete_type(type_id)


############################
# Entities (read-only for admin)
############################


@router.get("/entities")
async def get_entities(
    entity_type: Optional[str] = None,
    user=Depends(get_admin_user),
):
    return MemoryEntities.get_entities_grouped_by_type(entity_type=entity_type)

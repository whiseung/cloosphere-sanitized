import logging
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from open_webui.env import SRC_LOG_LEVELS
from open_webui.models.memories import Memories, MemoryModel
from open_webui.retrieval.vector.connector import VECTOR_DB_CLIENT
from open_webui.utils.audit_logger import AuditLogger
from open_webui.utils.auth import get_admin_user, get_verified_user
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])

router = APIRouter()


@router.get("/ef")
async def get_embeddings(request: Request):
    if not request.app.state.EMBEDDING_FUNCTION:
        raise HTTPException(status_code=503, detail="Embedding function not configured")
    return {"result": await request.app.state.EMBEDDING_FUNCTION("hello world")}


############################
# GetMemories
############################


@router.get("/", response_model=list[MemoryModel])
async def get_memories(user=Depends(get_verified_user)):
    return Memories.get_memories_by_user_id(user.id)


############################
# AddMemory
############################


class AddMemoryForm(BaseModel):
    content: str


class MemoryUpdateModel(BaseModel):
    content: Optional[str] = None


@router.post("/add", response_model=Optional[MemoryModel])
async def add_memory(
    request: Request,
    form_data: AddMemoryForm,
    user=Depends(get_verified_user),
):
    memory = Memories.insert_new_memory(user.id, form_data.content)

    AuditLogger.log_create(
        resource_type="memory",
        resource_id=memory.id,
        data={"source": "manual", "retention_class": "standard"},
        resource_name=form_data.content[:50],
        meta={"actor": f"user:{user.id}"},
    )

    if request.app.state.EMBEDDING_FUNCTION:
        try:
            embedding = await request.app.state.EMBEDDING_FUNCTION(
                memory.content, user=user
            )
            VECTOR_DB_CLIENT.upsert(
                collection_name=f"user-memory-{user.id}",
                items=[
                    {
                        "id": memory.id,
                        "text": memory.content,
                        "vector": embedding,
                        "metadata": {"created_at": memory.created_at},
                    }
                ],
            )
        except Exception as e:
            log.error(f"Failed to store memory embedding: {e}")

    return memory


############################
# QueryMemory
############################


class QueryMemoryForm(BaseModel):
    content: str
    k: Optional[int] = 1


@router.post("/query")
async def query_memory(
    request: Request, form_data: QueryMemoryForm, user=Depends(get_verified_user)
):
    if not request.app.state.EMBEDDING_FUNCTION:
        raise HTTPException(status_code=503, detail="Embedding function not configured")

    try:
        embedding = await request.app.state.EMBEDDING_FUNCTION(
            form_data.content, user=user
        )
    except Exception as e:
        log.error(f"Memory query embedding failed: {e}")
        raise HTTPException(status_code=500, detail="Embedding generation failed")

    try:
        results = VECTOR_DB_CLIENT.search(
            collection_name=f"user-memory-{user.id}",
            vectors=[embedding],
            limit=form_data.k,
        )
    except Exception as e:
        log.error(f"Memory vector search failed: {e}")
        return []

    return results


############################
# ResetMemoryFromVectorDB
############################
@router.post("/reset", response_model=bool)
async def reset_memory_from_vector_db(
    request: Request, user=Depends(get_verified_user)
):
    if not request.app.state.EMBEDDING_FUNCTION:
        raise HTTPException(status_code=503, detail="Embedding function not configured")

    try:
        VECTOR_DB_CLIENT.delete_collection(f"user-memory-{user.id}")
    except Exception as e:
        log.error(f"Failed to delete memory collection: {e}")

    memories = Memories.get_memories_by_user_id(user.id)

    items = []
    for memory in memories:
        try:
            embedding = await request.app.state.EMBEDDING_FUNCTION(
                memory.content, user=user
            )
            items.append(
                {
                    "id": memory.id,
                    "text": memory.content,
                    "vector": embedding,
                    "metadata": {
                        "created_at": memory.created_at,
                        "updated_at": memory.updated_at,
                    },
                }
            )
        except Exception as e:
            log.error(f"Failed to generate embedding for memory {memory.id}: {e}")

    if items:
        try:
            VECTOR_DB_CLIENT.upsert(
                collection_name=f"user-memory-{user.id}",
                items=items,
            )
        except Exception as e:
            log.error(f"Failed to upsert memory vectors: {e}")

    return True


############################
# DeleteMemoriesByUserId
############################


@router.delete("/delete/user", response_model=bool)
async def delete_memory_by_user_id(user=Depends(get_verified_user)):
    deleted_ids = Memories.soft_delete_memories_by_user_id(user.id)

    if deleted_ids:
        try:
            VECTOR_DB_CLIENT.delete_collection(f"user-memory-{user.id}")
        except Exception as e:
            log.error(e)

        for mid in deleted_ids:
            AuditLogger.log_delete(
                resource_type="memory",
                resource_id=mid,
                data={},
                meta={"actor": f"user:{user.id}", "bulk": True},
            )
        return True

    return False


############################
# UpdateMemoryById
############################


@router.post("/{memory_id}/update", response_model=Optional[MemoryModel])
async def update_memory_by_id(
    memory_id: str,
    request: Request,
    form_data: MemoryUpdateModel,
    user=Depends(get_verified_user),
):
    before_memory = Memories.get_memory_by_id(memory_id)

    memory = Memories.update_memory_by_id_and_user_id(
        memory_id, user.id, form_data.content
    )
    if memory is None:
        raise HTTPException(status_code=404, detail="Memory not found")

    AuditLogger.log_update(
        resource_type="memory",
        resource_id=memory_id,
        before_data={"content_length": len(before_memory.content)}
        if before_memory
        else {},
        after_data={
            "content_length": len(form_data.content) if form_data.content else 0
        },
        resource_name=(form_data.content or "")[:50],
        meta={"actor": f"user:{user.id}"},
    )

    if form_data.content is not None and request.app.state.EMBEDDING_FUNCTION:
        try:
            embedding = await request.app.state.EMBEDDING_FUNCTION(
                memory.content, user=user
            )
            VECTOR_DB_CLIENT.upsert(
                collection_name=f"user-memory-{user.id}",
                items=[
                    {
                        "id": memory.id,
                        "text": memory.content,
                        "vector": embedding,
                        "metadata": {
                            "created_at": memory.created_at,
                            "updated_at": memory.updated_at,
                        },
                    }
                ],
            )
        except Exception as e:
            log.error(f"Failed to update memory embedding: {e}")

    return memory


############################
# DeleteMemoryById
############################


@router.delete("/{memory_id}", response_model=bool)
async def delete_memory_by_id(memory_id: str, user=Depends(get_verified_user)):
    # Fetch before soft delete to capture metadata for audit
    memory = Memories.get_memory_by_id(memory_id)
    result = Memories.soft_delete_memory_by_id_and_user_id(memory_id, user.id)

    if result:
        try:
            VECTOR_DB_CLIENT.delete(
                collection_name=f"user-memory-{user.id}", ids=[memory_id]
            )
        except Exception as e:
            log.error(f"Failed to delete memory vector {memory_id}: {e}")
        age_days = int((time.time() - memory.created_at) / 86400) if memory else 0
        AuditLogger.log_delete(
            resource_type="memory",
            resource_id=memory_id,
            data={
                "retention_class": memory.retention_class if memory else "unknown",
                "memory_age_days": age_days,
            },
            resource_name=(memory.content[:50] if memory else None),
            meta={"actor": f"user:{user.id}"},
        )
        return True

    return False


############################
# Memory Extraction Config (Admin)
############################


class MemoryExtractionConfigForm(BaseModel):
    MEMORY_EXTRACTION_MODEL: Optional[str] = None
    MEMORY_EXTRACTION_CONFIDENCE: Optional[float] = Field(None, ge=0.0, le=1.0)


@router.get("/config", response_model=dict)
async def get_memory_extraction_config(request: Request, user=Depends(get_admin_user)):
    return {
        "MEMORY_EXTRACTION_MODEL": request.app.state.config.MEMORY_EXTRACTION_MODEL,
        "MEMORY_EXTRACTION_CONFIDENCE": request.app.state.config.MEMORY_EXTRACTION_CONFIDENCE,
    }


@router.post("/config", response_model=dict)
async def update_memory_extraction_config(
    request: Request,
    form_data: MemoryExtractionConfigForm,
    user=Depends(get_admin_user),
):
    before_data = {
        "MEMORY_EXTRACTION_MODEL": request.app.state.config.MEMORY_EXTRACTION_MODEL,
        "MEMORY_EXTRACTION_CONFIDENCE": request.app.state.config.MEMORY_EXTRACTION_CONFIDENCE,
    }

    if form_data.MEMORY_EXTRACTION_MODEL is not None:
        request.app.state.config.MEMORY_EXTRACTION_MODEL = (
            form_data.MEMORY_EXTRACTION_MODEL
        )
    if form_data.MEMORY_EXTRACTION_CONFIDENCE is not None:
        request.app.state.config.MEMORY_EXTRACTION_CONFIDENCE = (
            form_data.MEMORY_EXTRACTION_CONFIDENCE
        )

    AuditLogger.log_settings_change(
        "memory/extraction",
        before_data=before_data,
        after_data={
            "MEMORY_EXTRACTION_MODEL": request.app.state.config.MEMORY_EXTRACTION_MODEL,
            "MEMORY_EXTRACTION_CONFIDENCE": request.app.state.config.MEMORY_EXTRACTION_CONFIDENCE,
        },
    )

    return {
        "MEMORY_EXTRACTION_MODEL": request.app.state.config.MEMORY_EXTRACTION_MODEL,
        "MEMORY_EXTRACTION_CONFIDENCE": request.app.state.config.MEMORY_EXTRACTION_CONFIDENCE,
    }

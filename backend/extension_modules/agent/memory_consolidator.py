"""User profile consolidation from individual memory facts.

Periodically consolidates atomic facts into a structured profile document.
Runs as a background task triggered after memory extraction.
"""

import logging
import time
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

logger = logging.getLogger(__name__)

# Track last consolidation time per user
_last_consolidation: dict[str, float] = {}
PROFILE_TRIGGER_HOURS = 24
PROFILE_TRIGGER_FACTS = 5

PROFILE_CONSOLIDATION_PROMPT = """You are a user profile summarizer. Given a list of individual facts about a user, create a structured profile document.

Rules:
- Write in the SAME LANGUAGE as the majority of the facts
- Organize into clear sections
- Merge duplicate or overlapping facts into single statements
- Resolve conflicts by preferring the most recent fact (later items are newer)
- Keep each section concise (2-5 bullet points max)
- Do NOT invent information not present in the facts
- Do NOT include section headers with zero items

Use this exact format:

## Role & Work
- ...

## Tech Preferences
- ...

## Current Projects
- ...

## Constraints & Requirements
- ...

## Communication Style
- ...

## Personal
- ...
"""


async def maybe_consolidate_profile(
    user_id: str,
    new_facts_count: int,
    llm_config: dict[str, Any],
    app: Any,
) -> None:
    """Check trigger conditions and consolidate if needed.

    Trigger conditions (OR):
    - new_facts_count >= PROFILE_TRIGGER_FACTS
    - last consolidation > PROFILE_TRIGGER_HOURS ago AND new_facts_count >= 1
    """
    now = time.time()
    last = _last_consolidation.get(user_id, 0)
    hours_since = (now - last) / 3600

    should_consolidate = new_facts_count >= PROFILE_TRIGGER_FACTS or (
        hours_since >= PROFILE_TRIGGER_HOURS and new_facts_count >= 1
    )

    if not should_consolidate:
        return

    try:
        await consolidate_user_profile(user_id, llm_config, app)
        _last_consolidation[user_id] = now
    except Exception as e:
        logger.warning(f"[MemoryConsolidator] Failed: {e}")


async def consolidate_user_profile(
    user_id: str,
    llm_config: dict[str, Any],
    app: Any,
) -> None:
    """Consolidate all user facts into a structured profile document."""
    from open_webui.models.memories import Memories

    # Load all non-profile memories
    all_memories = Memories.get_memories_by_user_id(user_id)
    if not all_memories:
        return

    facts = [m for m in all_memories if m.source != "profile"]
    if not facts:
        return

    # Build facts text (ordered by created_at for recency preference)
    facts.sort(key=lambda m: m.created_at)
    facts_text = "\n".join(f"- [{m.source}] {m.content}" for m in facts)

    logger.info(
        f"[MemoryConsolidator] Consolidating {len(facts)} facts for user {user_id[:8]}"
    )

    # LLM consolidation
    from extension_modules.utils.llm import create_llm

    llm = create_llm(llm_config, streaming=False, json_mode=True, temperature=0.1)

    response = await llm.ainvoke(
        [
            SystemMessage(content=PROFILE_CONSOLIDATION_PROMPT),
            HumanMessage(content=f"User facts ({len(facts)} items):\n{facts_text}"),
        ]
    )

    raw_content = response.content
    if isinstance(raw_content, list):
        profile_text = " ".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in raw_content
        ).strip()
    else:
        profile_text = str(raw_content).strip()
    if not profile_text:
        logger.warning("[MemoryConsolidator] LLM returned empty profile")
        return

    # Upsert profile
    result = Memories.upsert_profile(user_id, profile_text)
    if result:
        logger.info(
            f"[MemoryConsolidator] Profile updated for user {user_id[:8]} "
            f"({len(profile_text)} chars)"
        )

        from open_webui.utils.audit_logger import AuditLogger

        # Determine if this was a create or update
        is_new = abs(result.created_at - result.updated_at) < 2
        if is_new:
            AuditLogger.log_create(
                resource_type="memory",
                resource_id=result.id,
                data={"source": "profile", "retention_class": "permanent"},
                resource_name=profile_text[:50],
                meta={"actor": "system:consolidation", "user_id": user_id},
            )
        else:
            AuditLogger.log_update(
                resource_type="memory",
                resource_id=result.id,
                before_data={},
                after_data={"source": "profile", "retention_class": "permanent"},
                resource_name=profile_text[:50],
                meta={"actor": "system:consolidation", "user_id": user_id},
            )

        # Update vector DB embedding for profile
        if not app.state.EMBEDDING_FUNCTION:
            logger.warning(
                "[MemoryConsolidator] EMBEDDING_FUNCTION not configured, skipping vector upsert"
            )
            return
        try:
            embedding = await app.state.EMBEDDING_FUNCTION(profile_text)
            from open_webui.retrieval.vector.connector import VECTOR_DB_CLIENT

            VECTOR_DB_CLIENT.upsert(
                collection_name=f"user-memory-{user_id}",
                items=[
                    {
                        "id": result.id,
                        "text": profile_text,
                        "vector": embedding,
                        "metadata": {"created_at": result.created_at},
                    }
                ],
            )
        except Exception as e:
            logger.warning(f"[MemoryConsolidator] Profile vector upsert failed: {e}")

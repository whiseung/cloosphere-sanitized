"""Auto memory extraction pipeline for UnifiedAgent.

Extracts memorable facts from conversations and stores them as long-term memory.
Runs as a background task after streaming completes (non-blocking).
"""

import json
import logging
import re
import time
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

logger = logging.getLogger(__name__)

# Debounce: Redis (multi-worker safe) with in-process dict fallback
_last_extraction: dict[str, float] = {}
_DEBOUNCE_SECONDS = 300  # 5 minutes
_redis_client = None
_redis_init_done = False


def _get_redis_client():
    """Lazy-init Redis client for debounce. Returns None if unavailable."""
    global _redis_client, _redis_init_done
    if _redis_init_done:
        return _redis_client
    _redis_init_done = True
    try:
        from open_webui.env import REDIS_URL

        if REDIS_URL:
            from open_webui.env import (
                REDIS_SENTINEL_HOSTS,
                REDIS_SENTINEL_PORT,
            )
            from open_webui.utils.redis import (
                get_redis_connection,
                get_sentinels_from_env,
            )

            sentinels = get_sentinels_from_env(
                REDIS_SENTINEL_HOSTS, REDIS_SENTINEL_PORT
            )
            _redis_client = get_redis_connection(REDIS_URL, sentinels)
            logger.info("[MemoryExtractor] Redis debounce enabled")
    except Exception as e:
        logger.debug(f"[MemoryExtractor] Redis unavailable, using in-process dict: {e}")
    return _redis_client


def _check_debounce(chat_id: str) -> bool:
    """Check if extraction should be debounced. Returns True if should skip."""
    redis = _get_redis_client()
    debounce_key = f"memory:debounce:{chat_id}"

    if redis:
        try:
            # Atomic SET NX EX: only first caller wins (no TOCTOU race)
            was_set = redis.set(debounce_key, "1", ex=_DEBOUNCE_SECONDS, nx=True)
            return not was_set  # True = debounced (key existed), False = proceed
        except Exception:
            pass  # Fall through to in-process dict

    # Fallback: in-process dict
    now = time.time()
    last = _last_extraction.get(chat_id, 0)
    if now - last < _DEBOUNCE_SECONDS:
        return True
    _last_extraction[chat_id] = now
    return False


FACT_EXTRACTION_PROMPT_TEMPLATE = """You are a memory extraction assistant. Extract key facts from the conversation for future reference.

Focus on: user's role, technical preferences, projects, constraints, communication style.

Rules:
- Extract only factual USER statements (not assistant's words)
- Each fact: single concise sentence, SAME LANGUAGE as conversation
- Include confidence (0.0-1.0) and named entities
- Skip PII (emails, phones, addresses) and transient info ("I'm tired today")

Output ONLY a JSON array:
[{{"fact": "...", "category": "...", "confidence": 0.9, "entities": [{{"name": "...", "type": "..."}}]}}]

Categories: role, tech_preference, project, constraint, communication_style, personal_info
Entity types: {entity_types}
If no facts found, output: []

Example input:
[user]: 나는 데이터 엔지니어이고 주로 Spark와 Airflow를 써
[assistant]: Spark와 Airflow 조합이 좋죠...

Example output:
[{{"fact": "데이터 엔지니어 역할", "category": "role", "confidence": 0.95, "entities": []}}, {{"fact": "주로 Spark와 Airflow를 사용", "category": "tech_preference", "confidence": 0.9, "entities": [{{"name": "Spark", "type": "tech"}}, {{"name": "Airflow", "type": "tech"}}]}}]"""


def _build_extraction_prompt(user_id: str | None = None) -> str:
    """Build extraction prompt with dynamic entity types and glossary terms."""
    try:
        from open_webui.models.memory_entity import EntityTypes

        types = EntityTypes.get_all_types()
        if types:
            type_list = ", ".join(t.name for t in types)
        else:
            type_list = "tech, project, person, organization, concept"
    except Exception:
        type_list = "tech, project, person, organization, concept"

    prompt = FACT_EXTRACTION_PROMPT_TEMPLATE.format(entity_types=type_list)

    # A-3: Inject glossary terms to prevent duplicate entity extraction
    if user_id:
        glossary_terms = _load_glossary_terms(user_id)
        if glossary_terms:
            terms_str = ", ".join(glossary_terms[:50])  # Max 50 terms
            prompt += (
                f"\n\nAlready known terms (from glossary, do NOT extract as entities): "
                f"{terms_str}"
            )

    return prompt


# Glossary terms cache: {user_id: (terms, timestamp)}
_glossary_terms_cache: dict[str, tuple[list[str], float]] = {}
_GLOSSARY_CACHE_TTL = 60  # 60 seconds


def _load_glossary_terms(user_id: str) -> list[str]:
    """Load glossary term names accessible to the user (cached 60s)."""
    now = time.time()
    cached = _glossary_terms_cache.get(user_id)
    if cached and now - cached[1] < _GLOSSARY_CACHE_TTL:
        return cached[0]

    try:
        from open_webui.models.glossary import Glossaries

        glossaries = Glossaries.get_glossaries_by_user_id(user_id, "read")
        terms = []
        for g in glossaries:
            data = g.data or {}
            for entry in data.get("entries", []):
                term = entry.get("term", "").strip()
                if term:
                    terms.append(term)
        _glossary_terms_cache[user_id] = (terms, now)
        return terms
    except Exception:
        return []


def _parse_json_array(text: str) -> list[dict] | None:
    """Parse JSON array from LLM response with robust fallbacks.

    Handles: raw JSON, markdown code blocks, text wrapping, partial JSON.
    Returns None if parsing fails completely.
    """
    text = text.strip()

    # Strip markdown code blocks (```json ... ``` or ``` ... ```)
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first line (```json or ```) and last line (```)
        inner = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        text = inner.strip()

    # Attempt 1: direct parse
    try:
        result = json.loads(text)
        if isinstance(result, list):
            return result
    except json.JSONDecodeError:
        pass

    # Attempt 2: extract [ ... ] substring
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end > start:
        try:
            result = json.loads(text[start : end + 1])
            if isinstance(result, list):
                return result
        except json.JSONDecodeError:
            pass

    # Attempt 3: fix common issues — trailing comma before ]
    if start != -1 and end > start:
        candidate = text[start : end + 1]
        # Remove trailing commas: ,] → ]
        candidate = re.sub(r",\s*]", "]", candidate)
        candidate = re.sub(r",\s*}", "}", candidate)
        try:
            result = json.loads(candidate)
            if isinstance(result, list):
                return result
        except json.JSONDecodeError:
            pass

    logger.warning(f"[MemoryExtractor] Failed to parse LLM response: {text[:200]}")
    return None


async def auto_extract_memories(
    user_id: str,
    messages: list[dict[str, Any]],
    chat_id: str,
    llm_config: dict[str, Any],
    app: Any,
) -> None:
    """Extract and store memorable facts from a conversation.

    Non-blocking background task. Failures are logged but never propagate.

    Args:
        user_id: User ID for memory storage
        messages: Conversation messages (role + content dicts)
        chat_id: Chat session ID (for debounce)
        llm_config: LLM configuration (model_id, api_key, base_url, api_config)
        app: FastAPI app instance (for EMBEDDING_FUNCTION)
    """
    # Debounce check (Redis if available, else in-process dict)
    if _check_debounce(chat_id):
        logger.info(f"[MemoryExtractor] Debounced for chat {chat_id[:8]}")
        return

    try:
        # 1. Extract facts from conversation
        try:
            confidence = float(app.state.config.MEMORY_EXTRACTION_CONFIDENCE or 0.8)
        except (AttributeError, TypeError, ValueError):
            confidence = 0.8
        facts = await _extract_facts(messages, llm_config, confidence, user_id)
        if not facts:
            logger.info("[MemoryExtractor] No facts extracted")
            return

        logger.info(f"[MemoryExtractor] Extracted {len(facts)} facts")

        # 2. Deduplicate and store
        stored = await _deduplicate_and_store(facts, user_id, app)
        logger.info(
            f"[MemoryExtractor] Stored {stored} new/updated memories "
            f"for user {user_id[:8]}"
        )

        # 3. Trigger profile consolidation if conditions met
        if stored > 0:
            try:
                from extension_modules.agent.memory_consolidator import (
                    maybe_consolidate_profile,
                )

                await maybe_consolidate_profile(
                    user_id=user_id,
                    new_facts_count=stored,
                    llm_config=llm_config,
                    app=app,
                )
            except Exception as e:
                logger.warning(f"[MemoryExtractor] Consolidation trigger failed: {e}")

    except Exception as e:
        logger.warning(f"[MemoryExtractor] Failed: {e}")


async def _extract_facts(
    messages: list[dict[str, Any]],
    llm_config: dict[str, Any],
    confidence_threshold: float = 0.8,
    user_id: str | None = None,
) -> list[dict[str, Any]]:
    """Use LLM to extract memorable facts from conversation."""
    from extension_modules.utils.llm import create_llm

    # Build conversation text (last 20 messages max)
    recent = messages[-20:]
    conversation_lines = []
    for msg in recent:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        if isinstance(content, list):
            text_parts = [
                b.get("text", "") if isinstance(b, dict) else str(b)
                for b in content
                if isinstance(b, str)
                or (isinstance(b, dict) and b.get("type") == "text")
            ]
            content = " ".join(text_parts)
        if content and role in ("user", "assistant"):
            # User messages: full context (500 chars)
            # Assistant messages: abbreviated (200 chars) — only for context
            max_len = 500 if role == "user" else 200
            conversation_lines.append(f"[{role}]: {content[:max_len]}")

    if not conversation_lines:
        return []

    conversation_text = "\n".join(conversation_lines)

    # Create LLM (non-streaming, low temperature for factual extraction)
    llm = create_llm(llm_config, streaming=False, json_mode=True, temperature=0.1)

    prompt_messages = [
        SystemMessage(content=_build_extraction_prompt(user_id)),
        HumanMessage(content=f"Conversation:\n{conversation_text}"),
    ]

    response = await llm.ainvoke(prompt_messages)
    # response.content는 str 또는 list[dict] (멀티파트 응답)
    raw_content = response.content
    if isinstance(raw_content, list):
        response_text = " ".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in raw_content
        ).strip()
    else:
        response_text = str(raw_content).strip()

    # Parse JSON response — robust handling for small models
    facts = _parse_json_array(response_text)
    if facts is None:
        return []

    # Filter by confidence
    return [
        f
        for f in facts
        if isinstance(f, dict)
        and f.get("confidence", 0) >= confidence_threshold
        and f.get("fact", "").strip()
    ]


def _store_entities(fact_data: dict, memory_id: str, user_id: str) -> None:
    """Store extracted entities from a fact."""
    entities = fact_data.get("entities", [])
    if not entities or not isinstance(entities, list):
        return
    try:
        from open_webui.models.memory_entity import MemoryEntities

        for ent in entities:
            if isinstance(ent, dict) and ent.get("name") and ent.get("type"):
                MemoryEntities.upsert_entity(
                    name=ent["name"],
                    entity_type=ent["type"],
                    memory_id=memory_id,
                    user_id=user_id,
                )
    except Exception as e:
        logger.debug(f"[MemoryExtractor] Entity store failed: {e}")


async def _deduplicate_and_store(
    facts: list[dict[str, Any]],
    user_id: str,
    app: Any,
) -> int:
    """Deduplicate facts against existing memories and store new ones.

    Returns number of memories stored/updated.
    """
    from open_webui.models.memories import Memories
    from open_webui.retrieval.vector.connector import VECTOR_DB_CLIENT
    from open_webui.utils.audit_logger import AuditLogger

    embedding_fn = app.state.EMBEDDING_FUNCTION
    collection_name = f"user-memory-{user_id}"
    stored_count = 0

    # Check memory count limit (max 100 auto memories per user)
    existing = Memories.get_memories_by_user_id(user_id)
    auto_count = sum(
        1 for m in (existing or []) if getattr(m, "source", "manual") == "auto"
    )
    max_auto = 100

    for fact_data in facts:
        if auto_count >= max_auto:
            logger.info(
                f"[MemoryExtractor] Auto memory limit reached ({max_auto}) "
                f"for user {user_id[:8]}"
            )
            break

        fact_text = fact_data["fact"].strip()

        # Generate embedding for the fact
        try:
            embedding = await embedding_fn(fact_text)
        except Exception as e:
            logger.warning(f"[MemoryExtractor] Embedding failed for fact: {e}")
            continue

        # Search for similar existing memories
        try:
            results = VECTOR_DB_CLIENT.search(
                collection_name=collection_name,
                vectors=[embedding],
                limit=1,
            )
        except Exception:
            # Collection may not exist yet
            results = None

        # Check similarity
        should_add = True
        update_id = None

        if results and results.distances and results.distances[0]:
            distance = results.distances[0][0]
            # distance < 0.15 means very similar (cosine distance)
            # distance > 0.15 means different enough to add
            if distance < 0.10:
                # Very similar — skip (NONE)
                should_add = False
                logger.debug(
                    f"[MemoryExtractor] Skip (too similar, dist={distance:.3f}): "
                    f"{fact_text[:50]}"
                )
            elif distance < 0.15:
                # Somewhat similar — update existing
                if results.ids and results.ids[0]:
                    update_id = results.ids[0][0]
                    logger.debug(
                        f"[MemoryExtractor] Update (dist={distance:.3f}): "
                        f"{fact_text[:50]}"
                    )

        if not should_add:
            continue

        if update_id:
            # UPDATE existing memory
            Memories.update_memory_by_id_and_user_id(update_id, user_id, fact_text)
            VECTOR_DB_CLIENT.upsert(
                collection_name=collection_name,
                items=[
                    {
                        "id": update_id,
                        "text": fact_text,
                        "vector": embedding,
                        "metadata": {"created_at": int(time.time())},
                    }
                ],
            )
            AuditLogger.log_update(
                resource_type="memory",
                resource_id=update_id,
                before_data={},
                after_data={"source": "auto", "retention_class": "temporary"},
                resource_name=fact_text[:50],
                meta={"actor": "system:extraction", "user_id": user_id},
            )
            # Process entities from this fact
            _store_entities(fact_data, update_id, user_id)
        else:
            # ADD new memory
            memory = Memories.insert_new_memory(user_id, fact_text, source="auto")
            if memory:
                VECTOR_DB_CLIENT.upsert(
                    collection_name=collection_name,
                    items=[
                        {
                            "id": memory.id,
                            "text": fact_text,
                            "vector": embedding,
                            "metadata": {"created_at": memory.created_at},
                        }
                    ],
                )
                AuditLogger.log_create(
                    resource_type="memory",
                    resource_id=memory.id,
                    data={"source": "auto", "retention_class": "temporary"},
                    resource_name=fact_text[:50],
                    meta={"actor": "system:extraction", "user_id": user_id},
                )
                # Process entities from this fact
                _store_entities(fact_data, memory.id, user_id)
                auto_count += 1

        stored_count += 1

    return stored_count

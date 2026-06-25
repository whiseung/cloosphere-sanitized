"""Adaptive conversation compression for short-term memory.

Compresses old messages into a summary, stored in chat["summary"].
Runs as a background task after streaming completes (non-blocking).
Summary is injected into system prompt on next conversation turn.
"""

import logging
import time
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

logger = logging.getLogger(__name__)

_COMPRESSION_THRESHOLD = 30  # Compress when messages exceed this count
_RECENT_KEEP = 10  # Keep this many recent messages uncompressed
_DEBOUNCE_SECONDS = 300  # 5 minutes debounce per chat

# In-process debounce fallback (Redis handled via memory_extractor's client)
_last_compression: dict[str, float] = {}

COMPRESSION_PROMPT = """You are a conversation summarizer. Summarize the older part of a conversation so the assistant can maintain context in future turns.

Rules:
- Write in the SAME LANGUAGE as the conversation
- Focus on: key decisions, user requirements, important facts, unresolved questions
- Be concise but preserve essential context (max 300 words)
- Do NOT include greetings or filler
- Use bullet points for clarity

Example:
Input: A long conversation about building a REST API with FastAPI...
Output:
- User is building a REST API with FastAPI for inventory management
- Decided on PostgreSQL with SQLAlchemy async
- Authentication: JWT with refresh tokens
- Completed: user CRUD, product endpoints
- Pending: order processing, webhook integration
- User prefers Korean responses with English technical terms"""


def _check_compression_debounce(chat_id: str) -> bool:
    """Check if compression should be debounced. Returns True if should skip."""
    from extension_modules.agent.memory_extractor import _get_redis_client

    redis = _get_redis_client()
    debounce_key = f"compress:debounce:{chat_id}"

    if redis:
        try:
            was_set = redis.set(debounce_key, "1", ex=_DEBOUNCE_SECONDS, nx=True)
            return not was_set
        except Exception:
            pass

    # Fallback: in-process dict
    now = time.time()
    last = _last_compression.get(chat_id, 0)
    if now - last < _DEBOUNCE_SECONDS:
        return True
    _last_compression[chat_id] = now
    return False


async def auto_compress_history(
    chat_id: str,
    user_id: str,
    messages: list[dict[str, Any]],
    llm_config: dict[str, Any],
) -> None:
    """Compress old messages into a summary and store in chat DB.

    Non-blocking background task. Failures are logged but never propagate.
    """
    if len(messages) < _COMPRESSION_THRESHOLD:
        return

    if _check_compression_debounce(chat_id):
        logger.info(f"[Compressor] Debounced for chat {chat_id[:8]}")
        return

    try:
        old_messages = messages[:-_RECENT_KEEP]
        summary = await _compress_messages(old_messages, llm_config)
        if not summary:
            return

        _store_summary(chat_id, user_id, summary)
        logger.info(
            f"[Compressor] Stored summary for chat {chat_id[:8]} "
            f"({len(old_messages)} messages → {len(summary)} chars)"
        )
    except Exception as e:
        logger.warning(f"[Compressor] Failed: {e}")


async def _compress_messages(
    messages: list[dict[str, Any]],
    llm_config: dict[str, Any],
) -> str | None:
    """Use LLM to compress old messages into a summary."""
    from extension_modules.utils.llm import create_llm

    conversation_lines = []
    for msg in messages:
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
            max_len = 300 if role == "user" else 150
            conversation_lines.append(f"[{role}]: {content[:max_len]}")

    if not conversation_lines:
        return None

    conversation_text = "\n".join(conversation_lines)
    llm = create_llm(llm_config, streaming=False, temperature=0.1, max_tokens=500)

    response = await llm.ainvoke(
        [
            SystemMessage(content=COMPRESSION_PROMPT),
            HumanMessage(content=f"Summarize this conversation:\n{conversation_text}"),
        ]
    )

    raw_content = response.content
    if isinstance(raw_content, list):
        summary = " ".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in raw_content
        ).strip()
    else:
        summary = str(raw_content).strip()
    return summary if summary and len(summary) >= 10 else None


def _store_summary(chat_id: str, user_id: str, summary: str) -> None:
    """Store compression summary in chat.chat['summary']."""
    try:
        from open_webui.internal.db import get_db
        from open_webui.models.chats import Chat
        from sqlalchemy.orm.attributes import flag_modified

        with get_db() as db:
            chat = db.query(Chat).filter_by(id=chat_id, user_id=user_id).first()
            if chat:
                chat_data = chat.chat if isinstance(chat.chat, dict) else {}
                chat_data["summary"] = summary
                chat.chat = chat_data
                flag_modified(chat, "chat")
                chat.updated_at = int(time.time())
                db.commit()
                logger.info(
                    f"[Compressor] DB commit OK for chat {chat_id[:8]}, "
                    f"summary={len(summary)} chars"
                )
            else:
                logger.warning(f"[Compressor] Chat not found: {chat_id[:8]}")
    except Exception as e:
        logger.warning(f"[Compressor] Failed to store summary: {e}")

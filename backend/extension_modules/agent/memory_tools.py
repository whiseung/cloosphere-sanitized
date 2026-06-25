"""Memory tools for UnifiedAgent — short-term (chat history) retrieval."""

import logging
from typing import List, Optional

from langchain_core.tools import StructuredTool
from open_webui.models.chats import Chats
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class GetRecentHistoryInput(BaseModel):
    n: int = Field(
        default=30,
        description="Number of recent messages to retrieve (default: 30, max: 50)",
        ge=1,
        le=50,
    )
    search_query: Optional[str] = Field(
        default=None,
        description="Optional keyword to filter messages by content",
    )


def create_get_recent_history_tool(
    chat_id: str,
    user_id: str,
    current_message_count: int,
) -> StructuredTool:
    """Create a tool that retrieves chat history beyond the current context window.

    Args:
        chat_id: Current chat session ID
        user_id: Current user ID
        current_message_count: Number of messages already in agent context
    """

    def get_recent_history(
        n: int = 30,
        search_query: Optional[str] = None,
    ) -> str:
        """Retrieve earlier messages from this conversation."""
        chat = Chats.get_chat_by_id_and_user_id(chat_id, user_id)
        if not chat or not chat.chat:
            return "No conversation history found."

        all_messages: List[dict] = chat.chat.get("messages", [])
        if not all_messages:
            return "No messages in this conversation."

        # Get messages BEFORE the current context window
        earlier_messages = (
            all_messages[:-current_message_count]
            if current_message_count > 0
            else all_messages
        )
        if not earlier_messages:
            return "No earlier messages beyond current context."

        # Apply keyword filter if provided
        if search_query:
            query_lower = search_query.lower()
            earlier_messages = [
                m
                for m in earlier_messages
                if isinstance(m.get("content"), str)
                and query_lower in m["content"].lower()
            ]
            if not earlier_messages:
                return (
                    f"No messages matching '{search_query}' found in earlier history."
                )

        # Take the last N from earlier messages (most recent first)
        selected = earlier_messages[-n:]

        # Format as concise summaries (role + truncated content)
        lines = []
        for msg in selected:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if isinstance(content, list):
                # Multi-part content (images etc.) — extract text only
                text_parts = [
                    block.get("text", "") if isinstance(block, dict) else str(block)
                    for block in content
                    if isinstance(block, str)
                    or (isinstance(block, dict) and block.get("type") == "text")
                ]
                content = " ".join(text_parts)
            # Truncate long messages
            if len(content) > 300:
                content = content[:300] + "..."
            lines.append(f"[{role}]: {content}")

        header = f"Retrieved {len(selected)} earlier messages"
        if search_query:
            header += f" matching '{search_query}'"
        header += f" (out of {len(earlier_messages)} total earlier messages)"

        return f"{header}\n\n" + "\n".join(lines)

    return StructuredTool.from_function(
        func=get_recent_history,
        name="get_recent_history",
        description=(
            "Retrieve earlier messages from this conversation that are outside your current context window.\n\n"
            f"You currently have the last {current_message_count} messages in context. "
            "Use this tool when:\n"
            "- The user asks about something they said earlier in this conversation\n"
            "- You need to find a specific detail from earlier in this chat\n"
            "- The user says 'I mentioned X earlier' but you don't see it in your context\n\n"
            "Parameters:\n"
            "- n: Number of messages to retrieve (default: 30, max: 50)\n"
            "- search_query: Optional keyword to filter messages"
        ),
        args_schema=GetRecentHistoryInput,
    )

"""
UnifiedAgent - Combined DbSphere + KbSphere agent module.

This module provides a unified agent that combines database querying (DbSphere)
and knowledge base search (KbSphere) capabilities in a single agent.

Usage:
    from extension_modules.agent import UnifiedAgent, UnifiedAgentState

    agent = UnifiedAgent(
        api_config=api_config,
        base_url=url,
        api_key=key,
        metadata=metadata,
        request=request,
    )
    result = await agent.run(
        request=request,
        payload=payload,
        metadata=metadata,
        user=user,
    )

The agent automatically determines which capabilities to use based on
connected resources (auto-detect from agent_config):
- knowledge_bases → Enable knowledge base search (KbSphere)
- dbspheres → Enable database querying (DbSphere)
"""

from extension_modules.agent.unified_agent import UnifiedAgent
from extension_modules.agent.unified_state import (
    UnifiedAgentOutput,
    UnifiedAgentState,
)

__all__ = [
    "UnifiedAgent",
    "UnifiedAgentState",
    "UnifiedAgentOutput",
]

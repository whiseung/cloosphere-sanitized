"""Flow Builder Agent.

자연어 의도를 분석하여 에이전트 플로우를 자동 생성하는 ReAct 에이전트.
DashboardBuilderAgent 패턴을 따름.
"""

import logging
import uuid
from typing import Any, Dict

from extension_modules.agent_flow.tools.flow_builder_tools import (
    FlowBuilderState,
    get_all_flow_builder_tools,
)
from extension_modules.react.react_base import ReactAgentBase
from fastapi import Request

logger = logging.getLogger(__name__)

FLOW_BUILDER_SYSTEM_PROMPT = """You are a Flow Builder Agent. Your task is to design and create AI workflows (flows) based on the user's description.

## Language
ALWAYS respond in the SAME language the user uses. If the user writes in Korean, respond in Korean. If English, respond in English.

## Available Node Types

### Entry/Exit
- **flowInput**: Flow entry point. ALWAYS create one first.
- **flowOutput**: Flow exit point. Creates the final response.

### AI Processing
- **model**: Direct LLM call with system prompt. Use for classification, generation, translation, summarization.
- **agent**: Execute a registered agent (may have knowledge bases, databases attached). Use for complex domain-specific tasks.

### Safety & Enrichment
- **guardrail**: Safety filter (PII detection, blocked words, LLM judge). Has TWO outputs: 'pass' and 'block'.
- **glossary**: Look up domain terms and enrich input with definitions.

### Logic & Control
- **condition**: True/False branch based on text matching (contains, regex, etc.)
- **router**: N-way routing based on rules or LLM classification.
- **transform**: Data transformation using Jinja2 templates.
- **merge**: Combine outputs from multiple parallel nodes.

## Available Resources
{available_resources}

## Connection Rules
- guardrail → 'pass' handle to safe path, 'block' handle to blocked path
- condition → 'true' handle and 'false' handle
- router → route ID as handle (e.g., 'tech', 'hr', 'general')
- All other nodes → 'output' handle (default, no need to specify)
- Multiple edges from one node = parallel execution (fan-out)

## State Sharing (Variables)
Each node automatically writes variables: {{NodeLabel}}.response, {{NodeLabel}}.result
In Transform templates, access as: {{{{ NodeLabel_response }}}} (replace dots/spaces with underscore)

## Process (FOLLOW STRICTLY)
1. Ask user for key decisions using ask_user (one question at a time)
2. After collecting user choices, create nodes AND edges together:
   - For EACH node you create, IMMEDIATELY create the edge connecting it to the previous node
   - Example pattern:
     create_input_node("start", "입력")
     create_guardrail_node("guard", "보안검사", "guard-id-xxx")
     create_edge("start", "guard")                          ← connect immediately!
     create_model_node("classifier", "분류기", ...)
     create_edge("guard", "classifier", "pass")             ← connect immediately!
     create_transform_node("block_msg", "차단안내", ...)
     create_edge("guard", "block_msg", "block")             ← connect immediately!
     create_output_node("end", "출력")
     create_edge("classifier", "end")                       ← connect immediately!
     create_edge("block_msg", "end")                        ← connect immediately!
3. Call validate_flow to self-check — write out ALL nodes and edges
4. Fix any missing edges
5. Call finalize_flow

CRITICAL: Every create_*_node MUST be followed by create_edge connecting it.
Never create all nodes first then edges — interleave them.

## Asking the User (IMPORTANT)
Use ask_user to get user choices. Follow these rules:
1. Ask ONE question at a time — never combine multiple questions
2. Keep options to max 6 per question
3. Use actual resource names from Available Resources above
4. For guardrails: show available ones + "사용 안함"
5. For models: show ALL available LLM models from the list
6. For routing: ask "어떤 카테고리로 분류할까요?" and let user type freely
7. After user answers, proceed to NEXT question or start building

Example flow of questions:
  Turn 1: ask_user("가드레일을 사용할까요?", ["개인정보보호", "금칙어 차단", "사용 안함"])
  Turn 2 (after user picks): ask_user("어떤 카테고리로 분류할까요? 원하는 부서명을 입력해주세요.", ["직접 입력"])
  Turn 3 (after user types): Start building with all collected info

If the user already specified everything clearly, skip asking and build immediately.

## CRITICAL Rules (MUST follow)
1. ALWAYS create_input_node FIRST
2. ALWAYS create_output_node LAST
3. EVERY path MUST end at the output node — connect ALL terminal nodes to output with create_edge
   - After guardrail: connect BOTH 'pass' path AND 'block' path to eventually reach output
   - After condition: connect BOTH 'true' AND 'false' paths to eventually reach output
   - After router: connect ALL routes to eventually reach output
4. VERIFY: Before calling finalize_flow, check that every branch leads to the output node
5. Use meaningful node_id values (lowercase, no spaces: 'pii_guard', 'topic_router')
6. Use descriptive labels in Korean when the user speaks Korean
7. For transform templates: use {{{{ NodeLabel_response }}}} format (dot/space → underscore)
"""


class FlowBuilderAgent(ReactAgentBase):
    """자연어 의도에서 에이전트 플로우를 자동 생성하는 에이전트."""

    def __init__(
        self,
        api_config: Dict[str, Any],
        base_url: str,
        api_key: str,
        metadata: Dict[str, Any],
        request: Request,
    ):
        self.api_config = api_config
        self.base_url = base_url
        self.api_key = api_key
        self.metadata = metadata
        self.request = request

    def get_tools(self) -> list:
        """Get all flow builder tools."""
        return get_all_flow_builder_tools()

    async def _build_resource_context(self) -> str:
        """Build available resources context for system prompt.

        Only includes resources the user has read access to.
        """
        lines = []
        user_id = self.metadata.get("user_id", "")
        user_role = self.metadata.get("user_role", "user")
        is_admin = user_role == "admin"

        try:
            from open_webui.models.models import Models

            if is_admin:
                all_models = Models.get_all_models()
            else:
                all_models = Models.get_models()  # Returns user-accessible models
            agents = [m for m in all_models if getattr(m, "base_model_id", None)]
            if agents:
                lines.append("### Available Agents")
                for a in agents[:15]:
                    lines.append(
                        f"- ID: `{a.id}` | Name: {a.name} | Base: {a.base_model_id}"
                    )
                lines.append("")
        except Exception as e:
            logger.warning(f"Failed to load agents: {e}")

        try:
            from open_webui.models.guardrails import Guardrails

            if is_admin:
                guardrails = Guardrails.get_guardrails()
            else:
                guardrails = Guardrails.get_guardrails_by_user_id(user_id, "read")
            if guardrails:
                lines.append("### Available Guardrails")
                for g in guardrails[:10]:
                    pii = g.pii_types if hasattr(g, "pii_types") else []
                    words = (g.blocked_words if hasattr(g, "blocked_words") else [])[:3]
                    strategy = g.pii_strategy if hasattr(g, "pii_strategy") else ""
                    lines.append(
                        f"- ID: `{g.id}` | Name: {g.name} | Strategy: {strategy} | PII: {pii} | Words: {words}"
                    )
                lines.append("")
        except Exception as e:
            logger.warning(f"Failed to load guardrails: {e}")

        try:
            from open_webui.models.glossary import Glossaries

            if is_admin:
                glossaries = Glossaries.get_glossaries()
            else:
                glossaries = Glossaries.get_glossaries_by_user_id(user_id, "read")
            if glossaries:
                lines.append("### Available Glossaries")
                for g in glossaries[:10]:
                    entries = (g.data or {}).get("entries", []) if g.data else []
                    lines.append(
                        f"- ID: `{g.id}` | Name: {g.name} | Terms: {len(entries)}"
                    )
                lines.append("")
        except Exception as e:
            logger.warning(f"Failed to load glossaries: {e}")

        # Available LLM models (from OpenAI endpoints, exclude flow/agent models)
        try:
            if self.request and hasattr(self.request, "app"):
                openai_models = getattr(self.request.app.state, "OPENAI_MODELS", {})
                if openai_models:
                    base_models = [
                        mid
                        for mid in sorted(openai_models.keys())
                        if not mid.startswith("flow_") and not mid.startswith("flow.")
                    ]
                    if base_models:
                        lines.append("### Available LLM Models for model nodes")
                        for mid in base_models:
                            lines.append(f"- `{mid}`")
                        lines.append("")
        except Exception as e:
            logger.warning(f"Failed to load LLM models: {e}")

        return "\n".join(lines) if lines else "(No resources available)"

    async def run_chat(
        self,
        messages: list,
        model_id: str,
    ) -> Dict:
        """Multi-turn conversational flow building.

        Args:
            messages: Conversation history [{"role": "user"|"assistant", "content": "..."}]
            model_id: LLM model for the builder agent

        Returns:
            {
                "assistant_message": str,
                "pending_input": {"question": str, "options": [str]} or None,
                "flow_data": {"nodes": [], "edges": []} or None,
                "flow_name": str,
                "flow_description": str,
            }
        """
        from extension_modules.utils.llm import create_llm_from_app
        from langchain.agents import create_agent

        resource_context = await self._build_resource_context()
        system_prompt = FLOW_BUILDER_SYSTEM_PROMPT.format(
            available_resources=resource_context,
        )

        llm = create_llm_from_app(
            self.request.app,
            model_id,
            model_kwargs={"temperature": 0.3, "max_tokens": 8192},
        )

        tools = self.get_tools()
        agent = create_agent(
            llm,
            tools,
            system_prompt=system_prompt,
            state_schema=FlowBuilderState,
        )

        logger.info(f"FlowBuilderAgent chat: {len(messages)} messages")

        result = await agent.ainvoke({"messages": messages})

        # Extract last AI message
        assistant_message = ""
        result_messages = result.get("messages", [])
        for msg in reversed(result_messages):
            content = getattr(msg, "content", "") if hasattr(msg, "content") else ""
            msg_type = getattr(msg, "type", "")
            # Skip tool messages, find last AI message
            if msg_type == "ai" and content and "ASK_USER:" not in content:
                assistant_message = content
                break

        # Check if ask_user was called (parse ASK_USER marker from tool messages)
        pending_input = None
        for msg in result_messages:
            content = getattr(msg, "content", "") if hasattr(msg, "content") else ""
            if "ASK_USER:" in str(content):
                try:
                    parts = content.split("::OPTIONS:")
                    question = parts[0].replace("ASK_USER:", "").strip()
                    options = parts[1].split("|") if len(parts) > 1 and parts[1] else []
                    options = [o.strip() for o in options if o.strip()]
                    pending_input = {"question": question, "options": options}
                    if not assistant_message:
                        assistant_message = question
                except Exception:
                    pass

        # Extract flow data if nodes were created
        nodes = result.get("node_definitions", [])
        edges = result.get("edge_definitions", [])
        flow_name = result.get("flow_name", "")
        flow_desc = result.get("flow_description", "")

        flow_data = None
        if nodes:
            edges_before = len(edges)
            self._ensure_all_paths_to_output(nodes, edges)
            edges_after = len(edges)
            if edges_after > edges_before:
                logger.info(
                    f"Auto-fix added {edges_after - edges_before} edges "
                    f"({edges_before} → {edges_after})"
                )
            self._auto_layout(nodes, edges)
            flow_data = {"nodes": nodes, "edges": edges}

        return {
            "assistant_message": assistant_message,
            "pending_input": pending_input,
            "flow_data": flow_data,
            "flow_name": flow_name,
            "flow_description": flow_desc,
        }

    async def run(
        self,
        intent: str,
        model_id: str,
        flow_name: str = "",
    ) -> Dict[str, Any]:
        """Run the flow builder agent.

        Args:
            intent: User's natural language description of the desired flow
            model_id: LLM model to use for the builder agent
            flow_name: Optional flow name (agent will generate if empty)

        Returns:
            Dict with flow_data (nodes, edges), flow_name, flow_description
        """
        from extension_modules.utils.llm import create_llm_from_app
        from langchain.agents import create_agent

        # Build resource context
        resource_context = await self._build_resource_context()

        # Build system prompt
        system_prompt = FLOW_BUILDER_SYSTEM_PROMPT.format(
            available_resources=resource_context,
        )

        # Create LLM
        llm = create_llm_from_app(
            self.request.app,
            model_id,
            model_kwargs={"temperature": 0.3, "max_tokens": 8192},
        )

        # Get tools
        tools = self.get_tools()

        # Create agent
        agent = create_agent(
            llm,
            tools,
            system_prompt=system_prompt,
            state_schema=FlowBuilderState,
        )

        # Run agent
        logger.info(f"Running FlowBuilderAgent with intent: {intent[:100]}...")
        user_message = intent
        if flow_name:
            user_message = f"Flow name: {flow_name}\n\nIntent: {intent}"

        result = await agent.ainvoke(
            {
                "messages": [{"role": "user", "content": user_message}],
            }
        )

        # Extract results
        node_definitions = result.get("node_definitions", [])
        edge_definitions = result.get("edge_definitions", [])
        flow_layout = result.get("flow_layout", {})
        result_name = result.get("flow_name", flow_name or "Auto-generated Flow")
        result_desc = result.get("flow_description", intent[:200])

        # Apply layout positions to nodes
        if flow_layout and flow_layout.get("positions"):
            pos_map = {}
            for p in flow_layout["positions"]:
                nid = p.get("nodeId") or p.get("node_id") or p.get("id", "")
                if nid:
                    pos_map[nid] = p
            for node in node_definitions:
                if node["id"] in pos_map:
                    pos = pos_map[node["id"]]
                    node["position"] = {
                        "x": pos.get("x", 0),
                        "y": pos.get("y", 0),
                    }

        # Smart auto-layout: topological order + branch spreading
        self._ensure_all_paths_to_output(node_definitions, edge_definitions)
        self._auto_layout(node_definitions, edge_definitions)

        logger.info(
            f"FlowBuilderAgent completed: {len(node_definitions)} nodes, {len(edge_definitions)} edges"
        )

        return {
            "flow_data": {
                "nodes": node_definitions,
                "edges": edge_definitions,
            },
            "flow_name": result_name,
            "flow_description": result_desc,
        }

    def _ensure_all_paths_to_output(self, nodes: list, edges: list):
        """Validate and fix flow connectivity.

        1. Ensure input node connects to something
        2. Ensure sequential nodes without edges are chained
        3. Ensure all terminal nodes connect to output
        """
        if not nodes or len(nodes) < 2:
            return

        existing_edges = {(e["source"], e["target"]) for e in edges}

        # Find input and output nodes
        input_nodes = [n for n in nodes if n.get("type") in ("flowInput", "input")]
        output_nodes = [n for n in nodes if n.get("type") in ("flowOutput", "output")]
        output_id = output_nodes[0]["id"] if output_nodes else None

        # Nodes with incoming/outgoing edges
        has_incoming = {e["target"] for e in edges}
        has_outgoing = {e["source"] for e in edges}

        # Step 1: Chain disconnected nodes in order
        # If a node has no incoming edge (except input) and the previous node has no outgoing,
        # connect them sequentially
        non_io_nodes = [
            n
            for n in nodes
            if n.get("type") not in ("flowInput", "input", "flowOutput", "output")
        ]
        for i, node in enumerate(non_io_nodes):
            nid = node["id"]
            if nid not in has_incoming:
                # This node has no incoming edge — find what should connect to it
                if i == 0 and input_nodes:
                    # First processing node: connect from input
                    src = input_nodes[0]["id"]
                    if (src, nid) not in existing_edges:
                        edges.append(
                            {
                                "id": f"edge_fix_{src}_{nid}",
                                "source": src,
                                "target": nid,
                                "sourceHandle": "output",
                            }
                        )
                        existing_edges.add((src, nid))
                        has_incoming.add(nid)
                        has_outgoing.add(src)
                        logger.info(f"Auto-fix: connected '{src}' → '{nid}'")
                elif i > 0:
                    # Connect from previous node
                    prev = non_io_nodes[i - 1]
                    prev_id = prev["id"]
                    if (
                        prev_id not in has_outgoing
                        and (prev_id, nid) not in existing_edges
                    ):
                        handle = "output"
                        # Check if prev is condition/guardrail (use 'true'/'pass')
                        prev_type = prev.get("type", "")
                        if prev_type in ("condition", "flowCondition"):
                            handle = "true"
                        elif prev_type == "guardrail":
                            handle = "pass"
                        edges.append(
                            {
                                "id": f"edge_fix_{prev_id}_{nid}",
                                "source": prev_id,
                                "target": nid,
                                "sourceHandle": handle,
                            }
                        )
                        existing_edges.add((prev_id, nid))
                        has_incoming.add(nid)
                        has_outgoing.add(prev_id)
                        logger.info(
                            f"Auto-fix: chained '{prev_id}' → '{nid}' (handle={handle})"
                        )

        # Step 2: Connect all terminal nodes to output
        if output_id:
            # Recalculate after fixes
            has_outgoing = {e["source"] for e in edges}
            for node in nodes:
                nid = node["id"]
                if nid == output_id:
                    continue
                if nid not in has_outgoing and (nid, output_id) not in existing_edges:
                    edges.append(
                        {
                            "id": f"edge_fix_{nid}_{output_id}",
                            "source": nid,
                            "target": output_id,
                            "sourceHandle": "output",
                        }
                    )
                    existing_edges.add((nid, output_id))
                    logger.info(f"Auto-fix: terminal '{nid}' → output")

        logger.info(f"Connectivity fix: {len(edges)} edges after validation")

    def _auto_layout(self, nodes: list, edges: list):
        """Auto-layout nodes using topological order with branch spreading."""
        from collections import defaultdict, deque

        if not nodes:
            return

        node_map = {n["id"]: n for n in nodes}
        children = defaultdict(list)  # parent → [children]
        parents = defaultdict(list)  # child → [parents]
        for e in edges:
            children[e["source"]].append(e["target"])
            parents[e["target"]].append(e["source"])

        # Find roots (no incoming edges)
        all_ids = {n["id"] for n in nodes}
        child_ids = {e["target"] for e in edges}
        roots = [nid for nid in all_ids if nid not in child_ids]
        if not roots:
            roots = [nodes[0]["id"]]

        # BFS to assign levels
        levels = {}  # node_id → level (y)
        queue = deque()
        for r in roots:
            levels[r] = 0
            queue.append(r)

        while queue:
            nid = queue.popleft()
            for child in children[nid]:
                new_level = levels[nid] + 1
                if child not in levels or new_level > levels[child]:
                    levels[child] = new_level
                    queue.append(child)

        # Assign levels to remaining unvisited nodes
        for n in nodes:
            if n["id"] not in levels:
                levels[n["id"]] = len(nodes)

        # Group by level
        level_groups = defaultdict(list)
        for nid, lvl in levels.items():
            level_groups[lvl].append(nid)

        # Assign positions
        Y_SPACING = 160
        X_SPACING = 250
        CENTER_X = 350

        for level, nids in sorted(level_groups.items()):
            count = len(nids)
            start_x = CENTER_X - ((count - 1) * X_SPACING) / 2
            for i, nid in enumerate(nids):
                if nid in node_map:
                    node_map[nid]["position"] = {
                        "x": int(start_x + i * X_SPACING),
                        "y": level * Y_SPACING,
                    }

    async def save_flow(
        self,
        user_id: str,
        flow_data: Dict[str, Any],
        flow_name: str,
        flow_description: str,
    ) -> str:
        """Save generated flow to database.

        Returns:
            Flow ID (without prefix)
        """
        from open_webui.models.models import ModelForm, ModelMeta, ModelParams, Models

        flow_id = f"auto-{uuid.uuid4().hex[:8]}"
        model_id = f"flow_{flow_id}"

        meta_dict = {
            "profile_image_url": "/static/favicon.png",
            "description": flow_description,
            "type": "agent_flow",
            "flow_data": flow_data,
        }

        model_form = ModelForm(
            id=model_id,
            base_model_id=None,
            name=flow_name,
            meta=ModelMeta(**meta_dict),
            params=ModelParams(),
            access_control=None,
            is_active=True,
        )

        model = Models.insert_new_model(model_form, user_id)
        if model:
            logger.info(f"Flow saved: {flow_id} ({flow_name})")
            return flow_id
        else:
            raise RuntimeError("Failed to save flow to database")

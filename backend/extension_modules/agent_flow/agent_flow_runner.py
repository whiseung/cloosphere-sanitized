"""
Agent Flow Runner

Dynamically builds and executes LangGraph flows from JSON flow data.
Similar to KBSphereAgent/DBSphereAgent pattern but with dynamic graph construction.
"""

import json
import logging
import time
import uuid
from typing import (
    Annotated,
    Any,
    AsyncGenerator,
    Callable,
    Dict,
    List,
    Optional,
    TypedDict,
)

from extension_modules.kbsphere.search_engines.azure_search import (
    KnowledgeSearchClient,
    KnowledgeSearchConfig,
)
from extension_modules.react.react_base import ReactAgentBase
from fastapi import Request
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Send
from open_webui.env import SRC_LOG_LEVELS
from open_webui.socket.main import get_event_call, get_event_emitter
from starlette.responses import StreamingResponse

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS.get("MODELS", logging.INFO))


def replace_value(current: Any, new: Any) -> Any:
    """Reducer that replaces the current value with the new value."""
    return new if new is not None else current


def merge_dict(current: Dict, new: Dict) -> Dict:
    """Reducer that merges dictionaries."""
    result = dict(current) if current else {}
    if new:
        result.update(new)
    return result


def append_list(current: List, new: List) -> List:
    """Reducer that appends to list."""
    result = list(current) if current else []
    if new:
        result.extend(new)
    return result


class FlowState(TypedDict, total=False):
    """State passed between nodes in the flow graph.

    Using TypedDict with Annotated reducers for LangGraph compatibility.
    Each node returns a dict with keys to update - reducers handle merging.
    """

    messages: Annotated[List[BaseMessage], append_list]
    input_text: Annotated[str, replace_value]
    current_output: Annotated[str, replace_value]
    context: Annotated[List[Dict[str, Any]], append_list]
    documents: Annotated[List[Dict[str, Any]], append_list]
    variables: Annotated[Dict[str, Any], merge_dict]
    node_outputs: Annotated[Dict[str, Any], merge_dict]
    error: Annotated[Optional[str], replace_value]


class StateAccessor:
    """Wrapper to access TypedDict state with attribute syntax."""

    def __init__(self, state: Dict[str, Any]):
        self._state = state

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            return object.__getattribute__(self, name)
        return self._state.get(name)

    def get(self, name: str, default: Any = None) -> Any:
        return self._state.get(name, default)

    def get_var(self, key: str, default: Any = None) -> Any:
        """Get a variable from the variables dict."""
        return self._state.get("variables", {}).get(key, default)


class AgentFlowRunner(ReactAgentBase):
    """
    Dynamically builds and runs LangGraph flows from JSON flow data.

    Follows the same pattern as KBSphereAgent/DBSphereAgent for integration
    with the openai.py router.
    """

    def __init__(
        self,
        api_config: Dict[str, Any],
        base_url: str,
        api_key: str,
        metadata: Dict[str, Any],
        request: Request,
        flow_data: Dict[str, Any],
    ):
        self.api_config = api_config
        self.base_url = base_url
        self.api_key = api_key
        self.metadata = metadata
        self.request = request
        self.flow_data = flow_data
        self.event_emitter = None
        self.event_call = None
        self._stream_id = None
        self._trace_context = None
        self._chain_run = None

    def _resolve_model_endpoint(self, base_model_id: str) -> tuple:
        """Resolve the correct API endpoint for a given base model ID.

        Returns (api_config, base_url, api_key) for the model's provider.
        Falls back to self's defaults if not found.
        """
        if not self.request or not hasattr(self.request, "app"):
            return self.api_config, self.base_url, self.api_key

        openai_models = getattr(self.request.app.state, "OPENAI_MODELS", {})
        model_entry = openai_models.get(base_model_id)
        if not model_entry or "urlIdx" not in model_entry:
            return self.api_config, self.base_url, self.api_key

        idx = model_entry["urlIdx"]
        urls = self.request.app.state.config.OPENAI_API_BASE_URLS
        keys = self.request.app.state.config.OPENAI_API_KEYS
        configs = self.request.app.state.config.OPENAI_API_CONFIGS

        if not urls or len(urls) <= idx:
            return self.api_config, self.base_url, self.api_key

        url = urls[idx]
        key = keys[idx] if keys and len(keys) > idx else ""
        api_config = configs.get(str(idx), configs.get(url, {}))

        log.info(
            f"Resolved endpoint idx={idx} for model={base_model_id}, url={url[:40]}"
        )
        return api_config, url, key

    def _items_to_openwebui_sources(self, items: Any) -> Dict[str, Any]:
        """
        Azure Search items -> OpenWebUI sources 포맷으로 변환.
        tools_base.py의 패턴을 따름.
        """
        # items가 {"items":[...]}일 수도, list일 수도 있다.
        if isinstance(items, dict) and isinstance(items.get("items"), list):
            items_list = items.get("items") or []
        elif isinstance(items, list):
            items_list = items
        else:
            items_list = []

        sources: List[Dict[str, Any]] = []
        for idx, it in enumerate(items_list, start=1):
            # dict가 아닌 객체인 경우 dict로 변환 시도
            if not isinstance(it, dict):
                try:
                    if hasattr(it, "model_dump"):
                        it = it.model_dump()
                    else:
                        it = dict(it)
                except Exception:
                    continue

            sid = it.get("id")
            content = it.get("content") or it.get("data", {}).get("content") or ""

            meta_raw = it.get("metadata") or it.get("meta") or {}
            meta: Dict[str, Any] = {}

            if isinstance(meta_raw, str):
                try:
                    meta = json.loads(meta_raw)
                except Exception:
                    meta = {"raw": meta_raw}
            elif isinstance(meta_raw, dict):
                meta = meta_raw

            # 파일명 추출
            name = (
                it.get("filename")
                or it.get("name")
                or meta.get("name")
                or meta.get("file_name")
                or meta.get("filename")
                or meta.get("title")
                or meta.get("source")
                or meta.get("url")
            )

            stable_source = (
                meta.get("source")
                or meta.get("url")
                or (f"file:{name}" if name else None)
                or f"file:doc_{idx}"
            )

            meta["source"] = stable_source
            if name and "name" not in meta:
                meta["name"] = name

            sources.append(
                {
                    "source": {
                        "id": sid if sid else stable_source,
                        "name": name or stable_source,
                    },
                    "document": [content if isinstance(content, str) else str(content)],
                    "metadata": [meta],
                    **(
                        {"distances": [it.get("score")]}
                        if it.get("score") is not None
                        else {}
                    ),
                }
            )

        return {"sources": sources}

    def _get_nodes_and_edges(self) -> tuple:
        """Extract nodes and edges from flow_data."""
        nodes = self.flow_data.get("nodes", [])
        edges = self.flow_data.get("edges", [])
        return nodes, edges

    def _get_node_by_id(self, node_id: str, nodes: list) -> Optional[dict]:
        """Get node by ID."""
        return next((n for n in nodes if n.get("id") == node_id), None)

    def _topological_sort(self, nodes: list, edges: list) -> list:
        """Sort nodes in topological order for execution."""
        adjacency = {n.get("id"): [] for n in nodes}
        in_degree = {n.get("id"): 0 for n in nodes}

        for edge in edges:
            source = edge.get("source")
            target = edge.get("target")
            if source in adjacency and target in in_degree:
                adjacency[source].append(target)
                in_degree[target] += 1

        queue = [node_id for node_id, degree in in_degree.items() if degree == 0]
        sorted_ids = []

        while queue:
            node_id = queue.pop(0)
            sorted_ids.append(node_id)
            for neighbor in adjacency.get(node_id, []):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        return sorted_ids

    def _build_graph(self, nodes: list, edges: list) -> CompiledStateGraph:
        """Build LangGraph StateGraph from flow nodes and edges."""
        graph = StateGraph(FlowState)

        # Debug logging
        log.info(f"Building flow graph with {len(nodes)} nodes and {len(edges)} edges")
        for node in nodes:
            log.info(
                f"  Node: id={node.get('id')}, type={node.get('type')}, data={node.get('data', {})}"
            )
        for edge in edges:
            log.info(f"  Edge: {edge.get('source')} -> {edge.get('target')}")

        # Create node functions for each flow node
        node_functions = {}
        for node in nodes:
            node_id = node.get("id")
            node_type = node.get("type")
            node_data = node.get("data", {})

            node_func = self._create_node_function(node_id, node_type, node_data)
            node_functions[node_id] = node_func
            graph.add_node(node_id, node_func)

        # Pre-collect conditional edges by source node to avoid overwriting
        condition_edges: Dict[
            str, Dict[str, str]
        ] = {}  # source_id -> {"true": target, "false": target}
        router_edges: Dict[
            str, Dict[str, str]
        ] = {}  # source_id -> {route_id: target_id}
        normal_edges = []

        for edge in edges:
            source = edge.get("source")
            target = edge.get("target")
            source_handle = edge.get("sourceHandle", "output")

            source_node = self._get_node_by_id(source, nodes)
            # Condition and Guardrail both support true/false (pass/fail) branching
            if source_node and source_node.get("type") in (
                "condition",
                "flowCondition",
                "guardrail",
            ):
                if source_handle in ("true", "false", "pass", "block"):
                    if source not in condition_edges:
                        condition_edges[source] = {}
                    # Normalize: pass→true, block→false
                    normalized = {"pass": "true", "block": "false"}.get(
                        source_handle, source_handle
                    )
                    condition_edges[source][normalized] = target
                else:
                    normal_edges.append(edge)
            elif source_node and source_node.get("type") == "router":
                if source not in router_edges:
                    router_edges[source] = {}
                router_edges[source][source_handle] = target
            else:
                normal_edges.append(edge)

        # Detect fan-out patterns (one source → multiple targets = parallel)
        from collections import defaultdict

        fanout_map = defaultdict(list)  # source_id → [target_ids]
        for edge in normal_edges:
            fanout_map[edge.get("source")].append(edge.get("target"))

        # Add normal edges: single-target = regular edge, multi-target = Send() parallel
        for source_id, targets in fanout_map.items():
            if len(targets) == 1:
                graph.add_edge(source_id, targets[0])
            else:
                # Fan-out: use conditional edges with Send() for parallel execution
                def _make_fanout(src_id, target_list):
                    def fanout_fn(state):
                        return [Send(t, state) for t in target_list]

                    return fanout_fn

                graph.add_conditional_edges(
                    source_id,
                    _make_fanout(source_id, targets),
                )
                log.info(f"Fan-out from '{source_id}' → {targets} (parallel via Send)")

        # Add single conditional edge per condition node (handles both true/false)
        def _make_condition_router(source_id, true_target, false_target):
            """Factory to avoid closure variable capture bug."""

            def router(state):
                result = (
                    state.get("node_outputs", {})
                    .get(source_id, {})
                    .get("result", False)
                )
                if result and true_target:
                    return true_target
                elif not result and false_target:
                    return false_target
                return END

            return router

        for source_id, targets in condition_edges.items():
            true_target = targets.get("true")
            false_target = targets.get("false")

            path_map = {END: END}
            if true_target:
                path_map[true_target] = true_target
            if false_target:
                path_map[false_target] = false_target

            graph.add_conditional_edges(
                source_id,
                _make_condition_router(source_id, true_target, false_target),
                path_map,
            )

        # Add router conditional edges (N-way branching)
        def _make_router_fn(src_id, valid_routes):
            """Factory for router routing function."""

            def router_fn(state):
                route = state.get("node_outputs", {}).get(src_id, {}).get("route")
                if route in valid_routes:
                    return route
                return END

            return router_fn

        for source_id, routes in router_edges.items():
            path_map = {END: END}
            for route_id, target_id in routes.items():
                path_map[route_id] = target_id

            graph.add_conditional_edges(
                source_id,
                _make_router_fn(source_id, set(routes.keys())),
                path_map,
            )

        # Find input nodes (entry points) - supports both explicit and implicit
        input_types = ("input", "flowInput")
        input_nodes = [n.get("id") for n in nodes if n.get("type") in input_types]
        sorted_ids = self._topological_sort(nodes, edges)

        if input_nodes:
            graph.set_entry_point(input_nodes[0])
        elif sorted_ids:
            # Implicit entry: use first node in topological order
            graph.set_entry_point(sorted_ids[0])
            log.info(
                f"No input node found, using implicit entry point: {sorted_ids[0]}"
            )

        # Find output nodes and connect to END
        # If no explicit output nodes, connect leaf nodes (no outgoing edges) to END
        output_types = ("output", "flowOutput")
        output_nodes = [n.get("id") for n in nodes if n.get("type") in output_types]
        all_node_ids = {n.get("id") for n in nodes}

        if output_nodes:
            for output_node_id in output_nodes:
                graph.add_edge(output_node_id, END)
        else:
            # Implicit exit: leaf nodes with no outgoing edges
            nodes_with_outgoing = set()
            for edge in edges:
                nodes_with_outgoing.add(edge.get("source"))
            # Also include condition/router edge sources
            for source_id in condition_edges:
                nodes_with_outgoing.add(source_id)
            for source_id in router_edges:
                nodes_with_outgoing.add(source_id)

            leaf_nodes = all_node_ids - nodes_with_outgoing
            for leaf_id in leaf_nodes:
                graph.add_edge(leaf_id, END)
            if leaf_nodes:
                log.info(
                    f"No output node found, using implicit exit points: {leaf_nodes}"
                )

        # Reachability check (warning only)
        entry_id = (
            input_nodes[0] if input_nodes else (sorted_ids[0] if sorted_ids else None)
        )
        if entry_id:
            adjacency = {n.get("id"): [] for n in nodes}
            for edge in normal_edges:
                src = edge.get("source")
                if src in adjacency:
                    adjacency[src].append(edge.get("target"))
            for src, targets in condition_edges.items():
                if src in adjacency:
                    for tgt in targets.values():
                        if tgt:
                            adjacency[src].append(tgt)
            for src, targets in router_edges.items():
                if src in adjacency:
                    for tgt in targets.values():
                        if tgt:
                            adjacency[src].append(tgt)

            reachable = set()
            queue = [entry_id]
            while queue:
                nid = queue.pop(0)
                if nid in reachable:
                    continue
                reachable.add(nid)
                for neighbor in adjacency.get(nid, []):
                    if neighbor not in reachable:
                        queue.append(neighbor)

            unreachable = all_node_ids - reachable
            if unreachable:
                log.warning(f"Unreachable nodes in flow: {unreachable}")

        # Compile with checkpointer for resumable execution and audit trail
        try:
            from langgraph.checkpoint.memory import MemorySaver

            checkpointer = MemorySaver()
            return graph.compile(checkpointer=checkpointer)
        except ImportError:
            log.warning(
                "langgraph.checkpoint not available, compiling without checkpointer"
            )
            return graph.compile()

    def _start_node_trace(
        self, node_id: str, node_type: str, inputs: Optional[dict] = None
    ):
        """Start a trace run for a node execution using TraceContext."""
        if not self._trace_context or not self._trace_context.enabled:
            return None
        try:
            run_type_map = {
                "model": "llm",
                "agent": "chain",
                "guardrail": "guardrail",
                "condition": "chain",
                "router": "chain",
                "transform": "chain",
                "merge": "chain",
                "glossary": "retrieval",
                "input": "chain",
                "flowInput": "chain",
                "output": "chain",
                "flowOutput": "chain",
            }
            run_type = run_type_map.get(node_type, "chain")

            safe_inputs = {}
            if inputs:
                for k, v in inputs.items():
                    safe_inputs[k] = str(v)[:500] if v else ""

            run = self._trace_context.begin_run(
                run_type=run_type,
                name=f"flow_node:{node_id}({node_type})",
                inputs=safe_inputs,
            )
            return run
        except Exception as e:
            log.warning(f"Failed to start trace for node {node_id}: {e}")
            return None

    def _end_node_trace(
        self, trace, outputs: Optional[dict] = None, error: Optional[str] = None
    ):
        """End a trace run for a node execution."""
        if not trace:
            return
        try:
            safe_outputs = {}
            if outputs:
                for k, v in outputs.items():
                    safe_outputs[k] = str(v)[:500] if v else ""

            if hasattr(trace, "complete"):
                if error:
                    trace.set_error(error)
                if safe_outputs:
                    trace.set_outputs(safe_outputs)
                trace.complete()
        except Exception as e:
            log.warning(f"Failed to end trace: {e}")

    def _wrap_node_function(
        self,
        node_id: str,
        node_type: str,
        func: Callable,
        node_data: Optional[dict] = None,
    ) -> Callable:
        """Wrap a node function with error handling, retry, timeout, and tracing."""
        config = (node_data or {}).get("config", {})
        max_retries = config.get("maxRetries", 0)
        retry_interval = config.get("retryInterval", 1.0)
        timeout_seconds = config.get("timeout", 0)  # 0 = no timeout
        default_value = config.get("defaultValue")
        error_strategy = config.get("errorStrategy", "fail")  # fail, default, continue
        node_label = (node_data or {}).get("label", node_id)

        async def wrapped(state: FlowState) -> Dict[str, Any]:
            import asyncio as _asyncio

            # Start trace for this node
            trace_inputs = {
                "node_id": node_id,
                "node_type": node_type,
                "node_label": node_label,
                "input_text": (
                    state.get("current_output") or state.get("input_text", "")
                )[:500],
            }
            trace_run = self._start_node_trace(node_id, node_type, trace_inputs)

            last_error = None
            for attempt in range(max_retries + 1):
                try:
                    if timeout_seconds > 0:
                        result = await _asyncio.wait_for(
                            func(state), timeout=timeout_seconds
                        )
                    else:
                        result = await func(state)

                    # Complete trace with success
                    trace_outputs = {}
                    if isinstance(result, dict):
                        out_text = result.get("current_output", "")
                        trace_outputs["output"] = out_text[:500] if out_text else ""
                        if result.get("error"):
                            trace_outputs["error"] = result["error"]
                    self._end_node_trace(trace_run, outputs=trace_outputs)
                    return result

                except _asyncio.TimeoutError:
                    last_error = f"Timeout after {timeout_seconds}s"
                    log.warning(
                        f"[{node_id}] Timeout (attempt {attempt + 1}/{max_retries + 1})"
                    )
                except Exception as e:
                    last_error = str(e)
                    log.warning(
                        f"[{node_id}] Error (attempt {attempt + 1}/{max_retries + 1}): {e}"
                    )

                if attempt < max_retries:
                    await _asyncio.sleep(retry_interval)

            # All retries exhausted
            log.exception(
                f"Error executing node {node_id} (type={node_type}): {last_error}"
            )
            self._end_node_trace(trace_run, error=last_error)

            if error_strategy == "default" and default_value is not None:
                return {
                    "current_output": str(default_value),
                    "node_outputs": {
                        node_id: {"text": str(default_value), "used_default": True}
                    },
                }
            elif error_strategy == "continue":
                return {
                    "node_outputs": {node_id: {"error": last_error, "skipped": True}},
                }
            else:
                return {
                    "error": f"Node '{node_id}' ({node_type}) failed: {last_error}",
                    "node_outputs": {node_id: {"error": last_error}},
                }

        return wrapped

    def _create_node_function(
        self, node_id: str, node_type: str, node_data: dict
    ) -> Callable[[FlowState], FlowState]:
        """Create a node function based on node type."""

        # Node label for variables namespace (e.g., "Agent 1.response")
        node_label = node_data.get("label", node_id)

        def _make_var_key(key: str) -> str:
            """Create a namespaced variable key: 'NodeLabel.key'."""
            return f"{node_label}.{key}"

        async def input_node(state: FlowState) -> Dict[str, Any]:
            """Input node - entry point."""
            s = StateAccessor(state)
            log.info(f"[{node_id}] input_node executing, input_text={s.input_text}")
            return {
                "current_output": s.input_text or "",
                "node_outputs": {node_id: {"text": s.input_text or ""}},
            }

        async def output_node(state: FlowState) -> Dict[str, Any]:
            """Output node - returns final result with configurable action type.

            Action types:
            - passthrough: Pass through the current output as-is (default)
            - response: Generate a response using configured prompt and model
            - error: Return an error with configured template
            """
            s = StateAccessor(state)
            config = node_data.get("config", {})
            action_type = config.get("actionType", "passthrough")

            log.info(
                f"[{node_id}] output_node executing, actionType={action_type}, current_output={s.current_output[:100] if s.current_output else 'None'}..."
            )

            if action_type == "error":
                # Return error with configured template
                error_template = config.get(
                    "errorTemplate", "An error occurred in the flow."
                )
                try:
                    from jinja2 import Template

                    template = Template(error_template)
                    error_message = template.render(
                        input=s.current_output or s.input_text or "",
                        context=s.context or [],
                        documents=s.documents or [],
                        variables=s.variables or {},
                        error=s.error or "",
                    )
                except Exception as e:
                    log.warning(f"Error rendering error template: {e}")
                    error_message = error_template

                return {
                    "error": error_message,
                    "node_outputs": {node_id: {"text": error_message, "isError": True}},
                }

            elif action_type == "response":
                # Generate response using configured prompt and model
                use_prompt = config.get("usePrompt", False)
                prompt_template = config.get("prompt", "")
                model_id = config.get("modelId", "")

                if not use_prompt or not prompt_template:
                    # No prompt configured, fall back to passthrough
                    return {
                        "node_outputs": {node_id: {"text": s.current_output or ""}},
                    }

                # Render prompt template
                try:
                    from jinja2 import Template

                    template = Template(prompt_template)
                    rendered_prompt = template.render(
                        input=s.current_output or s.input_text or "",
                        context=s.context or [],
                        documents=s.documents or [],
                        variables=s.variables or {},
                        node_outputs=s.node_outputs or {},
                    )
                except Exception as e:
                    log.warning(f"Error rendering prompt template: {e}")
                    rendered_prompt = prompt_template

                # Get model for generation
                if not model_id:
                    # Try to get model from flow's agent/model nodes
                    nodes = self.flow_data.get("nodes", [])
                    for node in nodes:
                        if node.get("type") in ("agent", "model"):
                            resource_id = node.get("data", {}).get("resourceId")
                            if resource_id:
                                from open_webui.models.models import Models

                                model = Models.get_model_by_id(resource_id)
                                if model and model.base_model_id:
                                    model_id = model.base_model_id
                                    break

                if not model_id:
                    model_id = self.api_config.get("model")
                if not model_id:
                    raise ValueError(
                        f"Model node {node_id} has no model configured — "
                        "set a model in the node config or flow api_config"
                    )

                # Build messages for LLM
                messages = [
                    SystemMessage(
                        content="You are a helpful assistant. Generate a response based on the given context."
                    ),
                    HumanMessage(content=rendered_prompt),
                ]

                # Create LLM and generate response
                payload = {
                    "model": model_id,
                    "temperature": config.get("temperature", 0.7),
                    "max_tokens": config.get("maxTokens", 4096),
                }
                llm = self._create_llm(payload, stream=False)

                try:
                    response = await llm.ainvoke(messages)
                    output_text = (
                        response.content
                        if hasattr(response, "content")
                        else str(response)
                    )
                    # Gemini/Vertex AI may return list of content blocks
                    if isinstance(output_text, list):
                        output_text = "".join(
                            block.get("text", "")
                            if isinstance(block, dict)
                            else str(block)
                            for block in output_text
                        )
                    log.info(f"[{node_id}] Generated response: {output_text[:100]}...")
                    return {
                        "current_output": output_text,
                        "node_outputs": {
                            node_id: {"text": output_text, "generated": True}
                        },
                    }
                except Exception as e:
                    log.exception(
                        f"Error generating response in output node {node_id}: {e}"
                    )
                    return {
                        "error": str(e),
                        "node_outputs": {
                            node_id: {"text": s.current_output or "", "error": str(e)}
                        },
                    }

            else:
                # passthrough (default) - just pass through current output
                return {
                    "node_outputs": {node_id: {"text": s.current_output or ""}},
                }

        async def model_node(state: FlowState) -> Dict[str, Any]:
            """Model node - directly calls LLM without agent logic."""
            s = StateAccessor(state)
            config = node_data.get("config", {})
            resource_id = node_data.get("resourceId")
            log.info(
                f"[{node_id}] model_node executing, resourceId={resource_id}, current_output={s.current_output[:50] if s.current_output else 'None'}..."
            )

            # Get model info - prefer config.modelId, fallback to resourceId
            from open_webui.models.models import Models

            config_model_id = config.get("modelId")
            model = Models.get_model_by_id(resource_id) if resource_id else None
            log.info(
                f"[{node_id}] model lookup: resourceId={resource_id}, config.modelId={config_model_id}, model={model.name if model else 'None'}"
            )

            # Priority: config.modelId > model.base_model_id > resourceId
            base_model_id = config_model_id or (
                model.base_model_id if model and model.base_model_id else resource_id
            )
            if not base_model_id:
                log.warning(f"[{node_id}] No model configured")
                return {"error": f"No model configured for model node {node_id}"}

            # Build messages
            messages = []
            system_prompt = config.get("systemPrompt") or (
                model.meta.model_dump().get("system") if model and model.meta else None
            )
            if system_prompt:
                messages.append(SystemMessage(content=system_prompt))

            # Add context from documents
            context_text = ""
            docs = s.documents or []
            if docs:
                context_text = "\n\n".join(
                    [
                        f"[Source: {d.get('source', 'unknown')}]\n{d.get('content', d.get('text', ''))}"
                        for d in docs
                    ]
                )

            user_content = s.current_output or s.input_text or ""
            if context_text:
                user_content = f"Context:\n{context_text}\n\nQuestion: {user_content}"
            messages.append(HumanMessage(content=user_content))

            # Resolve correct endpoint for this model's provider
            resolved_config, resolved_url, resolved_key = self._resolve_model_endpoint(
                base_model_id
            )
            saved = (self.api_config, self.base_url, self.api_key)
            self.api_config, self.base_url, self.api_key = (
                resolved_config,
                resolved_url,
                resolved_key,
            )

            # Create LLM with proper payload dict
            payload = {
                "model": base_model_id,
                "temperature": config.get("temperature", 0.7),
                "max_tokens": config.get("maxTokens", 4096),
            }
            llm = self._create_llm(payload, stream=False)
            try:
                log.info(
                    f"[{node_id}] Calling LLM with model={base_model_id}, messages count={len(messages)}"
                )
                response = await llm.ainvoke(messages)
                output_text = (
                    response.content if hasattr(response, "content") else str(response)
                )
                # Gemini/Vertex AI may return list of content blocks
                if isinstance(output_text, list):
                    output_text = "".join(
                        block.get("text", "") if isinstance(block, dict) else str(block)
                        for block in output_text
                    )
                log.info(f"[{node_id}] LLM response: {output_text[:100]}...")
                return {
                    "current_output": output_text,
                    "node_outputs": {node_id: {"text": output_text}},
                    "variables": {_make_var_key("response"): output_text},
                }
            except Exception as e:
                log.exception(f"Error in model node {node_id}: {e}")
                return {"error": str(e)}
            finally:
                # Restore original endpoint config
                self.api_config, self.base_url, self.api_key = saved

        async def agent_node(state: FlowState) -> Dict[str, Any]:
            """Agent node - runs KBSphereAgent or DBSphereAgent based on config."""
            s = StateAccessor(state)
            config = node_data.get("config", {})
            resource_id = node_data.get("resourceId")

            if not resource_id:
                return {"error": f"No agent configured for node {node_id}"}

            # Get model/agent info
            from open_webui.models.models import Models
            from open_webui.models.users import Users
            from open_webui.utils.access_control import has_access

            model = Models.get_model_by_id(resource_id)
            if not model:
                return {"error": f"Agent/Model not found: {resource_id}"}

            # Verify user has read access
            flow_user_id = self.metadata.get("user_id", "")
            flow_user = Users.get_user_by_id(flow_user_id) if flow_user_id else None
            if not flow_user or (
                flow_user.role != "admin"
                and model.user_id != flow_user_id
                and not has_access(flow_user_id, "read", model.access_control)
            ):
                return {"error": f"Access denied to agent/model: {resource_id}"}

            # Check agent type from model params (not meta)
            model_params = model.params.model_dump() if model.params else {}
            model_meta = model.meta.model_dump() if model.meta else {}
            enable_kbsphere = model_params.get("enable_kbsphere", False)
            enable_dbsphere = model_params.get("enable_dbsphere", False)
            log.info(
                f"[{node_id}] agent_node: resource_id={resource_id}, enable_kbsphere={enable_kbsphere}, enable_dbsphere={enable_dbsphere}"
            )

            base_model_id = model.base_model_id if model.base_model_id else resource_id

            # Build payload for agent
            user_content = s.current_output or s.input_text or ""
            payload = {
                "model": base_model_id,
                "messages": [{"role": "user", "content": user_content}],
                "stream": False,
                "temperature": config.get("temperature", 0.7),
                "max_tokens": config.get("maxTokens", 4096),
            }

            # Build enhanced_params for agent runners
            enhanced_params = {
                "enable_kbsphere": enable_kbsphere,
                "enable_dbsphere": enable_dbsphere,
            }

            # Build metadata
            metadata = {
                **self.metadata,
                "model": {"id": model.id, "info": {"meta": model_meta}},
                "enhanced_params": enhanced_params,
            }

            try:
                # Resolve the correct API endpoint for this agent's base model
                agent_api_config, agent_base_url, agent_api_key = (
                    self._resolve_model_endpoint(base_model_id)
                )

                if enable_dbsphere:
                    from extension_modules.dbsphere.dbsphere_agent import (
                        DBSphereAgent,
                    )

                    runner = DBSphereAgent(
                        api_config=agent_api_config,
                        base_url=agent_base_url,
                        api_key=agent_api_key,
                        metadata=metadata,
                        request=self.request,
                    )
                elif enable_kbsphere:
                    from extension_modules.kbsphere.kbsphere_agent import KBSphereAgent

                    runner = KBSphereAgent(
                        api_config=agent_api_config,
                        base_url=agent_base_url,
                        api_key=agent_api_key,
                        metadata=metadata,
                        request=self.request,
                    )
                else:
                    # Fall back to direct LLM call if not a special agent
                    return await model_node(state)

                variables = s.variables or {}

                # KBSphere supports run_flow=True, DBSphere doesn't yet
                if enable_kbsphere:
                    # Run with run_flow=True to get messages + sources dict
                    result = await runner.run(
                        request=self.request,
                        payload=payload,
                        metadata=metadata,
                        user=variables.get("user"),
                        run_flow=True,
                    )

                    # result = {"messages": [...], "sources": {...}}
                    messages = result.get("messages", [])
                    sources = result.get("sources", {})

                    # Extract final AI message content from messages (search from end)
                    output_text = ""
                    tool_messages = []
                    for msg in reversed(messages):
                        msg_type = (
                            getattr(msg, "type", None) or msg.get("type")
                            if isinstance(msg, dict)
                            else None
                        )
                        if msg_type == "ai":
                            if hasattr(msg, "content"):
                                output_text = msg.content
                            elif isinstance(msg, dict):
                                output_text = msg.get("content", "")
                            break
                        elif msg_type == "tool":
                            tool_messages.append(msg)

                    log.info(
                        f"[{node_id}] KBSphere result: output_text={output_text[:100] if output_text else 'None'}..., sources_count={len(sources)}, tool_messages={len(tool_messages)}"
                    )

                    return {
                        "current_output": output_text,
                        "node_outputs": {
                            node_id: {
                                "text": output_text,
                                "sources": sources,
                                "messages": messages,
                                "tool_messages": tool_messages,
                            }
                        },
                        "variables": {_make_var_key("response"): output_text},
                    }
                else:
                    # DBSphere: consume streaming response (legacy approach)
                    result = await runner.run(
                        request=self.request,
                        payload=payload,
                        metadata=metadata,
                        user=variables.get("user"),
                    )

                    if hasattr(result, "body_iterator"):
                        output_chunks = []
                        parse_errors = 0
                        async for chunk in result.body_iterator:
                            if isinstance(chunk, bytes):
                                chunk = chunk.decode("utf-8")
                            if chunk.startswith("data: "):
                                data_str = chunk[6:].strip()
                                if data_str and data_str != "[DONE]":
                                    try:
                                        data = json.loads(data_str)
                                        delta = data.get("choices", [{}])[0].get(
                                            "delta", {}
                                        )
                                        content = delta.get("content", "")
                                        if content:
                                            output_chunks.append(content)
                                    except json.JSONDecodeError as e:
                                        parse_errors += 1
                                        log.warning(
                                            f"[{node_id}] JSON parse error in DBSphere chunk: {e}, data={data_str[:100]}"
                                        )
                        if parse_errors > 0:
                            log.warning(
                                f"[{node_id}] {parse_errors} JSON parse errors during DBSphere streaming"
                            )
                        output_text = "".join(output_chunks)
                        if not output_text:
                            log.warning(
                                f"[{node_id}] DBSphere returned empty output from streaming response"
                            )
                    else:
                        output_text = str(result)
                        log.warning(
                            f"[{node_id}] DBSphere returned non-streaming response"
                        )

                    log.info(
                        f"[{node_id}] DBSphere result: output_text={output_text[:100] if output_text else 'None'}..."
                    )

                    return {
                        "current_output": output_text,
                        "node_outputs": {node_id: {"text": output_text}},
                        "variables": {_make_var_key("response"): output_text},
                    }
            except Exception as e:
                log.exception(f"Error in agent node {node_id}: {e}")
                return {"error": str(e)}

        async def knowledge_node(state: FlowState) -> Dict[str, Any]:
            """Knowledge node - retrieves documents using KnowledgeSearchClient."""
            s = StateAccessor(state)
            config = node_data.get("config", {})
            resource_id = node_data.get("resourceId")

            if not resource_id:
                return {"error": f"No knowledge base configured for node {node_id}"}

            from open_webui.models.knowledge import Knowledges
            from open_webui.models.users import Users
            from open_webui.utils.access_control import has_access

            knowledge = Knowledges.get_knowledge_by_id(resource_id)
            if not knowledge:
                return {"error": f"Knowledge base not found: {resource_id}"}

            # Verify user has read access
            flow_user_id = self.metadata.get("user_id", "")
            flow_user = Users.get_user_by_id(flow_user_id) if flow_user_id else None
            if not flow_user or (
                flow_user.role != "admin"
                and knowledge.user_id != flow_user_id
                and not has_access(flow_user_id, "read", knowledge.access_control)
            ):
                return {"error": f"Access denied to knowledge base: {resource_id}"}

            query = s.current_output or s.input_text or ""
            query_list = [query] if isinstance(query, str) else query

            # Get config options
            reranker_threshold = config.get("rerankerThreshold", 0.0)
            index_name = config.get("indexName", "default")

            try:
                # Use KnowledgeSearchClient pattern from tools_base.py
                knowledge_search_config = KnowledgeSearchConfig(
                    index_name=index_name,
                    column_info=[],
                )

                # Build filter for the specific knowledge base collection
                filter_expr = f"collection eq '{resource_id}'"

                async with KnowledgeSearchClient(
                    config=knowledge_search_config
                ) as client:
                    results = await client.search_documents(
                        filter=filter_expr,
                        queries=query_list,
                        reranker_threshold=reranker_threshold,
                    )

                # Convert to OpenWebUI sources format
                sources_data = self._items_to_openwebui_sources(results)
                sources = sources_data.get("sources", [])

                # Convert sources to documents format for state
                documents = []
                for source in sources:
                    doc_content = (
                        source.get("document", [""])[0]
                        if source.get("document")
                        else ""
                    )
                    doc_metadata = (
                        source.get("metadata", [{}])[0]
                        if source.get("metadata")
                        else {}
                    )
                    documents.append(
                        {
                            "content": doc_content,
                            "source": source.get("source", {}).get(
                                "name", knowledge.name
                            ),
                            "metadata": doc_metadata,
                        }
                    )

                return {
                    "documents": documents,
                    "node_outputs": {
                        node_id: {"documents": documents, "sources": sources}
                    },
                    "variables": {_make_var_key("documents"): documents},
                }
            except Exception as e:
                log.warning(f"Error querying knowledge base: {e}")
                return {"node_outputs": {node_id: {"documents": []}}}

        async def guardrail_node(state: FlowState) -> Dict[str, Any]:
            """Guardrail node - filters content using middleware pattern."""
            s = StateAccessor(state)
            resource_id = node_data.get("resourceId")

            if not resource_id:
                return {"error": f"No guardrail configured for node {node_id}"}

            from open_webui.models.guardrails import Guardrails
            from open_webui.models.users import Users
            from open_webui.utils.access_control import has_access

            guardrail = Guardrails.get_guardrail_by_id(resource_id)
            if not guardrail:
                return {"error": f"Guardrail not found: {resource_id}"}

            # Verify user has read access
            flow_user_id = self.metadata.get("user_id", "")
            flow_user = Users.get_user_by_id(flow_user_id) if flow_user_id else None
            if not flow_user or (
                flow_user.role != "admin"
                and guardrail.user_id != flow_user_id
                and not has_access(flow_user_id, "read", guardrail.access_control)
            ):
                return {"error": f"Access denied to guardrail: {resource_id}"}

            text = s.current_output or s.input_text or ""

            # Use middleware pattern for full guardrail support
            # (LLM Judge, PII, blocked words, log strategy, etc.)
            from extension_modules.guardrail.middleware import (
                GuardrailBlockedError,
                create_guardrail_middlewares,
            )

            try:
                middlewares = create_guardrail_middlewares(
                    [resource_id],
                    app=self.request.app if self.request else None,
                    metadata=self.metadata,
                    trace_context=None,
                )

                mw_state = {"messages": [HumanMessage(content=text)]}
                violations = []

                for mw in middlewares:
                    update = await mw.abefore_model(mw_state, runtime=None)
                    if update:
                        mw_state = {**mw_state, **update}

                # Extract processed text from modified messages
                processed_messages = mw_state.get("messages", [])
                if processed_messages:
                    last_msg = processed_messages[-1]
                    processed_text = (
                        last_msg.content
                        if hasattr(last_msg, "content")
                        else str(last_msg)
                    )
                else:
                    processed_text = text

                # Collect violation info from middlewares
                for mw in middlewares:
                    if hasattr(mw, "detected_violation_types"):
                        violations.extend(mw.detected_violation_types)

                return {
                    "current_output": processed_text,
                    "node_outputs": {
                        node_id: {
                            "result": True,
                            "text": processed_text,
                            "violations": violations,
                        }
                    },
                    "variables": {
                        _make_var_key("passed"): True,
                        _make_var_key("text"): processed_text,
                    },
                }

            except GuardrailBlockedError as e:
                log.info(
                    f"[{node_id}] Guardrail blocked: {e.guardrail_name} - {e.reason}"
                )
                block_msg = f"Blocked by {e.guardrail_name}: {e.reason}"
                return {
                    "current_output": block_msg,
                    "node_outputs": {
                        node_id: {
                            "result": False,
                            "blocked": True,
                            "guardrail_name": e.guardrail_name,
                            "reason": e.reason,
                        }
                    },
                    "variables": {
                        _make_var_key("passed"): False,
                        _make_var_key("reason"): e.reason,
                    },
                }
            except Exception as e:
                log.exception(f"Guardrail execution error in node {node_id}: {e}")
                return {
                    "current_output": f"Guardrail error: {str(e)}",
                    "node_outputs": {node_id: {"result": False, "error": str(e)}},
                    "variables": {_make_var_key("passed"): False},
                }

        async def condition_node(state: FlowState) -> Dict[str, Any]:
            """Condition node - evaluates a condition."""
            s = StateAccessor(state)
            config = node_data.get("config", {})
            condition_type = config.get("conditionType", "contains")
            value = config.get("value", "")
            text = s.current_output or s.input_text or ""

            result = False
            if condition_type == "contains":
                result = value.lower() in text.lower()
            elif condition_type == "not_contains":
                result = value.lower() not in text.lower()
            elif condition_type == "equals":
                result = text.strip() == value.strip()
            elif condition_type == "starts_with":
                result = text.lower().startswith(value.lower())
            elif condition_type == "ends_with":
                result = text.lower().endswith(value.lower())
            elif condition_type == "regex":
                import re

                result = bool(re.search(value, text))

            return {
                "node_outputs": {node_id: {"result": result}},
                "variables": {_make_var_key("result"): result},
            }

        async def merge_node(state: FlowState) -> Dict[str, Any]:
            """Merge node - combines outputs from multiple upstream nodes."""
            s = StateAccessor(state)
            config = node_data.get("config", {})
            merge_type = config.get("mergeType", "concat")
            separator = config.get("separator", "\n\n")
            template_str = config.get("template", "")

            # Collect all node outputs
            all_outputs = s.node_outputs or {}
            variables = s.variables or {}

            # Get source keys to merge (if specified, else merge all)
            source_keys = config.get("sourceKeys", [])

            if merge_type == "template" and template_str:
                # Jinja2 template with access to all variables
                from jinja2 import Template

                template = Template(template_str)
                flat_vars = {}
                for k, v in variables.items():
                    safe_key = k.replace(".", "_").replace(" ", "_")
                    flat_vars[safe_key] = v
                result = template.render(
                    input=s.current_output or "",
                    variables=variables,
                    outputs=all_outputs,
                    **flat_vars,
                )
            elif merge_type == "json":
                # Merge as JSON object
                import json

                merged = {}
                for key in source_keys:
                    merged[key] = variables.get(key, "")
                if not source_keys:
                    # Auto-collect all non-system variables
                    for k, v in variables.items():
                        if not k.startswith("user_"):
                            merged[k] = v
                result = json.dumps(merged, ensure_ascii=False, indent=2)
            else:
                # Default: concat text outputs
                parts = []
                if source_keys:
                    for key in source_keys:
                        val = variables.get(key, "")
                        if val:
                            parts.append(
                                f"[{key}]\n{val}" if isinstance(val, str) else str(val)
                            )
                else:
                    # Auto-collect response variables
                    for k, v in sorted(variables.items()):
                        if (
                            k.endswith(".response")
                            or k.endswith(".result")
                            or k.endswith(".text")
                        ):
                            parts.append(
                                f"[{k}]\n{v}" if isinstance(v, str) else str(v)
                            )
                result = separator.join(parts) if parts else (s.current_output or "")

            log.info(
                f"[{node_id}] merge_node: type={merge_type}, result_len={len(result)}"
            )
            return {
                "current_output": result,
                "node_outputs": {node_id: {"text": result}},
                "variables": {_make_var_key("result"): result},
            }

        async def glossary_node(state: FlowState) -> Dict[str, Any]:
            """Glossary node - looks up terms from a glossary and enriches the input."""
            s = StateAccessor(state)
            resource_id = node_data.get("resourceId")

            if not resource_id:
                return {"error": f"No glossary configured for node {node_id}"}

            from open_webui.models.glossary import Glossaries
            from open_webui.models.users import Users
            from open_webui.utils.access_control import has_access

            glossary = Glossaries.get_glossary_by_id(resource_id)
            if not glossary:
                return {"error": f"Glossary not found: {resource_id}"}

            # Verify user has read access (knowledge_node/guardrail_node 패턴)
            flow_user_id = self.metadata.get("user_id", "")
            flow_user = Users.get_user_by_id(flow_user_id) if flow_user_id else None
            if not flow_user or (
                flow_user.role != "admin"
                and glossary.user_id != flow_user_id
                and not has_access(flow_user_id, "read", glossary.access_control)
            ):
                log.warning(
                    f"User {flow_user_id} blocked from glossary {resource_id} in flow node {node_id}"
                )
                return {"error": f"Access denied to glossary: {resource_id}"}

            text = s.current_output or s.input_text or ""
            entries = (glossary.data or {}).get("entries", [])

            if not entries:
                log.info(f"[{node_id}] Glossary '{glossary.name}' has no entries")
                return {
                    "node_outputs": {node_id: {"matched_terms": [], "text": text}},
                    "variables": {_make_var_key("matched"): []},
                }

            # Find matching terms in the input text
            matched_terms = []
            text_lower = text.lower()
            for entry in entries:
                term = entry.get("term", "")
                synonyms = entry.get("synonyms", [])
                definition = entry.get("definition") or entry.get("description", "")

                # Check term and synonyms
                all_forms = [term] + synonyms
                for form in all_forms:
                    if form and form.lower() in text_lower:
                        matched_terms.append(
                            {
                                "term": term,
                                "matched_form": form,
                                "definition": definition,
                            }
                        )
                        break

            # Build enriched output
            if matched_terms:
                term_lines = []
                for m in matched_terms:
                    term_lines.append(f"• {m['term']}: {m['definition']}")
                glossary_context = "\n".join(term_lines)
                enriched = f"{text}\n\n[용어 참조]\n{glossary_context}"
            else:
                enriched = text

            log.info(
                f"[{node_id}] glossary_node: matched {len(matched_terms)} terms from '{glossary.name}'"
            )
            return {
                "current_output": enriched,
                "node_outputs": {
                    node_id: {
                        "text": enriched,
                        "matched_terms": matched_terms,
                        "glossary_name": glossary.name,
                    }
                },
                "variables": {
                    _make_var_key("matched"): [m["term"] for m in matched_terms],
                    _make_var_key("context"): enriched,
                },
            }

        async def transform_node(state: FlowState) -> Dict[str, Any]:
            """Transform node - transforms data."""
            s = StateAccessor(state)
            config = node_data.get("config", {})
            template_str = config.get("template", "{{ input }}")

            try:
                from jinja2 import Template

                template = Template(template_str)
                # Make variables accessible both as variables["key"] and directly
                flat_vars = {}
                for k, v in (s.variables or {}).items():
                    # Convert "Node.key" to "Node_key" for Jinja2 compatibility
                    safe_key = k.replace(".", "_").replace(" ", "_")
                    flat_vars[safe_key] = v
                result = template.render(
                    input=s.current_output or s.input_text or "",
                    context=s.context or [],
                    documents=s.documents or [],
                    variables=s.variables or {},
                    **flat_vars,
                )
                return {
                    "current_output": result,
                    "node_outputs": {node_id: {"text": result}},
                    "variables": {_make_var_key("result"): result},
                }
            except Exception as e:
                log.warning(f"Error in transform template: {e}")
                return {"node_outputs": {node_id: {"text": s.current_output or ""}}}

        def _evaluate_route_condition(text: str, condition: dict) -> bool:
            """Evaluate a single route condition against text."""
            cond_type = condition.get("type", "contains")
            cond_value = condition.get("value", "")
            if not cond_value:
                return False
            if cond_type == "contains":
                return cond_value.lower() in text.lower()
            elif cond_type == "not_contains":
                return cond_value.lower() not in text.lower()
            elif cond_type == "equals":
                return text.strip() == cond_value.strip()
            elif cond_type == "starts_with":
                return text.lower().startswith(cond_value.lower())
            elif cond_type == "ends_with":
                return text.lower().endswith(cond_value.lower())
            elif cond_type == "regex":
                import re

                return bool(re.search(cond_value, text))
            return False

        async def router_node(state: FlowState) -> Dict[str, Any]:
            """Router node - N-way conditional routing."""
            s = StateAccessor(state)
            config = node_data.get("config", {})
            routes = config.get("routes", [])
            routing_type = config.get("routingType", "rule")
            source_field = config.get("sourceField", "")
            text = s.current_output or s.input_text or ""

            # Use source field from variables if specified
            if source_field:
                text = str(
                    (s.variables or {}).get(source_field, "")
                    or (s.node_outputs or {}).get(source_field, {}).get("text", "")
                    or text
                )

            if not routes:
                return {"error": f"No routes configured for router node {node_id}"}

            selected_route = None

            if routing_type == "llm":
                # LLM-based routing
                model_id = config.get("modelId")
                if not model_id:
                    model_id = self.api_config.get("model")
                if not model_id:
                    return {
                        "error": (
                            f"LLM router node {node_id} has no model configured — "
                            "set modelId in the node config or flow api_config"
                        )
                    }

                route_desc = "\n".join(
                    f"- {r.get('id')}: {r.get('label', r.get('id'))}" for r in routes
                )
                prompt = (
                    f"Select the most appropriate route for the given input.\n"
                    f"Available routes:\n{route_desc}\n\n"
                    f"Input: {text}\n\n"
                    f"Respond with ONLY the route id, nothing else."
                )
                try:
                    payload = {"model": model_id, "temperature": 0, "max_tokens": 50}
                    llm = self._create_llm(payload, stream=False)
                    result = await llm.ainvoke([HumanMessage(content=prompt)])
                    selected_id = result.content.strip()
                    matched = next(
                        (
                            r
                            for r in routes
                            if r.get("id") == selected_id
                            or r.get("label") == selected_id
                        ),
                        None,
                    )
                    if matched:
                        selected_route = matched.get("id")
                except Exception as e:
                    log.warning(f"LLM routing failed for node {node_id}: {e}")

            else:
                # Rule-based routing: evaluate conditions in order
                for route in routes:
                    condition = route.get("condition", {})
                    if condition and _evaluate_route_condition(text, condition):
                        selected_route = route.get("id")
                        break

            # Fallback to default route
            if not selected_route:
                default_route = config.get("defaultRoute")
                selected_route = default_route or routes[0].get("id")

            log.info(f"[{node_id}] Router selected route: {selected_route}")
            return {
                "node_outputs": {node_id: {"route": selected_route}},
                "variables": {_make_var_key("route"): selected_route},
            }

        # Map node types to functions
        node_type_map = {
            "input": input_node,
            "flowInput": input_node,  # Frontend uses flowInput
            "output": output_node,
            "flowOutput": output_node,  # Frontend uses flowOutput
            "agent": agent_node,  # Agent node - runs KBSphere/DBSphere agents
            "model": model_node,  # Model node - direct LLM call
            "knowledge": knowledge_node,
            "guardrail": guardrail_node,
            "condition": condition_node,
            "router": router_node,
            "merge": merge_node,
            "glossary": glossary_node,
            "transform": transform_node,
        }

        func = node_type_map.get(node_type)
        if func is None:
            raise ValueError(
                f"Unsupported node type: '{node_type}'. "
                f"Supported types: {', '.join(node_type_map.keys())}"
            )
        return self._wrap_node_function(node_id, node_type, func, node_data)

    async def run(
        self,
        *,
        request: Request,
        payload: Dict[str, Any],
        metadata: Dict[str, Any],
        user,
    ) -> StreamingResponse:
        """Execute the flow and return a streaming response."""
        self.event_emitter = get_event_emitter(metadata)
        self.event_call = get_event_call(metadata)

        # Initialize tracing
        try:
            from open_webui.utils.tracing import create_trace_context, get_trace_context

            self._trace_context = get_trace_context(request) if request else None
            if not self._trace_context:
                self._trace_context = create_trace_context(
                    user_id=user.id if user else "",
                    chat_id=metadata.get("chat_id"),
                    message_id=metadata.get("message_id"),
                )
        except Exception as e:
            log.warning(f"Tracing initialization failed: {e}")
            self._trace_context = None

        # Extract user message from payload
        messages = payload.get("messages", [])
        user_message = ""

        for msg in reversed(messages):
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, str):
                    user_message = content
                elif isinstance(content, list):
                    for item in content:
                        if isinstance(item, dict) and item.get("type") == "text":
                            user_message = item.get("text", "")
                            break
                        elif isinstance(item, str):
                            user_message = item
                            break
                break

        # Build and execute graph
        nodes, edges = self._get_nodes_and_edges()

        if not nodes:
            return self._error_response("Flow has no nodes")

        try:
            graph = self._build_graph(nodes, edges)
        except Exception as e:
            log.exception(f"Failed to build flow graph: {e}")
            return self._error_response(f"Failed to build flow: {str(e)}")

        # Initial state (current_output = user_message enables implicit input)
        initial_state = FlowState(
            input_text=user_message,
            current_output=user_message,
            variables={
                "user_id": user.id if user else None,
                "user_name": user.name if user else None,
            },
        )

        headers = {
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }

        return StreamingResponse(
            self._stream_execution(graph, initial_state),
            media_type="text/event-stream",
            headers=headers,
        )

    async def _stream_execution(
        self,
        graph: CompiledStateGraph,
        initial_state: FlowState,
    ) -> AsyncGenerator[str, None]:
        """Stream execution events as SSE with real-time node progress."""
        self._stream_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"

        # Start flow chain trace
        flow_name = self.flow_data.get("name", "agent_flow")
        node_count = len(self.flow_data.get("nodes", []))
        if self._trace_context and self._trace_context.enabled:
            self._chain_run = self._trace_context.begin_run(
                run_type="chain",
                name=f"agent_flow:{flow_name}",
                inputs={
                    "input_text": initial_state.get("input_text", "")[:500],
                    "node_count": node_count,
                },
            )

        try:
            await self.event_emitter(
                {
                    "type": "status",
                    "data": {
                        "description": "Executing flow...",
                        "done": False,
                    },
                }
            )

            # Execute graph with astream for real-time node progress
            log.info(
                f"Executing graph with initial state: input_text={initial_state.get('input_text')}"
            )
            final_state = initial_state
            prev_node_outputs = {}

            # Thread ID for checkpoint (unique per execution)
            config = {"configurable": {"thread_id": f"flow-{uuid.uuid4().hex[:8]}"}}

            async for state in graph.astream(
                initial_state, config=config, stream_mode="values"
            ):
                final_state = state
                # Detect which node just completed by comparing node_outputs
                current_outputs = state.get("node_outputs", {})
                for nid in current_outputs:
                    if nid not in prev_node_outputs:
                        node_result = current_outputs[nid]
                        has_error = (
                            node_result.get("error")
                            if isinstance(node_result, dict)
                            else False
                        )
                        status = "error" if has_error else "completed"
                        log.info(f"  Node '{nid}' {status}")
                        await self.event_emitter(
                            {
                                "type": "status",
                                "data": {
                                    "description": f"Node '{nid}' {status}",
                                    "done": False,
                                    "node_id": nid,
                                    "node_status": status,
                                },
                            }
                        )
                prev_node_outputs = dict(current_outputs)

            log.info(
                f"Graph execution complete. final_state keys: {list(final_state.keys())}"
            )
            log.info(
                f"  current_output: {final_state.get('current_output', '')[:100]}..."
            )
            log.info(f"  node_outputs: {final_state.get('node_outputs', {})}")

            error = final_state.get("error")
            if error:
                await self.event_emitter(
                    {
                        "type": "status",
                        "data": {
                            "description": "Error: {{detail}}",
                            "detail": str(error),
                            "done": True,
                        },
                    }
                )
                yield self._format_sse_chunk(f"Error: {error}")
                yield self._format_sse_done()
                self._end_node_trace(self._chain_run, error=str(error))
                return

            # Emit sources from agent nodes (KBSphere aggregated_sources format)
            node_outputs = final_state.get("node_outputs", {})
            for node_id, node_output in node_outputs.items():
                if not isinstance(node_output, dict):
                    continue

                # Handle sources from KBSphere/DBSphere agents
                # sources = {filename: {"source": {...}, "document": [...], "metadata": [...]}}
                sources = node_output.get("sources", {})
                if sources and isinstance(sources, dict):
                    for source_key, source_data in sources.items():
                        if isinstance(source_data, dict):
                            await self.event_emitter(
                                {"type": "source", "data": source_data}
                            )
                            log.info(f"Emitted source from {node_id}: {source_key}")

            # Also emit sources from documents (knowledge node format)
            documents = final_state.get("documents", [])
            for doc in documents:
                source_data = {
                    "source": {"name": doc.get("source", "Unknown")},
                    "document": [doc.get("content", "")],
                    "metadata": [doc.get("metadata", {})],
                }
                await self.event_emitter({"type": "source", "data": source_data})

            await self.event_emitter(
                {
                    "type": "status",
                    "data": {
                        "description": "Generating response...",
                        "done": False,
                    },
                }
            )

            # Check if output node already generated a response (actionType="response")
            output_generated = False
            for node_id, node_output in node_outputs.items():
                if isinstance(node_output, dict) and node_output.get("generated"):
                    output_generated = True
                    break

            # Check if we need to generate final answer (KBSphere agent with sources)
            has_agent_sources = False
            all_sources = {}
            for node_id, node_output in node_outputs.items():
                if isinstance(node_output, dict) and node_output.get("sources"):
                    has_agent_sources = True
                    all_sources.update(node_output.get("sources", {}))

            if output_generated:
                # Output node already generated response, just stream it
                final_output = final_state.get("current_output", "")
                if final_output:
                    chunk_size = 20
                    for i in range(0, len(final_output), chunk_size):
                        chunk = final_output[i : i + chunk_size]
                        yield self._format_sse_chunk(chunk)

                yield self._format_sse_done()

            elif has_agent_sources and all_sources:
                # Generate final answer using sources (like KBSphere's _run_stream)
                async for chunk in self._generate_final_answer(
                    initial_state, final_state, all_sources
                ):
                    yield chunk
            else:
                # Stream the final output directly
                final_output = final_state.get("current_output", "")
                if final_output:
                    chunk_size = 20
                    for i in range(0, len(final_output), chunk_size):
                        chunk = final_output[i : i + chunk_size]
                        yield self._format_sse_chunk(chunk)

                yield self._format_sse_done()

            # Complete flow chain trace (success)
            completed_nodes = list(final_state.get("node_outputs", {}).keys())
            self._end_node_trace(
                self._chain_run,
                outputs={
                    "completed_nodes": completed_nodes,
                    "output": (final_state.get("current_output") or "")[:500],
                },
            )

            await self.event_emitter(
                {
                    "type": "status",
                    "data": {
                        "description": "Generating final answer...",
                        "done": True,
                    },
                }
            )

        except Exception as e:
            log.exception(f"Error in flow execution: {e}")
            self._end_node_trace(self._chain_run, error=str(e))
            await self.event_emitter(
                {
                    "type": "status",
                    "data": {
                        "description": "Error: {{detail}}",
                        "detail": str(e),
                        "done": True,
                    },
                }
            )
            yield self._format_sse_chunk(f"Error executing flow: {str(e)}")
            yield self._format_sse_done()

    async def _generate_final_answer(
        self,
        initial_state: FlowState,
        final_state: Dict[str, Any],
        aggregated_sources: Dict[str, Any],
    ) -> AsyncGenerator[str, None]:
        """Generate final answer using sources, similar to KBSphere's _run_stream."""
        from extension_modules.react.prompts import get_final_answer_system_prompt

        # Build source context from aggregated_sources
        # aggregated_sources = {filename: {"source": {...}, "document": [...], "metadata": [...]}}
        source_lines: list[str] = []
        idx = 1

        for src in aggregated_sources.values():
            if not isinstance(src, dict):
                continue

            src_obj = src.get("source") or {}
            name = src_obj.get("name") or src_obj.get("id") or "N/A"

            docs = [
                d.strip()
                for d in src.get("document", [])
                if isinstance(d, str) and d.strip()
            ]
            if not docs:
                continue

            source_lines += [f"[{idx}] {name}", *[f"- {d}" for d in docs], ""]
            idx += 1

        source_ctx = "\n".join(source_lines).strip()
        user_question = initial_state.get("input_text", "")

        log.info(
            f"Generating final answer: user_question={user_question[:50]}..., sources_count={len(aggregated_sources)}"
        )

        # Get the base model from flow_data or use default
        model_id = None
        nodes = self.flow_data.get("nodes", [])
        for node in nodes:
            if node.get("type") in ("agent", "model"):
                resource_id = node.get("data", {}).get("resourceId")
                if resource_id:
                    from open_webui.models.models import Models

                    model = Models.get_model_by_id(resource_id)
                    if model and model.base_model_id:
                        model_id = model.base_model_id
                        break

        if not model_id:
            model_id = self.api_config.get("model")
        if not model_id:
            raise ValueError(
                "Final answer generator has no model configured — "
                "set a model on an upstream model node or flow api_config"
            )

        # Build messages for final answer (returns list of messages, not string)
        messages = get_final_answer_system_prompt(
            user_question=user_question,
            base_system_prompt=None,
            sources_context=source_ctx,
            language="",  # Auto-detect
            messages=[],
        )

        # Create payload for streaming
        payload = {
            "model": model_id,
            "temperature": 0.7,
            "max_tokens": 4096,
        }

        # Create LLM and stream response
        llm = self._create_llm(payload, stream=True)

        try:
            async for chunk in llm.astream(messages):
                if hasattr(chunk, "content") and chunk.content:
                    content = chunk.content
                    # Gemini/Vertex AI may return list of content blocks
                    if isinstance(content, list):
                        content = "".join(
                            block.get("text", "")
                            if isinstance(block, dict)
                            else str(block)
                            for block in content
                        )
                    if content:
                        yield self._format_sse_chunk(content)

            yield self._format_sse_done()
        except Exception as e:
            log.exception(f"Error generating final answer: {e}")
            yield self._format_sse_chunk(f"Error generating answer: {str(e)}")
            yield self._format_sse_done()

    def _format_sse_chunk(self, content: str) -> str:
        """Format content as OpenAI-compatible SSE chunk."""
        chunk_data = {
            "id": self._stream_id or f"chatcmpl-{uuid.uuid4().hex[:12]}",
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": "agent-flow",
            "choices": [
                {
                    "index": 0,
                    "delta": {"content": content},
                    "finish_reason": None,
                }
            ],
        }
        return f"data: {json.dumps(chunk_data)}\n\n"

    def _format_sse_done(self) -> str:
        """Format SSE done message."""
        done_data = {
            "id": self._stream_id or f"chatcmpl-{uuid.uuid4().hex[:12]}",
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": "agent-flow",
            "choices": [
                {
                    "index": 0,
                    "delta": {},
                    "finish_reason": "stop",
                }
            ],
        }
        return f"data: {json.dumps(done_data)}\n\ndata: [DONE]\n\n"

    def _error_response(self, error_message: str) -> StreamingResponse:
        """Return a streaming error response."""

        async def error_generator():
            yield self._format_sse_chunk(f"Error: {error_message}")
            yield self._format_sse_done()

        return StreamingResponse(
            error_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

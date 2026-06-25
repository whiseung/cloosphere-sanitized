"""
Trace Analysis 엔진.

트레이스 컨텍스트를 수집하고 LLM으로 분석 리포트를 생성합니다.
"""

import logging
import time
from typing import Any, Dict, List, Optional

from extension_modules.trace_analysis.prompts import (
    ANALYSIS_SYSTEM_PROMPT,
    ANALYSIS_USER_TEMPLATE,
)
from extension_modules.utils.llm import create_llm, get_model_config_from_app
from langchain_core.messages import HumanMessage, SystemMessage
from open_webui.env import DATA_DIR
from open_webui.models.trace_analysis import TraceAnalyses, TraceAnalysisUpdateForm
from open_webui.models.usage import Usages

logger = logging.getLogger(__name__)

REPORT_DIR = DATA_DIR / "report"


async def run_trace_analysis(
    app,
    analysis_id: str,
    trace_id: str,
    model_id: str,
    user_id: str,
    user_description: str,
) -> None:
    """
    트레이스 분석 실행 (백그라운드 태스크).

    1. status → running
    2. 컨텍스트 수집
    3. LLM 분석
    4. 리포트 저장
    5. status → completed | failed
    """
    try:
        # 1. status → running
        TraceAnalyses.update_analysis(
            analysis_id,
            TraceAnalysisUpdateForm(status="running"),
        )

        # 2. 컨텍스트 수집
        context = _collect_context(app, trace_id, user_id)

        # 3. 프롬프트 조립
        user_prompt = _build_prompt(context, user_description)

        # 4. LLM 호출
        model_config = get_model_config_from_app(app, model_id)
        if not model_config:
            raise ValueError(f"Model not found: {model_id}")

        llm = create_llm(
            model_config, json_mode=True, model_kwargs={"temperature": 0.2}
        )
        response = await llm.ainvoke(
            [
                SystemMessage(content=ANALYSIS_SYSTEM_PROMPT),
                HumanMessage(content=user_prompt),
            ]
        )
        report_text = response.content
        # content가 리스트(multi-part)로 올 수 있음 (예: Anthropic 모델)
        if isinstance(report_text, list):
            report_text = "\n".join(
                block.get("text", "") if isinstance(block, dict) else str(block)
                for block in report_text
            )

        # 4-1. Usage 로깅
        usage = getattr(response, "usage_metadata", None)
        _track_analysis_usage(
            user_id=user_id,
            model_id=model_id,
            analysis_id=analysis_id,
            usage=usage,
        )

        # 5. 파일 저장
        file_path = _save_report_to_file(trace_id, analysis_id, report_text)

        # 6. context_summary 생성
        context_summary = _build_context_summary(context, model_id)

        # 7. DB 업데이트 → completed
        TraceAnalyses.update_analysis(
            analysis_id,
            TraceAnalysisUpdateForm(
                status="completed",
                report=report_text,
                file_path=file_path,
                context_summary=context_summary,
            ),
        )
        logger.info(f"Trace analysis completed: {analysis_id}")

    except Exception as e:
        logger.exception(f"Trace analysis failed: {analysis_id}")
        TraceAnalyses.update_analysis(
            analysis_id,
            TraceAnalysisUpdateForm(
                status="failed",
                error_message=str(e),
            ),
        )


def _collect_context(
    app, trace_id: str, requester_user_id: Optional[str] = None
) -> Dict[str, Any]:
    """트레이스 관련 모든 컨텍스트 수집.

    requester_user_id: 분석을 요청한 사용자. agent 설정에 묶인 glossary/knowledge 등이
    분석자의 권한을 벗어나는 경우 reverse-lookup 노출 방지를 위해 필터링한다.
    """
    from open_webui.models.auto_evaluations import AutoEvaluations
    from open_webui.models.chats import Chats
    from open_webui.models.dbsphere import DbSpheres
    from open_webui.models.glossary import Glossaries
    from open_webui.models.guardrails import Guardrails
    from open_webui.models.knowledge import Knowledges
    from open_webui.models.message_trace import MessageTraces
    from open_webui.models.models import Models
    from open_webui.models.users import Users
    from open_webui.utils.access_control import has_access

    context: Dict[str, Any] = {}

    # 트레이스 트리
    trace_tree = MessageTraces.get_trace_tree(trace_id)
    context["trace_tree"] = trace_tree

    if not trace_tree:
        return context

    # 사용자 질의 추출
    context["user_query"] = _extract_user_query(trace_tree)

    # 도구 정보 추출 (Phase 1에서 사용 가능했던 도구)
    context["available_tools"] = _extract_available_tools(trace_tree)
    context["tool_calls_made"] = _extract_tool_calls(trace_tree)

    # 대화 이력
    chat_id = trace_tree.chat_id
    if chat_id:
        chat = Chats.get_chat_by_id(chat_id)
        if chat and chat.chat:
            messages = chat.chat.get("messages", [])
            context["chat_history"] = messages[-10:]  # 최근 10개
        else:
            context["chat_history"] = []
    else:
        context["chat_history"] = []

    # 에이전트 설정 (모델 정보에서)
    agent_model_id = _extract_model_id(trace_tree)
    agent_config_data = None
    if agent_model_id:
        try:
            model_info = Models.get_model_by_id(agent_model_id)
            if model_info:
                context["model_info"] = {
                    "id": model_info.id,
                    "name": model_info.name,
                    "base_model_id": model_info.base_model_id,
                }
                # AgentConfig 추출
                from open_webui.models.agent_config import AgentConfig

                if model_info.params and model_info.meta:
                    params = (
                        model_info.params
                        if isinstance(model_info.params, dict)
                        else model_info.params.model_dump()
                        if hasattr(model_info.params, "model_dump")
                        else {}
                    )
                    meta = (
                        model_info.meta
                        if isinstance(model_info.meta, dict)
                        else model_info.meta.model_dump()
                        if hasattr(model_info.meta, "model_dump")
                        else {}
                    )
                    agent_config_data = AgentConfig.from_model_info(
                        params=params,
                        meta=meta,
                        model_id=model_info.id,
                        base_model_id=model_info.base_model_id,
                    )
                    context["agent_config"] = agent_config_data
        except Exception as e:
            logger.warning(f"Failed to load agent config for {agent_model_id}: {e}")

    # 지식기반 설정
    knowledge_configs = []
    if agent_config_data and agent_config_data.has_knowledge():
        for kb_id in agent_config_data.get_knowledge_ids():
            kb = Knowledges.get_knowledge_by_id(kb_id)
            if kb:
                knowledge_configs.append(
                    {
                        "id": kb.id,
                        "name": kb.name,
                        "description": kb.description,
                    }
                )
    context["knowledge_configs"] = knowledge_configs

    # DB 설정
    dbsphere_configs = []
    if agent_config_data and agent_config_data.has_dbsphere():
        dbsphere_id = agent_config_data.get_first_dbsphere_id()
        if dbsphere_id:
            dbs = DbSpheres.get_dbsphere_by_id(dbsphere_id)
            if dbs:
                db_data = dbs.data or {}
                dbsphere_configs.append(
                    {
                        "id": dbs.id,
                        "name": dbs.name,
                        "description": dbs.description,
                        "db_type": db_data.get("type", ""),
                        "database": db_data.get("database", ""),
                        # 자격증명 제외
                    }
                )
    context["dbsphere_configs"] = dbsphere_configs

    # 용어집 — 분석 요청자 권한 기반 필터 (agent 설정에 타사용자 private glossary가 묶여 있을 수 있음).
    # requester_user_id가 None이면 fail-closed: 권한 확인 불가 → 컨텍스트에 포함하지 않음.
    glossary_configs = []
    if agent_config_data:
        glossary_ids = agent_config_data.get_glossary_ids()
        requester = (
            Users.get_user_by_id(requester_user_id) if requester_user_id else None
        )
        for g_id in glossary_ids:
            glossary = Glossaries.get_glossary_by_id(g_id)
            if not glossary:
                continue
            # admin / 소유자 / read access 중 하나여야 통과 (knowledge_node 패턴 정렬)
            if not requester or (
                requester.role != "admin"
                and glossary.user_id != requester_user_id
                and not has_access(requester_user_id, "read", glossary.access_control)
            ):
                logger.warning(
                    "Trace analysis: user %s blocked from glossary %s (reverse-lookup via agent config)",
                    requester_user_id,
                    g_id,
                )
                continue
            terms = (glossary.data or {}).get("terms", [])
            glossary_configs.append(
                {
                    "id": glossary.id,
                    "name": glossary.name,
                    "term_count": len(terms),
                    "sample_terms": terms[:10],
                }
            )
    context["glossary_configs"] = glossary_configs

    # 가드레일 설정
    guardrail_configs = []
    if agent_config_data:
        guardrail_ids = getattr(agent_config_data, "guardrail_ids", []) or []
        for gr_id in guardrail_ids:
            gr = Guardrails.get_guardrail_by_id(gr_id)
            if gr:
                guardrail_configs.append(
                    {
                        "id": gr.id,
                        "name": gr.name,
                        "description": gr.description,
                        "pii_types": gr.pii_types,
                        "pii_strategy": gr.pii_strategy,
                        "blocked_words": gr.blocked_words[:20],  # 20개 한도
                        "apply_to_input": gr.apply_to_input,
                        "apply_to_output": gr.apply_to_output,
                        "llm_judge_enabled": gr.llm_judge_enabled,
                    }
                )
    context["guardrail_configs"] = guardrail_configs

    # 자동 평가 결과
    message_id = trace_tree.message_id
    evaluations = []
    if message_id:
        try:
            evals = AutoEvaluations.get_auto_evaluations_by_message_id(message_id)
            for ev in evals:
                evaluations.append(
                    {
                        "type": ev.evaluation_type,
                        "score": ev.score,
                        "reasoning": ev.reasoning,
                        "status": ev.status,
                    }
                )
        except Exception as e:
            logger.warning(f"Failed to load evaluations: {e}")
    context["evaluations"] = evaluations

    return context


def _build_prompt(context: Dict[str, Any], user_description: str) -> str:
    """컨텍스트로 사용자 프롬프트 조립."""
    trace_tree = context.get("trace_tree")

    return ANALYSIS_USER_TEMPLATE.format(
        user_description=user_description or "(No description provided)",
        user_query=context.get("user_query", "(Unable to extract)"),
        trace_tree=_format_trace_tree(trace_tree) if trace_tree else "(No trace data)",
        available_tools=_format_available_tools(context),
        agent_config=_format_agent_config(context),
        chat_history=_format_chat_history(context.get("chat_history", [])),
        knowledge_config=_format_knowledge_config(context.get("knowledge_configs", [])),
        dbsphere_config=_format_dbsphere_config(context.get("dbsphere_configs", [])),
        glossary_config=_format_glossaries(context.get("glossary_configs", [])),
        guardrail_config=_format_guardrails(context.get("guardrail_configs", [])),
        evaluation_results=_format_evaluations(context.get("evaluations", [])),
    )


def _build_context_summary(context: Dict[str, Any], analysis_model_id: str) -> dict:
    """컨텍스트 요약 정보 생성."""
    trace_tree = context.get("trace_tree")
    model_info = context.get("model_info", {})
    runs = _flatten_runs(trace_tree.runs) if trace_tree else []

    return {
        "agent_name": model_info.get("name"),
        "model_id": model_info.get("base_model_id") or model_info.get("id"),
        "run_count": len(runs),
        "error_count": sum(1 for r in runs if r.status == "error"),
        "has_knowledge": bool(context.get("knowledge_configs")),
        "has_dbsphere": bool(context.get("dbsphere_configs")),
        "has_guardrails": bool(context.get("guardrail_configs")),
        "has_glossary": bool(context.get("glossary_configs")),
        "analysis_model": analysis_model_id,
    }


# ── Usage Tracking ──


def _track_analysis_usage(
    user_id: str,
    model_id: str,
    analysis_id: str,
    usage: Optional[dict],
) -> None:
    """트레이스 분석 LLM 호출의 토큰 사용량 기록."""
    if not user_id:
        return
    try:
        total_tokens = usage.get("total_tokens") if usage else None
        Usages.insert_new_usage(
            user_id=user_id,
            chat_id=None,
            model_id=model_id,
            message_id=f"trace_analysis:{analysis_id}",
            message_type="trace_analysis",
            total_tokens=total_tokens or 0,
            usage=usage,
        )
    except Exception as e:
        logger.debug(f"Failed to track trace analysis usage: {e}")


# ── Format Helpers ──


def _format_trace_tree(trace_tree) -> str:
    """트레이스 트리를 텍스트로 포맷."""
    lines = [
        f"Trace ID: {trace_tree.trace_id}",
        f"Status: {trace_tree.status}",
        f"Total Latency: {trace_tree.total_latency_ms}ms"
        if trace_tree.total_latency_ms
        else "Total Latency: N/A",
        f"Total Tokens: {trace_tree.total_tokens}"
        if trace_tree.total_tokens
        else "Total Tokens: N/A",
        "",
    ]
    for run in trace_tree.runs:
        lines.extend(_format_run(run, depth=0))
    return "\n".join(lines)


def _format_run(run, depth: int) -> List[str]:
    """단일 Run을 재귀적으로 포맷. 주요 필드를 구조화하여 표시."""
    indent = "  " * depth
    model_info = f", model={run.model_id}" if run.model_id else ""
    token_info = ""
    if run.token_usage:
        total = run.token_usage.get("total_tokens", 0)
        token_info = f", tokens={total}"

    lines = [
        f"{indent}[{run.run_type.upper()}] {run.name} "
        f"(status={run.status}, latency={run.latency_ms}ms{model_info}{token_info})",
    ]

    if run.inputs:
        # 주요 필드를 구조화하여 표시 (단순 str() 대신)
        lines.extend(_format_run_data(run.inputs, "Inputs", indent, is_inputs=True))

    if run.outputs:
        lines.extend(_format_run_data(run.outputs, "Outputs", indent, is_inputs=False))

    if run.error:
        lines.append(f"{indent}  Error: {run.error}")

    if run.children:
        for child in run.children:
            lines.extend(_format_run(child, depth + 1))
    return lines


def _format_run_data(data: dict, label: str, indent: str, is_inputs: bool) -> List[str]:
    """Run의 inputs/outputs 데이터를 구조화하여 포맷."""
    lines = []

    # tool_descriptions는 별도 섹션에서 처리하므로 제외
    display_data = {k: v for k, v in data.items() if k != "tool_descriptions"}

    # 주요 필드 개별 표시
    key_fields = [
        "user_message",
        "system_prompt",
        "normalized_question",
        "has_tool_calls",
        "response",
        "answerable",
        "language",
        "passed",
        "reason",
        "score",
        "reasoning",
        "active_capabilities",
    ]
    shown_keys = set()

    for key in key_fields:
        if key in display_data:
            value = display_data[key]
            if isinstance(value, str) and len(value) > 1000:
                value = value[:1000] + "...(truncated)"
            elif isinstance(value, str) and len(value) > 200:
                # system_prompt 등은 여유 있게 표시
                pass
            lines.append(f"{indent}  {label}.{key}: {value}")
            shown_keys.add(key)

    # 나머지 필드
    remaining = {k: v for k, v in display_data.items() if k not in shown_keys}
    if remaining:
        remaining_str = str(remaining)
        if len(remaining_str) > 500:
            remaining_str = remaining_str[:500] + "...(truncated)"
        lines.append(f"{indent}  {label} (other): {remaining_str}")

    return lines


def _format_available_tools(context: Dict[str, Any]) -> str:
    """Phase 1에서 사용 가능했던 도구 목록과 설명을 포맷."""
    available_tools = context.get("available_tools", {})
    tool_calls = context.get("tool_calls_made", [])

    if not available_tools:
        return "(No tools were available in Phase 1 — this may be a direct LLM call without UnifiedAgent)"

    lines = ["Available tools in react_agent Phase 1:"]
    for tool_name, description in available_tools.items():
        called = (
            "CALLED"
            if tool_name in [tc.get("name") for tc in tool_calls]
            else "NOT CALLED"
        )
        # 도구 설명은 충분히 표시 (1500자 한도)
        desc_str = str(description)
        if len(desc_str) > 1500:
            desc_str = desc_str[:1500] + "...(truncated)"
        lines.append(f"\n- **{tool_name}** [{called}]:")
        lines.append(f"  {desc_str}")

    if tool_calls:
        lines.append(f"\nActual tool calls made: {len(tool_calls)}")
        for tc in tool_calls:
            lines.append(f"  - {tc.get('name', 'unknown')}: {tc.get('summary', '')}")
    else:
        lines.append("\nNo tool calls were made (has_tool_calls: false)")

    return "\n".join(lines)


def _format_agent_config(context: Dict[str, Any]) -> str:
    """에이전트 설정 포맷."""
    model_info = context.get("model_info")
    agent_config = context.get("agent_config")

    if not model_info:
        return "(No agent configuration available)"

    lines = [
        f"Agent: {model_info.get('name', 'Unknown')} (id={model_info.get('id', '')})",
        f"Base Model: {model_info.get('base_model_id', 'N/A')}",
    ]

    if agent_config:
        if agent_config.has_knowledge():
            lines.append(f"Knowledge Bases: {agent_config.get_knowledge_ids()}")
        if agent_config.has_dbsphere():
            lines.append(f"DbSphere: {agent_config.get_first_dbsphere_id()}")
        guardrail_ids = getattr(agent_config, "guardrail_ids", [])
        if guardrail_ids:
            lines.append(f"Guardrails: {guardrail_ids}")
        glossaries = getattr(agent_config, "glossaries", [])
        if glossaries:
            lines.append(f"Glossaries: {glossaries}")

        # Capabilities
        capabilities = []
        if hasattr(agent_config, "has_web_search") and agent_config.has_web_search():
            capabilities.append("web_search")
        if (
            hasattr(agent_config, "has_image_generation")
            and agent_config.has_image_generation()
        ):
            capabilities.append("image_generation")
        if capabilities:
            lines.append(f"Capabilities: {capabilities}")

        # System/format prompts (Phase 1 task prompt & Phase 2 format prompt)
        system_prompt = getattr(agent_config, "system_prompt", None)
        if system_prompt:
            if len(system_prompt) > 800:
                system_prompt = system_prompt[:800] + "...(truncated)"
            lines.append(f"Task Prompt (Phase 1): {system_prompt}")

        format_prompt = getattr(agent_config, "format_prompt", None)
        if format_prompt:
            if len(format_prompt) > 800:
                format_prompt = format_prompt[:800] + "...(truncated)"
            lines.append(f"Format Prompt (Phase 2): {format_prompt}")

    return "\n".join(lines)


def _format_chat_history(messages: list) -> str:
    """대화 이력 포맷."""
    if not messages:
        return "(No conversation history)"

    lines = []
    for msg in messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")

        # 멀티모달 content 처리
        if isinstance(content, list):
            text_parts = [
                p.get("text", "")
                for p in content
                if isinstance(p, dict) and p.get("type") == "text"
            ]
            content = " ".join(text_parts)

        if isinstance(content, str) and len(content) > 500:
            content = content[:500] + "...(truncated)"
        elif not isinstance(content, str):
            content = str(content)[:500]

        lines.append(f"[{role}] {content}")

    return "\n".join(lines)


def _format_knowledge_config(configs: list) -> str:
    """지식기반 설정 포맷."""
    if not configs:
        return "(No knowledge bases configured)"

    lines = []
    for kb in configs:
        lines.append(f"- {kb['name']} (id={kb['id']}): {kb.get('description', '')}")
    return "\n".join(lines)


def _format_dbsphere_config(configs: list) -> str:
    """DB 설정 포맷."""
    if not configs:
        return "(No database configured)"

    lines = []
    for db in configs:
        lines.append(
            f"- {db['name']} (id={db['id']}): type={db.get('db_type', '')}, "
            f"database={db.get('database', '')}"
        )
    return "\n".join(lines)


def _format_glossaries(configs: list) -> str:
    """용어집 포맷."""
    if not configs:
        return "(No glossaries configured)"

    lines = []
    for g in configs:
        lines.append(f"- {g['name']} (id={g['id']}): {g['term_count']} terms")
        if g.get("sample_terms"):
            for term in g["sample_terms"]:
                term_name = (
                    term.get("term", term.get("name", ""))
                    if isinstance(term, dict)
                    else str(term)
                )
                term_def = (
                    term.get("definition", term.get("description", ""))
                    if isinstance(term, dict)
                    else ""
                )
                lines.append(f"  - {term_name}: {term_def}")
    return "\n".join(lines)


def _format_guardrails(configs: list) -> str:
    """가드레일 설정 포맷."""
    if not configs:
        return "(No guardrails configured)"

    lines = []
    for gr in configs:
        lines.append(f"- {gr['name']} (id={gr['id']})")
        if gr.get("description"):
            lines.append(f"  Description: {gr['description']}")
        lines.append(
            f"  Apply: input={gr.get('apply_to_input')}, output={gr.get('apply_to_output')}"
        )
        if gr.get("pii_types"):
            lines.append(
                f"  PII Types: {gr['pii_types']} (strategy={gr.get('pii_strategy')})"
            )
        if gr.get("blocked_words"):
            lines.append(f"  Blocked Words (sample): {gr['blocked_words']}")
        if gr.get("llm_judge_enabled"):
            lines.append("  LLM Judge: enabled")
    return "\n".join(lines)


def _format_evaluations(evaluations: list) -> str:
    """자동 평가 결과 포맷."""
    if not evaluations:
        return "(No auto-evaluation results)"

    lines = []
    for ev in evaluations:
        score = ev.get("score")
        score_str = f"{score:.2f}" if score is not None else "N/A"
        lines.append(
            f"- {ev.get('type', 'unknown')}: score={score_str}, "
            f"status={ev.get('status', '')}"
        )
        if ev.get("reasoning"):
            reasoning = ev["reasoning"]
            if len(reasoning) > 500:
                reasoning = reasoning[:500] + "...(truncated)"
            lines.append(f"  Reasoning: {reasoning}")
    return "\n".join(lines)


# ── Extract Helpers ──


def _extract_user_query(trace_tree) -> str:
    """트레이스 트리에서 사용자 질의 추출."""
    if not trace_tree or not trace_tree.runs:
        return "(Unable to extract)"

    # 모든 run을 평탄화하여 검색
    runs = _flatten_runs(trace_tree.runs)

    # react_agent 또는 첫 chain/llm run에서 user_message 추출
    for run in runs:
        inputs = run.inputs or {}
        if inputs.get("user_message"):
            return inputs["user_message"]

    # messages 배열에서 마지막 user 메시지
    for run in runs:
        inputs = run.inputs or {}
        messages = inputs.get("messages", [])
        if isinstance(messages, list):
            for msg in reversed(messages):
                if isinstance(msg, dict) and msg.get("role") == "user":
                    content = msg.get("content", "")
                    if isinstance(content, list):
                        text_parts = [
                            p.get("text", "")
                            for p in content
                            if isinstance(p, dict) and p.get("type") == "text"
                        ]
                        return " ".join(text_parts)
                    return str(content)

    return "(Unable to extract)"


def _extract_available_tools(trace_tree) -> Dict[str, str]:
    """트레이스에서 Phase 1 react_agent에 제공된 도구 목록 추출."""
    if not trace_tree or not trace_tree.runs:
        return {}

    runs = _flatten_runs(trace_tree.runs)

    for run in runs:
        inputs = run.inputs or {}
        # react_agent의 LLM run에 tool_descriptions가 있음
        tool_descriptions = inputs.get("tool_descriptions")
        if tool_descriptions and isinstance(tool_descriptions, dict):
            return tool_descriptions

    return {}


def _extract_tool_calls(trace_tree) -> List[Dict[str, str]]:
    """트레이스에서 실제 호출된 도구 정보 추출."""
    if not trace_tree or not trace_tree.runs:
        return []

    tool_calls = []
    runs = _flatten_runs(trace_tree.runs)

    for run in runs:
        if run.run_type == "tool":
            summary = ""
            if run.outputs:
                output_str = str(run.outputs)
                summary = output_str[:200] if len(output_str) > 200 else output_str
            tool_calls.append(
                {
                    "name": run.name,
                    "status": run.status,
                    "summary": summary,
                }
            )

    return tool_calls


def _extract_model_id(trace_tree) -> Optional[str]:
    """트레이스 트리에서 에이전트 모델 ID 추출 (커스텀 agent 모델)."""
    if not trace_tree or not trace_tree.runs:
        return None

    runs = _flatten_runs(trace_tree.runs)

    # react_agent chain run에서 모델 정보 추출
    for run in runs:
        if run.run_type == "chain" and run.name == "react_agent":
            meta = run.meta or {}
            if meta.get("model_id"):
                return meta["model_id"]
            # inputs에서 model_id 추출
            inputs = run.inputs or {}
            if inputs.get("model_id"):
                return inputs["model_id"]

    # root run의 model_id 또는 meta에서
    root = trace_tree.runs[0]
    if root.model_id:
        return root.model_id

    meta = root.meta or {}
    if meta.get("model_id"):
        return meta["model_id"]

    # final_answer LLM run에서 (Phase 2 모델이지만 에이전트 ID 힌트가 될 수 있음)
    for run in runs:
        if run.run_type == "llm" and run.name == "final_answer":
            # final_answer의 inputs에서 active_capabilities 확인
            inputs = run.inputs or {}
            capabilities = inputs.get("active_capabilities", [])
            if capabilities:
                # 에이전트가 활성화된 경우 → 에이전트 모델 ID 필요
                pass

    # 첫 non-task LLM run에서
    for run in runs:
        if run.run_type == "llm" and run.model_id:
            meta = run.meta or {}
            task = meta.get("task")
            if not task:  # task가 없는 LLM run = 메인 처리
                return run.model_id

    return None


def _flatten_runs(runs) -> list:
    """중첩 Run 트리를 평탄화."""
    result = []
    for run in runs:
        result.append(run)
        if hasattr(run, "children") and run.children:
            result.extend(_flatten_runs(run.children))
    return result


def _save_report_to_file(
    trace_id: str, analysis_id: str, report_text: str
) -> Optional[str]:
    """리포트를 파일로 저장."""
    try:
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = int(time.time())
        filename = f"trace_analysis_{trace_id[:8]}_{timestamp}.md"
        file_path = REPORT_DIR / filename
        file_path.write_text(report_text, encoding="utf-8")
        return str(file_path)
    except Exception as e:
        logger.warning(f"Failed to save report file: {e}")
        return None

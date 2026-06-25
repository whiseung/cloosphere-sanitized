"""
Auto-evaluation evaluator module.

Runs Judge LLM to evaluate agent responses on retrieval, faithfulness, and quality.
"""

import json
import logging
import re
import uuid
from typing import Any, Dict, List, Optional

from extension_modules.utils.llm import create_llm, get_model_config_from_app
from langchain_core.messages import HumanMessage, SystemMessage
from open_webui.models.auto_evaluations import (
    AutoEvaluations,
    AutoEvaluationUpdateForm,
)
from open_webui.models.message_trace import (
    MessageTraceCreateForm,
    MessageTraces,
    RunStatus,
    RunType,
)
from open_webui.models.usage import Usages

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Evaluation Prompts
# ---------------------------------------------------------------------------

RETRIEVAL_SYSTEM_PROMPT = """You are an expert evaluator assessing the quality of retrieved documents for a given query.

IMPORTANT CONTEXT: This is an enterprise RAG (Retrieval-Augmented Generation) system.
- The retrieved documents are from the user's organization's internal knowledge base.
- The user is an authenticated employee querying their own organization's documents.
- The assistant is EXPECTED to answer based on these retrieved documents as authoritative sources.
- Do NOT penalize for using organization-specific documents — that is the system's intended behavior.

Evaluate how well the retrieved contexts match the user's query. Consider:
- **Relevance**: Are the retrieved documents relevant to the query?
- **Coverage**: Do the documents contain enough information to answer the query?
- **Noise ratio**: How much irrelevant content is in the retrieved set?

Respond in JSON format:
{
  "score": <float 0.0-1.0>,
  "reasoning": "<brief explanation>",
  "details": {
    "relevance": <float 0.0-1.0>,
    "coverage": <float 0.0-1.0>,
    "noise_ratio": <float 0.0-1.0>
  }
}

Score guidelines:
- 0.9-1.0: Highly relevant, comprehensive coverage, minimal noise
- 0.7-0.8: Mostly relevant, good coverage, some noise
- 0.5-0.6: Partially relevant, moderate coverage
- 0.3-0.4: Low relevance, poor coverage, high noise
- 0.0-0.2: Irrelevant or empty contexts"""

RETRIEVAL_USER_TEMPLATE = """## User Query
{query}

## Retrieved Contexts
{contexts}

Evaluate the retrieval quality and respond in JSON format."""

FAITHFULNESS_SYSTEM_PROMPT = """You are an expert evaluator assessing whether an assistant's response is faithful to the provided contexts.

IMPORTANT CONTEXT: This is an enterprise RAG (Retrieval-Augmented Generation) system.
- The retrieved documents are from the user's organization's internal knowledge base.
- The assistant is designed to answer based on these retrieved documents as authoritative sources.
- Citing specific document names, regulations, or internal policies from the retrieved contexts is CORRECT behavior.
- Do NOT penalize for referencing organization-specific information that appears in the contexts.

WIDGET RENDERING NOTE:
- `[[dbsphere:chart]]` followed by a JSON code block means an interactive chart was rendered in the frontend UI for the user.
- Treat the presence of `[[dbsphere:chart]]` as a fully rendered visualization — do NOT penalize for this marker.

Evaluate how well the response is grounded in the retrieved contexts. Consider:
- **Grounded claims**: Statements in the response that are supported by the contexts
- **Ungrounded claims**: Statements that are NOT supported by any context
- **Contradictions**: Statements that contradict the contexts

Respond in JSON format:
{
  "score": <float 0.0-1.0>,
  "reasoning": "<brief explanation>",
  "details": {
    "grounded_claims": <int>,
    "ungrounded_claims": <int>,
    "contradictions": <int>
  }
}

Score guidelines:
- 0.9-1.0: All claims grounded, no contradictions
- 0.7-0.8: Most claims grounded, minor ungrounded claims
- 0.5-0.6: Mix of grounded and ungrounded claims
- 0.3-0.4: Many ungrounded claims or some contradictions
- 0.0-0.2: Mostly ungrounded or contradicts contexts"""

FAITHFULNESS_USER_TEMPLATE = """## User Query
{query}

## Retrieved Contexts
{contexts}

## Assistant Response
{response}

Evaluate the faithfulness of the response to the contexts and respond in JSON format."""

QUALITY_SYSTEM_PROMPT = """You are an expert evaluator assessing the overall quality of an assistant's response.

IMPORTANT CONTEXT: This is an enterprise RAG (Retrieval-Augmented Generation) system.
- The assistant answers questions using the user's organization's internal knowledge base.
- The user is an authenticated employee — the assistant does NOT need to ask "which company?" or verify identity.
- Answering directly based on the organization's documents is the INTENDED behavior, not an error.
- Evaluate the response purely on how well it answers the query using the available knowledge.

WIDGET RENDERING NOTE:
- `[[dbsphere:chart]]` followed by a JSON code block means an interactive chart (table, pie chart, bar chart, etc.) was rendered in the frontend UI for the user.
- Treat the presence of `[[dbsphere:chart]]` as a fully rendered visualization that the user saw — do NOT penalize for this marker or consider it "missing" output.
- The JSON inside the block contains the actual data (columns, rows) used to render the chart.

Evaluate the response quality considering:
- **Helpfulness**: Does the response address the user's query?
- **Accuracy**: Is the information correct and precise?
- **Completeness**: Does the response cover all aspects of the query?
- **Clarity**: Is the response clear and well-structured?

Respond in JSON format:
{
  "score": <float 0.0-1.0>,
  "reasoning": "<brief explanation>",
  "details": {
    "helpfulness": <float 0.0-1.0>,
    "accuracy": <float 0.0-1.0>,
    "completeness": <float 0.0-1.0>,
    "clarity": <float 0.0-1.0>
  }
}

Score guidelines:
- 0.9-1.0: Excellent on all dimensions
- 0.7-0.8: Good quality with minor issues
- 0.5-0.6: Acceptable but with notable gaps
- 0.3-0.4: Below average, significant issues
- 0.0-0.2: Poor quality, fails to address the query"""

QUALITY_USER_TEMPLATE = """## User Query
{query}

## Assistant Response
{response}

Evaluate the overall response quality and respond in JSON format."""

EVAL_PROMPTS = {
    "retrieval": {
        "system": RETRIEVAL_SYSTEM_PROMPT,
        "user": RETRIEVAL_USER_TEMPLATE,
        "requires_contexts": True,
        # 검색 품질 metric — chat_upload(사용자 ad-hoc 업로드)은 검색이 아니므로 제외 (PR6).
        "context_scope": "retrieval",
    },
    "faithfulness": {
        "system": FAITHFULNESS_SYSTEM_PROMPT,
        "user": FAITHFULNESS_USER_TEMPLATE,
        "requires_contexts": True,
        # 충실성 metric — 업로드 파일도 출처 자료라 전체 포함 (file-기반 주장 오penalty 방지) (PR6).
        "context_scope": "all",
    },
    "quality": {
        "system": QUALITY_SYSTEM_PROMPT,
        "user": QUALITY_USER_TEMPLATE,
        "requires_contexts": False,
        "context_scope": None,
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# chat_upload(사용자가 대화 중 올린 ad-hoc 파일)은 agent 의 retrieval 이 아니므로
# 검색 품질(retrieval) metric 에서 제외한다. 그 외(KB/web/KG/legacy unknown)는 모두
# retrieval 로 취급 — backward-safe.
_NON_RETRIEVAL_SOURCE_TYPES = {"chat_upload"}


def source_type_of(ctx: Dict[str, Any]) -> str:
    """source dict 의 provenance source_type 추출 (PR1 stamp).

    source 구조: {"source": {...}, "document": [...], "metadata": [meta]}.
    분류 규칙은 `_bundle_sources_by_provenance`(react_base.py) 와 동일 —
    metadata[0].source_type → source.type → "unknown" 순 (drift 방지). 단 malformed
    입력(metadata 가 list 아님·source 가 dict 아님)엔 isinstance 가드로 더 방어적
    (참조는 metadata=int 시 TypeError, 여기선 "unknown" 으로 수렴).
    """
    if not isinstance(ctx, dict):
        return "unknown"
    meta_list = ctx.get("metadata")
    meta0 = (
        meta_list[0]
        if isinstance(meta_list, list) and meta_list and isinstance(meta_list[0], dict)
        else {}
    )
    src_obj = ctx.get("source") if isinstance(ctx.get("source"), dict) else {}
    return meta0.get("source_type") or src_obj.get("type") or "unknown"


def select_eval_contexts(
    eval_type: str, retrieved_contexts: Optional[List[Dict[str, Any]]]
) -> Optional[List[Dict[str, Any]]]:
    """metric 의 context_scope 에 따라 평가에 쓸 context 부분집합을 반환한다 (PR6).

    - "retrieval"(검색 품질): chat_upload 제외 — 업로드는 검색이 아님.
    - "all"(faithfulness): 전체 — 업로드 파일도 출처 자료라 충실성 평가에 포함.
    - None(quality 등): context 미사용 → None.

    backward-safe: chat_upload 만 제외하므로 legacy/unknown 소스는 retrieval 로 유지.
    """
    scope = (EVAL_PROMPTS.get(eval_type) or {}).get("context_scope")
    if scope is None:
        return None
    ctxs = retrieved_contexts or []
    if scope == "all":
        return list(ctxs)
    # scope == "retrieval"
    return [c for c in ctxs if source_type_of(c) not in _NON_RETRIEVAL_SOURCE_TYPES]


def _format_contexts(contexts: List[Dict[str, Any]]) -> str:
    """Format retrieved source dicts into a readable string for the Judge prompt."""
    if not contexts:
        return "(no contexts)"

    parts: list[str] = []
    for i, ctx in enumerate(contexts, 1):
        # aggregated_sources value format: {"source": {...}, "document": [...]}
        source_obj = ctx.get("source") or {}
        name = source_obj.get("name") or source_obj.get("id") or f"Context {i}"
        docs = ctx.get("document", [])

        text = "\n".join(d.strip() for d in docs if isinstance(d, str) and d.strip())
        if not text:
            text = "(empty)"

        parts.append(f"### Context {i}: {name}\n{text}")

    return "\n\n".join(parts)


def _parse_judge_response(raw: str) -> Dict[str, Any]:
    """Parse Judge LLM JSON response, handling markdown code blocks."""
    text = raw.strip()

    # Strip markdown code block wrappers (```json ... ``` or ``` ... ```)
    match = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    if match:
        text = match.group(1).strip()

    return json.loads(text)


# ---------------------------------------------------------------------------
# Main evaluation runner
# ---------------------------------------------------------------------------


async def run_single_evaluation(
    app,
    eval_id: str,
    eval_type: str,
    judge_model_id: str,
    user_query: str,
    assistant_response: str,
    retrieved_contexts: Optional[List[Dict[str, Any]]] = None,
    user_id: Optional[str] = None,
    chat_id: Optional[str] = None,
    message_id: Optional[str] = None,
    trace_id: Optional[str] = None,
) -> None:
    """
    Run a single evaluation: call Judge LLM → parse → update DB record.

    This function is designed to be called as a fire-and-forget background task.
    All errors are caught and recorded in the DB as status='failed'.
    """
    trace_run_id = None

    try:
        prompt_config = EVAL_PROMPTS.get(eval_type)
        if not prompt_config:
            AutoEvaluations.update_auto_evaluation_by_id(
                eval_id,
                AutoEvaluationUpdateForm(
                    status="failed",
                    error_message=f"Unknown evaluation type: {eval_type}",
                ),
            )
            return

        # Build prompts
        context_str = _format_contexts(retrieved_contexts or [])
        user_prompt = prompt_config["user"].format(
            query=user_query,
            response=assistant_response,
            contexts=context_str,
        )

        # Start trace (uses shared trace_id from agent if available)
        trace_run_id = _start_eval_trace(
            eval_type=eval_type,
            eval_id=eval_id,
            model_id=judge_model_id,
            user_id=user_id,
            chat_id=chat_id,
            message_id=message_id,
            trace_id=trace_id,
            inputs={"query_length": len(user_query), "eval_type": eval_type},
        )

        # Call Judge LLM
        model_config = get_model_config_from_app(app, judge_model_id)
        if not model_config:
            raise ValueError(f"Judge model not found: {judge_model_id}")
        llm = create_llm(model_config, json_mode=True, temperature=0)
        response = await llm.ainvoke(
            [
                SystemMessage(content=prompt_config["system"]),
                HumanMessage(content=user_prompt),
            ]
        )

        raw_content = (
            response.content if hasattr(response, "content") else str(response)
        )
        # Handle list-of-blocks format (e.g. [{'type': 'text', 'text': '...'}])
        if isinstance(raw_content, list):
            raw_text = "\n".join(
                block.get("text", "") if isinstance(block, dict) else str(block)
                for block in raw_content
            )
        else:
            raw_text = str(raw_content)
        usage = getattr(response, "usage_metadata", None)

        # Track usage
        _track_eval_usage(
            user_id=user_id,
            chat_id=chat_id,
            message_id=message_id,
            model_id=judge_model_id,
            usage=usage,
            eval_type=eval_type,
        )

        # Parse response
        try:
            parsed = _parse_judge_response(raw_text)
        except (json.JSONDecodeError, ValueError) as parse_err:
            AutoEvaluations.update_auto_evaluation_by_id(
                eval_id,
                AutoEvaluationUpdateForm(
                    status="failed",
                    error_message=f"Failed to parse judge response: {parse_err}",
                    details={"raw_response": raw_text[:2000]},
                ),
            )
            _complete_eval_trace(
                trace_run_id,
                outputs={"error": f"Parse error: {parse_err}"},
                token_usage=usage,
            )
            return

        score = parsed.get("score")
        if score is not None:
            score = max(0.0, min(1.0, float(score)))

        AutoEvaluations.update_auto_evaluation_by_id(
            eval_id,
            AutoEvaluationUpdateForm(
                score=score,
                reasoning=parsed.get("reasoning", ""),
                details=parsed.get("details"),
                status="completed",
            ),
        )
        logger.info(
            f"[AutoEval] Completed {eval_type} evaluation {eval_id}: score={score}"
        )

        # Complete trace
        _complete_eval_trace(
            trace_run_id,
            outputs={"score": score, "reasoning": parsed.get("reasoning", "")},
            token_usage=usage,
        )

    except Exception as e:
        logger.exception(f"[AutoEval] Failed {eval_type} evaluation {eval_id}: {e}")
        _complete_eval_trace(trace_run_id, error=str(e))
        try:
            AutoEvaluations.update_auto_evaluation_by_id(
                eval_id,
                AutoEvaluationUpdateForm(
                    status="failed",
                    error_message=str(e)[:500],
                ),
            )
        except Exception:
            logger.exception(f"[AutoEval] Failed to update status for {eval_id}")


def _start_eval_trace(
    eval_type: str,
    eval_id: str,
    model_id: str,
    user_id: Optional[str] = None,
    chat_id: Optional[str] = None,
    message_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    inputs: Optional[dict] = None,
) -> Optional[str]:
    """Start a trace run for an evaluation LLM call."""
    if not user_id:
        return None
    try:
        # Use shared trace_id from agent, or generate standalone one
        effective_trace_id = trace_id or str(uuid.uuid4())
        form = MessageTraceCreateForm(
            trace_id=effective_trace_id,
            dotted_order="99",  # High number to appear after agent runs
            chat_id=chat_id,
            message_id=message_id,
            user_id=user_id,
            run_type=RunType.LLM.value,
            name=f"auto_eval:{eval_type}",
            status=RunStatus.RUNNING.value,
            inputs=inputs,
            model_id=model_id,
            meta={"eval_id": eval_id},
        )
        trace = MessageTraces.create_trace(form)
        return trace.id if trace else None
    except Exception as e:
        logger.debug(f"[AutoEval] Failed to start trace: {e}")
        return None


def _complete_eval_trace(
    trace_run_id: Optional[str],
    outputs: Optional[dict] = None,
    token_usage: Optional[dict] = None,
    error: Optional[str] = None,
) -> None:
    """Complete a trace run for an evaluation."""
    if not trace_run_id:
        return
    try:
        MessageTraces.complete_trace(
            trace_id=trace_run_id,
            outputs=outputs,
            token_usage=token_usage,
            error=error,
        )
    except Exception as e:
        logger.debug(f"[AutoEval] Failed to complete trace: {e}")


def _track_eval_usage(
    user_id: Optional[str],
    chat_id: Optional[str],
    message_id: Optional[str],
    model_id: str,
    usage: Optional[dict],
    eval_type: str,
) -> None:
    """Track LLM usage for an evaluation call."""
    if not user_id:
        return
    try:
        total_tokens = usage.get("total_tokens") if usage else None
        Usages.insert_new_usage(
            user_id=user_id,
            chat_id=chat_id,
            model_id=model_id,
            message_id=message_id or str(uuid.uuid4()),
            message_type=f"auto_eval:{eval_type}",
            total_tokens=total_tokens or 0,
            usage=usage,
        )
    except Exception as e:
        logger.debug(f"[AutoEval] Failed to track usage: {e}")

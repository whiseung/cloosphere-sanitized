"""
Auto-evaluation trigger module.

Decides whether to run evaluations (sampling) and creates background tasks.
"""

import asyncio
import logging
import random
from typing import Any, Dict, List, Optional

from open_webui.models.agent_config import AutoEvaluationConfig
from open_webui.models.auto_evaluations import (
    AutoEvaluationForm,
    AutoEvaluations,
)

from .evaluator import EVAL_PROMPTS, run_single_evaluation, select_eval_contexts

logger = logging.getLogger(__name__)


def should_evaluate(auto_eval_config: AutoEvaluationConfig) -> bool:
    """
    Determine whether to run auto-evaluation based on config and sampling rate.

    Returns True if all conditions are met:
    1. enabled is True
    2. evaluation_types is non-empty
    3. judge_model_id is set
    4. random sample passes the sampling_rate threshold
    """
    if not auto_eval_config.enabled:
        return False
    if not auto_eval_config.evaluation_types:
        return False
    if not auto_eval_config.judge_model_id:
        return False
    return random.random() < auto_eval_config.sampling_rate


def trigger_auto_evaluations(
    app,
    auto_eval_config: AutoEvaluationConfig,
    user_id: str,
    chat_id: str,
    message_id: str,
    model_id: str,
    user_query: str,
    assistant_response: str,
    retrieved_contexts: Optional[List[Dict[str, Any]]] = None,
    trace_id: Optional[str] = None,
) -> None:
    """
    Create evaluation records and launch background tasks for each eval type.

    For retrieval/faithfulness types, skips if retrieved_contexts is empty
    (e.g., DbSphere-only agents without RAG documents).
    """
    judge_model_id = auto_eval_config.judge_model_id

    for eval_type in auto_eval_config.evaluation_types:
        prompt_config = EVAL_PROMPTS.get(eval_type)
        if not prompt_config:
            logger.warning(f"[AutoEval] Unknown evaluation type: {eval_type}, skipping")
            continue

        # PR6: metric 별 source_type-aware context 선택 — chat_upload(사용자 ad-hoc
        # 업로드)은 retrieval(검색 품질) metric 에서 제외(부당한 grounding penalty 방지),
        # faithfulness 는 전체 포함, quality 는 None.
        eval_contexts = select_eval_contexts(eval_type, retrieved_contexts)

        # Skip context-dependent types when no (relevant) contexts available
        if prompt_config["requires_contexts"] and not eval_contexts:
            logger.debug(
                f"[AutoEval] Skipping {eval_type}: no retrieved contexts available"
            )
            continue

        # Create DB record (pending)
        try:
            form = AutoEvaluationForm(
                chat_id=chat_id,
                message_id=message_id,
                model_id=model_id,
                judge_model_id=judge_model_id,
                evaluation_type=eval_type,
                user_query=user_query,
                assistant_response=assistant_response,
                retrieved_contexts=eval_contexts,
            )
            record = AutoEvaluations.insert_new_auto_evaluation(user_id, form)
        except Exception as e:
            logger.warning(
                f"[AutoEval] Failed to create {eval_type} record: {e}, skipping"
            )
            continue

        if not record:
            logger.warning(f"[AutoEval] Failed to insert {eval_type} record, skipping")
            continue

        # Launch background task (fire-and-forget)
        asyncio.create_task(
            run_single_evaluation(
                app=app,
                eval_id=record.id,
                eval_type=eval_type,
                judge_model_id=judge_model_id,
                user_query=user_query,
                assistant_response=assistant_response,
                retrieved_contexts=eval_contexts,
                user_id=user_id,
                chat_id=chat_id,
                message_id=message_id,
                trace_id=trace_id,
            )
        )
        logger.info(
            f"[AutoEval] Triggered {eval_type} evaluation {record.id} "
            f"for message {message_id}"
        )

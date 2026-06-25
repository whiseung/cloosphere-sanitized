"""LangChain AgentMiddleware integration for Cloosphere guardrails.

Combines:
1. RuleBasedPIIMiddleware — GuardrailEngine 기반 PII 탐지/마스킹 (테스트와 동일 로직)
2. BlockedWordsMiddleware — for blocked word lists
3. LLMJudgeMiddleware — for LLM-as-a-Judge content evaluation
"""

import hashlib
import logging
import re
from typing import Any, Dict, List, Optional

from langchain.agents.middleware.types import AgentMiddleware
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.runtime import Runtime
from open_webui.models.message_trace import RunType
from open_webui.models.usage import Usages
from open_webui.utils.guardrails import GuardrailEngine

log = logging.getLogger(__name__)


def _extract_text(content: Any) -> str:
    """Extract text-only content from a message's content field.

    Handles both simple string content and multi-part content lists
    (e.g., [{"type": "text", "text": "..."}, {"type": "image_url", ...}]).
    Image URLs, base64 data, and other non-text parts are excluded.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("type") == "text":
                parts.append(item.get("text", ""))
        return " ".join(parts)
    return str(content) if content else ""


# ============================================================================
# Error
# ============================================================================


class GuardrailBlockedError(Exception):
    """Raised when a guardrail blocks the message."""

    def __init__(self, guardrail_name: str, reason: str):
        self.guardrail_name = guardrail_name
        self.reason = reason
        super().__init__(f"Guardrail '{guardrail_name}' blocked: {reason}")


# ============================================================================
# BlockedWordsMiddleware
# ============================================================================


class BlockedWordsMiddleware(AgentMiddleware):
    """Middleware to detect and handle blocked words in messages.

    PIIMiddleware로 처리할 수 없는 차단 단어 목록을 처리.
    """

    def __init__(
        self,
        guardrail_name: str,
        blocked_words: List[str],
        strategy: str,
        apply_to_input: bool = True,
        apply_to_output: bool = False,
    ):
        self._guardrail_name = guardrail_name
        self._blocked_words = [w for w in blocked_words if w]
        self._strategy = strategy
        self._apply_to_input = apply_to_input
        self._apply_to_output = apply_to_output

    @property
    def name(self) -> str:
        return f"BlockedWords[{self._guardrail_name}]"

    def _process_text(self, text: str) -> tuple[str, bool]:
        """Check text for blocked words. Returns (processed_text, modified)."""
        matches = []
        for word in self._blocked_words:
            pattern = re.compile(re.escape(word), re.IGNORECASE)
            for m in pattern.finditer(text):
                matches.append(m.group(0))

        if not matches:
            return text, False

        if self._strategy == "block":
            unique_words = list(dict.fromkeys(matches))[:5]
            words_display = ", ".join(f"'{w}'" for w in unique_words)
            raise GuardrailBlockedError(
                self._guardrail_name,
                f"Blocked word(s) detected: {words_display} ({len(matches)}건)",
            )

        processed = text
        for matched in matches:
            if self._strategy == "mask":
                replacement = "*" * len(matched)
            elif self._strategy == "hash":
                h = hashlib.sha256(matched.encode()).hexdigest()[:8]
                replacement = f"<blocked_hash:{h}>"
            else:  # redact
                replacement = "[BLOCKED]"
            processed = processed.replace(matched, replacement, 1)

        return processed, True

    async def abefore_model(
        self, state: dict, runtime: Runtime
    ) -> dict[str, Any] | None:
        if not self._apply_to_input:
            return None
        return self._check_messages(state, check_input=True)

    async def aafter_model(
        self, state: dict, runtime: Runtime
    ) -> dict[str, Any] | None:
        if not self._apply_to_output:
            return None
        return self._check_messages(state, check_input=False)

    def _check_messages(self, state: dict, check_input: bool) -> dict[str, Any] | None:
        messages = state.get("messages", [])
        if not messages:
            return None

        new_messages = list(messages)
        modified = False

        if check_input:
            # Check last user message only.
            # NOTE: ToolMessages are NOT scanned — they contain internal data
            # (SQL results, knowledge search results, distances) that must not
            # be corrupted by blocked word replacement.
            for i in range(len(messages) - 1, -1, -1):
                if isinstance(messages[i], HumanMessage) and messages[i].content:
                    processed, changed = self._process_text(
                        _extract_text(messages[i].content)
                    )
                    if changed:
                        new_messages[i] = HumanMessage(
                            content=processed,
                            id=messages[i].id,
                            name=getattr(messages[i], "name", None),
                        )
                        modified = True
                    break
        else:
            # Check last AI message
            for i in range(len(messages) - 1, -1, -1):
                if isinstance(messages[i], AIMessage) and messages[i].content:
                    processed, changed = self._process_text(
                        _extract_text(messages[i].content)
                    )
                    if changed:
                        new_messages[i] = AIMessage(
                            content=processed,
                            id=messages[i].id,
                            name=getattr(messages[i], "name", None),
                            tool_calls=messages[i].tool_calls,
                        )
                        modified = True
                    break

        return {"messages": new_messages} if modified else None


# ============================================================================
# LogOnlyMiddleware
# ============================================================================


class LogOnlyMiddleware(AgentMiddleware):
    """탐지만 하고 로그를 남기는 미들웨어 (텍스트 미수정, 비차단).

    "log" 전략일 때 PIIMiddleware 대신 사용.
    GuardrailEngine(regex 기반)으로 탐지 후 DB에 직접 로깅.
    """

    def __init__(
        self,
        guardrail_name: str,
        config: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self._guardrail_name = guardrail_name
        self._engine = GuardrailEngine(config)
        self._metadata = metadata or {}
        self._apply_to_input = config.get("apply_to_input", True)
        self._apply_to_output = config.get("apply_to_output", False)

    @property
    def name(self) -> str:
        return f"LogOnly[{self._guardrail_name}]"

    async def abefore_model(
        self, state: dict, runtime: Runtime
    ) -> dict[str, Any] | None:
        if self._apply_to_input:
            self._check_and_log(state, is_input=True)
        return None  # state 미수정

    async def aafter_model(
        self, state: dict, runtime: Runtime
    ) -> dict[str, Any] | None:
        if self._apply_to_output:
            self._check_and_log(state, is_input=False)
        return None

    def _check_and_log(self, state: dict, is_input: bool) -> None:
        messages = state.get("messages", [])
        if not messages:
            return

        # 마지막 user/AI 메시지 추출
        target_type = HumanMessage if is_input else AIMessage
        text = ""
        for msg in reversed(messages):
            if isinstance(msg, target_type) and msg.content:
                text = _extract_text(msg.content)
                break
        if not text:
            return

        # GuardrailEngine으로 탐지 (pii_strategy="log" → 텍스트 미수정)
        _, violations, _ = self._engine.process_text(text, is_input=is_input)
        if not violations:
            return

        # DB 로깅
        try:
            from open_webui.models.guardrail_log import (
                GuardrailLogCreateForm,
                GuardrailLogs,
            )

            for v in violations:
                det_source = v.get("type", "pii")
                GuardrailLogs.insert_guardrail_log(
                    GuardrailLogCreateForm(
                        user_id=self._metadata.get("user_id"),
                        chat_id=self._metadata.get("chat_id"),
                        message_id=self._metadata.get("message_id"),
                        guardrail_name=self._guardrail_name,
                        action="log",
                        detection_source=det_source,
                        detection_detail=v.get("pii_type")
                        or v.get("pattern_name")
                        or v.get("word", ""),
                        original_content=text,
                        processed_content="",
                    )
                )
        except Exception as e:
            log.warning(f"[LogOnlyMiddleware] Failed to log: {e}")


# ============================================================================
# RuleBasedPIIMiddleware
# ============================================================================


class RuleBasedPIIMiddleware(AgentMiddleware):
    """GuardrailEngine 기반 PII 미들웨어.

    테스트 엔드포인트와 동일한 탐지 패턴 + 마스킹 로직 사용.
    ToolMessage는 스캔하지 않음 (float 오탐 방지).
    """

    def __init__(
        self,
        guardrail_name: str,
        config: Dict[str, Any],
        apply_to_input: bool = True,
        apply_to_output: bool = False,
    ):
        self._guardrail_name = guardrail_name
        self._engine = GuardrailEngine(config)
        self._apply_to_input = apply_to_input
        self._apply_to_output = apply_to_output
        # Track detected violation types for post-agent context enrichment
        self.detected_violation_types: List[str] = []

    @property
    def name(self) -> str:
        return f"RuleBasedPII[{self._guardrail_name}]"

    async def abefore_model(
        self, state: dict, runtime: Runtime
    ) -> dict[str, Any] | None:
        if not self._apply_to_input:
            return None
        return self._check_messages(state, check_input=True)

    async def aafter_model(
        self, state: dict, runtime: Runtime
    ) -> dict[str, Any] | None:
        if not self._apply_to_output:
            return None
        return self._check_messages(state, check_input=False)

    def _check_messages(self, state: dict, check_input: bool) -> dict[str, Any] | None:
        messages = state.get("messages", [])
        if not messages:
            return None

        new_messages = list(messages)
        modified = False

        if check_input:
            for i in range(len(messages) - 1, -1, -1):
                if isinstance(messages[i], HumanMessage) and messages[i].content:
                    processed, violations, blocked = self._engine.process_text(
                        _extract_text(messages[i].content), is_input=True
                    )
                    if blocked:
                        raise GuardrailBlockedError(
                            self._guardrail_name,
                            self._format_pii_reason(violations),
                        )
                    if violations:
                        self._store_violation_types(violations)
                        new_messages[i] = HumanMessage(
                            content=processed,
                            id=messages[i].id,
                            name=getattr(messages[i], "name", None),
                        )
                        modified = True
                    break
        else:
            for i in range(len(messages) - 1, -1, -1):
                if isinstance(messages[i], AIMessage) and messages[i].content:
                    processed, violations, blocked = self._engine.process_text(
                        _extract_text(messages[i].content), is_input=False
                    )
                    if blocked:
                        raise GuardrailBlockedError(
                            self._guardrail_name,
                            self._format_pii_reason(violations),
                        )
                    if violations:
                        self._store_violation_types(violations)
                        new_messages[i] = AIMessage(
                            content=processed,
                            id=messages[i].id,
                            name=getattr(messages[i], "name", None),
                            tool_calls=messages[i].tool_calls,
                        )
                        modified = True
                    break

        return {"messages": new_messages} if modified else None

    @staticmethod
    def _format_pii_reason(violations: List[Dict[str, Any]]) -> str:
        """Format PII violation details into a human-readable reason string."""
        type_names: list[str] = []
        for v in violations:
            vtype = v.get("type", "")
            if vtype == "pii":
                name = v.get("pii_type", "pii")
            elif vtype == "custom_pattern":
                name = v.get("pattern_name", "custom_pattern")
            else:
                name = vtype or "unknown"
            if name not in type_names:
                type_names.append(name)
        types_display = ", ".join(type_names[:10])
        return f"PII detected: {types_display} ({len(violations)}건)"

    def _store_violation_types(self, violations: List[Dict[str, Any]]):
        """Store detected violation type names for post-agent context enrichment."""
        for v in violations:
            vtype = v.get("type", "")
            if vtype == "pii":
                name = v.get("pii_type", "pii")
            elif vtype == "custom_pattern":
                name = v.get("pattern_name", "custom_pattern")
            elif vtype == "blocked_word":
                name = "blocked_word"
            else:
                name = vtype or "unknown"
            if name and name not in self.detected_violation_types:
                self.detected_violation_types.append(name)


# ============================================================================
# LLMJudgeMiddleware
# ============================================================================

_DEFAULT_JUDGE_PROMPT = (
    "You are a content moderator. Evaluate the following content and respond "
    'with either "PASS" if the content is appropriate, or "BLOCK" if it '
    "should be blocked.\n\n"
    "Be strict about blocking harmful, inappropriate, or policy-violating content."
)


class LLMJudgeMiddleware(AgentMiddleware):
    """Middleware that uses LLM-as-a-Judge for content evaluation.

    가드레일의 LLM Judge 설정 기반으로 콘텐츠를 LLM에 판정 요청.
    Few-shot 예시(pass/block)를 프롬프트에 포함.
    """

    def __init__(
        self,
        config: Dict[str, Any],
        app: Any,
        metadata: Optional[Dict[str, Any]] = None,
        trace_context: Optional[Any] = None,
    ):
        """
        Args:
            config: Guardrail config dict (from GuardrailModel.model_dump())
            app: FastAPI application (for LLM access via create_llm_from_app)
            metadata: Request metadata (user_id, chat_id, message_id) for tracking
            trace_context: TraceContext for shared tracing (same trace_id as agent)
        """
        self._guardrail_name = config.get("name", "unknown")
        self._model_id = config.get("llm_judge_model")
        self._prompt = config.get("llm_judge_prompt") or _DEFAULT_JUDGE_PROMPT
        self._pass_examples = config.get("llm_judge_pass_examples", [])
        self._block_examples = config.get("llm_judge_block_examples", [])
        self._apply_to_input = config.get("llm_judge_apply_to_input", True)
        self._apply_to_output = config.get("llm_judge_apply_to_output", False)
        self._app = app
        self._metadata = metadata or {}
        self._trace_context = trace_context
        self._input_checked = False  # Skip repeated input checks across agent turns

    @property
    def name(self) -> str:
        return f"LLMJudge[{self._guardrail_name}]"

    def _build_prompt(self, text: str) -> str:
        """Build judge prompt with few-shot examples."""
        examples_section = ""

        if self._pass_examples:
            examples_section += "\n\nExamples of content that should PASS:\n"
            for i, example in enumerate(self._pass_examples, 1):
                examples_section += f"{i}. {example}\n"

        if self._block_examples:
            examples_section += "\n\nExamples of content that should be BLOCKED:\n"
            for i, example in enumerate(self._block_examples, 1):
                examples_section += f"{i}. {example}\n"

        return (
            f"You are a content moderator. Evaluate the content below based on "
            f"the following policy.\n\n"
            f"## Policy\n{self._prompt}\n\n"
            f"## Rules\n"
            f"- ONLY block content that CLEARLY and DIRECTLY violates the policy above\n"
            f"- If the content does not match any specific violation described in the policy, respond PASS\n"
            f"- Do NOT over-interpret the policy — when in doubt, PASS\n"
            f"{examples_section}\n\n"
            f"Content to evaluate:\n---\n{text}\n---\n\n"
            f'Respond with only "PASS" or "BLOCK".'
        )

    async def _judge(self, text: str) -> tuple[bool, str]:
        """Judge content with LLM. Returns (passed, reason)."""
        if not self._model_id:
            return True, "LLM judge model not configured"

        try:
            from extension_modules.utils.llm import create_llm_from_app

            llm = create_llm_from_app(
                self._app, self._model_id, temperature=0, max_tokens=100
            )
            log.info(
                f"[LLMJudge:{self._guardrail_name}] model_id={self._model_id}, "
                f"llm_type={type(llm).__name__ if llm else 'None'}"
            )
            if not llm:
                log.warning(
                    f"[LLMJudge:{self._guardrail_name}] Model not found: {self._model_id}"
                )
                return True, "LLM judge model not available"

            prompt = self._build_prompt(text)

            # Execute with trace context (shared trace_id with agent)
            tc = self._trace_context
            if tc and tc.enabled:
                with tc.start_run(
                    run_type=RunType.GUARDRAIL.value,
                    name=f"guardrail:{self._guardrail_name}",
                    model_id=self._model_id,
                    inputs={"text_length": len(text)},
                    push_stack=False,
                ) as run:
                    response = await llm.ainvoke([HumanMessage(content=prompt)])
                    usage = getattr(response, "usage_metadata", None)
                    resp_content = response.content
                    if isinstance(resp_content, list):
                        resp_content = "".join(
                            b.get("text", "") if isinstance(b, dict) else str(b)
                            for b in resp_content
                        )
                    response_lower = resp_content.lower().strip()
                    passed = "block" not in response_lower
                    reason = (
                        "Content approved by LLM judge"
                        if passed
                        else "Content blocked by LLM judge"
                    )
                    if run:
                        run.set_token_usage(usage)
                        run.set_outputs({"passed": passed, "reason": reason})
            else:
                response = await llm.ainvoke([HumanMessage(content=prompt)])
                usage = getattr(response, "usage_metadata", None)
                resp_content = response.content
                if isinstance(resp_content, list):
                    resp_content = "".join(
                        b.get("text", "") if isinstance(b, dict) else str(b)
                        for b in resp_content
                    )
                response_lower = resp_content.lower().strip()
                passed = "block" not in response_lower
                reason = (
                    "Content approved by LLM judge"
                    if passed
                    else "Content blocked by LLM judge"
                )

            # Track usage
            self._track_usage(usage)

            return passed, reason

        except Exception as e:
            log.error(f"[LLMJudge:{self._guardrail_name}] Error: {e}")
            return True, f"LLM judge error: {e}"

    def _track_usage(self, usage: Optional[dict] = None) -> None:
        """Track LLM usage for this guardrail call."""
        if not self._metadata or not self._metadata.get("user_id"):
            return
        try:
            total_tokens = usage.get("total_tokens") if usage else None
            Usages.insert_new_usage(
                user_id=self._metadata["user_id"],
                chat_id=self._metadata.get("chat_id"),
                model_id=self._model_id or "",
                message_id=self._metadata.get("message_id", ""),
                message_type="guardrail",
                total_tokens=total_tokens or 0,
                usage=usage,
            )
        except Exception as e:
            log.debug(f"[LLMJudge] Failed to track usage: {e}")

    async def abefore_model(
        self, state: dict, runtime: Runtime
    ) -> dict[str, Any] | None:
        if not self._apply_to_input:
            return None

        # Input (user message) doesn't change between agent turns — check once only
        if self._input_checked:
            return None

        messages = state.get("messages", [])
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage) and msg.content:
                passed, reason = await self._judge(_extract_text(msg.content))
                self._input_checked = True
                if not passed:
                    raise GuardrailBlockedError(self._guardrail_name, reason)
                break

        return None

    async def aafter_model(
        self, state: dict, runtime: Runtime
    ) -> dict[str, Any] | None:
        if not self._apply_to_output:
            return None

        messages = state.get("messages", [])
        for msg in reversed(messages):
            if isinstance(msg, AIMessage) and msg.content:
                passed, reason = await self._judge(_extract_text(msg.content))
                if not passed:
                    raise GuardrailBlockedError(self._guardrail_name, reason)
                break

        return None


# ============================================================================
# Factory
# ============================================================================


def create_guardrail_middlewares(
    guardrail_ids: List[str],
    app: Optional[Any] = None,
    metadata: Optional[Dict[str, Any]] = None,
    trace_context: Optional[Any] = None,
) -> List[AgentMiddleware]:
    """Load guardrails from DB and create middleware instances.

    For each guardrail config:
    1. RuleBasedPIIMiddleware for PII types + custom patterns (GuardrailEngine 기반)
    2. BlockedWordsMiddleware for blocked word lists
    3. LLMJudgeMiddleware for LLM-as-a-Judge (requires app)

    Args:
        guardrail_ids: List of guardrail UUIDs from AgentConfig
        app: FastAPI application (required for LLM Judge)
        metadata: Request metadata for Usage/Trace tracking (user_id, chat_id, message_id)
        trace_context: TraceContext for shared tracing with agent

    Returns:
        List of AgentMiddleware instances
    """
    if not guardrail_ids:
        return []

    from open_webui.models.guardrails import Guardrails

    middlewares: List[AgentMiddleware] = []
    guardrails = Guardrails.get_guardrails_by_ids(guardrail_ids)

    for guardrail in guardrails:
        config = guardrail.model_dump()
        name = config.get("name", "unknown")
        strategy = config.get("pii_strategy", "redact")

        apply_input = config.get("apply_to_input", True)
        apply_output = config.get("apply_to_output", False)
        has_rules = False

        if strategy == "log":
            # "log" 전략: PIIMiddleware 대신 LogOnlyMiddleware 사용
            # (PIIMiddleware는 "log" 전략 미지원)
            has_rules = bool(
                config.get("pii_types")
                or config.get("custom_patterns")
                or config.get("blocked_words")
            )
            if has_rules:
                middlewares.append(
                    LogOnlyMiddleware(
                        guardrail_name=name,
                        config=config,
                        metadata=metadata,
                    )
                )
        else:
            # 1. RuleBasedPIIMiddleware for PII types + custom patterns
            # GuardrailEngine 기반 — 테스트 엔드포인트와 동일한 탐지/마스킹 로직
            pii_types = config.get("pii_types", [])
            custom_patterns = config.get("custom_patterns", [])
            if pii_types or custom_patterns:
                middlewares.append(
                    RuleBasedPIIMiddleware(
                        guardrail_name=name,
                        config=config,
                        apply_to_input=apply_input,
                        apply_to_output=apply_output,
                    )
                )
                has_rules = True

            # 2. BlockedWordsMiddleware for blocked word lists
            blocked_words = config.get("blocked_words", [])
            if blocked_words:
                middlewares.append(
                    BlockedWordsMiddleware(
                        guardrail_name=name,
                        blocked_words=blocked_words,
                        strategy=strategy,
                        apply_to_input=apply_input,
                        apply_to_output=apply_output,
                    )
                )
                has_rules = True

        # 4. LLMJudgeMiddleware for LLM-as-a-Judge (strategy와 무관하게 항상)
        if config.get("llm_judge_enabled") and app:
            middlewares.append(
                LLMJudgeMiddleware(
                    config,
                    app,
                    metadata=metadata,
                    trace_context=trace_context,
                )
            )
            has_rules = True

        if not has_rules:
            log.debug(f"[Guardrail:{name}] Skipping — no rules configured")

    return middlewares

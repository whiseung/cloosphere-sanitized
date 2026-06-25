"""
Guardrail Module
================

LangChain PIIMiddleware 기반 가드레일 모듈.

사용법:
    from extension_modules.guardrail import apply_guardrail, apply_guardrails

    # 규칙 기반만
    result = apply_guardrail(config, text)

    # 규칙 기반 + LLM Judge (async)
    result = await apply_guardrail_with_llm(config, text, generate_func=generate)

    if result.blocked:
        raise Exception(result.block_reason)
    else:
        processed_text = result.text
"""

from extension_modules.guardrail.pii_detector import (
    # 상수
    SUPPORTED_PII_TYPES,
    SUPPORTED_STRATEGIES,
    GuardrailResult,
    LLMJudge,
    # 클래스
    RuleBasedGuardrail,
    Violation,
    # 규칙 기반 함수
    apply_guardrail,
    # 규칙 기반 + LLM Judge 함수 (async)
    apply_guardrail_with_llm,
    apply_guardrails,
    apply_guardrails_with_llm,
)

__all__ = [
    # 클래스
    "RuleBasedGuardrail",
    "LLMJudge",
    "Violation",
    "GuardrailResult",
    # 규칙 기반 함수
    "apply_guardrail",
    "apply_guardrails",
    # 규칙 기반 + LLM Judge 함수 (async)
    "apply_guardrail_with_llm",
    "apply_guardrails_with_llm",
    # 상수
    "SUPPORTED_PII_TYPES",
    "SUPPORTED_STRATEGIES",
]

__version__ = "1.0.0"

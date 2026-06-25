"""
Guardrail PII Detector
======================

LangChain PIIMiddleware 기반 PII 탐지 및 처리.
- 규칙 기반 탐지: PII, 커스텀 패턴, 차단 단어
- LLM Judge: 프롬프트 기반 판정 (few-shot 포함)
"""

import logging
import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Literal, Optional, Tuple

log = logging.getLogger(__name__)

from langchain.agents.middleware._redaction import (
    BUILTIN_DETECTORS,
)
from langchain.agents.middleware._redaction import (
    apply_strategy as lc_apply_strategy,
)
from langchain.agents.middleware._redaction import (
    resolve_detector as lc_resolve_detector,
)
from langchain.agents.middleware.pii import PIIDetectionError

# 지원 PII 유형
SUPPORTED_PII_TYPES = ["email", "credit_card", "ip", "mac_address", "url", "api_key"]

# 지원 전략
SUPPORTED_STRATEGIES = ["block", "redact", "mask", "hash", "log"]

# 커스텀 패턴 (LangChain 내장에 없는 것)
CUSTOM_PATTERNS: Dict[str, str] = {
    "api_key": r"sk-[a-zA-Z0-9]{20,}",
}


# ---------------------------------------------------------------------------
# Unicode-safe PII 감지기
# Python 3의 \b는 유니코드 word char(한글, 일본어 등)를 인식하므로
# "sim@cloocus.com이" 같이 CJK 문자가 바로 이어붙는 경우 매칭 실패.
# lookaround 기반으로 교체하여 한글 환경에서도 정상 동작.
# ---------------------------------------------------------------------------
import ipaddress as _ipaddress
import re as _re

from langchain.agents.middleware.pii import PIIMatch as _PIIMatch


def _detect_email_unicode(content: str) -> list:
    """Detect email addresses."""
    pattern = r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?![A-Za-z0-9])"
    return [
        _PIIMatch(type="email", value=m.group(), start=m.start(), end=m.end())
        for m in _re.finditer(pattern, content)
    ]


def _detect_credit_card_unicode(content: str) -> list:
    """Detect credit card numbers with Luhn validation."""
    from langchain.agents.middleware._redaction import _passes_luhn

    pattern = r"(?<!\d)\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}(?!\d)"
    matches = []
    for m in _re.finditer(pattern, content):
        if _passes_luhn(m.group()):
            matches.append(
                _PIIMatch(
                    type="credit_card", value=m.group(), start=m.start(), end=m.end()
                )
            )
    return matches


def _detect_ip_unicode(content: str) -> list:
    """Detect IPv4 addresses."""
    pattern = r"(?<!\d)(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?!\d)"
    matches = []
    for m in _re.finditer(pattern, content):
        try:
            _ipaddress.ip_address(m.group())
        except ValueError:
            continue
        matches.append(
            _PIIMatch(type="ip", value=m.group(), start=m.start(), end=m.end())
        )
    return matches


def _detect_mac_address_unicode(content: str) -> list:
    """Detect MAC addresses."""
    pattern = r"(?<![0-9A-Fa-f])([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}(?![0-9A-Fa-f])"
    return [
        _PIIMatch(type="mac_address", value=m.group(), start=m.start(), end=m.end())
        for m in _re.finditer(pattern, content)
    ]


# Unicode-safe 감지기 매핑 (email, credit_card, ip, mac_address)
# url은 \b 문제가 경미하고 로직이 복잡하므로 LangChain 내장 유지
_UNICODE_SAFE_DETECTORS: Dict[str, Callable] = {
    "email": _detect_email_unicode,
    "credit_card": _detect_credit_card_unicode,
    "ip": _detect_ip_unicode,
    "mac_address": _detect_mac_address_unicode,
}

# 전략 타입
StrategyType = Literal["block", "redact", "mask", "hash", "log"]

# 마스킹 시 남길 글자 수
_MASK_VISIBLE_CHARS = 1


def _mask_value(pii_type: str, value: str) -> str:
    """PII 값을 첫 글자만 남기고 마스킹한다."""
    if pii_type == "email":
        parts = value.split("@")
        if len(parts) == 2:
            local = parts[0]
            domain_parts = parts[1].split(".")
            masked_local = (
                local[:_MASK_VISIBLE_CHARS] + "****"
                if len(local) > _MASK_VISIBLE_CHARS
                else "****"
            )
            if len(domain_parts) > 1:
                masked_domain = "****." + domain_parts[-1]
            else:
                masked_domain = "****"
            return f"{masked_local}@{masked_domain}"
        return "****"
    elif pii_type == "credit_card":
        digits_only = "".join(c for c in value if c.isdigit())
        return f"****{digits_only[-4:]}" if len(digits_only) >= 4 else "****"
    elif pii_type == "ip":
        octets = value.split(".")
        return f"*.*.*.{octets[-1]}" if len(octets) == 4 else "****"
    elif pii_type == "mac_address":
        sep = ":" if ":" in value else "-"
        return f"**{sep}**{sep}**{sep}**{sep}**{sep}{value[-2:]}"
    elif pii_type == "url":
        return "[MASKED_URL]"
    else:
        return (
            value[:_MASK_VISIBLE_CHARS] + "****"
            if len(value) > _MASK_VISIBLE_CHARS
            else "****"
        )


def _apply_custom_mask(content: str, matches: list) -> str:
    """커스텀 마스킹 적용 (첫 글자만 남기고 마스킹)."""
    result = content
    for match in sorted(matches, key=lambda m: m["start"], reverse=True):
        masked = _mask_value(match["type"], match["value"])
        result = result[: match["start"]] + masked + result[match["end"] :]
    return result


@dataclass
class Violation:
    """위반 사항"""

    type: str  # pii, custom_pattern, blocked_word
    matched: str
    start: int
    end: int
    pii_type: Optional[str] = None
    pattern_name: Optional[str] = None
    word: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "type": self.type,
            "matched": self.matched,
            "start": self.start,
            "end": self.end,
        }
        if self.pii_type:
            result["pii_type"] = self.pii_type
        if self.pattern_name:
            result["pattern_name"] = self.pattern_name
        if self.word:
            result["word"] = self.word
        return result


@dataclass
class GuardrailResult:
    """가드레일 처리 결과"""

    text: str
    violations: List[Violation]
    blocked: bool
    block_reason: Optional[str] = None

    @property
    def has_violations(self) -> bool:
        return len(self.violations) > 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "processed_text": self.text,
            "violations": [v.to_dict() for v in self.violations],
            "blocked": self.blocked,
            "block_reason": self.block_reason,
        }


class RuleBasedGuardrail:
    """규칙 기반 가드레일"""

    def __init__(self, config: Dict[str, Any]):
        """
        Args:
            config: 가드레일 설정
                - pii_types: 탐지할 PII 유형 목록
                - pii_strategy: 처리 전략 (block, redact, mask, hash)
                - custom_patterns: 커스텀 패턴 [{name, pattern}]
                - blocked_words: 차단 단어 목록
                - apply_to_input: 입력에 적용 여부
                - apply_to_output: 출력에 적용 여부
        """
        self.config = config
        self.pii_types = config.get("pii_types", [])
        self.strategy: StrategyType = config.get("pii_strategy", "redact")
        self.custom_patterns = config.get("custom_patterns", [])
        self.blocked_words = config.get("blocked_words", [])
        self.apply_to_input = config.get("apply_to_input", True)
        self.apply_to_output = config.get("apply_to_output", False)

        # PII 탐지기 초기화
        self._detectors: Dict[str, Callable] = {}
        self._init_detectors()

    def _init_detectors(self) -> None:
        """PII 탐지기 초기화"""
        for pii_type in self.pii_types:
            # Unicode-safe 감지기 우선 사용 (한글 환경 호환)
            if pii_type in _UNICODE_SAFE_DETECTORS:
                self._detectors[pii_type] = _UNICODE_SAFE_DETECTORS[pii_type]
            elif pii_type in BUILTIN_DETECTORS:
                self._detectors[pii_type] = BUILTIN_DETECTORS[pii_type]
            elif pii_type in CUSTOM_PATTERNS:
                pattern = CUSTOM_PATTERNS[pii_type]
                self._detectors[pii_type] = lc_resolve_detector(pii_type, pattern)

        # 커스텀 패턴 추가
        for custom in self.custom_patterns:
            name = custom.get("name")
            pattern = custom.get("pattern")
            if name and pattern:
                try:
                    self._detectors[f"custom_{name}"] = lc_resolve_detector(
                        name, pattern
                    )
                except Exception:
                    pass

    def process(self, text: str, is_input: bool = True) -> GuardrailResult:
        """
        텍스트 처리

        Args:
            text: 처리할 텍스트
            is_input: 입력 여부

        Returns:
            처리 결과
        """
        # 적용 범위 확인
        if is_input and not self.apply_to_input:
            return GuardrailResult(text=text, violations=[], blocked=False)
        if not is_input and not self.apply_to_output:
            return GuardrailResult(text=text, violations=[], blocked=False)

        violations: List[Violation] = []

        # 1. PII 탐지
        pii_violations = self._detect_pii(text)
        violations.extend(pii_violations)

        # 2. 차단 단어 탐지
        word_violations = self._detect_blocked_words(text)
        violations.extend(word_violations)

        if not violations:
            return GuardrailResult(text=text, violations=[], blocked=False)

        # 3. 전략 적용
        if self.strategy == "block":
            return GuardrailResult(
                text=text,
                violations=violations,
                blocked=True,
                block_reason=f"Detected {len(violations)} violation(s)",
            )

        if self.strategy == "log":
            return GuardrailResult(text=text, violations=violations, blocked=False)

        # LangChain 전략 적용 (PII만)
        pii_matches = [
            {
                "type": v.pii_type or v.pattern_name,
                "value": v.matched,
                "start": v.start,
                "end": v.end,
            }
            for v in violations
            if v.type in ("pii", "custom_pattern")
        ]

        processed_text = text
        if pii_matches:
            try:
                if self.strategy == "mask":
                    processed_text = _apply_custom_mask(text, pii_matches)
                else:
                    processed_text = lc_apply_strategy(text, pii_matches, self.strategy)
            except PIIDetectionError:
                return GuardrailResult(
                    text=text,
                    violations=violations,
                    blocked=True,
                    block_reason="PII detected",
                )

        # 차단 단어 처리
        for v in violations:
            if v.type == "blocked_word":
                if self.strategy == "redact":
                    replacement = "[BLOCKED]"
                elif self.strategy == "mask":
                    replacement = "*" * len(v.matched)
                elif self.strategy == "hash":
                    import hashlib

                    h = hashlib.sha256(v.matched.encode()).hexdigest()[:8]
                    replacement = f"<blocked_hash:{h}>"
                else:
                    replacement = "[BLOCKED]"

                processed_text = processed_text.replace(v.matched, replacement, 1)

        return GuardrailResult(
            text=processed_text,
            violations=violations,
            blocked=False,
        )

    def _detect_pii(self, text: str) -> List[Violation]:
        """PII 탐지"""
        violations = []

        for pii_type, detector in self._detectors.items():
            is_custom = pii_type.startswith("custom_")
            actual_type = pii_type[7:] if is_custom else pii_type

            for match in detector(text):
                violations.append(
                    Violation(
                        type="custom_pattern" if is_custom else "pii",
                        matched=match["value"],
                        start=match["start"],
                        end=match["end"],
                        pii_type=None if is_custom else actual_type,
                        pattern_name=actual_type if is_custom else None,
                    )
                )

        return violations

    def _detect_blocked_words(self, text: str) -> List[Violation]:
        """차단 단어 탐지"""
        violations = []

        for word in self.blocked_words:
            if not word:
                continue

            pattern = re.compile(re.escape(word), re.IGNORECASE)
            for match in pattern.finditer(text):
                violations.append(
                    Violation(
                        type="blocked_word",
                        matched=match.group(0),
                        start=match.start(),
                        end=match.end(),
                        word=word,
                    )
                )

        return violations


def apply_guardrail(
    config: Dict[str, Any],
    text: str,
    is_input: bool = True,
) -> GuardrailResult:
    """
    단일 가드레일 적용

    Args:
        config: 가드레일 설정 (GuardrailModel.model_dump())
        text: 처리할 텍스트
        is_input: 입력 여부

    Returns:
        처리 결과
    """
    guardrail = RuleBasedGuardrail(config)
    return guardrail.process(text, is_input)


def apply_guardrails(
    configs: List[Dict[str, Any]],
    text: str,
    is_input: bool = True,
) -> GuardrailResult:
    """
    다중 가드레일 순차 적용

    Args:
        configs: 가드레일 설정 목록
        text: 처리할 텍스트
        is_input: 입력 여부

    Returns:
        최종 처리 결과
    """
    all_violations: List[Violation] = []
    processed_text = text

    for config in configs:
        result = apply_guardrail(config, processed_text, is_input)
        all_violations.extend(result.violations)
        processed_text = result.text

        if result.blocked:
            return GuardrailResult(
                text=processed_text,
                violations=all_violations,
                blocked=True,
                block_reason=result.block_reason
                or f"Blocked by guardrail: {config.get('name', 'Unknown')}",
            )

    return GuardrailResult(
        text=processed_text,
        violations=all_violations,
        blocked=False,
    )


# ============================================================================
# LLM Judge
# ============================================================================

DEFAULT_JUDGE_PROMPT = """You are a content moderator. Evaluate the following content and respond with either "PASS" if the content is appropriate, or "BLOCK" if it should be blocked.

Be strict about blocking harmful, inappropriate, or policy-violating content."""


class LLMJudge:
    """LLM 기반 콘텐츠 판정기"""

    def __init__(self, config: Dict[str, Any]):
        """
        Args:
            config: 가드레일 설정
                - llm_judge_enabled: 활성화 여부
                - llm_judge_model: 사용할 모델
                - llm_judge_prompt: 커스텀 프롬프트
                - llm_judge_pass_examples: 통과 예시 (few-shot)
                - llm_judge_block_examples: 차단 예시 (few-shot)
                - llm_judge_apply_to_input: 입력에 적용
                - llm_judge_apply_to_output: 출력에 적용
        """
        self.enabled = config.get("llm_judge_enabled", False)
        self.model = config.get("llm_judge_model")
        self.prompt = config.get("llm_judge_prompt") or DEFAULT_JUDGE_PROMPT
        self.pass_examples = config.get("llm_judge_pass_examples", [])
        self.block_examples = config.get("llm_judge_block_examples", [])
        self.apply_to_input = config.get("llm_judge_apply_to_input", True)
        self.apply_to_output = config.get("llm_judge_apply_to_output", False)

    def _build_prompt(self, text: str) -> str:
        """판정 프롬프트 구성 (few-shot 포함)"""
        examples_section = ""

        # Pass 예시 (few-shot)
        if self.pass_examples:
            examples_section += "\n\nExamples of content that should PASS:\n"
            for i, example in enumerate(self.pass_examples, 1):
                examples_section += f"{i}. {example}\n"

        # Block 예시 (few-shot)
        if self.block_examples:
            examples_section += "\n\nExamples of content that should be BLOCKED:\n"
            for i, example in enumerate(self.block_examples, 1):
                examples_section += f"{i}. {example}\n"

        return f"""{self.prompt}
{examples_section}

Content to evaluate:
---
{text}
---

Respond with only "PASS" or "BLOCK"."""

    async def judge(
        self,
        text: str,
        is_input: bool,
        generate_func: Callable,
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        LLM으로 콘텐츠 판정

        Args:
            text: 판정할 텍스트
            is_input: 입력 여부
            generate_func: LLM 호출 함수

        Returns:
            (passed, reason, raw_response)
        """
        # 활성화 확인
        if not self.enabled:
            return True, "LLM judge not enabled", None

        if not self.model:
            return True, "LLM judge model not configured", None

        # 적용 범위 확인
        if is_input and not self.apply_to_input:
            return True, "LLM judge not applied to input", None
        if not is_input and not self.apply_to_output:
            return True, "LLM judge not applied to output", None

        # 프롬프트 구성
        prompt = self._build_prompt(text)

        try:
            # LLM 호출
            response = await generate_func(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=100,
                temperature=0,
            )

            # 응답 파싱
            response_text = (
                response.get("choices", [{}])[0].get("message", {}).get("content", "")
            )

            # 판정
            response_lower = response_text.lower().strip()
            if "pass" in response_lower and "block" not in response_lower:
                return True, "Content approved by LLM judge", response_text
            elif "block" in response_lower:
                return False, "Content blocked by LLM judge", response_text
            else:
                return (
                    True,
                    "LLM judge response unclear, defaulting to pass",
                    response_text,
                )

        except Exception as e:
            log.error(f"LLM judge error: {e}")
            return True, f"LLM judge error: {str(e)}", None


async def apply_guardrail_with_llm(
    config: Dict[str, Any],
    text: str,
    is_input: bool = True,
    generate_func: Optional[Callable] = None,
) -> GuardrailResult:
    """
    규칙 기반 + LLM Judge 가드레일 적용

    Args:
        config: 가드레일 설정
        text: 처리할 텍스트
        is_input: 입력 여부
        generate_func: LLM 호출 함수 (async)

    Returns:
        처리 결과
    """
    # 1. 규칙 기반 처리
    result = apply_guardrail(config, text, is_input)

    # 차단됐으면 바로 반환
    if result.blocked:
        return result

    # 2. LLM Judge 처리
    if config.get("llm_judge_enabled") and generate_func:
        judge = LLMJudge(config)
        passed, reason, _ = await judge.judge(result.text, is_input, generate_func)

        if not passed:
            # LLM Judge 위반 추가
            result.violations.append(
                Violation(
                    type="llm_judge",
                    matched=text,
                    start=0,
                    end=len(text),
                )
            )
            return GuardrailResult(
                text=result.text,
                violations=result.violations,
                blocked=True,
                block_reason=reason,
            )

    return result


async def apply_guardrails_with_llm(
    configs: List[Dict[str, Any]],
    text: str,
    is_input: bool = True,
    generate_func: Optional[Callable] = None,
) -> GuardrailResult:
    """
    다중 가드레일 순차 적용 (규칙 기반 + LLM Judge)

    Args:
        configs: 가드레일 설정 목록
        text: 처리할 텍스트
        is_input: 입력 여부
        generate_func: LLM 호출 함수 (async)

    Returns:
        최종 처리 결과
    """
    all_violations: List[Violation] = []
    processed_text = text

    for config in configs:
        result = await apply_guardrail_with_llm(
            config, processed_text, is_input, generate_func
        )
        all_violations.extend(result.violations)
        processed_text = result.text

        if result.blocked:
            return GuardrailResult(
                text=processed_text,
                violations=all_violations,
                blocked=True,
                block_reason=result.block_reason
                or f"Blocked by guardrail: {config.get('name', 'Unknown')}",
            )

    return GuardrailResult(
        text=processed_text,
        violations=all_violations,
        blocked=False,
    )

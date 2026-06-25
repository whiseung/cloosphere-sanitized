"""
Guardrail Tests
"""

import asyncio
import re

from extension_modules.guardrail import (
    LLMJudge,
    apply_guardrail,
    apply_guardrail_with_llm,
    apply_guardrails,
)
from open_webui.utils.guardrails import PII_PATTERNS, GuardrailEngine


class TestPIIDetection:
    """PII 탐지 테스트"""

    def test_detect_email(self):
        config = {
            "pii_types": ["email"],
            "pii_strategy": "redact",
            "apply_to_input": True,
        }
        result = apply_guardrail(config, "Contact: user@example.com")
        assert result.has_violations
        assert "[REDACTED_EMAIL]" in result.text

    def test_detect_credit_card(self):
        config = {
            "pii_types": ["credit_card"],
            "pii_strategy": "mask",
            "apply_to_input": True,
        }
        result = apply_guardrail(config, "Card: 4532015112830366")
        assert result.has_violations
        assert "0366" in result.text

    def test_detect_ip(self):
        config = {"pii_types": ["ip"], "pii_strategy": "redact", "apply_to_input": True}
        result = apply_guardrail(config, "Server: 192.168.1.1")
        assert result.has_violations
        assert "[REDACTED_IP]" in result.text

    def test_detect_mac_address(self):
        config = {
            "pii_types": ["mac_address"],
            "pii_strategy": "redact",
            "apply_to_input": True,
        }
        result = apply_guardrail(config, "MAC: 00:1A:2B:3C:4D:5E")
        assert result.has_violations
        assert "[REDACTED_MAC_ADDRESS]" in result.text

    def test_detect_url(self):
        config = {
            "pii_types": ["url"],
            "pii_strategy": "redact",
            "apply_to_input": True,
        }
        result = apply_guardrail(config, "Link: https://example.com")
        assert result.has_violations
        assert "[REDACTED_URL]" in result.text

    def test_detect_api_key(self):
        config = {
            "pii_types": ["api_key"],
            "pii_strategy": "redact",
            "apply_to_input": True,
        }
        result = apply_guardrail(config, "Key: sk-abcdefghij1234567890abcdefghij12")
        assert result.has_violations
        assert "[REDACTED_API_KEY]" in result.text


class TestBlockedWords:
    """차단 단어 테스트"""

    def test_blocked_word_redact(self):
        config = {
            "blocked_words": ["password"],
            "pii_strategy": "redact",
            "apply_to_input": True,
        }
        result = apply_guardrail(config, "My password is secret")
        assert result.has_violations
        assert "[BLOCKED]" in result.text

    def test_blocked_word_mask(self):
        config = {
            "blocked_words": ["secret"],
            "pii_strategy": "mask",
            "apply_to_input": True,
        }
        result = apply_guardrail(config, "My secret is here")
        assert "******" in result.text

    def test_blocked_word_case_insensitive(self):
        config = {
            "blocked_words": ["password"],
            "pii_strategy": "redact",
            "apply_to_input": True,
        }
        result = apply_guardrail(config, "PASSWORD is here")
        assert result.has_violations


class TestCustomPatterns:
    """커스텀 패턴 테스트"""

    def test_custom_pattern(self):
        config = {
            "custom_patterns": [{"name": "order_id", "pattern": r"ORD-\d{6}"}],
            "pii_strategy": "redact",
            "apply_to_input": True,
        }
        result = apply_guardrail(config, "Order: ORD-123456")
        assert result.has_violations
        assert "[REDACTED_ORDER_ID]" in result.text


class TestStrategies:
    """전략 테스트"""

    def test_strategy_block(self):
        config = {
            "pii_types": ["email"],
            "pii_strategy": "block",
            "apply_to_input": True,
        }
        result = apply_guardrail(config, "Email: test@example.com")
        assert result.blocked
        assert result.block_reason is not None

    def test_strategy_redact(self):
        config = {
            "pii_types": ["email"],
            "pii_strategy": "redact",
            "apply_to_input": True,
        }
        result = apply_guardrail(config, "Email: test@example.com")
        assert not result.blocked
        assert "[REDACTED_EMAIL]" in result.text

    def test_strategy_mask(self):
        config = {
            "pii_types": ["credit_card"],
            "pii_strategy": "mask",
            "apply_to_input": True,
        }
        result = apply_guardrail(config, "Card: 4532015112830366")
        assert not result.blocked
        assert "0366" in result.text

    def test_strategy_hash(self):
        config = {
            "pii_types": ["email"],
            "pii_strategy": "hash",
            "apply_to_input": True,
        }
        result = apply_guardrail(config, "Email: test@example.com")
        assert not result.blocked
        assert "<email_hash:" in result.text


class TestApplyScope:
    """적용 범위 테스트"""

    def test_apply_to_input_only(self):
        config = {
            "pii_types": ["email"],
            "pii_strategy": "redact",
            "apply_to_input": True,
            "apply_to_output": False,
        }
        result = apply_guardrail(config, "test@example.com", is_input=True)
        assert result.has_violations
        result = apply_guardrail(config, "test@example.com", is_input=False)
        assert not result.has_violations

    def test_apply_to_output_only(self):
        config = {
            "pii_types": ["email"],
            "pii_strategy": "redact",
            "apply_to_input": False,
            "apply_to_output": True,
        }
        result = apply_guardrail(config, "test@example.com", is_input=True)
        assert not result.has_violations
        result = apply_guardrail(config, "test@example.com", is_input=False)
        assert result.has_violations


class TestMultipleGuardrails:
    """다중 가드레일 테스트"""

    def test_apply_multiple(self):
        configs = [
            {
                "name": "pii_guard",
                "pii_types": ["email"],
                "pii_strategy": "redact",
                "apply_to_input": True,
            },
            {
                "name": "word_guard",
                "blocked_words": ["secret"],
                "pii_strategy": "redact",
                "apply_to_input": True,
            },
        ]
        result = apply_guardrails(configs, "Email: test@example.com, secret data")
        assert len(result.violations) == 2
        assert "[REDACTED_EMAIL]" in result.text
        assert "[BLOCKED]" in result.text

    def test_stop_on_block(self):
        configs = [
            {
                "name": "strict",
                "pii_types": ["email"],
                "pii_strategy": "block",
                "apply_to_input": True,
            },
            {
                "name": "lenient",
                "pii_types": ["ip"],
                "pii_strategy": "redact",
                "apply_to_input": True,
            },
        ]
        result = apply_guardrails(configs, "Email: test@example.com, IP: 1.2.3.4")
        assert result.blocked
        assert len(result.violations) == 1


class TestGuardrailResult:
    """GuardrailResult 테스트"""

    def test_to_dict(self):
        config = {
            "pii_types": ["email"],
            "pii_strategy": "redact",
            "apply_to_input": True,
        }
        result = apply_guardrail(config, "test@example.com")
        d = result.to_dict()
        assert "processed_text" in d
        assert "violations" in d
        assert "blocked" in d

    def test_no_violations(self):
        config = {
            "pii_types": ["email"],
            "pii_strategy": "redact",
            "apply_to_input": True,
        }
        result = apply_guardrail(config, "Hello world")
        assert not result.has_violations
        assert result.text == "Hello world"


class TestLLMJudge:
    """LLM Judge 테스트"""

    def test_judge_disabled(self):
        config = {"llm_judge_enabled": False}
        judge = LLMJudge(config)
        assert not judge.enabled

    def test_judge_prompt_building(self):
        config = {
            "llm_judge_enabled": True,
            "llm_judge_model": "gpt-4",
            "llm_judge_prompt": "Check this content.",
            "llm_judge_pass_examples": ["Good content", "Normal text"],
            "llm_judge_block_examples": ["Bad content", "Harmful text"],
        }
        judge = LLMJudge(config)
        prompt = judge._build_prompt("Test content")
        assert "Check this content." in prompt
        assert "Test content" in prompt
        assert "Good content" in prompt
        assert "Bad content" in prompt
        assert "PASS" in prompt
        assert "BLOCK" in prompt

    def test_judge_apply_scope(self):
        config = {
            "llm_judge_enabled": True,
            "llm_judge_model": "gpt-4",
            "llm_judge_apply_to_input": True,
            "llm_judge_apply_to_output": False,
        }
        judge = LLMJudge(config)
        assert judge.apply_to_input
        assert not judge.apply_to_output

    def test_judge_not_enabled(self):
        async def _test():
            config = {"llm_judge_enabled": False}
            judge = LLMJudge(config)
            passed, reason, _ = await judge.judge("test", True, None)
            assert passed
            assert "not enabled" in reason

        asyncio.run(_test())

    def test_judge_no_model(self):
        async def _test():
            config = {"llm_judge_enabled": True, "llm_judge_model": None}
            judge = LLMJudge(config)
            passed, reason, _ = await judge.judge("test", True, None)
            assert passed
            assert "not configured" in reason

        asyncio.run(_test())


class TestApplyGuardrailWithLLM:
    """규칙 기반 + LLM Judge 통합 테스트"""

    def test_rule_based_only(self):
        """LLM 없이 규칙 기반만"""

        async def _test():
            config = {
                "pii_types": ["email"],
                "pii_strategy": "redact",
                "apply_to_input": True,
                "llm_judge_enabled": False,
            }
            result = await apply_guardrail_with_llm(config, "test@example.com")
            assert "[REDACTED_EMAIL]" in result.text
            assert not result.blocked

        asyncio.run(_test())

    def test_rule_blocked_skips_llm(self):
        """규칙에서 차단되면 LLM 스킵"""

        async def _test():
            config = {
                "pii_types": ["email"],
                "pii_strategy": "block",
                "apply_to_input": True,
                "llm_judge_enabled": True,
                "llm_judge_model": "gpt-4",
            }
            result = await apply_guardrail_with_llm(config, "test@example.com")
            assert result.blocked
            assert result.violations[0].type == "pii"

        asyncio.run(_test())

    def test_with_mock_llm_pass(self):
        """Mock LLM - PASS 응답"""

        async def _test():
            async def mock_generate(**kwargs):
                return {"choices": [{"message": {"content": "PASS"}}]}

            config = {
                "pii_types": [],
                "apply_to_input": True,
                "llm_judge_enabled": True,
                "llm_judge_model": "gpt-4",
                "llm_judge_apply_to_input": True,
            }
            result = await apply_guardrail_with_llm(
                config, "Hello world", generate_func=mock_generate
            )
            assert not result.blocked

        asyncio.run(_test())

    def test_with_mock_llm_block(self):
        """Mock LLM - BLOCK 응답"""

        async def _test():
            async def mock_generate(**kwargs):
                return {"choices": [{"message": {"content": "BLOCK"}}]}

            config = {
                "pii_types": [],
                "apply_to_input": True,
                "llm_judge_enabled": True,
                "llm_judge_model": "gpt-4",
                "llm_judge_apply_to_input": True,
            }
            result = await apply_guardrail_with_llm(
                config, "Bad content", generate_func=mock_generate
            )
            assert result.blocked
            assert "LLM judge" in result.block_reason
            assert any(v.type == "llm_judge" for v in result.violations)

        asyncio.run(_test())


class TestBoundaryDetection:
    """EXP-025: 한글/영문자 뒤 word boundary 실패 수정 검증"""

    def test_credit_card_after_korean(self):
        """한글 뒤 credit card 탐지 (기존 \\b에서 실패)"""
        pattern = PII_PATTERNS["credit_card"]["pattern"]
        assert re.search(pattern, "4111-1111-1111-1111ㅁ")

    def test_credit_card_after_alpha(self):
        """영문자 뒤 credit card 탐지"""
        pattern = PII_PATTERNS["credit_card"]["pattern"]
        assert re.search(pattern, "카드번호는4111-1111-1111-1111입니다")

    def test_credit_card_normal(self):
        """일반 credit card 탐지"""
        pattern = PII_PATTERNS["credit_card"]["pattern"]
        assert re.search(pattern, "4111-1111-1111-1111")

    def test_credit_card_no_digit_adjacent(self):
        """숫자 인접 시 미탐지 (18자리 숫자열 중간 매칭 방지)"""
        pattern = PII_PATTERNS["credit_card"]["pattern"]
        assert not re.search(pattern, "14111111111111111")

    def test_ip_after_alpha(self):
        """영문자 뒤 IP 탐지 (기존 \\b에서 실패)"""
        pattern = PII_PATTERNS["ip"]["pattern"]
        assert re.search(pattern, "10.1.0.10dk")

    def test_ip_after_korean(self):
        """한글 뒤 IP 탐지"""
        pattern = PII_PATTERNS["ip"]["pattern"]
        assert re.search(pattern, "서버10.1.0.10입니다")

    def test_ip_normal(self):
        """일반 IP 탐지"""
        pattern = PII_PATTERNS["ip"]["pattern"]
        assert re.search(pattern, "192.168.1.1")

    def test_ip_no_digit_adjacent(self):
        """숫자 인접 시 미탐지"""
        pattern = PII_PATTERNS["ip"]["pattern"]
        assert not re.search(pattern, "1192.168.1.1")

    def test_float_not_credit_card(self):
        """float 거리값이 credit_card로 오탐되지 않는지 확인 (회귀 테스트)"""
        engine = GuardrailEngine(
            {
                "pii_types": ["credit_card"],
                "pii_strategy": "redact",
                "apply_to_input": True,
            }
        )
        text = "distance: 2.329124689102173"
        _, violations, _ = engine.process_text(text, is_input=True)
        assert len(violations) == 0


class TestMaskingConsistency:
    """EXP-024: GuardrailEngine 마스킹 형식 확인"""

    def test_email_mask(self):
        """이메일 마스킹: 첫 글자 + *** @ *** + 도메인 마지막 4자"""
        engine = GuardrailEngine(
            {"pii_types": ["email"], "pii_strategy": "mask", "apply_to_input": True}
        )
        text = "jooho@cloocus.com"
        processed, violations, _ = engine.process_text(text, is_input=True)
        assert len(violations) == 1
        assert processed == "j***@***.com"

    def test_ip_mask(self):
        """IP 마스킹: 첫 옥텟 유지 + 나머지 ***"""
        engine = GuardrailEngine(
            {"pii_types": ["ip"], "pii_strategy": "mask", "apply_to_input": True}
        )
        text = "192.168.1.1"
        processed, violations, _ = engine.process_text(text, is_input=True)
        assert len(violations) == 1
        assert processed == "192.***.***.***"

    def test_credit_card_mask(self):
        """카드 마스킹: ****-****-****-마지막4자리"""
        engine = GuardrailEngine(
            {
                "pii_types": ["credit_card"],
                "pii_strategy": "mask",
                "apply_to_input": True,
            }
        )
        text = "4532015112830366"
        processed, violations, _ = engine.process_text(text, is_input=True)
        assert len(violations) == 1
        assert processed == "****-****-****-0366"

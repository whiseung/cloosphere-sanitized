"""Tests for AgentConfig grounding 토글 (capabilities.grounding).

grounding 은 엄격 근거 준수 모드의 binary(on/off) 토글이다. 명시값(on/off)은
그대로 존중하고, **미설정(None) 시 컨텍스트 기본**을 적용한다:
  - 에이전트(base_model_id 있음) → on (연결 리소스에 근거)
  - 기본 모델(base_model_id 없음) → off (근거할 소스 없는 plain LLM)
on = 연결 데이터에만 근거(없으면 "자료 없음" 명시). off = 부족 시 일반 지식 보완.
"""

from open_webui.models.agent_config import AgentConfig, CapabilitiesConfig

AGENT = "gpt-4"  # base_model_id 가 있으면 에이전트


class TestGroundingContextDefault:
    def test_agent_unset_defaults_on(self):
        # 에이전트(base_model_id 있음) + grounding 미설정 → on.
        c = AgentConfig.from_model_info(
            meta={"capabilities": {"web_search": "off"}},
            base_model_id=AGENT,
        )
        assert c.capabilities.grounding is None
        assert c.is_grounding_enabled() is True

    def test_base_model_unset_defaults_off(self):
        # 기본 모델(base_model_id 없음) + grounding 미설정 → off.
        c = AgentConfig.from_model_info(meta={"capabilities": {"web_search": "off"}})
        assert c.capabilities.grounding is None
        assert c.is_grounding_enabled() is False

    def test_legacy_no_capabilities_key_agent_on(self):
        # capabilities 키 자체가 없는 legacy 에이전트 → on.
        c = AgentConfig.from_model_info(meta={}, base_model_id=AGENT)
        assert c.is_grounding_enabled() is True

    def test_legacy_no_capabilities_key_base_model_off(self):
        c = AgentConfig.from_model_info(meta={})
        assert c.is_grounding_enabled() is False


class TestGroundingExplicitRespected:
    def test_explicit_off_on_agent(self):
        # 명시적 off 는 에이전트라도 그대로 off.
        c = AgentConfig.from_model_info(
            meta={"capabilities": {"grounding": "off"}}, base_model_id=AGENT
        )
        assert c.capabilities.grounding == "off"
        assert c.is_grounding_enabled() is False

    def test_explicit_on_on_base_model(self):
        # 명시적 on 은 기본 모델이라도 그대로 on.
        c = AgentConfig.from_model_info(meta={"capabilities": {"grounding": "on"}})
        assert c.capabilities.grounding == "on"
        assert c.is_grounding_enabled() is True


class TestGroundingNormalization:
    def test_boolean_true_normalized_on(self):
        assert CapabilitiesConfig(grounding=True).grounding == "on"

    def test_boolean_false_normalized_off(self):
        assert CapabilitiesConfig(grounding=False).grounding == "off"

    def test_unrecognized_value_normalized_none(self):
        # 미인식 문자열은 None(미설정) — 컨텍스트 기본이 적용되도록.
        assert CapabilitiesConfig(grounding="garbage").grounding is None

    def test_default_is_none(self):
        assert CapabilitiesConfig().grounding is None


class TestIsGroundingEnabledHelper:
    def test_none_capabilities_agent_returns_true(self):
        c = AgentConfig(capabilities=None, base_model_id=AGENT)
        assert c.is_grounding_enabled() is True

    def test_none_capabilities_base_model_returns_false(self):
        c = AgentConfig(capabilities=None)
        assert c.is_grounding_enabled() is False

    def test_explicit_off_returns_false(self):
        c = AgentConfig(
            capabilities=CapabilitiesConfig(grounding="off"), base_model_id=AGENT
        )
        assert c.is_grounding_enabled() is False

    def test_explicit_on_returns_true(self):
        c = AgentConfig(capabilities=CapabilitiesConfig(grounding="on"))
        assert c.is_grounding_enabled() is True

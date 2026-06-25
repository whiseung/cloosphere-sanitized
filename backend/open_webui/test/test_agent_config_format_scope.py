"""Tests for AgentConfig.format_prompt_scope + effective_format_prompt (PR5).

format_prompt_scope (params JSON 파생, DB 마이그레이션 없음) 가 현재 턴 chat upload
시 에이전트의 영구 format_prompt 적용 여부를 결정한다. fail-safe 기본 =
exclude_chat_uploads — 미설정/미인식 scope 는 업로드에 format 을 적용하지 않는다
(ad-hoc 업로드에 영구 포맷이 새는 것을 차단).

B1 결정: 필드는 유지하되 FE 는 생략 — params/raw API 로만 "always" override 가능.

Reference: dev/active/agent-file-context-prefetch/ (PR5)
"""

from open_webui.models.agent_config import AgentConfig


class TestFormatPromptScopeParsing:
    def test_scope_parsed_from_params(self):
        c = AgentConfig.from_model_info(params={"format_prompt_scope": "always"})
        assert c.format_prompt_scope == "always"

    def test_scope_absent_is_none(self):
        c = AgentConfig.from_model_info(params={"format_prompt": "X"})
        assert c.format_prompt_scope is None


class TestEffectiveFormatPrompt:
    # --- format_prompt 가 비어있으면 scope/upload 무관하게 항상 "" ---
    def test_empty_format_prompt_returns_empty_regardless(self):
        c = AgentConfig(format_prompt=None, format_prompt_scope="always")
        assert c.effective_format_prompt(has_chat_upload=True) == ""
        assert c.effective_format_prompt(has_chat_upload=False) == ""

    def test_whitespace_only_format_prompt_returns_empty(self):
        c = AgentConfig(format_prompt="   \n  ", format_prompt_scope="always")
        assert c.effective_format_prompt(has_chat_upload=False) == ""

    # --- 현재 턴 업로드 없음: scope 무관하게 항상 format_prompt 적용 ---
    def test_no_upload_always_applies_format_prompt(self):
        for scope in (None, "always", "exclude_chat_uploads", "garbage"):
            c = AgentConfig(format_prompt="FMT", format_prompt_scope=scope)
            assert c.effective_format_prompt(has_chat_upload=False) == "FMT"

    # --- 업로드 + scope=always: override, 적용 유지 (리포맷 전용 에이전트용 escape hatch) ---
    def test_upload_scope_always_keeps_format_prompt(self):
        c = AgentConfig(format_prompt="FMT", format_prompt_scope="always")
        assert c.effective_format_prompt(has_chat_upload=True) == "FMT"

    # --- 업로드 + scope=exclude_chat_uploads: 제외 ---
    def test_upload_scope_exclude_drops_format_prompt(self):
        c = AgentConfig(format_prompt="FMT", format_prompt_scope="exclude_chat_uploads")
        assert c.effective_format_prompt(has_chat_upload=True) == ""

    # --- 업로드 + scope 미설정(None): fail-safe exclude ---
    def test_upload_unset_scope_failsafe_exclude(self):
        c = AgentConfig(format_prompt="FMT", format_prompt_scope=None)
        assert c.effective_format_prompt(has_chat_upload=True) == ""

    # --- 업로드 + 미인식 scope 문자열: fail-safe exclude ---
    def test_upload_unrecognized_scope_failsafe_exclude(self):
        c = AgentConfig(format_prompt="FMT", format_prompt_scope="nonsense")
        assert c.effective_format_prompt(has_chat_upload=True) == ""

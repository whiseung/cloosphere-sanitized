"""
Teams bot router — M365 Agents SDK 통합 (feat/teams).

**격리 원칙**: 이 모듈은 Cloosphere 의 기존 채팅/에이전트 코드를 전혀 수정하지
않는다. 순수 어댑터 계층.

플로우:
    Teams → M365 Agents SDK → Cloosphere REST API
       - POST /api/v1/chats/new           (첫 턴 chat record 생성)
       - POST /api/chat/completions       (본 대화, chat_id + id 포함)
       - POST /api/v1/chats/{chat_id}     (응답 후 message tree 저장)
    Socket.IO 구독 → status/source 이벤트 relay → StreamingResponse UI

**계정 매핑**:
1. Teams Activity.from.aadObjectId → User.oauth_oid 매핑 → per-user JWT
2. 실패 시 TEAMS_BOT_TEST_JWT env fallback

**플랫폼 식별**: 요청 헤더 `X-Client-Type: teams` 가 main.py metadata.client_type 으로
전달되어 Usages 로그/관리자 모니터링에 "teams" 플랫폼으로 표시.

**P2 모드** (Azure Bot 등록됨):
- MsalConnectionManager + route 내부 JWT 검증
- env: TEAMS_BOT_APP_ID, TEAMS_BOT_APP_PASSWORD, TEAMS_BOT_TENANT_ID

**P1 모드** (Playground / 로컬):
- AnonymousConnections
- env 없을 때 자동 선택
"""

import asyncio
import contextvars
import json
import logging
import os
import time
import uuid
from datetime import timedelta
from functools import lru_cache
from pathlib import Path

import aiohttp
import socketio
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from microsoft_agents.authentication.msal import MsalConnectionManager
from microsoft_agents.hosting.core import (
    AgentApplication,
    AgentAuthConfiguration,
    AnonymousTokenProvider,
    AuthTypes,
    CardFactory,
    JwtTokenValidator,
    MemoryStorage,
    MessageFactory,
    TurnContext,
    TurnState,
)
from microsoft_agents.hosting.core.app.streaming.citation import Citation
from microsoft_agents.hosting.core.authorization import ClaimsIdentity
from microsoft_agents.hosting.fastapi import (
    CloudAdapter,
    StreamingResponse,
    start_agent_process,
)
from open_webui.models.users import Users
from open_webui.utils.auth import create_token

log = logging.getLogger(__name__)
router = APIRouter()


# ---- Configuration --------------------------------------------------------
# 설정값은 `request.app.state.config.TEAMS_BOT_*` (PersistentConfig 값 직접 반환) 우선,
# env 가 비어있고 config 도 비어있으면 fallback 으로 env 재확인.
# AppConfig.__getattr__ 는 PersistentConfig.value 를 바로 반환함에 주의.
def _cfg_get(app_state_config, name: str, default: str = "") -> str:
    try:
        v = getattr(app_state_config, name)
    except AttributeError:
        v = None
    if v is None or (isinstance(v, str) and v.strip() == ""):
        env_val = os.environ.get(name, default)
        if isinstance(env_val, str):
            return env_val.strip()
        return env_val
    if isinstance(v, str):
        return v.strip()
    return v


def _cfg_model_id(cfg) -> str:
    """관리자가 설정한 기본 에이전트. 미설정 시 빈 문자열 —
    이 경우 사용자는 `/agent` picker 로 반드시 먼저 선택해야 함.
    """
    return _cfg_get(cfg, "TEAMS_BOT_MODEL_ID", "")


def _cfg_test_jwt() -> str:
    """로컬 개발 fallback JWT — DB config 에 두지 않고 env 만."""
    return os.environ.get("TEAMS_BOT_TEST_JWT", "")


def _cfg_base_url() -> str:
    return os.environ.get("CLOOSPHERE_BASE_URL", "http://localhost:8080")


def _cfg_timeout_sec() -> int:
    return int(os.environ.get("TEAMS_BOT_BACKEND_TIMEOUT", "300"))


def _cfg_enabled(cfg) -> bool:
    try:
        v = getattr(cfg, "TEAMS_BOT_ENABLED")
    except AttributeError:
        v = None
    if v is None:
        return os.environ.get("TEAMS_BOT_ENABLED", "false").strip().lower() == "true"
    return bool(v)


# ---- i18n ----------------------------------------------------------------
# 프론트엔드와 같은 translation.json 파일을 그대로 재사용한다. 키는 `teams.bot.*`
# 네임스페이스로 구분. 지원 언어가 55개지만 실 번역은 ko-KR / en-US 만 채우고
# 나머지는 en-US fallback. Teams Activity.locale 을 기본으로 하되 `/lang` 으로 override.
_LOCALES_DIR_CANDIDATES = [
    Path("/cloosphere/src/lib/i18n/locales"),
    Path(__file__).resolve().parents[4] / "src" / "lib" / "i18n" / "locales",
]


def _locales_dir() -> Path:
    for p in _LOCALES_DIR_CANDIDATES:
        if p.is_dir():
            return p
    # 마지막 fallback: 현재 repo root 기준
    return Path("/cloosphere/src/lib/i18n/locales")


@lru_cache(maxsize=64)
def _load_translations(locale: str) -> dict:
    """translation.json 로드. 없으면 빈 dict."""
    path = _locales_dir() / locale / "translation.json"
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        log.exception("[teams_bot.i18n] failed to load %s", locale)
        return {}


def _available_locales() -> list[str]:
    try:
        return sorted(p.name for p in _locales_dir().iterdir() if p.is_dir())
    except Exception:
        return ["en-US", "ko-KR"]


_LOCALE_ALIASES = {"ko": "ko-KR", "en": "en-US", "ja": "ja-JP", "zh": "zh-CN"}


def _normalize_locale(locale: str | None) -> str:
    """임의 locale 문자열 → 실제 폴더명으로 정규화. 매칭 실패 시 en-US."""
    if not locale or not isinstance(locale, str):
        return "en-US"
    loc = locale.strip()
    if not loc:
        return "en-US"
    avail = set(_available_locales())
    # 1) 완전 일치
    if loc in avail:
        return loc
    # 2) 알리아스
    if loc in _LOCALE_ALIASES and _LOCALE_ALIASES[loc] in avail:
        return _LOCALE_ALIASES[loc]
    # 3) prefix 매칭 (ja-XX → ja-JP 등)
    prefix = loc.split("-")[0].lower()
    for candidate in avail:
        if candidate.lower().startswith(prefix + "-"):
            return candidate
        if candidate.lower() == prefix:
            return candidate
    return "en-US"


def t(key: str, locale: str | None = None, **kwargs) -> str:
    """key 를 locale 번역으로 반환. 없으면 en-US fallback, 그래도 없으면 key 자체.
    `{{var}}` 템플릿은 kwargs 로 치환 (i18next 호환)."""
    norm = _normalize_locale(locale)
    text = _load_translations(norm).get(key)
    if not text:
        text = _load_translations("en-US").get(key)
    if not text:
        text = key  # 최종 fallback — 키 자체 표시
    for k, v in kwargs.items():
        text = text.replace("{{" + k + "}}", str(v))
    return text


# 에이전트 status 이벤트의 영어 description → i18n 키 매핑.
_STATUS_KEY_MAP = {
    "Preparing context...": "teams.bot.status.preparing_context",
    "Processing your request...": "teams.bot.status.processing_request",
    "Starting Agent...": "teams.bot.status.starting_agent",
    "Agent completed...": "teams.bot.status.agent_completed",
    "Tool call: {{toolName}}": "teams.bot.status.tool_call",
    "Searching knowledge base...": "teams.bot.status.searching_kb",
    "Running SQL...": "teams.bot.status.running_sql",
    "Generating SQL...": "teams.bot.status.generating_sql",
    "Executing query...": "teams.bot.status.executing_query",
    "Thinking...": "teams.bot.status.thinking",
}


_SIO_CONNECT_TIMEOUT = 10

# Activity handler 내부에서 현재 request 의 config 에 접근하기 위한 ContextVar.
# messages_handler 가 request 시점에 set 하고, _on_message_impl 이 get 해서 사용.
_REQUEST_CONFIG: contextvars.ContextVar = contextvars.ContextVar(
    "teams_bot_request_config", default=None
)
# informative update 최대 개수 — 첫 한 번만 표시. 더 보내면 SDK queue drain 이
# 1초/item 속도라 final 뒤에 typing tail 이 길어지고 hot-reload 시 좀비 task 유발.
_MAX_INFORMATIVE_UPDATES = 1
# end_stream 이 pending queue drain 기다리다 block 되는 것을 방지하는 timeout.
_END_STREAM_TIMEOUT_SEC = 5.0

# ---- State KV (Redis-backed, 멀티워커 공유) ------------------------------
# Teams 봇은 여러 워커에 로드밸런싱되므로 세션 state 를 Redis 로 공유해야 한다.
# 값이 크지 않고 변경 빈도도 분당 수회 수준이라 sync Redis 직접 호출로 충분.
# Redis 미구성 시 per-process 메모리 fallback (single-worker 개발 환경).

_REDIS_CLIENT = (
    None  # lazy-init: None=미초기화, _NO_REDIS=초기화됐고 비활성, redis.Redis=사용중
)
_NO_REDIS = object()  # sentinel — Redis 없거나 연결 실패 상태


def _redis():
    """Lazy 싱글톤. Redis 미설정/연결 실패면 None 반환 (메모리 fallback)."""
    global _REDIS_CLIENT
    if _REDIS_CLIENT is _NO_REDIS:
        return None
    if _REDIS_CLIENT is not None:
        return _REDIS_CLIENT
    try:
        from open_webui.env import REDIS_SENTINEL_HOSTS, REDIS_SENTINEL_PORT, REDIS_URL
        from open_webui.utils.redis import get_redis_connection, get_sentinels_from_env

        if not REDIS_URL:
            _REDIS_CLIENT = _NO_REDIS
            log.info(
                "[teams_bot] REDIS_URL not set — using in-memory state (single-worker only)"
            )
            return None
        sentinels = get_sentinels_from_env(REDIS_SENTINEL_HOSTS, REDIS_SENTINEL_PORT)
        _REDIS_CLIENT = get_redis_connection(
            REDIS_URL, sentinels, decode_responses=True
        )
        return _REDIS_CLIENT
    except Exception:
        log.exception(
            "[teams_bot] Redis connect failed; falling back to in-memory state"
        )
        _REDIS_CLIENT = _NO_REDIS
        return None


# Namespace: "open-webui:teams:<kind>:<key>"
_KV_PREFIX = "open-webui:teams"
_TTL_USER_CHOICE = 30 * 86400  # 30d — 사용자 agent/locale 선택
_TTL_CONV_CHAT_ID = 7 * 86400  # 7d — Teams 대화 수명 정도
_TTL_MSG_TREE = 2 * 3600  # 2h — 최근 컨텍스트만 유지

# In-memory fallback (Redis 없을 때만 실질 사용).
_MEM_CONVERSATION_CHAT_ID: dict[str, str] = {}
_MEM_CONVERSATION_MSG_TREE: dict[str, dict] = {}
_MEM_USER_AGENT_CHOICE: dict[str, str] = {}
_MEM_USER_LANG: dict[str, str] = {}


def _kv_get(kind: str, key: str, mem: dict):
    r = _redis()
    if r is None:
        return mem.get(key)
    try:
        raw = r.get(f"{_KV_PREFIX}:{kind}:{key}")
        if raw is None:
            return None
        return json.loads(raw)
    except Exception:
        log.exception("[teams_bot] kv_get(%s, %s) failed", kind, key)
        return mem.get(key)


def _kv_set(kind: str, key: str, value, ttl: int, mem: dict) -> None:
    mem[key] = value  # 같은 워커에서 hot read 가속
    r = _redis()
    if r is None:
        return
    try:
        r.set(f"{_KV_PREFIX}:{kind}:{key}", json.dumps(value), ex=ttl)
    except Exception:
        log.exception("[teams_bot] kv_set(%s, %s) failed", kind, key)


def _kv_delete(kind: str, key: str, mem: dict) -> None:
    mem.pop(key, None)
    r = _redis()
    if r is None:
        return
    try:
        r.delete(f"{_KV_PREFIX}:{kind}:{key}")
    except Exception:
        pass


# /chat/completions payload 의 messages 로 직전 N 턴까지만 송신 (LLM context 제약).
# 전체 tree 는 DB 에 저장되어 사용자/관리자가 UI 에서 확인 가능.
_HISTORY_MAX_TURNS = 10

# ChoiceSet 표시할 최대 에이전트 개수 (Adaptive Card 가 너무 길어지면 렌더 부자연스럽)
_MAX_PICKER_CHOICES = 30


# ---- Cloosphere REST helpers ---------------------------------------------
async def _cloosphere_list_models(
    session: aiohttp.ClientSession, base_url: str, jwt: str
) -> list[dict]:
    """사용자가 접근 가능한 모델/에이전트 목록. /api/models 는 JWT 유저의 권한으로
    자동 필터링됨. 반환: [{id, name, base_model_id}, ...]. 실패 시 [].
    """
    try:
        async with session.get(
            f"{base_url}/api/models",
            headers={"Authorization": f"Bearer {jwt}"},
        ) as resp:
            if resp.status != 200:
                log.warning("[teams_bot] /api/models %s", resp.status)
                return []
            data = await resp.json()
            items = data.get("data") or []
            out = []
            for m in items:
                info = (m.get("info") or {}) if isinstance(m, dict) else {}
                out.append(
                    {
                        "id": m.get("id"),
                        "name": m.get("name") or m.get("id"),
                        "base_model_id": info.get("base_model_id"),
                    }
                )
            return out
    except Exception:
        log.exception("[teams_bot] list models failed")
        return []


def _build_agent_picker_card(
    current_id: str, models: list[dict], locale: str = "en-US"
) -> dict:
    """Teams Adaptive Card v1.5 — 에이전트 ChoiceSet + 저장 Action."""
    # 에이전트 (base_model_id 있는 것) 우선, 순수 모델은 뒤로.
    agents = [m for m in models if m.get("base_model_id")]
    raw_models = [m for m in models if not m.get("base_model_id")]
    sorted_list = agents + raw_models
    # 너무 많으면 자름
    sorted_list = sorted_list[:_MAX_PICKER_CHOICES]

    agent_marker = t("teams.bot.agent_marker", locale)
    choices = []
    for m in sorted_list:
        mid = m.get("id") or ""
        name = m.get("name") or mid
        marker = f" · {agent_marker}" if m.get("base_model_id") else ""
        choices.append({"title": f"{name}{marker}", "value": mid})

    # 기본 선택: 현재 값이 목록에 있으면 그것, 아니면 첫 번째
    default_value = current_id
    if not any(c["value"] == default_value for c in choices) and choices:
        default_value = choices[0]["value"]

    return {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.5",
        "body": [
            {
                "type": "TextBlock",
                "text": t("teams.bot.picker_title", locale),
                "weight": "Bolder",
                "size": "Medium",
                "wrap": True,
            },
            {
                "type": "TextBlock",
                "text": t(
                    "teams.bot.picker_current", locale, current=current_id or "—"
                ),
                "isSubtle": True,
                "spacing": "Small",
                "wrap": True,
            },
            {
                "type": "Input.ChoiceSet",
                "id": "agent_id",
                "value": default_value,
                "style": "compact",
                "choices": choices,
            },
        ],
        "actions": [
            {
                "type": "Action.Submit",
                "title": t("teams.bot.picker_save", locale),
                "data": {"action": "select_agent"},
            }
        ],
    }


async def _cloosphere_create_chat(
    session: aiohttp.ClientSession,
    base_url: str,
    jwt: str,
    title: str,
    teams_conversation_id: str | None = None,
) -> str | None:
    """Cloosphere chat record 생성. teams_conversation_id 가 주어지면 Chat.meta 에
    저장되어 재시작 후 lookup 가능. /chats/import 엔드포인트가 meta 직접 지원."""
    chat_meta = {}
    if teams_conversation_id:
        chat_meta = {
            "source": "teams",
            "teams_conversation_id": teams_conversation_id,
        }
    try:
        async with session.post(
            f"{base_url}/api/v1/chats/import",
            headers={
                "Authorization": f"Bearer {jwt}",
                "Content-Type": "application/json",
                "X-Client-Type": "teams",
            },
            json={
                "chat": {
                    "title": title,
                    "history": {"messages": {}, "currentId": None},
                },
                "meta": chat_meta,
            },
        ) as resp:
            if resp.status != 200:
                err = (await resp.text())[:200]
                log.warning("[teams_bot] /chats/import %s: %s", resp.status, err)
                return None
            data = await resp.json()
            return data.get("id")
    except Exception:
        log.exception("[teams_bot] create chat failed")
        return None


async def _cloosphere_find_chat_by_conv(
    session: aiohttp.ClientSession,
    base_url: str,
    jwt: str,
    teams_conversation_id: str,
) -> str | None:
    """재시작 이후 in-memory 캐시가 비어있을 때, 사용자 chat 중 meta 에 매칭되는
    항목을 찾아 chat_id 복원. /api/v1/chats/all 이 meta 포함된 ChatResponse 리턴.
    성능: 사용자 chat 수가 많을 수 있으므로 archived/pinned 제외하지 않고 전체 순회.
    """
    try:
        async with session.get(
            f"{base_url}/api/v1/chats/all",
            headers={"Authorization": f"Bearer {jwt}"},
        ) as resp:
            if resp.status != 200:
                log.warning("[teams_bot] /chats/all %s", resp.status)
                return None
            chats = await resp.json()
        for c in chats or []:
            if not isinstance(c, dict):
                continue
            meta = c.get("meta") or {}
            if (
                meta.get("source") == "teams"
                and meta.get("teams_conversation_id") == teams_conversation_id
            ):
                return c.get("id")
        return None
    except Exception:
        log.exception("[teams_bot] find chat by conv failed")
        return None


async def _cloosphere_update_chat(
    session: aiohttp.ClientSession,
    base_url: str,
    jwt: str,
    chat_id: str,
    chat_body: dict,
) -> bool:
    try:
        async with session.post(
            f"{base_url}/api/v1/chats/{chat_id}",
            headers={
                "Authorization": f"Bearer {jwt}",
                "Content-Type": "application/json",
                "X-Client-Type": "teams",
            },
            json={"chat": chat_body},
        ) as resp:
            if resp.status != 200:
                log.warning("[teams_bot] /chats/%s update %s", chat_id, resp.status)
                return False
            return True
    except Exception:
        log.exception("[teams_bot] update chat failed")
        return False


# ---- Message tree management (Redis-backed) ------------------------------
def _tree_state(conv_id: str) -> dict:
    """conv_id 별 tree state 를 Redis 에서 로드 (없으면 빈 상태). Mutation 후엔
    반드시 `_save_tree_state(conv_id, state)` 로 flush 해야 한다."""
    state = _kv_get("tree", conv_id, _MEM_CONVERSATION_MSG_TREE)
    if not isinstance(state, dict) or "messages" not in state:
        return {"messages": {}, "last_id": None}
    return state


def _save_tree_state(conv_id: str, state: dict) -> None:
    _kv_set("tree", conv_id, state, _TTL_MSG_TREE, _MEM_CONVERSATION_MSG_TREE)


def _delete_tree_state(conv_id: str) -> None:
    _kv_delete("tree", conv_id, _MEM_CONVERSATION_MSG_TREE)


def _get_conv_chat_id(conv_id: str) -> str | None:
    return _kv_get("chat", conv_id, _MEM_CONVERSATION_CHAT_ID)


def _set_conv_chat_id(conv_id: str, chat_id: str) -> None:
    _kv_set("chat", conv_id, chat_id, _TTL_CONV_CHAT_ID, _MEM_CONVERSATION_CHAT_ID)


def _delete_conv_chat_id(conv_id: str) -> None:
    _kv_delete("chat", conv_id, _MEM_CONVERSATION_CHAT_ID)


def _get_user_agent_choice(ukey: str) -> str | None:
    return _kv_get("agent", ukey, _MEM_USER_AGENT_CHOICE)


def _set_user_agent_choice(ukey: str, agent_id: str) -> None:
    _kv_set("agent", ukey, agent_id, _TTL_USER_CHOICE, _MEM_USER_AGENT_CHOICE)


def _get_user_lang(ukey: str) -> str | None:
    return _kv_get("lang", ukey, _MEM_USER_LANG)


def _set_user_lang(ukey: str, locale: str) -> None:
    _kv_set("lang", ukey, locale, _TTL_USER_CHOICE, _MEM_USER_LANG)


def _add_user_entry(conv_id: str, model_id: str, content: str) -> str:
    state = _tree_state(conv_id)
    user_msg_id = str(uuid.uuid4())
    ts = int(time.time())
    prev_id = state["last_id"]
    state["messages"][user_msg_id] = {
        "id": user_msg_id,
        "parentId": prev_id,
        "childrenIds": [],
        "role": "user",
        "content": content,
        "timestamp": ts,
        "models": [model_id],
    }
    if prev_id and prev_id in state["messages"]:
        state["messages"][prev_id]["childrenIds"].append(user_msg_id)
    state["last_id"] = user_msg_id
    _save_tree_state(conv_id, state)
    return user_msg_id


def _add_assistant_entry(
    conv_id: str, model_id: str, assistant_msg_id: str, content: str = ""
) -> None:
    state = _tree_state(conv_id)
    user_msg_id = state["last_id"]
    ts = int(time.time())
    state["messages"][assistant_msg_id] = {
        "id": assistant_msg_id,
        "parentId": user_msg_id,
        "childrenIds": [],
        "role": "assistant",
        "content": content,
        "timestamp": ts,
        "model": model_id,
        "modelName": model_id,
    }
    if user_msg_id and user_msg_id in state["messages"]:
        state["messages"][user_msg_id]["childrenIds"].append(assistant_msg_id)
    state["last_id"] = assistant_msg_id
    _save_tree_state(conv_id, state)


def _set_assistant_content(conv_id: str, assistant_msg_id: str, content: str) -> None:
    state = _tree_state(conv_id)
    if assistant_msg_id in state["messages"]:
        state["messages"][assistant_msg_id]["content"] = content
        state["messages"][assistant_msg_id]["timestamp"] = int(time.time())
        _save_tree_state(conv_id, state)


def _linear_messages(conv_id: str, max_turns: int) -> list[dict]:
    """현재 last_id 부터 parentId 체인을 역추적해 linear message list 생성.
    assistant 메시지가 아직 비어있으면 제외. 최근 max_turns*2 메시지만 리턴.
    """
    state = _tree_state(conv_id)
    msgs = state["messages"]
    cur = state["last_id"]
    linear = []
    while cur and cur in msgs:
        m = msgs[cur]
        if m["role"] == "assistant" and not (m.get("content") or "").strip():
            # 현재 진행 중인 assistant 빈 entry 는 payload 에 포함하지 않음
            cur = m.get("parentId")
            continue
        linear.append({"role": m["role"], "content": m["content"]})
        cur = m.get("parentId")
    linear.reverse()
    return linear[-(max_turns * 2) :]


def _chat_body_for_post(conv_id: str, title: str) -> dict:
    state = _tree_state(conv_id)
    return {
        "title": title,
        "history": {
            "messages": state["messages"],
            "currentId": state["last_id"],
        },
        "messages": [
            state["messages"][mid]
            for mid in state["messages"]
            if mid  # frontend 는 list 도 포함
        ],
    }


# ---- Anonymous Connections (P1) -------------------------------------------
class _AnonymousConnections:
    def __init__(self):
        self._provider = AnonymousTokenProvider()
        self._config = AgentAuthConfiguration(anonymous_allowed=True)

    def get_connection(self, connection_name: str):
        return self._provider

    def get_default_connection(self):
        return self._provider

    def get_token_provider(self, claims_identity, service_url: str):
        return self._provider

    def get_default_connection_configuration(self):
        return self._config


# ---- P1/P2 모드 lazy 빌드 (config-driven) --------------------------------
# 관리자 UI 에서 credentials 가 변경되면 signature 가 바뀌어 자동 재생성.
# _RUNTIME 캐시: {signature, adapter, validator, p2_mode, agent_app}
_RUNTIME: dict = {"signature": None}


def _runtime_signature(cfg) -> str:
    app_id = _cfg_get(cfg, "TEAMS_BOT_APP_ID", "")
    password = _cfg_get(cfg, "TEAMS_BOT_APP_PASSWORD", "")
    tenant = _cfg_get(cfg, "TEAMS_BOT_TENANT_ID", "")
    # 비밀번호는 길이+앞 6자로 축약해서 signature 에 포함 (변경 감지용)
    pw_sig = f"{len(password)}:{password[:6]}" if password else ""
    return f"{app_id}|{pw_sig}|{tenant}"


def _build_runtime_components(app_id: str, password: str, tenant_id: str):
    """Config 기반으로 connection_manager/validator/p2_mode/agent_app 생성."""
    effective_tenant = tenant_id or "common"
    if app_id and password:
        log.info(
            "[teams_bot] P2 mode: config 기반 credentials (app_id=%s..., tenant=%s)",
            app_id[:8],
            effective_tenant,
        )
        service_config = AgentAuthConfiguration(
            auth_type=AuthTypes.client_secret,
            client_id=app_id,
            client_secret=password,
            tenant_id=effective_tenant,
        )
        connection_manager = MsalConnectionManager(
            connections_configurations={"SERVICE_CONNECTION": service_config}
        )
        validator = JwtTokenValidator(service_config)
        p2_mode = True
    else:
        log.info("[teams_bot] P1 mode: anonymous auth (config/env credentials 없음)")
        connection_manager = _AnonymousConnections()
        validator = None
        p2_mode = False

    agent_app = AgentApplication[TurnState](
        storage=MemoryStorage(),
        adapter=CloudAdapter(connection_manager=connection_manager),
    )
    _register_activity_handlers(agent_app)
    return {
        "adapter": agent_app.adapter,
        "validator": validator,
        "p2_mode": p2_mode,
        "agent_app": agent_app,
    }


def _get_runtime(request: Request) -> dict:
    """Request 시점 config 로 runtime 을 얻거나 생성. signature 불변이면 캐시 재사용."""
    cfg = request.app.state.config
    sig = _runtime_signature(cfg)
    if _RUNTIME.get("signature") != sig:
        app_id = _cfg_get(cfg, "TEAMS_BOT_APP_ID", "")
        password = _cfg_get(cfg, "TEAMS_BOT_APP_PASSWORD", "")
        tenant = _cfg_get(cfg, "TEAMS_BOT_TENANT_ID", "")
        _RUNTIME.update(_build_runtime_components(app_id, password, tenant))
        _RUNTIME["signature"] = sig
    return _RUNTIME


# activity 핸들러 함수는 아래에서 정의되며, _register_activity_handlers 로 AgentApplication
# 인스턴스에 연결한다. (AgentApplication 이 재생성될 때마다 재등록 필요)
def _register_activity_handlers(agent_app: "AgentApplication") -> None:
    @agent_app.activity("message")
    async def _on_message(context: TurnContext, state: TurnState) -> None:
        await _on_message_impl(context, state)


def _resolve_user_jwt(activity) -> tuple[str, str]:
    """aadObjectId → User.oauth_oid → per-user JWT. 실패 시 TEAMS_BOT_TEST_JWT fallback."""
    sender = getattr(activity, "from_property", None)
    aad_oid = getattr(sender, "aad_object_id", None) if sender else None

    if aad_oid:
        user = Users.get_user_by_oauth_oid(aad_oid)
        if user:
            jwt = create_token(
                data={"id": user.id},
                expires_delta=timedelta(hours=1),
            )
            return jwt, f"user:{user.email}"
        log.info(
            "[teams_bot] aadObjectId %s 로 매칭되는 Cloosphere 사용자 없음. fallback 사용.",
            aad_oid,
        )

    fallback = _cfg_test_jwt()
    if fallback:
        return fallback, "fallback:TEAMS_BOT_TEST_JWT"
    return "", "none"


# 사용자별 locale override (/lang 로 설정). key: aadObjectId or from.id
def _resolve_locale(activity, ukey: str | None) -> str:
    """locale 우선순위: 사용자 override > activity.locale > env 기본 > en-US."""
    if ukey:
        override = _get_user_lang(ukey)
        if override:
            return override
    activity_locale = getattr(activity, "locale", None) if activity else None
    if activity_locale:
        return _normalize_locale(activity_locale)
    env_default = os.environ.get("TEAMS_BOT_DEFAULT_LOCALE", "").strip()
    if env_default:
        return _normalize_locale(env_default)
    return "en-US"


def _format_status_text(ev_data: dict, locale: str) -> str:
    """에이전트가 영어로 emit 한 status description 을 locale 에 맞게 번역."""
    description = (ev_data.get("description") or "").strip()
    detail = (ev_data.get("detail") or "").strip()
    key = _STATUS_KEY_MAP.get(description)
    if key:
        if key == "teams.bot.status.tool_call":
            return t(key, locale, tool=detail or "?")
        return t(key, locale)
    # Unmapped status — 그대로 원문 반환 (fallback)
    if description and "{{toolName}}" in description and detail:
        description = description.replace("{{toolName}}", detail)
    return description or detail


import re as _re


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """본문 맨 앞 `---\\n...key: value...\\n---` frontmatter 파싱.
    Returns (meta dict, body 본문). frontmatter 없으면 ({}, text) 리턴.
    """
    m = _re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", text or "", flags=_re.DOTALL)
    if not m:
        return {}, text or ""
    meta = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            meta[k.strip()] = v.strip()
    return meta, m.group(2)


def _source_to_citation(source_data: dict) -> Citation | None:
    """Cloosphere source 이벤트 → Teams Citation 변환.

    KG/KB 에이전트가 emit 하는 source.name 은 제네릭 라벨("Knowledge Graph —
    Document Search" 등) 이라 citation 구분이 안 됨. document[] 첫 청크의
    frontmatter 에서 실제 문서 식별 정보(품목명, 문서유형 등)를 뽑아 title 을 구성.
    """
    if not isinstance(source_data, dict):
        return None
    src_obj = source_data.get("source") or {}
    docs = source_data.get("document") or []
    meta = source_data.get("metadata") or []

    # 본문 청크(첫 번째 사용). frontmatter 파싱해서 meaningful title 생성 시도.
    raw_first = ""
    if docs and isinstance(docs[0], str):
        raw_first = docs[0]
    elif isinstance(src_obj.get("content"), str):
        raw_first = src_obj["content"]

    fm, body = _parse_frontmatter(raw_first)

    # Title 우선순위:
    #   frontmatter(품목명·문서명·title 등) > source.name > metadata > "Source"
    candidate_title = (
        fm.get("품목명") or fm.get("title") or fm.get("name") or fm.get("문서명")
    )
    doc_type = fm.get("문서유형") or fm.get("type")
    if candidate_title and doc_type:
        title = f"{candidate_title} · {doc_type}"
    elif candidate_title:
        title = candidate_title
    else:
        # metadata 리스트 (list[dict]) 에서 fallback 탐색
        if isinstance(meta, list) and meta and isinstance(meta[0], dict):
            title = (
                meta[0].get("name")
                or meta[0].get("title")
                or src_obj.get("name")
                or "Source"
            )
        else:
            title = src_obj.get("name") or src_obj.get("id") or "Source"

    # Content: frontmatter 걷어낸 body 첫 500자. body 가 비었으면 원문 사용.
    content = (body or raw_first)[:500]

    # URL: source.url > metadata url > None (KG 는 대부분 None)
    url = src_obj.get("url") or None
    if not url and isinstance(meta, list) and meta and isinstance(meta[0], dict):
        url = meta[0].get("url") or None

    # filepath: Teams 가 "file://..." 링크 제공용. source.file_id 있으면 사용.
    filepath = src_obj.get("file_id") or fm.get("품목기준코드") or None

    if not content:
        return None
    return Citation(content=content, title=title, url=url, filepath=filepath)


# ---- Main message handler -------------------------------------------------
def _user_key(activity) -> str | None:
    """사용자 state 키 (agent 선택/locale 등). oauth_oid 우선, 없으면 from.id."""
    sender = getattr(activity, "from_property", None)
    if not sender:
        return None
    return getattr(sender, "aad_object_id", None) or getattr(sender, "id", None)


async def _on_message_impl(context: TurnContext, _state: TurnState) -> None:
    """실제 메시지 처리 로직. `_register_activity_handlers` 가 AgentApplication 에
    연결해 message activity 처리. request config 는 ContextVar `_REQUEST_CONFIG` 로 접근.
    """
    activity = context.activity
    user_text = (activity.text or "").strip()
    ukey = _user_key(activity)
    # Locale 결정: 사용자 override > Teams activity.locale > env 기본 > en-US
    locale = _resolve_locale(activity, ukey)

    # Submit action (Adaptive Card 저장) — value 에 데이터 실려옴.
    submit_value = getattr(activity, "value", None)
    if isinstance(submit_value, dict) and submit_value.get("action") == "select_agent":
        chosen = (submit_value.get("agent_id") or "").strip()
        if chosen and ukey:
            _set_user_agent_choice(ukey, chosen)
            await context.send_activity(
                t("teams.bot.agent_changed", locale, agent=chosen)
            )
        else:
            await context.send_activity(t("teams.bot.no_agent_info", locale))
        return

    if not user_text and submit_value is None:
        await context.send_activity(t("teams.bot.empty_message", locale))
        return

    jwt, resolution = _resolve_user_jwt(activity)
    if not jwt:
        await context.send_activity(t("teams.bot.user_match_failed", locale))
        return
    log.info("[teams_bot] jwt resolution: %s", resolution)

    # request 시점 config (messages_handler 가 ContextVar 에 set)
    cfg = _REQUEST_CONFIG.get()
    base_url = _cfg_base_url()

    # 슬래시 명령 처리. Teams commandLists 자동완성은 텍스트에 "/" 를 포함하지
    # 않을 수 있으므로 양쪽 형태 모두 허용 — "/agent" 와 "agent" 둘 다 매칭.
    conv_obj_early = getattr(activity, "conversation", None)
    conv_id = getattr(conv_obj_early, "id", None) or "default"
    cmd_tokens = user_text.lower().split()
    cmd_head = cmd_tokens[0].lstrip("/") if cmd_tokens else ""
    if cmd_head in ("pick", "agents", "agent", "model"):
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as s:
            models = await _cloosphere_list_models(s, base_url, jwt)
        if not models:
            await context.send_activity(t("teams.bot.no_accessible_agents", locale))
            return
        current = (_get_user_agent_choice(ukey) if ukey else None) or _cfg_model_id(cfg)
        card = _build_agent_picker_card(current, models, locale)
        await context.send_activity(
            MessageFactory.attachment(CardFactory.adaptive_card(card))
        )
        return
    if cmd_head in ("current", "me"):
        current = (_get_user_agent_choice(ukey) if ukey else None) or _cfg_model_id(cfg)
        if current:
            await context.send_activity(
                t("teams.bot.current_agent", locale, agent=current)
            )
        else:
            await context.send_activity(t("teams.bot.no_selected_agent", locale))
        return
    if cmd_head in ("reset", "new", "clear"):
        _delete_conv_chat_id(conv_id)
        _delete_tree_state(conv_id)
        await context.send_activity(t("teams.bot.reset_banner", locale))
        return
    if cmd_head in ("lang", "language", "locale"):
        # /lang <code> — 사용자별 locale override 설정
        requested = cmd_tokens[1] if len(cmd_tokens) >= 2 else ""
        if not requested:
            await context.send_activity(t("teams.bot.lang_unsupported", locale))
            return
        norm = _normalize_locale(requested)
        requested_prefix = requested.split("-")[0].lower()
        # _normalize_locale 는 매칭 실패 시 en-US 로 fallback 하므로, 요청이 en 계열이 아닌데
        # 결과가 en-US 면 미지원 코드로 간주.
        if norm == "en-US" and requested_prefix != "en":
            await context.send_activity(t("teams.bot.lang_unsupported", locale))
            return
        if ukey:
            _set_user_lang(ukey, norm)
        await context.send_activity(t("teams.bot.lang_set", norm, code=norm))
        return
    if cmd_head in ("help", "?"):
        await context.send_activity(t("teams.bot.help_text", locale))
        return

    # 모델 결정: 사용자 선택값 > config/env 기본값.
    model_id = (_get_user_agent_choice(ukey) if ukey else None) or _cfg_model_id(cfg)
    if not model_id:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as s:
            models = await _cloosphere_list_models(s, base_url, jwt)
        if not models:
            await context.send_activity(t("teams.bot.no_accessible_agents", locale))
            return
        card = _build_agent_picker_card("", models, locale)
        await context.send_activity(
            MessageFactory.attachment(CardFactory.adaptive_card(card))
        )
        await context.send_activity(t("teams.bot.select_agent_first", locale))
        return

    # conv_id 는 명령 처리 섹션에서 이미 계산했으므로 재사용.

    # tree 에 user 엔트리 append → assistant 엔트리 placeholder 생성
    _add_user_entry(conv_id, model_id, user_text)
    assistant_msg_id = str(uuid.uuid4())
    _add_assistant_entry(conv_id, model_id, assistant_msg_id, content="")
    turn_message_id = assistant_msg_id  # Socket.IO 필터 + Cloosphere usage/trace

    streaming = StreamingResponse(context)
    # Teams citation 카드 는 "AI-generated" 라벨이 있을 때만 정상 렌더. feedback_loop
    # 은 일부 클라이언트에서 final message 포맷 문제 일으킴 — 우선 생략.
    try:
        streaming.set_generated_by_ai_label(True)
    except Exception:
        log.exception("[teams_bot] set_generated_by_ai_label failed")
    streaming.queue_informative_update(
        t("teams.bot.calling_model", locale, model=model_id)
    )

    citations: list[Citation] = []
    event_counts = {
        "status": 0,
        "status_dropped": 0,
        "source": 0,
        "other": 0,
        "filtered": 0,
        "late": 0,
    }
    stream_open = True
    token_streaming_started = False
    last_informative_text = ""
    last_informative_ts = 0.0
    informative_sent_count = 0

    sio_client = socketio.AsyncClient(reconnection=False, logger=False)

    @sio_client.on("chat-events")
    async def on_chat_events(data):
        nonlocal last_informative_text, last_informative_ts
        if not isinstance(data, dict):
            return
        incoming_mid = data.get("message_id")
        incoming_type = (data.get("data") or {}).get("type")
        if incoming_mid != turn_message_id:
            log.info(
                "[teams_bot] FILTERED event: type=%s incoming_mid=%s expected=%s",
                incoming_type,
                incoming_mid,
                turn_message_id,
            )
            event_counts["filtered"] += 1
            return
        # 매칭 이벤트는 로그 남겨서 source 이벤트가 실제 도착하는지 추적
        log.info("[teams_bot] MATCH event: type=%s mid=%s", incoming_type, incoming_mid)
        if not stream_open:
            event_counts["late"] += 1
            return
        event = data.get("data") or {}
        etype = event.get("type")
        edata = event.get("data") or {}
        if etype == "status":
            nonlocal informative_sent_count
            if token_streaming_started:
                event_counts["status_dropped"] += 1
                return
            # MAX 개수 제한 — 초기 "호출 중…" 후 추가 progress 는 모두 drop.
            # SDK queue drain 이 1초/item 이라 여러 개 큐잉하면 final 뒤 tail 발생.
            if informative_sent_count >= _MAX_INFORMATIVE_UPDATES:
                event_counts["status_dropped"] += 1
                return
            text = _format_status_text(edata, locale)
            if not text or text == last_informative_text:
                event_counts["status_dropped"] += 1
                return
            event_counts["status"] += 1
            last_informative_text = text
            last_informative_ts = time.monotonic()
            informative_sent_count += 1
            try:
                streaming.queue_informative_update(text)
            except RuntimeError:
                event_counts["late"] += 1
        elif etype in ("source", "citation"):
            event_counts["source"] += 1
            log.info("[teams_bot] raw source event keys=%s", list(edata.keys()))
            log.info(
                "[teams_bot] raw source event dump: %s",
                json.dumps(edata, ensure_ascii=False, default=str)[:800],
            )
            cit = _source_to_citation(edata)
            if cit is not None:
                log.info(
                    "[teams_bot] mapped Citation: title=%r content_len=%d url=%s filepath=%s",
                    cit.title,
                    len(cit.content or ""),
                    cit.url,
                    cit.filepath,
                )
                citations.append(cit)
            else:
                log.warning("[teams_bot] source → Citation mapping returned None")
        else:
            event_counts["other"] += 1

    socketio_connected = False
    try:
        await sio_client.connect(
            base_url,
            socketio_path="/ws/socket.io",
            auth={"token": jwt},
            transports=["websocket"],
            wait_timeout=_SIO_CONNECT_TIMEOUT,
        )
        socketio_connected = True
    except Exception as e:
        log.warning(
            "[teams_bot] Socket.IO connect failed: %s — status/citations 표시 스킵됨", e
        )

    accumulated = ""
    chat_title = f"Teams: {user_text[:40]}"
    chat_id: str | None = None

    timeout = aiohttp.ClientTimeout(total=_cfg_timeout_sec())
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            # 1) chat 확보 (첫 턴이면 생성)
            #    우선순위: (a) Redis 캐시 (워커간 공유) → (b) Cloosphere DB 에
            #    teams_conversation_id meta 로 저장된 기존 chat lookup → (c) 신규 생성.
            chat_id = _get_conv_chat_id(conv_id)
            if not chat_id:
                chat_id = await _cloosphere_find_chat_by_conv(
                    session, base_url, jwt, conv_id
                )
                if chat_id:
                    log.info(
                        "[teams_bot] Cloosphere chat reused from meta lookup: "
                        "conv=%s → chat_id=%s",
                        conv_id[:20],
                        chat_id,
                    )
                else:
                    chat_id = await _cloosphere_create_chat(
                        session,
                        base_url,
                        jwt,
                        chat_title,
                        teams_conversation_id=conv_id,
                    )
                    if chat_id:
                        log.info(
                            "[teams_bot] Cloosphere chat created: conv=%s → chat_id=%s",
                            conv_id[:20],
                            chat_id,
                        )
                if chat_id:
                    _set_conv_chat_id(conv_id, chat_id)

            # 2) payload — chat_id, id(=assistant_msg_id), messages(linear window), X-Client-Type
            messages_payload = _linear_messages(conv_id, _HISTORY_MAX_TURNS)
            payload = {
                "model": model_id,
                "stream": True,
                "messages": messages_payload,
                "id": assistant_msg_id,
                "chat_id": chat_id,  # None 이어도 안전
            }

            async with session.post(
                f"{base_url}/api/chat/completions",
                headers={
                    "Authorization": f"Bearer {jwt}",
                    "Content-Type": "application/json",
                    "Accept": "text/event-stream",
                    "X-Client-Type": "teams",
                },
                json=payload,
            ) as resp:
                if resp.status != 200:
                    err_text = (await resp.text())[:300]
                    log.warning(
                        "[teams_bot] backend returned %s: %s", resp.status, err_text
                    )
                    streaming.queue_text_chunk(
                        t(
                            "teams.bot.backend_error",
                            locale,
                            status=resp.status,
                            err=err_text,
                        )
                    )
                    return

                async for raw_line in resp.content:
                    line = raw_line.decode("utf-8", errors="ignore").strip()
                    if not line.startswith("data:"):
                        continue
                    data_str = line[len("data:") :].strip()
                    if not data_str or data_str == "[DONE]":
                        if data_str == "[DONE]":
                            break
                        continue
                    try:
                        chunk = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    piece = delta.get("content") or ""
                    if piece:
                        accumulated += piece
                        token_streaming_started = True
                        streaming.queue_text_chunk(piece)

        if not accumulated:
            streaming.queue_text_chunk(t("teams.bot.empty_response", locale))
        _set_assistant_content(conv_id, assistant_msg_id, accumulated)
    except aiohttp.ClientError as e:
        log.exception("[teams_bot] client error")
        streaming.queue_text_chunk(t("teams.bot.network_error", locale, err=str(e)))
    except Exception:
        log.exception("[teams_bot] unexpected error")
        streaming.queue_text_chunk(t("teams.bot.unexpected_error", locale))
    finally:
        stream_open = False
        if socketio_connected:
            try:
                await sio_client.disconnect()
            except Exception:
                pass
        try:
            await asyncio.sleep(0.1)
        except Exception:
            pass
        if citations:
            try:
                streaming.set_citations(citations)
            except Exception:
                log.exception("[teams_bot] set_citations failed")
        try:
            await asyncio.wait_for(
                streaming.end_stream(), timeout=_END_STREAM_TIMEOUT_SEC
            )
        except asyncio.TimeoutError:
            log.warning(
                "[teams_bot] end_stream timed out after %ds — pending queue 강제 포기",
                _END_STREAM_TIMEOUT_SEC,
            )
        except RuntimeError as e:
            log.warning("[teams_bot] end_stream error (likely already ended): %s", e)

        # 3) Cloosphere chat record 업데이트 (full tree) — 관리자 모니터링/추적/토큰 사용량
        if chat_id and accumulated:
            try:
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    ok = await _cloosphere_update_chat(
                        session,
                        base_url,
                        jwt,
                        chat_id,
                        _chat_body_for_post(conv_id, chat_title),
                    )
                    if not ok:
                        log.warning(
                            "[teams_bot] chat update failed chat_id=%s", chat_id
                        )
            except Exception:
                log.exception("[teams_bot] chat update exception")

        log.info(
            "[teams_bot] bridge events: status=%d status_dropped=%d source=%d "
            "other=%d filtered=%d late=%d citations_attached=%d chat_id=%s",
            event_counts["status"],
            event_counts["status_dropped"],
            event_counts["source"],
            event_counts["other"],
            event_counts["filtered"],
            event_counts["late"],
            len(citations),
            chat_id,
        )


# ---- FastAPI route --------------------------------------------------------
@router.post("/messages")
async def messages_handler(request: Request):
    cfg = request.app.state.config
    # 비활성화 상태면 Teams 에 403 — 관리자가 의도적으로 끈 경우.
    if not _cfg_enabled(cfg):
        return JSONResponse(
            {"error": "Teams bot is disabled. Enable it in admin settings."},
            status_code=403,
        )
    runtime = _get_runtime(request)
    if runtime["p2_mode"]:
        auth_header = request.headers.get("Authorization", "")
        parts = auth_header.split(" ", 1)
        if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
            return JSONResponse(
                {"error": "Authorization: Bearer <token> required"}, status_code=401
            )
        try:
            claims = await runtime["validator"].validate_token(parts[1].strip())
            request.state.claims_identity = claims
        except ValueError as e:
            log.warning("[teams_bot] P2 JWT 검증 실패: %s", e)
            return JSONResponse(
                {"error": "Invalid bot framework token"}, status_code=401
            )
    else:
        request.state.claims_identity = ClaimsIdentity(
            claims={}, is_authenticated=False, authentication_type="Anonymous"
        )
    # ContextVar 로 request config 를 activity 핸들러에 전파
    token = _REQUEST_CONFIG.set(cfg)
    try:
        return await start_agent_process(
            request, runtime["agent_app"], runtime["adapter"]
        )
    finally:
        _REQUEST_CONFIG.reset(token)


@router.get("/messages")
async def messages_health(request: Request):
    cfg = request.app.state.config
    runtime = _get_runtime(request)
    return {
        "status": "ok",
        "bot": "cloosphere-teams",
        "enabled": _cfg_enabled(cfg),
        "mode": "p2-azure-bot" if runtime["p2_mode"] else "p1-anonymous",
        "model": _cfg_model_id(cfg),
        "jwt_configured": bool(_cfg_test_jwt()),
        "active_conversations_cached": len(_MEM_CONVERSATION_CHAT_ID),
        "redis_backed": _redis() is not None,
    }

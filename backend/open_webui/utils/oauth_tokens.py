"""사용자별 OAuth 토큰 자동 갱신 helper.

`UserOAuthTokens` 테이블의 access_token 이 만료 임박이면 refresh_token 으로
갱신해 새 access_token 을 반환한다. Outlook / Gmail 도구 진입점에서 사용해
호출 측이 만료 처리를 신경 쓰지 않게 한다.

refresh 실패 시 None 반환 — row 삭제는 호출 측 책임. 무차별 삭제는 transient
실패에서 사용자 연결을 잃게 만들기 때문.
"""

import logging
import time
from typing import Optional

import aiohttp
from open_webui.config import (
    GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET,
    MICROSOFT_CLIENT_ID,
    MICROSOFT_CLIENT_SECRET,
    MICROSOFT_CLIENT_TENANT_ID,
)
from open_webui.env import SRC_LOG_LEVELS
from open_webui.models.user_oauth_tokens import UserOAuthTokens

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS.get("OAUTH", "INFO"))

# expires_at 까지 60초 미만 남았으면 미리 갱신.
_REFRESH_LEEWAY_SEC = 60
_HTTP_TIMEOUT = aiohttp.ClientTimeout(total=10)


async def _refresh_microsoft(refresh_token: str) -> Optional[dict]:
    url = (
        f"https://login.microsoftonline.com/"
        f"{MICROSOFT_CLIENT_TENANT_ID.value}/oauth2/v2.0/token"
    )
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": MICROSOFT_CLIENT_ID.value,
        "client_secret": MICROSOFT_CLIENT_SECRET.value,
    }
    async with aiohttp.ClientSession(timeout=_HTTP_TIMEOUT) as s:
        async with s.post(url, data=data) as resp:
            try:
                body = await resp.json()
            except Exception:
                body = {"raw": await resp.text()}
            if not resp.ok:
                log.warning(
                    f"microsoft refresh failed status={resp.status} body={body}"
                )
                return None
            return body


async def _refresh_google(refresh_token: str) -> Optional[dict]:
    url = "https://oauth2.googleapis.com/token"
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": GOOGLE_CLIENT_ID.value,
        "client_secret": GOOGLE_CLIENT_SECRET.value,
    }
    async with aiohttp.ClientSession(timeout=_HTTP_TIMEOUT) as s:
        async with s.post(url, data=data) as resp:
            try:
                body = await resp.json()
            except Exception:
                body = {"raw": await resp.text()}
            if not resp.ok:
                log.warning(f"google refresh failed status={resp.status} body={body}")
                return None
            return body


def resolver_for_auth_type(user_id: Optional[str], auth_type: Optional[str]):
    """tool_connection 의 auth_type 을 보고 동적 토큰 resolver 를 만들어준다.

    auth_type='oauth_microsoft' / 'oauth_google' 이고 user_id 가 있으면
    호출마다 `get_valid_access_token(user_id, provider)` 를 실행하는 비동기
    callable 반환. 그 외엔 None — 정적 인증 (bearer / api_key) 사용.

    `MCPClient(... token_resolver=...)` 와 OpenAPI connector 양쪽에서 공용으로
    쓰여 ToolConnectionManager / 라우터 / 그 외 통합 지점이 같은 흐름을 갖는다.
    """
    if not user_id:
        return None
    provider_map = {"oauth_microsoft": "microsoft", "oauth_google": "google"}
    provider = provider_map.get((auth_type or "").lower())
    if not provider:
        return None

    async def _resolver():
        return await get_valid_access_token(user_id, provider)

    return _resolver


async def get_valid_access_token(user_id: str, provider: str) -> Optional[str]:
    """현재 access_token 반환. 만료 임박이면 refresh_token 으로 갱신 후 반환.

    None 을 반환하는 경우:
      - 사용자가 해당 provider 에 연결돼 있지 않음 (row 없음)
      - refresh_token 이 없어 갱신 불가
      - refresh 호출이 실패 (네트워크 / invalid_grant / 서버 오류)

    호출 측은 None 시 사용자에게 "재로그인 필요" 안내.
    """
    row = UserOAuthTokens.get(user_id, provider)
    if row is None:
        return None
    now = int(time.time())
    if row.expires_at - now > _REFRESH_LEEWAY_SEC:
        return row.access_token
    if not row.refresh_token:
        return None

    if provider == "microsoft":
        body = await _refresh_microsoft(row.refresh_token)
    elif provider == "google":
        body = await _refresh_google(row.refresh_token)
    else:
        log.warning(f"refresh not implemented for provider={provider}")
        return None

    if not body or not body.get("access_token"):
        return None

    expires_in = int(body.get("expires_in") or 3600)
    UserOAuthTokens.upsert(
        user_id=user_id,
        provider=provider,
        access_token=body["access_token"],
        refresh_token=body.get("refresh_token"),  # 빈 값이면 upsert 가 기존 값 보존
        expires_at=now + expires_in,
        scopes=body.get("scope") or row.scopes,
        account_email=row.account_email,
    )
    return body["access_token"]

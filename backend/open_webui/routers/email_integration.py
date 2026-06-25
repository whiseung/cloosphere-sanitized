"""사용자별 OAuth provider 연결 상태 조회/해제.

admin 토글은 제거됨 (Microsoft / Google OAuth 가 설정돼 있으면 SSO 로그인 시
GRAPH/GMAIL 위임 권한 scope 가 항상 결합되며, 실제 노출은 Azure / Google
Cloud Console 의 admin grant 정책으로 통제). 본 라우터는 사용자가 본인의
OAuth 토큰 row 가 어떤 provider 로 보관돼 있는지 확인하고 필요 시 disconnect
(token row 삭제 → 재로그인 강제) 할 수 있게 한다.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from open_webui.config import GWS_FEATURE_REQUIRED_SCOPES
from open_webui.constants import ERROR_MESSAGES
from open_webui.env import SRC_LOG_LEVELS
from open_webui.models.user_oauth_tokens import UserOAuthTokens
from open_webui.utils.auth import get_verified_user
from pydantic import BaseModel

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MAIN"])

router = APIRouter()

SUPPORTED_PROVIDERS = ("microsoft", "google")


class ProviderConnectionStatus(BaseModel):
    provider: str
    connected: bool
    account_email: Optional[str] = None
    expires_at: Optional[int] = None
    scopes: Optional[list[str]] = None  # 토큰 부여된 OAuth scope 목록 (UI 표시용)
    # 채팅 통합 기능별 scope 충족 여부 (google 전용). 토큰 row 가 있어도
    # GWS delegated scope 도입 이전 로그인이면 false — 프론트 토글 게이트가
    # connected 대신 이 값으로 기능별 활성화를 판정한다.
    features: Optional[dict[str, bool]] = None


def _split_scopes(scope_str: Optional[str]) -> Optional[list[str]]:
    """공백 구분 scope 문자열을 리스트로 분해.  빈 값은 None 유지."""
    if not scope_str:
        return None
    return [s for s in scope_str.split() if s]


def _gws_feature_flags(scope_str: Optional[str]) -> dict[str, bool]:
    """google 토큰 scope 로 gmail/calendar/drive 기능별 충족 여부 계산."""
    granted = set((scope_str or "").split())
    return {
        feature: required <= granted
        for feature, required in GWS_FEATURE_REQUIRED_SCOPES.items()
    }


@router.get("/connections", response_model=list[ProviderConnectionStatus])
async def list_my_connections(user=Depends(get_verified_user)):
    """본인의 provider 별 연결 상태. 미연결 provider 도 connected=False 로 함께 반환."""
    rows = {r.provider: r for r in UserOAuthTokens.list_by_user(user.id)}
    return [
        ProviderConnectionStatus(
            provider=p,
            connected=p in rows,
            account_email=rows[p].account_email if p in rows else None,
            expires_at=rows[p].expires_at if p in rows else None,
            scopes=_split_scopes(rows[p].scopes) if p in rows else None,
            features=(
                _gws_feature_flags(rows[p].scopes)
                if p == "google" and p in rows
                else None
            ),
        )
        for p in SUPPORTED_PROVIDERS
    ]


@router.delete("/connections/{provider}", response_model=bool)
async def disconnect_my_provider(provider: str, user=Depends(get_verified_user)):
    if provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT(f"unsupported provider: {provider}"),
        )
    return UserOAuthTokens.delete(user.id, provider)

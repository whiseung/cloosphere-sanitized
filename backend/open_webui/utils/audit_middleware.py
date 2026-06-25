"""
Audit Context Middleware

요청마다 감사 컨텍스트를 설정하는 미들웨어.
"""

import logging
from typing import Callable

from fastapi import Request
from open_webui.env import SRC_LOG_LEVELS
from open_webui.utils.audit_logger import (
    AuditContext,
    clear_audit_context,
    set_audit_context,
)
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MAIN"])


class AuditContextMiddleware(BaseHTTPMiddleware):
    """요청 컨텍스트를 감사 로거에 전달하는 미들웨어"""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # KMS audit ContextVar — providers (azure_key_vault, ...) read this
        # to tag wrap/unwrap rows with the request's IP / request_id /
        # actor_id (the latter filled in after auth via
        # update_audit_context_user). Lazy-imported to keep this module's
        # bootstrap path off the KMS package.
        from open_webui.models.kms_audit_log import (
            reset_request_context as kms_reset_ctx,
        )
        from open_webui.models.kms_audit_log import (
            set_request_context as kms_set_ctx,
        )

        kms_token = None
        try:
            # 기본 컨텍스트 설정
            context = AuditContext(
                ip_address=self._get_client_ip(request),
                user_agent=request.headers.get("user-agent"),
                request_path=str(request.url.path),
            )

            # 인증된 사용자 정보가 있으면 추가
            # 주의: 이 시점에서는 아직 인증이 처리되지 않았을 수 있음
            # 실제 사용자 정보는 라우터에서 update_audit_context_user()로 업데이트
            set_audit_context(context)

            kms_token = kms_set_ctx(
                client_ip=context.ip_address,
                request_id=(
                    request.headers.get("x-request-id")
                    or request.headers.get("x-correlation-id")
                ),
            )

            response = await call_next(request)
            return response

        except Exception as e:
            log.exception(f"Error in AuditContextMiddleware: {e}")
            raise

        finally:
            # 요청 종료 시 컨텍스트 정리
            clear_audit_context()
            kms_reset_ctx(kms_token)

    def _get_client_ip(self, request: Request) -> str:
        """클라이언트 IP 주소 추출"""
        # X-Forwarded-For 헤더 확인 (프록시/로드밸런서 뒤에 있는 경우)
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            # 첫 번째 IP가 원래 클라이언트
            return forwarded_for.split(",")[0].strip()

        # X-Real-IP 헤더 확인
        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip

        # 직접 연결된 클라이언트 IP
        if request.client:
            return request.client.host

        return "unknown"


def update_audit_context_user(
    user_id: str,
    user_email: str = None,
    user_name: str = None,
    organization_id: str = None,
) -> None:
    """
    인증 후 감사 컨텍스트에 사용자 정보 업데이트.
    라우터의 Depends(get_verified_user) 후에 호출.
    """
    from open_webui.utils.audit_logger import get_audit_context, set_audit_context

    context = get_audit_context()
    ip_address = context.ip_address if context else None
    if context:
        context.user_id = user_id
        context.user_email = user_email
        context.user_name = user_name
        context.organization_id = organization_id
        set_audit_context(context)
    else:
        # 컨텍스트가 없으면 새로 생성
        set_audit_context(
            AuditContext(
                user_id=user_id,
                user_email=user_email,
                user_name=user_name,
                organization_id=organization_id,
            )
        )

    # Mirror onto the KMS audit ContextVar — providers tag wrap/unwrap
    # rows with the now-known actor. Reset is owned by the middleware's
    # finally block (the new token is intentionally discarded here:
    # ContextVar.reset on the original token unwinds every later set).
    try:
        from open_webui.models.kms_audit_log import set_request_context as kms_set

        kms_set(
            actor_id=user_id,
            actor_type="user",
            org_id=organization_id,
            client_ip=ip_address,
        )
    except Exception as e:
        log.debug(f"KMS audit ctx mirror skipped: {e}")

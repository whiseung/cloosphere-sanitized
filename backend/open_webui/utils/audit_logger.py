"""
Audit Logger

감사 로그를 생성하고 관리하는 핵심 로직.
SQLAlchemy 이벤트 훅과 명시적 호출 모두 지원.
"""

import logging
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Optional

from open_webui.env import SRC_LOG_LEVELS
from open_webui.models.audit_log import (
    AuditAction,
    AuditLogCreateForm,
    AuditLogs,
    AuditResourceType,
)

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MAIN"])


####################
# Request Context
####################


@dataclass
class AuditContext:
    """요청 컨텍스트 정보"""

    user_id: Optional[str] = None
    user_email: Optional[str] = None
    user_name: Optional[str] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    request_path: Optional[str] = None
    organization_id: Optional[str] = None


# Context variable for storing request context
_audit_context: ContextVar[Optional[AuditContext]] = ContextVar(
    "audit_context", default=None
)


def set_audit_context(context: AuditContext) -> None:
    """현재 요청의 감사 컨텍스트 설정"""
    _audit_context.set(context)


def get_audit_context() -> Optional[AuditContext]:
    """현재 요청의 감사 컨텍스트 조회"""
    return _audit_context.get()


def clear_audit_context() -> None:
    """감사 컨텍스트 초기화"""
    _audit_context.set(None)


####################
# Sensitive Field Masking
####################

# 마스킹할 민감 필드 목록
SENSITIVE_FIELDS = {
    "password",
    "api_key",
    "oauth_sub",
    "token",
    "secret",
    "credentials",
}

# 중첩 경로로 지정된 민감 필드
SENSITIVE_PATHS = {
    "settings.ui.notifications.webhook_url",
    "data.connection.password",
    "data.connection.api_key",
    "config.api_key",
    "config.password",
    "valves",  # Tool valves (API keys 포함 가능)
}

# 로깅에서 제외할 대용량 필드
EXCLUDED_FIELDS = {
    "content",  # Tool, Prompt 등의 코드 내용
    "specs",  # Tool specs
    "params",  # Model params
}


def _is_sensitive_key(key: str) -> bool:
    """민감한 키인지 확인"""
    key_lower = key.lower()
    return any(sensitive in key_lower for sensitive in SENSITIVE_FIELDS)


def _mask_value(value: Any) -> str:
    """값을 마스킹"""
    if value is None:
        return None
    if isinstance(value, str) and len(value) > 0:
        return "***MASKED***"
    return "***MASKED***"


def mask_sensitive_data(data: dict, path: str = "") -> dict:
    """민감한 데이터를 마스킹"""
    if not isinstance(data, dict):
        return data

    masked = {}
    for key, value in data.items():
        current_path = f"{path}.{key}" if path else key

        # 제외할 필드는 건너뛰기
        if key in EXCLUDED_FIELDS:
            masked[key] = "***EXCLUDED***"
            continue

        # 민감한 키인지 확인
        if _is_sensitive_key(key):
            masked[key] = _mask_value(value)
            continue

        # 경로로 지정된 민감 필드인지 확인
        if current_path in SENSITIVE_PATHS:
            masked[key] = _mask_value(value)
            continue

        # 중첩 딕셔너리 처리
        if isinstance(value, dict):
            masked[key] = mask_sensitive_data(value, current_path)
        elif isinstance(value, list):
            masked[key] = [
                mask_sensitive_data(item, current_path)
                if isinstance(item, dict)
                else item
                for item in value
            ]
        else:
            masked[key] = value

    return masked


####################
# Change Detection
####################


def calculate_changed_fields(before: dict, after: dict) -> list[str]:
    """변경된 필드 목록 계산"""
    if not before or not after:
        return []

    changed = []
    all_keys = set(before.keys()) | set(after.keys())

    for key in all_keys:
        before_val = before.get(key)
        after_val = after.get(key)

        if before_val != after_val:
            changed.append(key)

    return changed


def calculate_access_control_changes(
    before: Optional[dict], after: Optional[dict]
) -> Optional[dict]:
    """access_control 변경 상세 계산"""
    if before == after:
        return None

    before = before or {}
    after = after or {}

    changes = {}

    # read 권한 변경
    before_read = before.get("read", {})
    after_read = after.get("read", {})

    before_read_groups = set(before_read.get("group_ids", []))
    after_read_groups = set(after_read.get("group_ids", []))
    before_read_users = set(before_read.get("user_ids", []))
    after_read_users = set(after_read.get("user_ids", []))

    if after_read_groups - before_read_groups:
        changes["added_read_groups"] = list(after_read_groups - before_read_groups)
    if before_read_groups - after_read_groups:
        changes["removed_read_groups"] = list(before_read_groups - after_read_groups)
    if after_read_users - before_read_users:
        changes["added_read_users"] = list(after_read_users - before_read_users)
    if before_read_users - after_read_users:
        changes["removed_read_users"] = list(before_read_users - after_read_users)

    # write 권한 변경
    before_write = before.get("write", {})
    after_write = after.get("write", {})

    before_write_groups = set(before_write.get("group_ids", []))
    after_write_groups = set(after_write.get("group_ids", []))
    before_write_users = set(before_write.get("user_ids", []))
    after_write_users = set(after_write.get("user_ids", []))

    if after_write_groups - before_write_groups:
        changes["added_write_groups"] = list(after_write_groups - before_write_groups)
    if before_write_groups - after_write_groups:
        changes["removed_write_groups"] = list(before_write_groups - after_write_groups)
    if after_write_users - before_write_users:
        changes["added_write_users"] = list(after_write_users - before_write_users)
    if before_write_users - after_write_users:
        changes["removed_write_users"] = list(before_write_users - after_write_users)

    return changes if changes else None


def calculate_member_changes(
    before: Optional[list], after: Optional[list]
) -> tuple[list[str], list[str]]:
    """멤버 목록 변경 계산 (user_ids, member_ids)"""
    before_set = set(before or [])
    after_set = set(after or [])

    added = list(after_set - before_set)
    removed = list(before_set - after_set)

    return added, removed


####################
# AuditLogger Class
####################


class AuditLogger:
    """감사 로그 생성 클래스"""

    # 리소스 타입별 이름 필드 매핑
    RESOURCE_NAME_FIELDS = {
        AuditResourceType.MODEL.value: "name",
        AuditResourceType.KNOWLEDGE.value: "name",
        AuditResourceType.DBSPHERE.value: "name",
        AuditResourceType.GLOSSARY.value: "name",
        AuditResourceType.PROMPT.value: "title",
        AuditResourceType.TOOL.value: "name",
        AuditResourceType.USER.value: "name",
        AuditResourceType.ORGANIZATION.value: "name",
        AuditResourceType.ORGANIZATIONAL_UNIT.value: "name",
        AuditResourceType.GROUP.value: "name",
        AuditResourceType.MEMORY.value: "content",
    }

    # 리소스 타입별 ID 필드 매핑
    RESOURCE_ID_FIELDS = {
        AuditResourceType.PROMPT.value: "command",  # Prompt는 command가 PK
    }

    @classmethod
    def _get_context_data(cls, meta: Optional[dict] = None) -> dict:
        """현재 컨텍스트에서 데이터 추출.

        AuditContext가 없는 환경(background task)에서는 meta에서
        user_id를 fallback으로 추출하여 audit_log.user_id 컬럼에 기록.
        """
        context = get_audit_context()
        if context:
            return {
                "user_id": context.user_id,
                "user_email": context.user_email,
                "user_name": context.user_name,
                "ip_address": context.ip_address,
                "user_agent": context.user_agent,
                "request_path": context.request_path,
                "organization_id": context.organization_id,
            }
        # Background task fallback: meta에서 user_id 추출
        if meta and meta.get("user_id"):
            return {"user_id": meta["user_id"]}
        return {}

    @classmethod
    def _get_resource_name(cls, resource_type: str, data: dict) -> Optional[str]:
        """리소스 이름 추출"""
        name_field = cls.RESOURCE_NAME_FIELDS.get(resource_type, "name")
        return data.get(name_field)

    @classmethod
    def _get_resource_id(cls, resource_type: str, data: dict) -> Optional[str]:
        """리소스 ID 추출"""
        id_field = cls.RESOURCE_ID_FIELDS.get(resource_type, "id")
        return data.get(id_field)

    @classmethod
    def log_create(
        cls,
        resource_type: str,
        resource_id: str,
        data: dict,
        resource_name: Optional[str] = None,
        meta: Optional[dict] = None,
    ) -> None:
        """CREATE 이벤트 로깅"""
        try:
            context_data = cls._get_context_data(meta=meta)
            masked_data = mask_sensitive_data(data)

            form = AuditLogCreateForm(
                **context_data,
                resource_type=resource_type,
                resource_id=resource_id,
                resource_name=resource_name
                or cls._get_resource_name(resource_type, data),
                action=AuditAction.CREATE.value,
                after_state=masked_data,
                meta=meta,
            )

            AuditLogs.insert_audit_log(form)
            log.debug(f"Audit log created: CREATE {resource_type}/{resource_id}")

        except Exception as e:
            log.exception(f"Failed to create audit log: {e}")

    @classmethod
    def log_update(
        cls,
        resource_type: str,
        resource_id: str,
        before_data: dict,
        after_data: dict,
        resource_name: Optional[str] = None,
        meta: Optional[dict] = None,
    ) -> None:
        """UPDATE 이벤트 로깅"""
        try:
            context_data = cls._get_context_data(meta=meta)

            masked_before = mask_sensitive_data(before_data)
            masked_after = mask_sensitive_data(after_data)
            changed_fields = calculate_changed_fields(before_data, after_data)

            # access_control 변경 확인
            access_control_changes = None
            if "access_control" in changed_fields:
                access_control_changes = calculate_access_control_changes(
                    before_data.get("access_control"), after_data.get("access_control")
                )

            form = AuditLogCreateForm(
                **context_data,
                resource_type=resource_type,
                resource_id=resource_id,
                resource_name=resource_name
                or cls._get_resource_name(resource_type, after_data),
                action=AuditAction.UPDATE.value,
                before_state=masked_before,
                after_state=masked_after,
                changed_fields=changed_fields,
                access_control_changes=access_control_changes,
                meta=meta,
            )

            AuditLogs.insert_audit_log(form)
            log.debug(f"Audit log created: UPDATE {resource_type}/{resource_id}")

        except Exception as e:
            log.exception(f"Failed to create audit log: {e}")

    @classmethod
    def log_delete(
        cls,
        resource_type: str,
        resource_id: str,
        data: dict,
        resource_name: Optional[str] = None,
        meta: Optional[dict] = None,
    ) -> None:
        """DELETE 이벤트 로깅"""
        try:
            context_data = cls._get_context_data(meta=meta)
            masked_data = mask_sensitive_data(data)

            form = AuditLogCreateForm(
                **context_data,
                resource_type=resource_type,
                resource_id=resource_id,
                resource_name=resource_name
                or cls._get_resource_name(resource_type, data),
                action=AuditAction.DELETE.value,
                before_state=masked_data,
                meta=meta,
            )

            AuditLogs.insert_audit_log(form)
            log.debug(f"Audit log created: DELETE {resource_type}/{resource_id}")

        except Exception as e:
            log.exception(f"Failed to create audit log: {e}")

    @classmethod
    def log_access_control_change(
        cls,
        resource_type: str,
        resource_id: str,
        before_access_control: Optional[dict],
        after_access_control: Optional[dict],
        resource_name: Optional[str] = None,
        meta: Optional[dict] = None,
    ) -> None:
        """ACCESS_CONTROL_CHANGE 이벤트 로깅 (권한 변경 전용)"""
        try:
            context_data = cls._get_context_data()

            access_control_changes = calculate_access_control_changes(
                before_access_control, after_access_control
            )

            if not access_control_changes:
                return  # 변경 사항 없음

            form = AuditLogCreateForm(
                **context_data,
                resource_type=resource_type,
                resource_id=resource_id,
                resource_name=resource_name,
                action=AuditAction.ACCESS_CONTROL_CHANGE.value,
                before_state={"access_control": before_access_control},
                after_state={"access_control": after_access_control},
                changed_fields=["access_control"],
                access_control_changes=access_control_changes,
                meta=meta,
            )

            AuditLogs.insert_audit_log(form)
            log.debug(
                f"Audit log created: ACCESS_CONTROL_CHANGE {resource_type}/{resource_id}"
            )

        except Exception as e:
            log.exception(f"Failed to create audit log: {e}")

    @classmethod
    def log_permission_change(
        cls,
        resource_type: str,
        resource_id: str,
        before_permissions: Optional[dict],
        after_permissions: Optional[dict],
        resource_name: Optional[str] = None,
        meta: Optional[dict] = None,
    ) -> None:
        """PERMISSION_CHANGE 이벤트 로깅 (Group 권한 변경)"""
        try:
            context_data = cls._get_context_data()

            form = AuditLogCreateForm(
                **context_data,
                resource_type=resource_type,
                resource_id=resource_id,
                resource_name=resource_name,
                action=AuditAction.PERMISSION_CHANGE.value,
                before_state={"permissions": before_permissions},
                after_state={"permissions": after_permissions},
                changed_fields=["permissions"],
                meta=meta,
            )

            AuditLogs.insert_audit_log(form)
            log.debug(
                f"Audit log created: PERMISSION_CHANGE {resource_type}/{resource_id}"
            )

        except Exception as e:
            log.exception(f"Failed to create audit log: {e}")

    @classmethod
    def log_member_change(
        cls,
        resource_type: str,
        resource_id: str,
        added_members: list[str],
        removed_members: list[str],
        resource_name: Optional[str] = None,
        meta: Optional[dict] = None,
    ) -> None:
        """MEMBER_ADD/MEMBER_REMOVE 이벤트 로깅"""
        try:
            context_data = cls._get_context_data()

            if added_members:
                form = AuditLogCreateForm(
                    **context_data,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    resource_name=resource_name,
                    action=AuditAction.MEMBER_ADD.value,
                    after_state={"added_members": added_members},
                    meta=meta,
                )
                AuditLogs.insert_audit_log(form)
                log.debug(
                    f"Audit log created: MEMBER_ADD {resource_type}/{resource_id}"
                )

            if removed_members:
                form = AuditLogCreateForm(
                    **context_data,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    resource_name=resource_name,
                    action=AuditAction.MEMBER_REMOVE.value,
                    before_state={"removed_members": removed_members},
                    meta=meta,
                )
                AuditLogs.insert_audit_log(form)
                log.debug(
                    f"Audit log created: MEMBER_REMOVE {resource_type}/{resource_id}"
                )

        except Exception as e:
            log.exception(f"Failed to create audit log: {e}")

    @classmethod
    def log_role_change(
        cls,
        user_id: str,
        before_role: str,
        after_role: str,
        user_name: Optional[str] = None,
        user_email: Optional[str] = None,
        meta: Optional[dict] = None,
    ) -> None:
        """ROLE_CHANGE 이벤트 로깅 (사용자 역할 변경)"""
        try:
            context_data = cls._get_context_data()

            form = AuditLogCreateForm(
                **context_data,
                resource_type=AuditResourceType.USER.value,
                resource_id=user_id,
                resource_name=user_name or user_email,
                action=AuditAction.ROLE_CHANGE.value,
                before_state={"role": before_role},
                after_state={"role": after_role},
                changed_fields=["role"],
                meta=meta,
            )

            AuditLogs.insert_audit_log(form)
            log.debug(f"Audit log created: ROLE_CHANGE user/{user_id}")

        except Exception as e:
            log.exception(f"Failed to create audit log: {e}")

    @classmethod
    def log_settings_change(
        cls,
        section: str,
        before_data: Optional[dict] = None,
        after_data: Optional[dict] = None,
        meta: Optional[dict] = None,
    ) -> None:
        """관리자 설정 변경 이벤트 로깅

        Args:
            section: 설정 섹션 이름 (e.g., "general", "connections/openai", "audio", "notifications")
            before_data: 변경 전 설정 값
            after_data: 변경 후 설정 값
            meta: 추가 메타데이터
        """
        try:
            context_data = cls._get_context_data()

            masked_before = mask_sensitive_data(before_data) if before_data else None
            masked_after = mask_sensitive_data(after_data) if after_data else None
            changed_fields = (
                calculate_changed_fields(before_data, after_data)
                if before_data and after_data
                else None
            )

            form = AuditLogCreateForm(
                **context_data,
                resource_type=AuditResourceType.ADMIN_SETTINGS.value,
                resource_id=section,
                resource_name=section,
                action=AuditAction.SETTINGS_CHANGE.value,
                before_state=masked_before,
                after_state=masked_after,
                changed_fields=changed_fields,
                meta=meta,
            )

            AuditLogs.insert_audit_log(form)
            log.debug(f"Audit log created: SETTINGS_CHANGE admin_settings/{section}")

        except Exception as e:
            log.exception(f"Failed to create audit log: {e}")

    @classmethod
    def log_auth_event(
        cls,
        action: AuditAction,
        user_id: Optional[str] = None,
        user_email: Optional[str] = None,
        user_name: Optional[str] = None,
        success: bool = True,
        meta: Optional[dict] = None,
    ) -> None:
        """인증 관련 이벤트 로깅 (LOGIN, LOGOUT, LOGIN_FAILED 등)"""
        try:
            context = get_audit_context()

            form = AuditLogCreateForm(
                user_id=user_id,
                user_email=user_email,
                user_name=user_name,
                ip_address=context.ip_address if context else None,
                user_agent=context.user_agent if context else None,
                request_path=context.request_path if context else None,
                organization_id=context.organization_id if context else None,
                resource_type=AuditResourceType.AUTH.value,
                resource_id=user_id,
                resource_name=user_email,
                action=action.value,
                meta={
                    **(meta or {}),
                    "success": success,
                },
            )

            AuditLogs.insert_audit_log(form)
            log.debug(f"Audit log created: {action.value} auth/{user_id}")

        except Exception as e:
            log.exception(f"Failed to create audit log: {e}")

"""
Audit Events - SQLAlchemy Event Hooks

SQLAlchemy 이벤트를 통한 자동 CRUD 감사 로깅.
main.py에서 register_audit_events()를 호출하여 활성화.
"""

import logging
from typing import Any, Optional

from open_webui.env import SRC_LOG_LEVELS
from open_webui.models.audit_log import AuditResourceType
from sqlalchemy import event, inspect

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MAIN"])

# 감사 대상 테이블 목록
AUDITABLE_TABLES = {
    "model": AuditResourceType.MODEL.value,
    "knowledge": AuditResourceType.KNOWLEDGE.value,
    "dbsphere": AuditResourceType.DBSPHERE.value,
    "glossary": AuditResourceType.GLOSSARY.value,
    "prompt": AuditResourceType.PROMPT.value,
    "tool": AuditResourceType.TOOL.value,
    "user": AuditResourceType.USER.value,
    "organization": AuditResourceType.ORGANIZATION.value,
    "organizational_unit": AuditResourceType.ORGANIZATIONAL_UNIT.value,
    "group": AuditResourceType.GROUP.value,
}

# ID 필드 매핑 (기본값: "id")
ID_FIELD_MAPPING = {
    "prompt": "command",  # Prompt는 command가 PK
}

# 변경 전 상태 저장용
_before_state_cache: dict[int, dict] = {}


def _get_table_name(obj: Any) -> Optional[str]:
    """객체의 테이블 이름 반환"""
    try:
        return obj.__tablename__
    except AttributeError:
        return None


def _get_resource_type(table_name: str) -> Optional[str]:
    """테이블 이름으로 리소스 타입 반환"""
    return AUDITABLE_TABLES.get(table_name)


def _get_id_field(table_name: str) -> str:
    """테이블의 ID 필드명 반환"""
    return ID_FIELD_MAPPING.get(table_name, "id")


def _obj_to_dict(obj: Any) -> dict:
    """SQLAlchemy 객체를 dict로 변환"""
    try:
        mapper = inspect(obj.__class__)
        return {column.key: getattr(obj, column.key) for column in mapper.columns}
    except Exception:
        return {}


def _cache_before_state(obj: Any) -> None:
    """변경 전 상태 캐싱"""
    obj_id = id(obj)
    _before_state_cache[obj_id] = _obj_to_dict(obj)


def _get_cached_before_state(obj: Any) -> Optional[dict]:
    """캐싱된 변경 전 상태 조회"""
    return _before_state_cache.pop(id(obj), None)


def _on_after_insert(mapper, connection, target):
    """INSERT 후 이벤트 핸들러"""
    table_name = _get_table_name(target)
    resource_type = _get_resource_type(table_name)

    if not resource_type:
        return

    # AuditLog 자체는 감사하지 않음
    if table_name == "audit_log":
        return

    try:
        from open_webui.utils.audit_logger import AuditLogger

        id_field = _get_id_field(table_name)
        resource_id = getattr(target, id_field, None)
        data = _obj_to_dict(target)

        AuditLogger.log_create(
            resource_type=resource_type,
            resource_id=str(resource_id) if resource_id else None,
            data=data,
        )

    except Exception as e:
        log.exception(f"Failed to log INSERT for {table_name}: {e}")


def _on_before_update(mapper, connection, target):
    """UPDATE 전 이벤트 핸들러 - 변경 전 상태 캐싱"""
    table_name = _get_table_name(target)
    resource_type = _get_resource_type(table_name)

    if not resource_type:
        return

    if table_name == "audit_log":
        return

    try:
        # 현재 상태를 변경 전 상태로 캐싱
        # 주의: ORM에서 flush 전 호출되므로 현재 DB 상태와 다를 수 있음
        _cache_before_state(target)

    except Exception as e:
        log.exception(f"Failed to cache before state for {table_name}: {e}")


def _on_after_update(mapper, connection, target):
    """UPDATE 후 이벤트 핸들러"""
    table_name = _get_table_name(target)
    resource_type = _get_resource_type(table_name)

    if not resource_type:
        return

    if table_name == "audit_log":
        return

    try:
        from open_webui.utils.audit_logger import AuditLogger, calculate_member_changes

        id_field = _get_id_field(table_name)
        resource_id = getattr(target, id_field, None)

        before_data = _get_cached_before_state(target) or {}
        after_data = _obj_to_dict(target)

        # 멤버 변경 감지 (Group의 user_ids, OrganizationalUnit의 member_ids)
        if table_name == "group" and "user_ids" in after_data:
            added, removed = calculate_member_changes(
                before_data.get("user_ids"), after_data.get("user_ids")
            )
            if added or removed:
                AuditLogger.log_member_change(
                    resource_type=resource_type,
                    resource_id=str(resource_id) if resource_id else None,
                    added_members=added,
                    removed_members=removed,
                    resource_name=after_data.get("name"),
                )

        if table_name == "organizational_unit" and "member_ids" in after_data:
            added, removed = calculate_member_changes(
                before_data.get("member_ids"), after_data.get("member_ids")
            )
            if added or removed:
                AuditLogger.log_member_change(
                    resource_type=resource_type,
                    resource_id=str(resource_id) if resource_id else None,
                    added_members=added,
                    removed_members=removed,
                    resource_name=after_data.get("name"),
                )

        # permissions 변경 감지 (Group)
        if table_name == "group":
            before_perms = before_data.get("permissions")
            after_perms = after_data.get("permissions")
            if before_perms != after_perms:
                AuditLogger.log_permission_change(
                    resource_type=resource_type,
                    resource_id=str(resource_id) if resource_id else None,
                    before_permissions=before_perms,
                    after_permissions=after_perms,
                    resource_name=after_data.get("name"),
                )

        # role 변경 감지 (User)
        if table_name == "user":
            before_role = before_data.get("role")
            after_role = after_data.get("role")
            if before_role and after_role and before_role != after_role:
                AuditLogger.log_role_change(
                    user_id=str(resource_id) if resource_id else None,
                    before_role=before_role,
                    after_role=after_role,
                    user_name=after_data.get("name"),
                    user_email=after_data.get("email"),
                )

        # 일반 UPDATE 로깅
        AuditLogger.log_update(
            resource_type=resource_type,
            resource_id=str(resource_id) if resource_id else None,
            before_data=before_data,
            after_data=after_data,
        )

    except Exception as e:
        log.exception(f"Failed to log UPDATE for {table_name}: {e}")


def _on_before_delete(mapper, connection, target):
    """DELETE 전 이벤트 핸들러"""
    table_name = _get_table_name(target)
    resource_type = _get_resource_type(table_name)

    if not resource_type:
        return

    if table_name == "audit_log":
        return

    try:
        from open_webui.utils.audit_logger import AuditLogger

        id_field = _get_id_field(table_name)
        resource_id = getattr(target, id_field, None)
        data = _obj_to_dict(target)

        AuditLogger.log_delete(
            resource_type=resource_type,
            resource_id=str(resource_id) if resource_id else None,
            data=data,
        )

    except Exception as e:
        log.exception(f"Failed to log DELETE for {table_name}: {e}")


def register_audit_events():
    """감사 이벤트 등록 - main.py에서 호출"""
    try:
        # 각 감사 대상 모델에 이벤트 리스너 등록
        from open_webui.models.dbsphere import DbSphere
        from open_webui.models.glossary import Glossary
        from open_webui.models.groups import Group
        from open_webui.models.knowledge import Knowledge
        from open_webui.models.models import Model
        from open_webui.models.organization import Organization, OrganizationalUnit
        from open_webui.models.prompts import Prompt
        from open_webui.models.tools import Tool
        from open_webui.models.users import User

        auditable_models = [
            Model,
            Knowledge,
            DbSphere,
            Glossary,
            Prompt,
            Tool,
            User,
            Organization,
            OrganizationalUnit,
            Group,
        ]

        for model in auditable_models:
            event.listen(model, "after_insert", _on_after_insert)
            event.listen(model, "before_update", _on_before_update)
            event.listen(model, "after_update", _on_after_update)
            event.listen(model, "before_delete", _on_before_delete)

        log.info(f"Audit events registered for {len(auditable_models)} models")

    except Exception as e:
        log.exception(f"Failed to register audit events: {e}")

"""
Audit Log Models

시스템 전체의 CRUD 및 권한 변경을 추적하는 감사 로그 모델.
"""

import logging
import time
import uuid
from enum import Enum
from typing import Optional

from open_webui.env import SRC_LOG_LEVELS
from open_webui.internal.db import Base, get_db
from pydantic import BaseModel, ConfigDict
from sqlalchemy import JSON, BigInteger, Column, Index, String, Text, distinct

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])


####################
# Enums
####################


class AuditAction(str, Enum):
    """감사 로그 액션 타입"""

    # 기본 CRUD
    CREATE = "CREATE"
    READ = "READ"
    UPDATE = "UPDATE"
    DELETE = "DELETE"

    # 권한 관련
    ACCESS_CONTROL_CHANGE = "ACCESS_CONTROL_CHANGE"  # 리소스별 접근 권한 변경
    PERMISSION_CHANGE = "PERMISSION_CHANGE"  # Group 기능 권한 변경
    MEMBER_ADD = "MEMBER_ADD"  # 그룹/조직단위 멤버 추가
    MEMBER_REMOVE = "MEMBER_REMOVE"  # 그룹/조직단위 멤버 제거
    ROLE_CHANGE = "ROLE_CHANGE"  # 사용자 역할 변경

    # 설정 변경
    SETTINGS_CHANGE = "SETTINGS_CHANGE"

    # 인증 관련
    LOGIN = "LOGIN"
    LOGOUT = "LOGOUT"
    LOGIN_FAILED = "LOGIN_FAILED"
    API_KEY_CREATED = "API_KEY_CREATED"
    API_KEY_DELETED = "API_KEY_DELETED"

    # 임베드 위젯
    GUEST_SESSION = "GUEST_SESSION"  # 게스트 세션 생성

    # DbSphere SQL Editor 직접 실행 (append-only).
    # 시퀀스: SQL_PENDING (pop_pending 직후) → SQL_COMMITTED / SQL_FAILED.
    # 워커가 SQL_PENDING 후 죽으면 final row 없음 → orphan 으로 감지 가능 (audit 갭 차단).
    SQL_PENDING = "SQL_PENDING"  # pop_pending 직후 — runner 실행 직전 evidence row
    SQL_COMMITTED = "SQL_COMMITTED"  # DML/DDL 사용자 승인 → 실제 실행 성공
    SQL_REJECTED = "SQL_REJECTED"  # DML/DDL 사용자 거부
    SQL_FAILED = "SQL_FAILED"  # 실행 시도 후 예외 (timeout 포함)
    SQL_UNKNOWN = "SQL_UNKNOWN"  # admin reconcile 가 orphan SQL_PENDING 을 명시적 마킹

    # 외부 API 호출 — Gmail / Calendar 채팅 통합 (사용자 명의 발송/일정 등록 추적)
    # MVP 는 사용자 confirm 후 발송된 메일/일정만 기록. delete tool 은 미지원이라 enum 없음.
    GMAIL_SEND = "GMAIL_SEND"  # 메일 발송 성공 (HITL confirm 통과)
    GMAIL_SEND_FAILED = (
        "GMAIL_SEND_FAILED"  # 메일 발송 실패 (Google API 오류, scope 거절 등)
    )
    CALENDAR_CREATE_EVENT = "CALENDAR_CREATE_EVENT"  # 일정 생성 성공
    CALENDAR_CREATE_EVENT_FAILED = "CALENDAR_CREATE_EVENT_FAILED"  # 일정 생성 실패 (Google API 오류, scope 거절 등)
    # Drive 채팅 통합 — 구글 문서 생성 추적 (HITL confirm 후 2-call 실행).
    # resource_type 은 literal "drive_document" (AuditResourceType enum 미추가).
    # 자유 String 컬럼이라 마이그레이션 불필요.
    DRIVE_CREATE_DOC = "DRIVE_CREATE_DOC"  # 구글 문서 생성 성공 (HITL confirm 통과)
    DRIVE_CREATE_DOC_FAILED = "DRIVE_CREATE_DOC_FAILED"  # 문서 생성 실패 (Step1/Step2 Google API 오류, scope 거절 등)


class AuditResourceType(str, Enum):
    """감사 대상 리소스 타입"""

    # 워크스페이스 기능
    MODEL = "model"
    KNOWLEDGE = "knowledge"
    DBSPHERE = "dbsphere"
    GLOSSARY = "glossary"
    PROMPT = "prompt"
    TOOL = "tool"
    AGENT = "agent"

    # 채팅
    CHAT = "chat"

    # 조직/사용자
    USER = "user"
    ORGANIZATION = "organization"
    ORGANIZATIONAL_UNIT = "organizational_unit"
    GROUP = "group"

    # 인증
    AUTH = "auth"

    # 메모리
    MEMORY = "memory"

    # 관리자 설정
    ADMIN_SETTINGS = "admin_settings"

    # 임베드 위젯
    EMBED_WIDGET = "embed_widget"


####################
# AuditLog DB Schema
####################


class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(Text, primary_key=True)

    # === 누가 ===
    user_id = Column(Text, nullable=True)
    user_email = Column(Text, nullable=True)  # 비정규화 (사용자 삭제 대비)
    user_name = Column(Text, nullable=True)  # 비정규화 (사용자 삭제 대비)

    # === 무엇을 ===
    resource_type = Column(
        String(50), nullable=False
    )  # model, knowledge, user, group...
    resource_id = Column(Text, nullable=True)
    resource_name = Column(Text, nullable=True)  # 비정규화 (리소스 삭제 대비)

    # === 어떤 액션 ===
    action = Column(String(50), nullable=False)
    # CREATE, UPDATE, DELETE, ACCESS_CONTROL_CHANGE, ...

    # === 변경 내용 ===
    before_state = Column(JSON, nullable=True)  # 이전 상태
    after_state = Column(JSON, nullable=True)  # 이후 상태
    changed_fields = Column(JSON, nullable=True)  # ["name", "access_control"]

    # === 권한 변경 상세 ===
    access_control_changes = Column(JSON, nullable=True)
    # {
    #   "added_read_groups": ["group_id"],
    #   "removed_read_groups": [],
    #   "added_write_users": ["user_id"],
    #   "removed_write_users": [],
    #   ...
    # }

    # === 요청 컨텍스트 ===
    ip_address = Column(String(45), nullable=True)  # IPv6 최대 길이
    user_agent = Column(Text, nullable=True)
    request_path = Column(Text, nullable=True)

    # === 조직 컨텍스트 ===
    organization_id = Column(Text, nullable=True)

    # === 메타데이터 ===
    meta = Column(JSON, nullable=True)

    # === 타임스탬프 ===
    created_at = Column(BigInteger, nullable=False)

    # 복합 인덱스 정의
    __table_args__ = (
        Index("ix_audit_log_resource", "resource_type", "resource_id"),
        Index("ix_audit_log_user_id", "user_id"),
        Index("ix_audit_log_action", "action"),
        Index("ix_audit_log_created_at", "created_at"),
        Index("ix_audit_log_organization_id", "organization_id"),
    )


####################
# Pydantic Models
####################


class AuditLogModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str

    # 누가
    user_id: Optional[str] = None
    user_email: Optional[str] = None
    user_name: Optional[str] = None

    # 무엇을
    resource_type: str
    resource_id: Optional[str] = None
    resource_name: Optional[str] = None

    # 어떤 액션
    action: str

    # 변경 내용
    before_state: Optional[dict] = None
    after_state: Optional[dict] = None
    changed_fields: Optional[list[str]] = None

    # 권한 변경 상세
    access_control_changes: Optional[dict] = None

    # 요청 컨텍스트
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    request_path: Optional[str] = None

    # 조직 컨텍스트
    organization_id: Optional[str] = None

    # 메타데이터
    meta: Optional[dict] = None

    # 타임스탬프
    created_at: int


class AuditLogResponse(AuditLogModel):
    """API 응답용 모델"""

    pass


####################
# Forms
####################


class AuditLogCreateForm(BaseModel):
    """Audit Log 생성 폼 (내부 사용)"""

    user_id: Optional[str] = None
    user_email: Optional[str] = None
    user_name: Optional[str] = None

    resource_type: str
    resource_id: Optional[str] = None
    resource_name: Optional[str] = None

    action: str

    before_state: Optional[dict] = None
    after_state: Optional[dict] = None
    changed_fields: Optional[list[str]] = None

    access_control_changes: Optional[dict] = None

    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    request_path: Optional[str] = None

    organization_id: Optional[str] = None

    meta: Optional[dict] = None


class AuditLogQueryParams(BaseModel):
    """Audit Log 조회 쿼리 파라미터"""

    page: int = 1
    limit: int = 50

    resource_type: Optional[str] = None
    resource_id: Optional[str] = None
    action: Optional[str] = None
    user_id: Optional[str] = None
    organization_id: Optional[str] = None

    from_date: Optional[int] = None  # Unix timestamp
    to_date: Optional[int] = None  # Unix timestamp


####################
# AuditLog Table Operations
####################


class AuditLogTable:
    def get_distinct_resource_types(self, action: Optional[str] = None) -> list[str]:
        """DB에 실제 존재하는 리소스 타입 목록 (action 필터 적용 가능)"""
        with get_db() as db:
            query = db.query(distinct(AuditLog.resource_type)).filter(
                AuditLog.resource_type.isnot(None)
            )
            if action:
                actions = [a.strip() for a in action.split(",")]
                query = query.filter(AuditLog.action.in_(actions))
            return sorted([r[0] for r in query.all() if r[0]])

    def get_distinct_actions(self, resource_type: Optional[str] = None) -> list[str]:
        """DB에 실제 존재하는 액션 타입 목록 (resource_type 필터 적용 가능)"""
        with get_db() as db:
            query = db.query(distinct(AuditLog.action)).filter(
                AuditLog.action.isnot(None)
            )
            if resource_type:
                types = [rt.strip() for rt in resource_type.split(",")]
                query = query.filter(AuditLog.resource_type.in_(types))
            return sorted([r[0] for r in query.all() if r[0]])

    def insert_audit_log(
        self, form_data: AuditLogCreateForm
    ) -> Optional[AuditLogModel]:
        """감사 로그 생성"""
        with get_db() as db:
            audit_log = AuditLogModel(
                **{
                    **form_data.model_dump(),
                    "id": str(uuid.uuid4()),
                    "created_at": int(time.time()),
                }
            )

            try:
                result = AuditLog(**audit_log.model_dump())
                db.add(result)
                db.commit()
                db.refresh(result)
                if result:
                    return AuditLogModel.model_validate(result)
                else:
                    return None
            except Exception as e:
                log.exception(f"Error inserting audit log: {e}")
                return None

    def get_audit_logs(
        self, params: AuditLogQueryParams
    ) -> tuple[list[AuditLogModel], int]:
        """감사 로그 조회 (페이지네이션 포함)"""
        with get_db() as db:
            query = db.query(AuditLog)

            # 필터 적용 (콤마로 구분된 다중 값 지원)
            if params.resource_type:
                resource_types = [rt.strip() for rt in params.resource_type.split(",")]
                if len(resource_types) == 1:
                    query = query.filter(AuditLog.resource_type == resource_types[0])
                else:
                    query = query.filter(AuditLog.resource_type.in_(resource_types))
            if params.resource_id:
                query = query.filter(AuditLog.resource_id == params.resource_id)
            if params.action:
                actions = [a.strip() for a in params.action.split(",")]
                if len(actions) == 1:
                    query = query.filter(AuditLog.action == actions[0])
                else:
                    query = query.filter(AuditLog.action.in_(actions))
            if params.user_id:
                # UUID 형태면 user_id 정확 매칭, 아니면 user_name LIKE 검색
                search_val = params.user_id.strip()
                try:
                    uuid.UUID(search_val)
                    query = query.filter(AuditLog.user_id == search_val)
                except ValueError:
                    query = query.filter(AuditLog.user_name.ilike(f"%{search_val}%"))
            if params.organization_id:
                query = query.filter(AuditLog.organization_id == params.organization_id)
            if params.from_date:
                query = query.filter(AuditLog.created_at >= params.from_date)
            if params.to_date:
                query = query.filter(AuditLog.created_at <= params.to_date)

            # 전체 개수
            total = query.count()

            # 페이지네이션
            offset = (params.page - 1) * params.limit
            logs = (
                query.order_by(AuditLog.created_at.desc())
                .offset(offset)
                .limit(params.limit)
                .all()
            )

            return ([AuditLogModel.model_validate(log) for log in logs], total)

    def get_audit_log_by_id(self, id: str) -> Optional[AuditLogModel]:
        """ID로 감사 로그 조회"""
        try:
            with get_db() as db:
                audit_log = db.query(AuditLog).filter_by(id=id).first()
                return AuditLogModel.model_validate(audit_log) if audit_log else None
        except Exception:
            return None

    def get_audit_logs_by_resource(
        self, resource_type: str, resource_id: str, limit: int = 100
    ) -> list[AuditLogModel]:
        """특정 리소스의 감사 로그 조회"""
        with get_db() as db:
            logs = (
                db.query(AuditLog)
                .filter(
                    AuditLog.resource_type == resource_type,
                    AuditLog.resource_id == resource_id,
                )
                .order_by(AuditLog.created_at.desc())
                .limit(limit)
                .all()
            )
            return [AuditLogModel.model_validate(log) for log in logs]

    def get_audit_logs_by_user(
        self, user_id: str, limit: int = 100
    ) -> list[AuditLogModel]:
        """특정 사용자의 활동 로그 조회"""
        with get_db() as db:
            logs = (
                db.query(AuditLog)
                .filter(AuditLog.user_id == user_id)
                .order_by(AuditLog.created_at.desc())
                .limit(limit)
                .all()
            )
            return [AuditLogModel.model_validate(log) for log in logs]

    def get_access_control_changes(
        self, resource_type: Optional[str] = None, limit: int = 100
    ) -> list[AuditLogModel]:
        """권한 변경 로그 조회"""
        with get_db() as db:
            query = db.query(AuditLog).filter(
                AuditLog.action == AuditAction.ACCESS_CONTROL_CHANGE.value
            )

            if resource_type:
                query = query.filter(AuditLog.resource_type == resource_type)

            logs = query.order_by(AuditLog.created_at.desc()).limit(limit).all()
            return [AuditLogModel.model_validate(log) for log in logs]

    def get_auth_logs(
        self, user_id: Optional[str] = None, limit: int = 100
    ) -> list[AuditLogModel]:
        """인증 관련 로그 조회"""
        with get_db() as db:
            auth_actions = [
                AuditAction.LOGIN.value,
                AuditAction.LOGOUT.value,
                AuditAction.LOGIN_FAILED.value,
                AuditAction.API_KEY_CREATED.value,
                AuditAction.API_KEY_DELETED.value,
            ]

            query = db.query(AuditLog).filter(AuditLog.action.in_(auth_actions))

            if user_id:
                query = query.filter(AuditLog.user_id == user_id)

            logs = query.order_by(AuditLog.created_at.desc()).limit(limit).all()
            return [AuditLogModel.model_validate(log) for log in logs]

    def delete_audit_logs_before(self, timestamp: int) -> int:
        """특정 시점 이전의 로그 삭제 (보존 기간 정책용)"""
        try:
            with get_db() as db:
                count = (
                    db.query(AuditLog).filter(AuditLog.created_at < timestamp).delete()
                )
                db.commit()
                return count
        except Exception as e:
            log.exception(f"Error deleting old audit logs: {e}")
            return 0

    def get_audit_log_stats(
        self,
        from_date: Optional[int] = None,
        to_date: Optional[int] = None,
        resource_type: Optional[str] = None,
        action: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> dict:
        """감사 로그 통계 조회"""
        with get_db() as db:
            from sqlalchemy import func

            query = db.query(AuditLog)

            if from_date:
                query = query.filter(AuditLog.created_at >= from_date)
            if to_date:
                query = query.filter(AuditLog.created_at <= to_date)
            if resource_type:
                resource_types = [rt.strip() for rt in resource_type.split(",")]
                if len(resource_types) == 1:
                    query = query.filter(AuditLog.resource_type == resource_types[0])
                else:
                    query = query.filter(AuditLog.resource_type.in_(resource_types))
            if action:
                actions = [a.strip() for a in action.split(",")]
                if len(actions) == 1:
                    query = query.filter(AuditLog.action == actions[0])
                else:
                    query = query.filter(AuditLog.action.in_(actions))
            if user_id:
                import re

                if re.match(
                    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
                    user_id,
                ):
                    query = query.filter(AuditLog.user_id == user_id)
                else:
                    query = query.filter(AuditLog.user_name.ilike(f"%{user_id}%"))

            # 액션별 카운트
            action_counts = (
                query.with_entities(AuditLog.action, func.count(AuditLog.id))
                .group_by(AuditLog.action)
                .all()
            )

            # 리소스 타입별 카운트
            resource_counts = (
                query.with_entities(AuditLog.resource_type, func.count(AuditLog.id))
                .group_by(AuditLog.resource_type)
                .all()
            )

            return {
                "by_action": {action: count for action, count in action_counts},
                "by_resource_type": {rt: count for rt, count in resource_counts},
                "total": query.count(),
            }


# Singleton instance
AuditLogs = AuditLogTable()

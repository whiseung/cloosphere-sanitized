import logging
import time
import uuid
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional, Sequence, Union
from zoneinfo import ZoneInfo

from open_webui.env import SRC_LOG_LEVELS
from open_webui.internal.db import Base, get_db
from pydantic import BaseModel, ConfigDict
from sqlalchemy import (
    JSON,
    BigInteger,
    Column,
    Index,
    Integer,
    String,
    distinct,
    func,
    or_,
)

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])


# 일일 한도 카운터의 "오늘" 기준 타임존. KST 자정 (= UTC 15:00 전일) 에 리셋.
# UTC 기준이면 한국 사용자가 KST 00:00 ~ 09:00 사이에 어제 사용분이 그대로 잡혀
# 사용률이 리셋 안 된 것처럼 보이는 문제 방지.
_LOCAL_DAY_TZ = ZoneInfo("Asia/Seoul")


def get_today_start_ts() -> int:
    """오늘(KST) 자정의 Unix timestamp.

    SQLAlchemy 의 `Usage.created_at >= since_ts` 비교에 쓰이며, KST 매일
    00:00 에 일일 카운터가 리셋된다.
    """
    return int(
        datetime.now(_LOCAL_DAY_TZ)
        .replace(hour=0, minute=0, second=0, microsecond=0)
        .timestamp()
    )


####################
# Usage Message Type
####################
class UsageMessageType(Enum):
    CHAT = "chat"
    EMBEDDING = "embedding"
    GENERATION = "generation"
    AGENT_STATE = "agent_state"
    REASONING = "reasoning"
    TOOL_CALL = "tool_call"
    SYSTEM = "system"
    # Background Tasks
    TITLE_GENERATION = "title_generation"
    TAGS_GENERATION = "tags_generation"
    EMOJI_GENERATION = "emoji_generation"
    QUERY_GENERATION = "query_generation"
    IMAGE_PROMPT_GENERATION = "image_prompt_generation"
    IMAGE_GENERATION = "image_generation"
    AUTOCOMPLETE_GENERATION = "autocomplete_generation"
    FUNCTION_CALLING = "function_calling"
    MOA_RESPONSE_GENERATION = "moa_response_generation"
    CODE_GATEWAY = "code_gateway"
    # 외부 서비스(예: Presenton)가 API 키로 /openai 게이트웨이를 직접 호출 — chat_id 없음.
    # 모니터링/가시성용. USER_QUOTA_MESSAGE_TYPES 에는 의도적으로 미등록(쿼터 잠식 방지).
    EXTERNAL_SERVICE = "external_service"


# 사용자 일일 한도 카운트 대상 (의도적 사용). 백그라운드 task 는 제외하므로
# 자동 title/tags/emoji/query 생성이 사용자 quota 를 잠식하지 않는다.
# 새 사용자 가시 message_type 추가 시 이 리스트에 명시적으로 등록 필요 (안 하면
# 한도 enforce 에서 빠짐 → 청구 위험). 새 배경 task 는 이 리스트에 추가 안 해야 함.
USER_QUOTA_MESSAGE_TYPES: list[str] = [
    UsageMessageType.CHAT.value,
    UsageMessageType.GENERATION.value,
    UsageMessageType.AGENT_STATE.value,
    UsageMessageType.REASONING.value,
    UsageMessageType.TOOL_CALL.value,
    UsageMessageType.FUNCTION_CALLING.value,
    UsageMessageType.IMAGE_GENERATION.value,
    UsageMessageType.CODE_GATEWAY.value,
    UsageMessageType.MOA_RESPONSE_GENERATION.value,
    UsageMessageType.EMBEDDING.value,  # RAG retrieval — 사용자 채팅에 직접 부수
]
# 명시 제외: TITLE_GENERATION, TAGS_GENERATION, EMOJI_GENERATION,
# QUERY_GENERATION, IMAGE_PROMPT_GENERATION, AUTOCOMPLETE_GENERATION, SYSTEM


####################
# Usage DB Schema
####################
class Usage(Base):
    __tablename__ = "log_usage"
    __table_args__ = (
        Index("ix_log_usage_user_id", "user_id"),
        Index("ix_log_usage_model_id", "model_id"),
        Index("ix_log_usage_agent_id", "agent_id"),
        Index("ix_log_usage_created_at", "created_at"),
        Index("ix_log_usage_message_type", "message_type"),
    )

    id = Column(String, primary_key=True, unique=True)
    user_id = Column(String)
    chat_id = Column(String)
    agent_id = Column(String, nullable=True)  # 워크스페이스 에이전트 ID
    model_id = Column(String)  # 실제 사용된 LLM 모델 ID
    message_id = Column(String, nullable=True)
    message_step = Column(Integer)
    message_type = Column(String)
    total_tokens = Column(Integer)
    usage = Column(JSON, nullable=True)
    tool_calls = Column(JSON, nullable=True)
    created_at = Column(BigInteger)
    updated_at = Column(BigInteger)


class UsageModel(BaseModel):
    id: str
    user_id: str
    chat_id: Optional[str] = None  # 임베딩 등 채팅 외 사용량은 None
    agent_id: Optional[str] = None  # 워크스페이스 에이전트 ID
    model_id: str  # 실제 사용된 LLM 모델 ID
    message_id: Optional[str] = None  # API 직접 호출 시 None
    message_step: int
    message_type: str
    total_tokens: int
    usage: Optional[dict] = None
    tool_calls: Optional[list[dict]] = None
    created_at: int
    updated_at: int
    model_config = ConfigDict(from_attributes=True)


####################
# Forms
####################


class UsageTable:
    def _get_user_ids_from_group(self, db, group_id: str) -> set:
        """그룹에 속한 사용자 ID 목록 조회"""
        from open_webui.models.groups import Group

        group = db.query(Group).filter_by(id=group_id).first()
        if group and group.user_ids:
            return set(group.user_ids)
        return set()

    def _get_user_ids_from_organization(self, db, organization_unit_id: str) -> set:
        """조직 단위(팀)에 속한 사용자 ID 목록 조회
        member_ids는 oauth_sub 값이므로 User 테이블에서 실제 user.id로 변환.
        meta.members의 이메일로도 매칭.
        """
        from open_webui.models.organization import OrganizationalUnit

        unit = db.query(OrganizationalUnit).filter_by(id=organization_unit_id).first()
        if not unit:
            return set()

        return self._resolve_unit_user_ids(db, unit)

    @staticmethod
    def _parse_filter(value: Optional[str]) -> Optional[list[str]]:
        """Parse comma-separated filter value.
        Returns None if no filter, empty list for '__none__' marker,
        or list of IDs for comma-separated values.
        """
        if not value:
            return None
        if value == "__none__":
            return []
        return [v.strip() for v in value.split(",") if v.strip()]

    def _apply_filters(
        self,
        db,
        query,
        model_id=None,
        user_id=None,
        group_id=None,
        organization_id=None,
        agent_id=None,
    ):
        """공통 필터 적용 (쉼표 구분 다중 값 지원)"""
        # Model filter
        model_ids = self._parse_filter(model_id)
        if model_ids is not None:
            if len(model_ids) == 0:
                query = query.filter(Usage.model_id == None)
            elif len(model_ids) == 1:
                query = query.filter(Usage.model_id == model_ids[0])
            else:
                query = query.filter(Usage.model_id.in_(model_ids))

        # Agent filter
        agent_ids = self._parse_filter(agent_id)
        if agent_ids is not None:
            if len(agent_ids) == 0:
                query = query.filter(Usage.agent_id == None)
            elif len(agent_ids) == 1:
                query = query.filter(Usage.agent_id == agent_ids[0])
            else:
                query = query.filter(Usage.agent_id.in_(agent_ids))

        # 사용자 ID 필터링 (그룹/조직 필터 포함)
        user_ids_filter = set()
        parsed_user_ids = self._parse_filter(user_id)
        if parsed_user_ids is not None:
            if len(parsed_user_ids) == 0:
                query = query.filter(Usage.user_id == None)
                return query
            user_ids_filter = set(parsed_user_ids)

        parsed_group_ids = self._parse_filter(group_id)
        if parsed_group_ids is not None:
            if len(parsed_group_ids) == 0:
                query = query.filter(Usage.user_id == None)
                return query
            group_user_ids = set()
            for gid in parsed_group_ids:
                group_user_ids.update(self._get_user_ids_from_group(db, gid))
            if user_ids_filter:
                user_ids_filter = user_ids_filter.intersection(group_user_ids)
            else:
                user_ids_filter = group_user_ids

        parsed_org_ids = self._parse_filter(organization_id)
        if parsed_org_ids is not None:
            if len(parsed_org_ids) == 0:
                query = query.filter(Usage.user_id == None)
                return query
            org_user_ids = set()
            for oid in parsed_org_ids:
                org_user_ids.update(self._get_user_ids_from_organization(db, oid))
            if user_ids_filter:
                user_ids_filter = user_ids_filter.intersection(org_user_ids)
            else:
                user_ids_filter = org_user_ids

        if user_ids_filter:
            query = query.filter(Usage.user_id.in_(user_ids_filter))
        elif (
            parsed_user_ids is not None
            or parsed_group_ids is not None
            or parsed_org_ids is not None
        ):
            # 필터가 있지만 매칭되는 사용자가 없는 경우
            query = query.filter(Usage.user_id == None)

        return query

    def get_user_daily_token_usage(self, user_id: str) -> int:
        """오늘(KST 자정 기준) 사용한 총 토큰 수 조회"""
        with get_db() as db:
            today_start = get_today_start_ts()

            result = (
                db.query(func.sum(Usage.total_tokens))
                .filter(
                    Usage.user_id == user_id,
                    Usage.created_at >= today_start,
                )
                .scalar()
            )
            return result or 0

    def get_user_daily_token_usage_for_model_row(
        self,
        user_id: str,
        model_row,
        message_types: Optional[Sequence[str]] = None,
    ) -> int:
        """오늘 (user, 특정 Model 행) 토큰 사용량 — since 일반화 버전의 today shortcut.

        `message_types` 지정 시 해당 타입만 합산 (사용자 한도 카운트엔
        `USER_QUOTA_MESSAGE_TYPES` 사용 권장). 오늘 기준은 KST 자정.
        """
        return self.get_user_token_usage_since_for_model_row(
            user_id, model_row, get_today_start_ts(), message_types=message_types
        )

    def get_user_token_usage_by_model_since(
        self,
        user_id: str,
        since_ts: int,
        message_types: Optional[Sequence[str]] = None,
    ) -> dict[str, int]:
        """주어진 시점 이후 (user, 모든 base 모델) 토큰 사용량을 한 번에 조회.

        agent 경유 호출은 `model_id=base` 로 적재되므로 base 단위 GROUP BY 만으로
        직접/agent 합산이 됨. 모델별 N+1 쿼리를 1 쿼리로 축약.

        Returns:
            {model_id: total_tokens}
        """
        with get_db() as db:
            query = db.query(Usage.model_id, func.sum(Usage.total_tokens)).filter(
                Usage.user_id == user_id,
                Usage.created_at >= since_ts,
            )
            if message_types:
                query = query.filter(Usage.message_type.in_(list(message_types)))
            return {
                mid: int(total or 0)
                for mid, total in query.group_by(Usage.model_id).all()
                if mid
            }

    def get_users_daily_token_usage_for_model_row(
        self,
        user_ids: Sequence[str],
        model_row,
        message_types: Optional[Sequence[str]] = None,
    ) -> dict[str, int]:
        """오늘 (여러 user, 특정 Model 행) 토큰 사용량을 한 번에 조회.

        per-model override 목록처럼 N 명의 사용량을 동시에 보여줘야 하는
        화면에서 N+1 쿼리를 1 쿼리로 축약. 누락된 user_id 는 결과 dict 에
        포함되지 않음 (호출자에서 0 으로 fallback).
        """
        if not user_ids or model_row is None:
            return {}
        with get_db() as db:
            query = db.query(Usage.user_id, func.sum(Usage.total_tokens)).filter(
                Usage.user_id.in_(list(user_ids)),
                Usage.created_at >= get_today_start_ts(),
            )
            if getattr(model_row, "base_model_id", None):
                query = query.filter(Usage.agent_id == model_row.id)
            else:
                query = query.filter(Usage.model_id == model_row.id)
            if message_types:
                query = query.filter(Usage.message_type.in_(list(message_types)))
            return {
                uid: int(total or 0)
                for uid, total in query.group_by(Usage.user_id).all()
                if uid
            }

    def get_user_token_usage_since_for_model_row(
        self,
        user_id: str,
        model_row,
        since_ts: int,
        message_types: Optional[Sequence[str]] = None,
    ) -> int:
        """주어진 시점(`since_ts`) 이후 (user, 특정 Model 행) 토큰 사용량.

        - workspace agent 행 (base_model_id 존재) → agent_id 필터
        - base LLM 행 → model_id 필터 (모든 호출 sum: agent 경유 + 직접 호출)
        - `message_types` 지정 시 `Usage.message_type IN (...)` 추가 필터
          (None = 전체 message_type 합산, 관리자 모니터링 등 운영 뷰용).
        """
        if model_row is None:
            return 0

        with get_db() as db:
            query = db.query(func.sum(Usage.total_tokens)).filter(
                Usage.user_id == user_id,
                Usage.created_at >= since_ts,
            )
            if getattr(model_row, "base_model_id", None):
                query = query.filter(Usage.agent_id == model_row.id)
            else:
                query = query.filter(Usage.model_id == model_row.id)

            if message_types:
                query = query.filter(Usage.message_type.in_(list(message_types)))

            return query.scalar() or 0

    def insert_new_usage(
        self,
        user_id: str,
        chat_id: Optional[str],
        model_id: str,
        message_id: Optional[str],
        message_type: Union[UsageMessageType, str],
        total_tokens: int,
        agent_id: Optional[str] = None,
        usage: Optional[dict] = None,
        message_step: int = None,
        tool_calls: Optional[list[dict]] = None,
    ) -> Optional[UsageModel]:
        if isinstance(message_type, UsageMessageType):
            message_type = message_type.value

        with get_db() as db:
            id = str(uuid.uuid4())

            if message_step is None:
                if message_id:
                    last_usage = (
                        db.query(Usage)
                        .filter_by(message_id=message_id)
                        .order_by(Usage.message_step.desc())
                        .first()
                    )
                    if last_usage:
                        message_step = last_usage.message_step + 1
                    else:
                        message_step = 1
                else:
                    message_step = 1

            usage_record = Usage(
                **{
                    "id": id,
                    "user_id": user_id,
                    "chat_id": chat_id,
                    "agent_id": agent_id,
                    "model_id": model_id,
                    "message_id": message_id,
                    "message_step": message_step,
                    "message_type": message_type,
                    "total_tokens": total_tokens,
                    "usage": usage,
                    "tool_calls": tool_calls,
                    "created_at": int(time.time()),
                    "updated_at": int(time.time()),
                }
            )
            db.add(usage_record)
            db.commit()
            db.refresh(usage_record)
            return UsageModel.model_validate(usage_record)

    ####################
    # Filter Options
    ####################

    def _get_non_model_ids(self, db) -> set:
        """에이전트/플로우 등 순수 LLM 모델이 아닌 ID 목록 조회

        - base_model_id가 있는 모델 = 워크스페이스 에이전트
        - ID가 'flow_' 또는 'flow.'로 시작 = Agent Flow 모델
        """
        from open_webui.models.models import Model

        agents = (
            db.query(Model.id)
            .filter(
                (Model.base_model_id.isnot(None))
                | (Model.id.like("flow!_%", escape="!"))
                | (Model.id.like("flow.%"))
            )
            .all()
        )
        return {a.id for a in agents}

    def get_available_models(self) -> list[dict]:
        """사용된 모델 목록 조회 (에이전트 제외)"""
        with get_db() as db:
            results = (
                db.query(distinct(Usage.model_id))
                .filter(Usage.model_id.isnot(None))
                .all()
            )
            model_ids = [r[0] for r in results if r[0]]

            non_model_ids = self._get_non_model_ids(db)
            return [{"id": m, "name": m} for m in model_ids if m not in non_model_ids]

    def get_available_users(self) -> list[dict]:
        """사용량이 있는 사용자 목록 조회"""
        from open_webui.models.users import User

        with get_db() as db:
            user_ids_result = (
                db.query(distinct(Usage.user_id))
                .filter(Usage.user_id.isnot(None))
                .all()
            )
            user_ids = [r[0] for r in user_ids_result if r[0]]

            users = db.query(User).filter(User.id.in_(user_ids)).all()
            return [{"id": u.id, "name": u.name or u.email} for u in users]

    def get_available_groups(self) -> list[dict]:
        """그룹 목록 조회"""
        from open_webui.models.groups import Group

        with get_db() as db:
            groups = db.query(Group).order_by(Group.name).all()
            return [{"id": g.id, "name": g.name} for g in groups]

    def get_available_organizations(self) -> list[dict]:
        """조직 단위(팀) 목록 조회"""
        from open_webui.models.organization import Organization, OrganizationalUnit

        with get_db() as db:
            units = (
                db.query(OrganizationalUnit)
                .order_by(
                    OrganizationalUnit.organization_id,
                    OrganizationalUnit.level,
                    OrganizationalUnit.name,
                )
                .all()
            )
            organizations = db.query(Organization).all()
            org_map = {org.id: org.display_name or org.name for org in organizations}

            result = []
            for unit in units:
                org_name = org_map.get(unit.organization_id, "")
                unit_name = unit.display_name or unit.name
                display_name = f"{org_name} / {unit_name}" if org_name else unit_name
                result.append({"id": unit.id, "name": display_name})

            return result

    def get_available_agents(self) -> list[dict]:
        """사용된 에이전트 목록 조회"""
        from open_webui.models.models import Model
        from sqlalchemy import and_

        with get_db() as db:
            results = (
                db.query(distinct(Usage.agent_id))
                .filter(and_(Usage.agent_id.isnot(None), Usage.agent_id != ""))
                .all()
            )

            agent_ids = [r[0] for r in results if r[0]]

            if not agent_ids:
                return []

            agents = db.query(Model).filter(Model.id.in_(agent_ids)).all()
            agent_map = {a.id: a.name for a in agents}

            result = []
            for agent_id in agent_ids:
                result.append(
                    {"id": agent_id, "name": agent_map.get(agent_id, agent_id)}
                )

            return sorted(result, key=lambda x: x["name"])

    ####################
    # Statistics
    ####################

    def get_usage_stats(
        self,
        from_date: Optional[int] = None,
        to_date: Optional[int] = None,
        model_id: Optional[str] = None,
        user_id: Optional[str] = None,
        group_id: Optional[str] = None,
        organization_id: Optional[str] = None,
        agent_id: Optional[str] = None,
    ) -> dict:
        """사용량 요약 통계"""
        with get_db() as db:
            query = db.query(Usage)

            if from_date:
                query = query.filter(Usage.created_at >= from_date)
            if to_date:
                query = query.filter(Usage.created_at <= to_date)

            query = self._apply_filters(
                db, query, model_id, user_id, group_id, organization_id, agent_id
            )

            total_tokens = (
                query.with_entities(func.sum(Usage.total_tokens)).scalar() or 0
            )
            total_requests = query.count()
            unique_users = (
                query.with_entities(func.count(distinct(Usage.user_id))).scalar() or 0
            )
            unique_chats = (
                query.with_entities(func.count(distinct(Usage.chat_id))).scalar() or 0
            )
            unique_models = (
                query.with_entities(func.count(distinct(Usage.model_id))).scalar() or 0
            )

            avg_tokens = total_tokens / total_requests if total_requests > 0 else 0

            return {
                "total_tokens": total_tokens,
                "total_requests": total_requests,
                "unique_users": unique_users,
                "unique_chats": unique_chats,
                "unique_models": unique_models,
                "avg_tokens_per_request": round(avg_tokens, 2),
            }

    def get_usage_trends(
        self,
        from_date: Optional[int] = None,
        to_date: Optional[int] = None,
        granularity: str = "day",  # day, hour
        model_id: Optional[str] = None,
        user_id: Optional[str] = None,
        group_id: Optional[str] = None,
        organization_id: Optional[str] = None,
        agent_id: Optional[str] = None,
    ) -> list[dict]:
        """시계열 사용량 데이터"""

        with get_db() as db:
            query = db.query(Usage)

            if from_date:
                query = query.filter(Usage.created_at >= from_date)
            if to_date:
                query = query.filter(Usage.created_at <= to_date)

            query = self._apply_filters(
                db, query, model_id, user_id, group_id, organization_id, agent_id
            )

            usages = query.order_by(Usage.created_at.asc()).all()

            # 시간대별 집계
            trends = {}
            for usage in usages:
                dt = datetime.fromtimestamp(usage.created_at)
                if granularity == "hour":
                    key = dt.strftime("%Y-%m-%d %H:00")
                else:
                    key = dt.strftime("%Y-%m-%d")

                if key not in trends:
                    trends[key] = {"date": key, "tokens": 0, "requests": 0}
                trends[key]["tokens"] += usage.total_tokens or 0
                trends[key]["requests"] += 1

            # 지정된 기간의 모든 날짜/시간을 채워서 반환
            if from_date and to_date:
                result = []
                current = datetime.fromtimestamp(from_date)
                end = datetime.fromtimestamp(to_date)

                if granularity == "hour":
                    # 시작 시간을 정시로 맞춤
                    current = current.replace(minute=0, second=0, microsecond=0)
                    delta = timedelta(hours=1)
                    fmt = "%Y-%m-%d %H:00"
                else:
                    # 시작 날짜를 자정으로 맞춤
                    current = current.replace(hour=0, minute=0, second=0, microsecond=0)
                    delta = timedelta(days=1)
                    fmt = "%Y-%m-%d"

                while current <= end:
                    key = current.strftime(fmt)
                    if key in trends:
                        result.append(trends[key])
                    else:
                        result.append({"date": key, "tokens": 0, "requests": 0})
                    current += delta

                return result

            return list(trends.values())

    def get_usage_by_model(
        self,
        from_date: Optional[int] = None,
        to_date: Optional[int] = None,
        model_id: Optional[str] = None,
        user_id: Optional[str] = None,
        group_id: Optional[str] = None,
        organization_id: Optional[str] = None,
        agent_id: Optional[str] = None,
    ) -> list[dict]:
        """모델별 사용량 집계 (에이전트 제외)"""
        with get_db() as db:
            query = db.query(
                Usage.model_id,
                func.sum(Usage.total_tokens).label("total_tokens"),
                func.count(Usage.id).label("request_count"),
            )

            if from_date:
                query = query.filter(Usage.created_at >= from_date)
            if to_date:
                query = query.filter(Usage.created_at <= to_date)

            # 에이전트/플로우 제외 (순수 LLM 모델만)
            non_model_ids = self._get_non_model_ids(db)
            if non_model_ids:
                query = query.filter(Usage.model_id.notin_(non_model_ids))

            query = self._apply_filters(
                db, query, model_id, user_id, group_id, organization_id, agent_id
            )

            results = query.group_by(Usage.model_id).all()

            return [
                {
                    "model_id": r.model_id,
                    "total_tokens": r.total_tokens or 0,
                    "request_count": r.request_count,
                }
                for r in results
            ]

    def get_usage_by_user(
        self,
        from_date: Optional[int] = None,
        to_date: Optional[int] = None,
        limit: int = 20,
        model_id: Optional[str] = None,
        user_id: Optional[str] = None,
        group_id: Optional[str] = None,
        organization_id: Optional[str] = None,
        agent_id: Optional[str] = None,
    ) -> list[dict]:
        """사용자별 사용량 집계"""
        from open_webui.models.users import User

        with get_db() as db:
            query = db.query(
                Usage.user_id,
                func.sum(Usage.total_tokens).label("total_tokens"),
                func.count(Usage.id).label("request_count"),
            )

            if from_date:
                query = query.filter(Usage.created_at >= from_date)
            if to_date:
                query = query.filter(Usage.created_at <= to_date)

            query = self._apply_filters(
                db, query, model_id, user_id, group_id, organization_id, agent_id
            )

            results = (
                query.group_by(Usage.user_id)
                .order_by(func.sum(Usage.total_tokens).desc())
                .limit(limit)
                .all()
            )

            # 사용자 정보 조회
            user_ids = [r.user_id for r in results]
            users = db.query(User).filter(User.id.in_(user_ids)).all()
            user_map = {u.id: {"name": u.name, "email": u.email} for u in users}

            return [
                {
                    "user_id": r.user_id,
                    "user_name": user_map.get(r.user_id, {}).get("name", "Unknown"),
                    "user_email": user_map.get(r.user_id, {}).get("email", ""),
                    "total_tokens": r.total_tokens or 0,
                    "request_count": r.request_count,
                }
                for r in results
            ]

    def get_usage_by_group(
        self,
        from_date: Optional[int] = None,
        to_date: Optional[int] = None,
        limit: int = 10,
        model_id: Optional[str] = None,
        user_id: Optional[str] = None,
        group_id: Optional[str] = None,
        organization_id: Optional[str] = None,
        agent_id: Optional[str] = None,
    ) -> list[dict]:
        """그룹별 사용량 집계"""
        from open_webui.models.groups import Group

        with get_db() as db:
            # 먼저 사용자별 토큰 집계
            query = db.query(
                Usage.user_id,
                func.sum(Usage.total_tokens).label("total_tokens"),
                func.count(Usage.id).label("request_count"),
            )

            if from_date:
                query = query.filter(Usage.created_at >= from_date)
            if to_date:
                query = query.filter(Usage.created_at <= to_date)

            query = self._apply_filters(
                db, query, model_id, user_id, None, organization_id, agent_id
            )

            user_usage = {
                r.user_id: {"tokens": r.total_tokens or 0, "requests": r.request_count}
                for r in query.group_by(Usage.user_id).all()
            }

            # 그룹 정보 조회 (group_id 필터 적용)
            parsed_group_ids = self._parse_filter(group_id)
            if parsed_group_ids is not None:
                if len(parsed_group_ids) == 0:
                    return []
                groups = db.query(Group).filter(Group.id.in_(parsed_group_ids)).all()
            else:
                groups = db.query(Group).all()
            group_usage = []

            for group in groups:
                group_tokens = 0
                group_requests = 0
                user_ids = group.user_ids or []

                for uid in user_ids:
                    if uid in user_usage:
                        group_tokens += user_usage[uid]["tokens"]
                        group_requests += user_usage[uid]["requests"]

                if group_tokens > 0 or group_requests > 0:
                    group_usage.append(
                        {
                            "group_id": group.id,
                            "group_name": group.name,
                            "total_tokens": group_tokens,
                            "request_count": group_requests,
                            "user_count": len(user_ids),
                        }
                    )

            # 토큰 순으로 정렬 후 limit 적용
            group_usage.sort(key=lambda x: x["total_tokens"], reverse=True)
            return group_usage[:limit]

    def _resolve_unit_user_ids(self, db, unit) -> set:
        """조직 단위의 member_ids(oauth_sub) + meta.members(email)를 실제 user.id로 변환"""
        from open_webui.models.users import User

        user_ids = set()

        # 1. member_ids (oauth_sub) → user.id
        if unit.member_ids:
            users_by_sub = (
                db.query(User.id).filter(User.oauth_sub.in_(unit.member_ids)).all()
            )
            user_ids.update(u.id for u in users_by_sub)

        # 2. meta.members 이메일 → user.id
        if unit.meta and "members" in unit.meta:
            member_emails = [
                m.get("email", "").lower()
                for m in unit.meta.get("members", [])
                if m.get("email")
            ]
            if member_emails:
                users_by_email = (
                    db.query(User.id)
                    .filter(func.lower(User.email).in_(member_emails))
                    .all()
                )
                user_ids.update(u.id for u in users_by_email)

        return user_ids

    def get_usage_by_organization(
        self,
        from_date: Optional[int] = None,
        to_date: Optional[int] = None,
        limit: int = 10,
        model_id: Optional[str] = None,
        user_id: Optional[str] = None,
        group_id: Optional[str] = None,
        organization_id: Optional[str] = None,
        agent_id: Optional[str] = None,
    ) -> list[dict]:
        """조직 단위(팀)별 사용량 집계"""
        from open_webui.models.organization import Organization, OrganizationalUnit

        with get_db() as db:
            # 먼저 사용자별 토큰 집계
            query = db.query(
                Usage.user_id,
                func.sum(Usage.total_tokens).label("total_tokens"),
                func.count(Usage.id).label("request_count"),
            )

            if from_date:
                query = query.filter(Usage.created_at >= from_date)
            if to_date:
                query = query.filter(Usage.created_at <= to_date)

            query = self._apply_filters(
                db, query, model_id, user_id, group_id, None, agent_id
            )

            user_usage = {
                r.user_id: {"tokens": r.total_tokens or 0, "requests": r.request_count}
                for r in query.group_by(Usage.user_id).all()
            }

            # 조직 단위(팀) 정보 조회 (organization_id 필터 적용)
            parsed_org_ids = self._parse_filter(organization_id)
            if parsed_org_ids is not None:
                if len(parsed_org_ids) == 0:
                    return []
                org_units = (
                    db.query(OrganizationalUnit)
                    .filter(OrganizationalUnit.id.in_(parsed_org_ids))
                    .all()
                )
            else:
                org_units = db.query(OrganizationalUnit).all()
            organizations = db.query(Organization).all()
            org_map = {org.id: org.display_name or org.name for org in organizations}

            unit_usage = []
            for unit in org_units:
                unit_tokens = 0
                unit_requests = 0

                # member_ids(oauth_sub)/meta.members(email) → 실제 user.id 변환
                resolved_user_ids = self._resolve_unit_user_ids(db, unit)

                for uid in resolved_user_ids:
                    if uid in user_usage:
                        unit_tokens += user_usage[uid]["tokens"]
                        unit_requests += user_usage[uid]["requests"]

                # 사용량이 있는 팀만 포함
                if unit_tokens > 0 or unit_requests > 0:
                    # 조직명 + 단위명 조합으로 표시
                    org_name = org_map.get(unit.organization_id, "")
                    unit_name = unit.display_name or unit.name
                    display_name = (
                        f"{org_name} / {unit_name}" if org_name else unit_name
                    )

                    unit_usage.append(
                        {
                            "organization_id": unit.id,  # 조직 단위 ID
                            "organization_name": display_name,
                            "total_tokens": unit_tokens,
                            "request_count": unit_requests,
                            "user_count": len(resolved_user_ids),
                        }
                    )

            # 토큰 순으로 정렬 후 limit 적용
            unit_usage.sort(key=lambda x: x["total_tokens"], reverse=True)
            return unit_usage[:limit]

    def get_usage_by_type(
        self,
        from_date: Optional[int] = None,
        to_date: Optional[int] = None,
        model_id: Optional[str] = None,
        user_id: Optional[str] = None,
        group_id: Optional[str] = None,
        organization_id: Optional[str] = None,
        agent_id: Optional[str] = None,
    ) -> list[dict]:
        """메시지 타입별 사용량 집계"""
        with get_db() as db:
            query = db.query(
                Usage.message_type,
                func.sum(Usage.total_tokens).label("total_tokens"),
                func.count(Usage.id).label("request_count"),
            )

            if from_date:
                query = query.filter(Usage.created_at >= from_date)
            if to_date:
                query = query.filter(Usage.created_at <= to_date)

            query = self._apply_filters(
                db, query, model_id, user_id, group_id, organization_id, agent_id
            )

            results = query.group_by(Usage.message_type).all()

            return [
                {
                    "message_type": r.message_type,
                    "total_tokens": r.total_tokens or 0,
                    "request_count": r.request_count,
                }
                for r in results
            ]

    def get_usage_by_agent(
        self,
        from_date: Optional[int] = None,
        to_date: Optional[int] = None,
        limit: int = 10,
        model_id: Optional[str] = None,
        user_id: Optional[str] = None,
        group_id: Optional[str] = None,
        organization_id: Optional[str] = None,
        agent_id: Optional[str] = None,
    ) -> list[dict]:
        """에이전트별 사용량 집계"""
        from open_webui.models.models import Model

        with get_db() as db:
            query = db.query(
                Usage.agent_id,
                func.sum(Usage.total_tokens).label("total_tokens"),
                func.count(Usage.id).label("request_count"),
            )

            if from_date:
                query = query.filter(Usage.created_at >= from_date)
            if to_date:
                query = query.filter(Usage.created_at <= to_date)

            # agent_id가 있는 레코드만 필터링 (단, agent_id 필터가 있으면 스킵)
            if not agent_id:
                query = query.filter(Usage.agent_id != None)
                query = query.filter(Usage.agent_id != "")

            query = self._apply_filters(
                db, query, model_id, user_id, group_id, organization_id, agent_id
            )

            results = (
                query.group_by(Usage.agent_id)
                .order_by(func.sum(Usage.total_tokens).desc())
                .limit(limit)
                .all()
            )

            # 에이전트 정보 조회
            agent_ids = [r.agent_id for r in results if r.agent_id]
            agents = db.query(Model).filter(Model.id.in_(agent_ids)).all()
            agent_map = {a.id: a.name for a in agents}

            return [
                {
                    "agent_id": r.agent_id,
                    "agent_name": agent_map.get(r.agent_id, r.agent_id or "Unknown"),
                    "total_tokens": r.total_tokens or 0,
                    "request_count": r.request_count,
                }
                for r in results
                if r.agent_id
            ]

    ####################
    # Code Gateway Usage
    ####################

    def get_code_gateway_logs(
        self,
        page: int = 1,
        limit: int = 50,
        user_id: Optional[str] = None,
        model_id: Optional[str] = None,
        from_date: Optional[int] = None,
        to_date: Optional[int] = None,
    ) -> dict:
        from open_webui.models.users import User

        with get_db() as db:
            query = db.query(Usage).filter(
                Usage.message_type == UsageMessageType.CODE_GATEWAY.value
            )

            if user_id:
                query = query.filter(Usage.user_id == user_id)
            if model_id:
                query = query.filter(Usage.model_id == model_id)
            if from_date:
                query = query.filter(Usage.created_at >= from_date)
            if to_date:
                query = query.filter(Usage.created_at <= to_date)

            total = query.count()
            records = (
                query.order_by(Usage.created_at.desc())
                .offset((page - 1) * limit)
                .limit(limit)
                .all()
            )

            # Batch user lookup
            user_ids = {r.user_id for r in records if r.user_id}
            users = {
                u.id: u for u in db.query(User).filter(User.id.in_(user_ids)).all()
            }

            # Batch agent name lookup
            agent_ids = {r.agent_id for r in records if r.agent_id}
            agent_names = {}
            if agent_ids:
                from open_webui.models.models import Model

                for m in (
                    db.query(Model.id, Model.name).filter(Model.id.in_(agent_ids)).all()
                ):
                    agent_names[m.id] = m.name

            items = []
            for r in records:
                u = users.get(r.user_id)
                usage_data = r.usage or {}
                req_summary = usage_data.get("request_summary", {})
                items.append(
                    {
                        "id": r.id,
                        "user_id": r.user_id,
                        "user_name": u.name if u else "",
                        "user_email": u.email if u else "",
                        "model_id": r.model_id or "",
                        "agent_id": r.agent_id or "",
                        "agent_name": agent_names.get(r.agent_id, ""),
                        "chat_id": r.chat_id or "",
                        "message_id": r.message_id or "",
                        "provider": usage_data.get("provider", ""),
                        "total_tokens": r.total_tokens or 0,
                        "input_tokens": usage_data.get("input_tokens")
                        or usage_data.get("prompt_tokens", 0),
                        "output_tokens": usage_data.get("output_tokens")
                        or usage_data.get("completion_tokens", 0),
                        "input_preview": req_summary.get("input_preview", ""),
                        "output_preview": usage_data.get("output_preview", ""),
                        "message_count": req_summary.get("message_count"),
                        "tools_count": req_summary.get("tools_count"),
                        "tool_calls": r.tool_calls or [],
                        "token_details": usage_data.get("token_details", {}),
                        "finish_reason": usage_data.get("finish_reason", ""),
                        "client_type": usage_data.get("client_type", ""),
                        "created_at": r.created_at,
                    }
                )

            return {
                "items": items,
                "total": total,
                "page": page,
                "limit": limit,
                "total_pages": max(1, (total + limit - 1) // limit),
            }

    def get_code_gateway_filter_models(self) -> list[dict]:
        with get_db() as db:
            results = (
                db.query(distinct(Usage.model_id))
                .filter(
                    Usage.message_type == UsageMessageType.CODE_GATEWAY.value,
                    Usage.model_id.isnot(None),
                )
                .all()
            )
            return [{"id": r[0], "name": r[0]} for r in results if r[0]]

    def get_code_gateway_filter_users(self) -> list[dict]:
        from open_webui.models.users import User

        with get_db() as db:
            user_ids = (
                db.query(distinct(Usage.user_id))
                .filter(
                    Usage.message_type == UsageMessageType.CODE_GATEWAY.value,
                    Usage.user_id.isnot(None),
                )
                .all()
            )
            user_ids = [r[0] for r in user_ids if r[0]]
            users = db.query(User).filter(User.id.in_(user_ids)).all()
            return [{"id": u.id, "name": u.name or u.email} for u in users]

    def get_code_gateway_stats(
        self,
        from_date: Optional[int] = None,
        to_date: Optional[int] = None,
    ) -> dict:
        with get_db() as db:
            query = db.query(Usage).filter(
                Usage.message_type == UsageMessageType.CODE_GATEWAY.value
            )
            if from_date:
                query = query.filter(Usage.created_at >= from_date)
            if to_date:
                query = query.filter(Usage.created_at <= to_date)

            total_requests = query.count()
            total_tokens = (
                db.query(func.sum(Usage.total_tokens))
                .filter(
                    Usage.message_type == UsageMessageType.CODE_GATEWAY.value,
                    *([Usage.created_at >= from_date] if from_date else []),
                    *([Usage.created_at <= to_date] if to_date else []),
                )
                .scalar()
                or 0
            )
            unique_users = (
                db.query(func.count(distinct(Usage.user_id)))
                .filter(
                    Usage.message_type == UsageMessageType.CODE_GATEWAY.value,
                    *([Usage.created_at >= from_date] if from_date else []),
                    *([Usage.created_at <= to_date] if to_date else []),
                )
                .scalar()
                or 0
            )
            unique_models = (
                db.query(func.count(distinct(Usage.model_id)))
                .filter(
                    Usage.message_type == UsageMessageType.CODE_GATEWAY.value,
                    *([Usage.created_at >= from_date] if from_date else []),
                    *([Usage.created_at <= to_date] if to_date else []),
                )
                .scalar()
                or 0
            )

            return {
                "total_requests": total_requests,
                "total_tokens": total_tokens,
                "unique_users": unique_users,
                "unique_models": unique_models,
            }

    ####################
    # Conversation Logs (Chat + Code Gateway + Agent)
    ####################

    @staticmethod
    def _build_source_type_filter(
        source_type: Optional[str],
        include_agent_steps: bool = False,
    ):
        """콤마 구분 source_type 문자열을 SQLAlchemy 필터로 변환.

        Args:
            source_type: 콤마 구분 문자열 (예: "chat,agent")
            include_agent_steps: True면 agent 선택 시 agent_state, tool_call도 포함 (토큰 합계용)

        Returns:
            SQLAlchemy filter condition 또는 None (필터 불필요 시)
        """
        if not source_type:
            return None

        source_map = {
            "chat": Usage.message_type == UsageMessageType.CHAT.value,
            "code_gateway": Usage.message_type == UsageMessageType.CODE_GATEWAY.value,
            "agent": (
                Usage.message_type.in_(
                    [
                        UsageMessageType.GENERATION.value,
                        UsageMessageType.AGENT_STATE.value,
                        UsageMessageType.TOOL_CALL.value,
                    ]
                )
                if include_agent_steps
                else Usage.message_type == UsageMessageType.GENERATION.value
            ),
            "api": Usage.usage["client_type"].as_string() == "api_key",
        }

        types = [t.strip() for t in source_type.split(",")]
        conditions = [source_map[t] for t in types if t in source_map]

        if not conditions:
            return None
        if len(conditions) == 1:
            return conditions[0]
        return or_(*conditions)

    def get_conversation_logs(
        self,
        page: int = 1,
        limit: int = 50,
        user_id: Optional[str] = None,
        user_search: Optional[str] = None,
        model_id: Optional[str] = None,
        source_type: Optional[str] = None,
        from_date: Optional[int] = None,
        to_date: Optional[int] = None,
    ) -> dict:
        from open_webui.models.users import User

        with get_db() as db:
            query = db.query(Usage).filter(
                Usage.message_type.in_(
                    [
                        UsageMessageType.CHAT.value,
                        UsageMessageType.CODE_GATEWAY.value,
                        UsageMessageType.GENERATION.value,
                    ]
                )
            )

            # Source type filter (콤마 구분 다중 값 지원)
            source_filter = self._build_source_type_filter(source_type)
            if source_filter is not None:
                query = query.filter(source_filter)

            if user_id:
                query = query.filter(Usage.user_id == user_id)
            elif user_search:
                # 사용자 이름/이메일로 검색하여 user_id 목록 조회
                keyword = f"%{user_search}%"
                matched_users = (
                    db.query(User.id)
                    .filter(
                        or_(
                            User.name.ilike(keyword),
                            User.email.ilike(keyword),
                        )
                    )
                    .all()
                )
                matched_ids = [u.id for u in matched_users]
                if matched_ids:
                    query = query.filter(Usage.user_id.in_(matched_ids))
                else:
                    query = query.filter(Usage.user_id == None)
            # Model filter (콤마 구분 다중 값 지원)
            if model_id:
                model_ids = [m.strip() for m in model_id.split(",")]
                if len(model_ids) == 1:
                    query = query.filter(Usage.model_id == model_ids[0])
                else:
                    query = query.filter(Usage.model_id.in_(model_ids))
            if from_date:
                query = query.filter(Usage.created_at >= from_date)
            if to_date:
                query = query.filter(Usage.created_at <= to_date)

            total = query.count()
            records = (
                query.order_by(Usage.created_at.desc())
                .offset((page - 1) * limit)
                .limit(limit)
                .all()
            )

            # Batch user lookup
            user_ids = {r.user_id for r in records if r.user_id}
            users = {
                u.id: u for u in db.query(User).filter(User.id.in_(user_ids)).all()
            }

            # Batch agent name lookup
            agent_ids = {r.agent_id for r in records if r.agent_id}
            agent_names = {}
            if agent_ids:
                from open_webui.models.models import Model

                for m in (
                    db.query(Model.id, Model.name).filter(Model.id.in_(agent_ids)).all()
                ):
                    agent_names[m.id] = m.name

            # Batch chat.meta lookup (embed widget 정보 등을 렌더링하기 위함)
            chat_ids = {r.chat_id for r in records if r.chat_id}
            chat_meta_by_id: dict = {}
            if chat_ids:
                from open_webui.models.chats import Chat

                for c in (
                    db.query(Chat.id, Chat.meta).filter(Chat.id.in_(chat_ids)).all()
                ):
                    chat_meta_by_id[c.id] = c.meta or {}

            # Aggregate total tokens per message_id
            # (including agent_state, tool_call steps for the same message)
            # Also build per-model breakdown for detail view
            msg_ids = {r.message_id for r in records if r.message_id}
            agg_tokens: dict = {}
            model_breakdown: dict = {}  # message_id -> {model_id -> {total, input, output}}
            agg_tool_calls: dict = {}  # message_id -> list of tool_call dicts
            agg_token_details: dict = {}  # message_id -> {input: {}, output: {}}
            if msg_ids:
                _all_conv_types = [
                    UsageMessageType.CHAT.value,
                    UsageMessageType.CODE_GATEWAY.value,
                    UsageMessageType.GENERATION.value,
                    UsageMessageType.AGENT_STATE.value,
                    UsageMessageType.TOOL_CALL.value,
                    UsageMessageType.EMBEDDING.value,
                ]
                related = (
                    db.query(Usage)
                    .filter(
                        Usage.message_id.in_(msg_ids),
                        Usage.message_type.in_(_all_conv_types),
                    )
                    .all()
                )
                for rel in related:
                    mid = rel.message_id
                    ud = rel.usage or {}
                    input_t = ud.get("input_tokens") or ud.get("prompt_tokens", 0)
                    output_t = ud.get("output_tokens") or ud.get("completion_tokens", 0)
                    total_t = rel.total_tokens or 0

                    # Aggregate totals
                    if mid not in agg_tokens:
                        agg_tokens[mid] = {"total": 0, "input": 0, "output": 0}
                    agg_tokens[mid]["total"] += total_t
                    agg_tokens[mid]["input"] += input_t
                    agg_tokens[mid]["output"] += output_t

                    # Per-model breakdown
                    model_id = rel.model_id or ""
                    if mid not in model_breakdown:
                        model_breakdown[mid] = {}
                    if model_id not in model_breakdown[mid]:
                        model_breakdown[mid][model_id] = {
                            "total": 0,
                            "input": 0,
                            "output": 0,
                        }
                    model_breakdown[mid][model_id]["total"] += total_t
                    model_breakdown[mid][model_id]["input"] += input_t
                    model_breakdown[mid][model_id]["output"] += output_t

                    # Collect tool_calls
                    if rel.tool_calls:
                        if mid not in agg_tool_calls:
                            agg_tool_calls[mid] = []
                        agg_tool_calls[mid].extend(rel.tool_calls)

                    # Collect token_details (cached_tokens, reasoning_tokens, etc.)
                    td = ud.get("token_details")
                    if td:
                        if mid not in agg_token_details:
                            agg_token_details[mid] = {}
                        for k, v in td.items():
                            if isinstance(v, dict):
                                if k not in agg_token_details[mid]:
                                    agg_token_details[mid][k] = {}
                                for sk, sv in v.items():
                                    if isinstance(sv, (int, float)):
                                        agg_token_details[mid][k][sk] = (
                                            agg_token_details[mid][k].get(sk, 0) + sv
                                        )
                                    elif sk not in agg_token_details[mid][k]:
                                        agg_token_details[mid][k][sk] = sv

            items = []
            for r in records:
                u = users.get(r.user_id)
                usage_data = r.usage or {}
                req_summary = usage_data.get("request_summary", {})
                agg = agg_tokens.get(r.message_id)

                # Build usage_breakdown list (sorted by total tokens desc)
                breakdown_dict = model_breakdown.get(r.message_id, {})
                usage_breakdown = sorted(
                    [
                        {
                            "model_id": mid,
                            "total_tokens": v["total"],
                            "input_tokens": v["input"],
                            "output_tokens": v["output"],
                        }
                        for mid, v in breakdown_dict.items()
                    ],
                    key=lambda x: x["total_tokens"],
                    reverse=True,
                )

                # tool_calls: from aggregated related records, or from primary record
                tool_calls = agg_tool_calls.get(r.message_id, [])
                if not tool_calls and r.tool_calls:
                    tool_calls = r.tool_calls

                # token_details: from aggregated related records, or from primary usage
                token_details = agg_token_details.get(r.message_id, {})
                if not token_details:
                    td = usage_data.get("token_details")
                    if td:
                        token_details = td

                chat_meta = chat_meta_by_id.get(r.chat_id, {}) if r.chat_id else {}
                items.append(
                    {
                        "id": r.id,
                        "user_id": r.user_id,
                        "user_name": u.name if u else "",
                        "user_email": u.email if u else "",
                        "model_id": r.model_id or "",
                        "agent_id": r.agent_id or "",
                        "agent_name": agent_names.get(r.agent_id, ""),
                        "source_type": r.message_type or "",
                        "chat_id": r.chat_id or "",
                        "embed_widget_id": chat_meta.get("embed_widget_id", ""),
                        "embed_widget_name": chat_meta.get("embed_widget_name", ""),
                        "message_id": r.message_id or "",
                        "total_tokens": agg["total"] if agg else (r.total_tokens or 0),
                        "input_tokens": agg["input"]
                        if agg
                        else (
                            usage_data.get("input_tokens")
                            or usage_data.get("prompt_tokens", 0)
                        ),
                        "output_tokens": agg["output"]
                        if agg
                        else (
                            usage_data.get("output_tokens")
                            or usage_data.get("completion_tokens", 0)
                        ),
                        "input_preview": req_summary.get("input_preview", ""),
                        "output_preview": usage_data.get("output_preview", ""),
                        "message_count": req_summary.get("message_count"),
                        "finish_reason": usage_data.get("finish_reason", ""),
                        "usage_breakdown": usage_breakdown,
                        "tool_calls": tool_calls,
                        "token_details": token_details,
                        "client_type": usage_data.get("client_type", ""),
                        "created_at": r.created_at,
                    }
                )

            return {
                "items": items,
                "total": total,
                "page": page,
                "limit": limit,
                "total_pages": max(1, (total + limit - 1) // limit),
            }

    def get_conversation_log_stats(
        self,
        from_date: Optional[int] = None,
        to_date: Optional[int] = None,
        source_type: Optional[str] = None,
    ) -> dict:
        with get_db() as db:
            # Primary types for request count / unique users / unique models
            _primary_types = [
                UsageMessageType.CHAT.value,
                UsageMessageType.CODE_GATEWAY.value,
                UsageMessageType.GENERATION.value,
            ]
            # All conversation types for token sum
            # (includes agent internal steps: agent_state, tool_call)
            _all_types = _primary_types + [
                UsageMessageType.AGENT_STATE.value,
                UsageMessageType.TOOL_CALL.value,
                UsageMessageType.EMBEDDING.value,
            ]

            primary_query = db.query(Usage).filter(
                Usage.message_type.in_(_primary_types)
            )
            token_query = db.query(Usage).filter(Usage.message_type.in_(_all_types))

            # Source type filter (콤마 구분 다중 값 지원)
            source_filter = self._build_source_type_filter(source_type)
            if source_filter is not None:
                primary_query = primary_query.filter(source_filter)
                # agent 토큰 합계 시 내부 스텝도 포함
                token_source_filter = self._build_source_type_filter(
                    source_type, include_agent_steps=True
                )
                token_query = token_query.filter(token_source_filter)

            if from_date:
                primary_query = primary_query.filter(Usage.created_at >= from_date)
                token_query = token_query.filter(Usage.created_at >= from_date)
            if to_date:
                primary_query = primary_query.filter(Usage.created_at <= to_date)
                token_query = token_query.filter(Usage.created_at <= to_date)

            total_requests = primary_query.count()
            total_tokens = (
                token_query.with_entities(func.sum(Usage.total_tokens)).scalar() or 0
            )
            unique_users = (
                primary_query.with_entities(
                    func.count(distinct(Usage.user_id))
                ).scalar()
                or 0
            )
            unique_models = (
                primary_query.with_entities(
                    func.count(distinct(Usage.model_id))
                ).scalar()
                or 0
            )

            return {
                "total_requests": total_requests,
                "total_tokens": total_tokens,
                "unique_users": unique_users,
                "unique_models": unique_models,
            }

    def get_conversation_log_filter_models(
        self,
        source_type: Optional[str] = None,
    ) -> list[dict]:
        with get_db() as db:
            query = db.query(distinct(Usage.model_id)).filter(
                Usage.message_type.in_(
                    [
                        UsageMessageType.CHAT.value,
                        UsageMessageType.CODE_GATEWAY.value,
                        UsageMessageType.GENERATION.value,
                    ]
                ),
                Usage.model_id.isnot(None),
            )

            source_filter = self._build_source_type_filter(source_type)
            if source_filter is not None:
                query = query.filter(source_filter)

            results = query.all()
            return [{"id": r[0], "name": r[0]} for r in results if r[0]]

    def get_conversation_log_filter_users(
        self,
        source_type: Optional[str] = None,
    ) -> list[dict]:
        from open_webui.models.users import User

        with get_db() as db:
            query = db.query(distinct(Usage.user_id)).filter(
                Usage.message_type.in_(
                    [
                        UsageMessageType.CHAT.value,
                        UsageMessageType.CODE_GATEWAY.value,
                        UsageMessageType.GENERATION.value,
                    ]
                ),
                Usage.user_id.isnot(None),
            )

            source_filter = self._build_source_type_filter(source_type)
            if source_filter is not None:
                query = query.filter(source_filter)

            user_ids = [r[0] for r in query.all() if r[0]]
            users = db.query(User).filter(User.id.in_(user_ids)).all()
            return [{"id": u.id, "name": u.name or u.email} for u in users]

    def delete_usage_logs_before(self, timestamp: int) -> int:
        """특정 시점 이전의 사용량 로그 삭제 (보존 기간 정책용)"""
        try:
            with get_db() as db:
                count = db.query(Usage).filter(Usage.created_at < timestamp).delete()
                db.commit()
                return count
        except Exception as e:
            log.exception(f"Error deleting old usage logs: {e}")
            return 0


Usages = UsageTable()

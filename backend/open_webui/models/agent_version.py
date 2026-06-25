import json
import logging
import time
import uuid
from typing import Optional

from open_webui.env import SRC_LOG_LEVELS
from open_webui.internal.db import Base, get_db
from pydantic import BaseModel, ConfigDict
from sqlalchemy import JSON, BigInteger, Column, Text

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])


####################
# AgentVersion DB Schema
####################

# 워크스페이스 에이전트(Model 행 중 base_model_id 보유) 설정 전체의 버전 스냅샷.
# - 부모 물리 테이블은 `model` 이지만 Cloosphere 에서 `model`/`model_id` 는 LLM
#   모델(gpt-4 등)도 지칭해 혼동되므로, 도메인 용어 `agent_*` 를 쓴다.
#   FK 대상은 여전히 `model.id`(워크스페이스 에이전트).
# - `model` 행 = 항상 최신(HEAD). 이 테이블은 과거 보관소.


class AgentVersion(Base):
    __tablename__ = "agent_version"

    id = Column(Text, primary_key=True)
    agent_id = Column(Text)  # model.id 참조 (워크스페이스 에이전트)
    version_number = Column(BigInteger)  # agent 별 시퀀스 (1, 2, 3 …)
    snapshot = Column(JSON)  # name, base_model_id, params, meta, access_control
    label = Column(Text, nullable=True)  # 사용자 이름표 (자동 생성 시 None)
    user_id = Column(Text)  # 에이전트 소유자 (멀티테넌시)
    created_by = Column(Text)  # 이 버전을 저장한 사용자 (소유자와 다를 수 있음)
    created_at = Column(BigInteger)


class AgentVersionModel(BaseModel):
    id: str
    agent_id: str
    version_number: int
    snapshot: dict
    label: Optional[str] = None
    user_id: str
    created_by: str
    created_at: int

    model_config = ConfigDict(from_attributes=True)


####################
# Forms / Responses
####################


# 목록용 경량 응답 (snapshot 본문 제외 — 상세 조회에서만 내려줌)
class AgentVersionResponse(BaseModel):
    id: str
    agent_id: str
    version_number: int
    label: Optional[str] = None
    user_id: str
    created_by: str
    created_at: int

    model_config = ConfigDict(from_attributes=True)


class AgentVersionLabelForm(BaseModel):
    label: Optional[str] = None


def _normalize(snapshot: dict) -> str:
    """dedup 비교용 정규화 — 키 순서·JSON 라운드트립 차이 무시."""
    return json.dumps(snapshot or {}, sort_keys=True, ensure_ascii=False)


class AgentVersionsTable:
    def create_version(
        self,
        agent_id: str,
        snapshot: dict,
        user_id: str,
        created_by: str,
        label: Optional[str] = None,
    ) -> Optional[AgentVersionModel]:
        """에이전트 설정 스냅샷을 새 버전으로 append.

        - base_model_id 가 없는 행(=base 모델)은 버전을 만들지 않는다 (skip → None).
        - 직전 HEAD 와 deep-equal 이면 새 버전을 만들지 않고 HEAD 를 반환 (no-op dedup).
        """
        # 게이트: 워크스페이스 에이전트(base_model_id 보유)만 버전 생성.
        if not snapshot.get("base_model_id"):
            return None
        try:
            with get_db() as db:
                head = (
                    db.query(AgentVersion)
                    .filter_by(agent_id=agent_id)
                    .order_by(AgentVersion.version_number.desc())
                    .first()
                )
                # no-op dedup
                if head is not None and _normalize(head.snapshot) == _normalize(
                    snapshot
                ):
                    return AgentVersionModel.model_validate(head)

                next_no = (head.version_number + 1) if head is not None else 1
                row = AgentVersion(
                    id=str(uuid.uuid4()),
                    agent_id=agent_id,
                    version_number=next_no,
                    snapshot=snapshot,
                    label=label,
                    user_id=user_id,
                    created_by=created_by,
                    created_at=int(time.time()),
                )
                db.add(row)
                db.commit()
                db.refresh(row)
                return AgentVersionModel.model_validate(row)
        except Exception as e:
            log.exception(f"Failed to create agent version for {agent_id}: {e}")
            return None

    def get_versions_by_agent_id(self, agent_id: str) -> list[AgentVersionResponse]:
        with get_db() as db:
            return [
                AgentVersionResponse.model_validate(v)
                for v in db.query(AgentVersion)
                .filter_by(agent_id=agent_id)
                .order_by(AgentVersion.version_number.desc())
                .all()
            ]

    def get_version(
        self, agent_id: str, version_number: int
    ) -> Optional[AgentVersionModel]:
        try:
            with get_db() as db:
                v = (
                    db.query(AgentVersion)
                    .filter_by(agent_id=agent_id, version_number=version_number)
                    .first()
                )
                return AgentVersionModel.model_validate(v) if v else None
        except Exception:
            return None

    def update_label(
        self, agent_id: str, version_number: int, label: Optional[str]
    ) -> Optional[AgentVersionModel]:
        try:
            with get_db() as db:
                v = (
                    db.query(AgentVersion)
                    .filter_by(agent_id=agent_id, version_number=version_number)
                    .first()
                )
                if not v:
                    return None
                v.label = label
                db.commit()
                db.refresh(v)
                return AgentVersionModel.model_validate(v)
        except Exception:
            return None

    def delete_versions_by_agent_id(self, agent_id: str) -> bool:
        """에이전트 삭제 시 버전 이력 정리 (cascade)."""
        try:
            with get_db() as db:
                db.query(AgentVersion).filter_by(agent_id=agent_id).delete()
                db.commit()
                return True
        except Exception:
            return False


AgentVersions = AgentVersionsTable()

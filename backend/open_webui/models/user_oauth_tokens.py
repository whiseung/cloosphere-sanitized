"""사용자별 OAuth provider 토큰 보관.

로그인 시 OAuth provider(microsoft/google) 가 발급한 access_token / refresh_token
을 사용자별로 저장. Outlook / Gmail 등 Graph / Gmail API 호출 시 이 테이블에서
토큰을 꺼내 쓰고 만료 임박이면 refresh_token 으로 갱신한다.

(user_id, provider) 가 unique — 한 사용자당 provider 하나의 활성 토큰만 유지.
"""

import logging
import time
import uuid
from typing import Optional

from open_webui.env import SRC_LOG_LEVELS
from open_webui.internal.db import Base, get_db
from open_webui.utils.secrets import decrypt_str, encrypt_str
from pydantic import BaseModel, ConfigDict
from sqlalchemy import BigInteger, Column, Text, UniqueConstraint

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])


####################
# DB Schema
####################


class UserOAuthToken(Base):
    __tablename__ = "user_oauth_token"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "provider", name="uq_user_oauth_token_user_provider"
        ),
    )

    id = Column(Text, unique=True, primary_key=True)
    user_id = Column(Text, nullable=False, index=True)
    provider = Column(Text, nullable=False)  # 'microsoft' | 'google'
    access_token = Column(Text, nullable=False)
    refresh_token = Column(Text, nullable=True)
    expires_at = Column(BigInteger, nullable=False)  # epoch seconds
    scopes = Column(Text, nullable=True)  # 공백 구분 scope 문자열 (감사/디버깅용)
    account_email = Column(Text, nullable=True)  # provider 측 계정 식별 — UI 표시용
    created_at = Column(BigInteger)
    updated_at = Column(BigInteger)


####################
# Pydantic
####################


class UserOAuthTokenModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    provider: str
    access_token: str
    refresh_token: Optional[str] = None
    expires_at: int
    scopes: Optional[str] = None
    account_email: Optional[str] = None
    created_at: int
    updated_at: int


####################
# CRUD
####################


class UserOAuthTokensTable:
    def upsert(
        self,
        user_id: str,
        provider: str,
        access_token: str,
        refresh_token: Optional[str],
        expires_at: int,
        scopes: Optional[str] = None,
        account_email: Optional[str] = None,
    ) -> Optional[UserOAuthTokenModel]:
        """있으면 갱신, 없으면 새로 삽입.

        access_token / refresh_token 은 Fernet 으로 암호화해 DB 에 저장한다 —
        DB 덤프/백업 유출 시 KEK 없이 복호화 불가.

        주의: refresh_token 이 빈 값으로 들어오면 기존 값을 보존한다.
        Microsoft/Google 모두 refresh 응답에서 새 refresh_token 을 항상 주지 않으며
        (rotation 이 아닌 reuse 정책), 빈 값으로 덮으면 다음 갱신이 깨진다.
        """
        encrypted_access = encrypt_str(access_token)
        encrypted_refresh = encrypt_str(refresh_token) if refresh_token else None

        with get_db() as db:
            row = (
                db.query(UserOAuthToken)
                .filter(
                    UserOAuthToken.user_id == user_id,
                    UserOAuthToken.provider == provider,
                )
                .first()
            )
            now = int(time.time())
            if row is None:
                row = UserOAuthToken(
                    id=str(uuid.uuid4()),
                    user_id=user_id,
                    provider=provider,
                    access_token=encrypted_access,
                    refresh_token=encrypted_refresh,
                    expires_at=expires_at,
                    scopes=scopes,
                    account_email=account_email,
                    created_at=now,
                    updated_at=now,
                )
                db.add(row)
            else:
                row.access_token = encrypted_access
                if refresh_token:
                    row.refresh_token = encrypted_refresh
                row.expires_at = expires_at
                if scopes is not None:
                    row.scopes = scopes
                if account_email is not None:
                    row.account_email = account_email
                row.updated_at = now
            db.commit()
            db.refresh(row)
            # Pydantic 모델로 반환할 때 호출 측이 평문 토큰을 기대 → 복호화.
            return self._row_to_model(row)

    def get(self, user_id: str, provider: str) -> Optional[UserOAuthTokenModel]:
        with get_db() as db:
            row = (
                db.query(UserOAuthToken)
                .filter(
                    UserOAuthToken.user_id == user_id,
                    UserOAuthToken.provider == provider,
                )
                .first()
            )
            return self._row_to_model(row) if row else None

    def list_by_user(self, user_id: str) -> list[UserOAuthTokenModel]:
        with get_db() as db:
            rows = (
                db.query(UserOAuthToken).filter(UserOAuthToken.user_id == user_id).all()
            )
            return [self._row_to_model(r) for r in rows]

    @staticmethod
    def _row_to_model(row: UserOAuthToken) -> UserOAuthTokenModel:
        """ORM row → Pydantic 모델 변환 + 토큰 컬럼 복호화."""
        return UserOAuthTokenModel(
            id=row.id,
            user_id=row.user_id,
            provider=row.provider,
            access_token=decrypt_str(row.access_token) or "",
            refresh_token=decrypt_str(row.refresh_token),
            expires_at=row.expires_at,
            scopes=row.scopes,
            account_email=row.account_email,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    def delete(self, user_id: str, provider: str) -> bool:
        with get_db() as db:
            row = (
                db.query(UserOAuthToken)
                .filter(
                    UserOAuthToken.user_id == user_id,
                    UserOAuthToken.provider == provider,
                )
                .first()
            )
            if not row:
                return False
            db.delete(row)
            db.commit()
            return True

    def delete_by_user(self, user_id: str) -> int:
        with get_db() as db:
            count = (
                db.query(UserOAuthToken)
                .filter(UserOAuthToken.user_id == user_id)
                .delete()
            )
            db.commit()
            return count


UserOAuthTokens = UserOAuthTokensTable()

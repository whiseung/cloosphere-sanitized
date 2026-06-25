import hashlib
import logging
import time
from typing import Optional

from open_webui.internal.db import Base, JSONField, get_db
from open_webui.models.chats import Chats
from open_webui.models.groups import Groups
from open_webui.utils.crypto import EncryptedText
from pydantic import BaseModel, ConfigDict
from sqlalchemy import BigInteger, Column, String, Text
from sqlalchemy.orm.attributes import flag_modified

log = logging.getLogger(__name__)


def hash_api_key(api_key: str) -> str:
    """Stable SHA-256 hex digest of an API key — used as a unique lookup
    index. Envelope-encrypted ciphertext can't be queried by equality
    (non-deterministic), so the hash carries the search key while the
    encrypted column carries the recoverable value.

    Empty / None input returns "" so callers can compare cleanly without
    None-handling at every site.
    """
    if not api_key:
        return ""
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


####################
# User DB Schema
####################


class User(Base):
    __tablename__ = "user"

    id = Column(String, primary_key=True)
    name = Column(String)
    email = Column(String)
    role = Column(String)
    profile_image_url = Column(Text)

    last_active_at = Column(BigInteger)
    updated_at = Column(BigInteger)
    created_at = Column(BigInteger)

    # KMS Phase 4.1: api_key value lives in DB as ciphertext (envelope under the
    # configured KMS provider, falling back to local Fernet). Lookup happens via
    # api_key_hash because envelope is non-deterministic — same plaintext yields
    # different ciphertext on each encrypt, so an indexed equality search on the
    # ciphertext itself is impossible. The Stripe / Slack pattern.
    #
    # Existing pre-migration rows still hold plaintext in api_key — EncryptedText
    # passes plaintext through on read, encrypts on next write. The unique
    # constraint that used to enforce key uniqueness is migrated to api_key_hash.
    api_key = Column(EncryptedText, nullable=True)
    api_key_hash = Column(String(64), nullable=True, unique=True, index=True)
    settings = Column(JSONField, nullable=True)
    info = Column(JSONField, nullable=True)

    oauth_sub = Column(Text, unique=True)

    # Entra / Azure AD 의 `oid` claim. `sub` 는 앱별 pairwise pseudonymous 이므로
    # Teams Activity 의 `from.aadObjectId` 와 직접 매칭되지 않는다. 별도 `oid` 를
    # 저장해 Teams 봇 등 외부 Entra 연동에서 사용자 식별용으로 사용.
    oauth_oid = Column(Text, nullable=True, index=True)


class UserSettings(BaseModel):
    ui: Optional[dict] = {}
    model_config = ConfigDict(extra="allow")
    pass


class UserModel(BaseModel):
    id: str
    name: str
    email: str
    role: str = "pending"
    profile_image_url: str

    last_active_at: int  # timestamp in epoch
    updated_at: int  # timestamp in epoch
    created_at: int  # timestamp in epoch

    api_key: Optional[str] = None
    settings: Optional[UserSettings] = None
    info: Optional[dict] = None

    oauth_sub: Optional[str] = None
    oauth_oid: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


####################
# Forms
####################


class UserResponse(BaseModel):
    id: str
    name: str
    email: str
    role: str
    profile_image_url: str


class UserNameResponse(BaseModel):
    id: str
    name: str
    role: str
    profile_image_url: str


class UserRoleUpdateForm(BaseModel):
    id: str
    role: str


class UserUpdateForm(BaseModel):
    name: str
    email: str
    profile_image_url: str
    password: Optional[str] = None
    role: Optional[str] = None


class UsersTable:
    def insert_new_user(
        self,
        id: str,
        name: str,
        email: str,
        profile_image_url: str = "/user.png",
        role: str = "pending",
        oauth_sub: Optional[str] = None,
    ) -> Optional[UserModel]:
        with get_db() as db:
            user = UserModel(
                **{
                    "id": id,
                    "name": name,
                    "email": email,
                    "role": role,
                    "profile_image_url": profile_image_url,
                    "last_active_at": int(time.time()),
                    "created_at": int(time.time()),
                    "updated_at": int(time.time()),
                    "oauth_sub": oauth_sub,
                }
            )
            result = User(**user.model_dump())
            db.add(result)
            db.commit()
            db.refresh(result)
            if result:
                return user
            else:
                return None

    def get_user_by_id(self, id: str) -> Optional[UserModel]:
        try:
            with get_db() as db:
                user = db.query(User).filter_by(id=id).first()
                return UserModel.model_validate(user)
        except Exception:
            return None

    def get_user_by_api_key(self, api_key: str) -> Optional[UserModel]:
        """Look up a user by API key.

        Primary path: SHA-256 hash equality on `api_key_hash`. This is the
        only path that works once envelope encryption is in effect — the
        ciphertext stored in `api_key` is non-deterministic and cannot be
        searched by equality.

        Fallback path: legacy plaintext rows that predate Phase 4.1 still
        carry the raw key in `api_key` and have NULL `api_key_hash`. We
        match those by direct equality and lazily backfill the hash so
        the next call uses the fast indexed path.
        """
        if not api_key:
            return None
        try:
            with get_db() as db:
                key_hash = hash_api_key(api_key)
                user = db.query(User).filter_by(api_key_hash=key_hash).first()
                if user:
                    return UserModel.model_validate(user)

                # Legacy fallback — pre-migration rows where api_key is
                # raw plaintext (NULL hash). Cannot use ORM filter_by here
                # because the EncryptedText type decorator runs
                # process_bind_param on the comparison value and would
                # encrypt the plaintext we are searching for, producing a
                # non-deterministic ciphertext that never matches the DB
                # row. Use raw SQL to compare plaintext against plaintext.
                from sqlalchemy import text

                row = db.execute(
                    text(
                        'SELECT id FROM "user" '
                        "WHERE api_key_hash IS NULL AND api_key = :v"
                    ),
                    {"v": api_key},
                ).fetchone()
                if row is None:
                    return None
                user = db.query(User).filter_by(id=row[0]).first()
                if user is None:
                    return None
                # Lazy backfill so the next lookup uses the indexed path.
                user.api_key_hash = key_hash
                # Force-flush api_key so EncryptedText.process_bind_param
                # encrypts the legacy plaintext on disk. SQLAlchemy would
                # otherwise treat "set to current in-memory value" as a
                # no-op and skip the UPDATE — the in-memory value is the
                # plaintext that came back through process_result_value.
                user.api_key = api_key
                flag_modified(user, "api_key")
                db.commit()
                db.refresh(user)
                return UserModel.model_validate(user)
        except Exception as e:
            log.warning("get_user_by_api_key failed: %s", e)
            return None

    def get_user_by_email(self, email: str) -> Optional[UserModel]:
        try:
            with get_db() as db:
                user = db.query(User).filter_by(email=email).first()
                return UserModel.model_validate(user)
        except Exception:
            return None

    def get_user_by_oauth_sub(self, sub: str) -> Optional[UserModel]:
        try:
            with get_db() as db:
                user = db.query(User).filter_by(oauth_sub=sub).first()
                return UserModel.model_validate(user)
        except Exception:
            return None

    def get_user_by_oauth_oid(self, oid: str) -> Optional[UserModel]:
        """Entra `oid` claim 으로 사용자 조회. Teams 봇이 Activity.from.aadObjectId
        를 이걸로 매칭. MS 로그인을 한 번이라도 한 사용자만 `oauth_oid` 가 채워짐."""
        try:
            with get_db() as db:
                user = db.query(User).filter_by(oauth_oid=oid).first()
                return UserModel.model_validate(user)
        except Exception:
            return None

    def get_users(
        self, skip: Optional[int] = None, limit: Optional[int] = None
    ) -> list[UserModel]:
        with get_db() as db:
            query = db.query(User).order_by(User.created_at.desc())

            if skip:
                query = query.offset(skip)
            if limit:
                query = query.limit(limit)

            users = query.all()

            return [UserModel.model_validate(user) for user in users]

    def search_users(self, query: str, limit: int = 50) -> list[UserModel]:
        with get_db() as db:
            pattern = f"%{query}%"
            users = (
                db.query(User)
                .filter((User.name.ilike(pattern)) | (User.email.ilike(pattern)))
                .order_by(User.name.asc())
                .limit(limit)
                .all()
            )
            return [UserModel.model_validate(user) for user in users]

    def get_users_by_user_ids(self, user_ids: list[str]) -> list[UserModel]:
        with get_db() as db:
            users = db.query(User).filter(User.id.in_(user_ids)).all()
            return [UserModel.model_validate(user) for user in users]

    def get_num_users(self) -> Optional[int]:
        with get_db() as db:
            return db.query(User).count()

    def get_first_user(self) -> UserModel:
        try:
            with get_db() as db:
                user = db.query(User).order_by(User.created_at).first()
                return UserModel.model_validate(user)
        except Exception:
            return None

    def get_user_webhook_url_by_id(self, id: str) -> Optional[str]:
        try:
            with get_db() as db:
                user = db.query(User).filter_by(id=id).first()

                if user.settings is None:
                    return None
                else:
                    return (
                        user.settings.get("ui", {})
                        .get("notifications", {})
                        .get("webhook_url", None)
                    )
        except Exception:
            return None

    def update_user_role_by_id(self, id: str, role: str) -> Optional[UserModel]:
        try:
            with get_db() as db:
                db.query(User).filter_by(id=id).update({"role": role})
                db.commit()
                user = db.query(User).filter_by(id=id).first()
                return UserModel.model_validate(user)
        except Exception:
            return None

    def update_user_profile_image_url_by_id(
        self, id: str, profile_image_url: str
    ) -> Optional[UserModel]:
        try:
            with get_db() as db:
                db.query(User).filter_by(id=id).update(
                    {"profile_image_url": profile_image_url}
                )
                db.commit()

                user = db.query(User).filter_by(id=id).first()
                return UserModel.model_validate(user)
        except Exception:
            return None

    def update_user_last_active_by_id(self, id: str) -> Optional[UserModel]:
        try:
            with get_db() as db:
                db.query(User).filter_by(id=id).update(
                    {"last_active_at": int(time.time())}
                )
                db.commit()

                user = db.query(User).filter_by(id=id).first()
                return UserModel.model_validate(user)
        except Exception:
            return None

    def update_user_oauth_sub_by_id(
        self, id: str, oauth_sub: str
    ) -> Optional[UserModel]:
        try:
            with get_db() as db:
                db.query(User).filter_by(id=id).update({"oauth_sub": oauth_sub})
                db.commit()

                user = db.query(User).filter_by(id=id).first()
                return UserModel.model_validate(user)
        except Exception:
            return None

    def update_user_oauth_oid_by_id(
        self, id: str, oauth_oid: str
    ) -> Optional[UserModel]:
        try:
            with get_db() as db:
                db.query(User).filter_by(id=id).update({"oauth_oid": oauth_oid})
                db.commit()

                user = db.query(User).filter_by(id=id).first()
                return UserModel.model_validate(user)
        except Exception:
            return None

    def update_user_by_id(self, id: str, updated: dict) -> Optional[UserModel]:
        try:
            with get_db() as db:
                db.query(User).filter_by(id=id).update(updated)
                db.commit()

                user = db.query(User).filter_by(id=id).first()
                return UserModel.model_validate(user)
                # return UserModel(**user.dict())
        except Exception:
            return None

    def update_user_settings_by_id(self, id: str, updated: dict) -> Optional[UserModel]:
        try:
            with get_db() as db:
                user_settings = db.query(User).filter_by(id=id).first().settings

                if user_settings is None:
                    user_settings = {}

                user_settings.update(updated)

                db.query(User).filter_by(id=id).update({"settings": user_settings})
                db.commit()

                user = db.query(User).filter_by(id=id).first()
                return UserModel.model_validate(user)
        except Exception:
            return None

    def delete_user_by_id(self, id: str) -> bool:
        try:
            # Remove User from Groups
            Groups.remove_user_from_all_groups(id)

            # Delete User Chats
            result = Chats.delete_chats_by_user_id(id)
            if result:
                with get_db() as db:
                    # Delete User
                    user = db.query(User).filter_by(id=id).first()
                    if user:
                        db.delete(user)
                        db.commit()
                        return True
                return False
            else:
                return False
        except Exception:
            return False

    def update_user_api_key_by_id(self, id: str, api_key: Optional[str]) -> bool:
        """Set or clear a user's API key.

        Both `api_key` (encrypted) and `api_key_hash` (lookup index) are
        updated together so they cannot drift. Passing None clears both.
        """
        try:
            with get_db() as db:
                user = db.query(User).filter_by(id=id).first()
                if not user:
                    return False
                user.api_key = api_key  # EncryptedText encrypts on flush
                user.api_key_hash = hash_api_key(api_key) if api_key else None
                db.commit()
                return True
        except Exception:
            return False

    def get_user_api_key_by_id(self, id: str) -> Optional[str]:
        """Return the user's plaintext API key for display.

        EncryptedText.process_result_value transparently decrypts on
        read, so legacy plaintext rows and Phase-4.1 ciphertext both
        return as plaintext.
        """
        try:
            with get_db() as db:
                user = db.query(User).filter_by(id=id).first()
                return user.api_key if user else None
        except Exception:
            return None

    def get_valid_user_ids(self, user_ids: list[str]) -> list[str]:
        with get_db() as db:
            users = db.query(User).filter(User.id.in_(user_ids)).all()
            return [user.id for user in users]


Users = UsersTable()

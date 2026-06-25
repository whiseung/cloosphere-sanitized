import copy
import logging
import time
import uuid
from typing import Optional

from open_webui.env import SRC_LOG_LEVELS
from open_webui.internal.db import Base, get_db
from open_webui.models.users import UserResponse, Users
from open_webui.utils.access_control import has_access
from open_webui.utils.crypto import decrypt_value, encrypt_value, is_encrypted
from pydantic import BaseModel, ConfigDict
from sqlalchemy import JSON, BigInteger, Column, Text

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])

####################
# ToolConnection DB Schema
####################


class ToolConnection(Base):
    __tablename__ = "tool_connection"

    id = Column(Text, unique=True, primary_key=True)
    user_id = Column(Text)

    name = Column(Text)
    description = Column(Text)

    data = Column(JSON, nullable=True)  # Connection details (url, auth, etc.)
    meta = Column(JSON, nullable=True)  # Additional metadata

    access_control = Column(JSON, nullable=True)

    created_at = Column(BigInteger)
    updated_at = Column(BigInteger)


class ToolConnectionModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str

    name: str
    description: str

    data: Optional[dict] = None
    meta: Optional[dict] = None

    access_control: Optional[dict] = None

    created_at: int
    updated_at: int


####################
# Forms
####################


class ToolConnectionUserModel(ToolConnectionModel):
    user: Optional[UserResponse] = None


class ToolConnectionResponse(ToolConnectionModel):
    pass


class ToolConnectionUserResponse(ToolConnectionUserModel):
    pass


class ToolConnectionForm(BaseModel):
    name: str
    description: str
    data: Optional[dict] = None
    meta: Optional[dict] = None
    access_control: Optional[dict] = None


# --------------------------------------------------------------------------
# Field-level encryption
# --------------------------------------------------------------------------
#
# `data.connection.key` carries the tool-server bearer token / API key for
# MCP and OpenAPI connections. The encryption is transparent at the model
# boundary: callers always see plaintext, the DB always stores ciphertext
# (legacy plaintext rows decrypt as plaintext via the `is_encrypted` guard).

_ENCRYPTED_DATA_PATHS: tuple[tuple[str, ...], ...] = (("connection", "key"),)


def _walk(data: dict, path: tuple[str, ...]) -> tuple[Optional[dict], Optional[str]]:
    """Return (parent_dict, leaf_key) for a path, or (None, None) if missing."""
    if not isinstance(data, dict) or not path:
        return None, None
    cur: object = data
    for part in path[:-1]:
        if not isinstance(cur, dict) or part not in cur:
            return None, None
        cur = cur[part]
    if not isinstance(cur, dict):
        return None, None
    return cur, path[-1]


def _encrypt_data_in_place(data: Optional[dict]) -> Optional[dict]:
    if not data:
        return data
    for path in _ENCRYPTED_DATA_PATHS:
        parent, leaf = _walk(data, path)
        if parent is None or leaf is None:
            continue
        value = parent.get(leaf)
        if isinstance(value, str) and value and not is_encrypted(value):
            try:
                parent[leaf] = encrypt_value(value)
            except Exception as e:
                log.warning("tool_connection encrypt %s failed: %s", path, e)
    return data


def _decrypt_data_in_place(data: Optional[dict]) -> Optional[dict]:
    if not data:
        return data
    for path in _ENCRYPTED_DATA_PATHS:
        parent, leaf = _walk(data, path)
        if parent is None or leaf is None:
            continue
        value = parent.get(leaf)
        if isinstance(value, str) and is_encrypted(value):
            try:
                parent[leaf] = decrypt_value(value)
            except Exception as e:
                log.warning("tool_connection decrypt %s failed: %s", path, e)
    return data


def _to_model_decrypted(orm_row) -> "ToolConnectionModel":
    """ORM row → ToolConnectionModel with decrypted data fields. Always
    operates on a deep copy so the SQLAlchemy session-attached dict is
    never mutated in place (which would round-trip plaintext back to disk
    on the next flush)."""
    payload = ToolConnectionModel.model_validate(orm_row).model_dump()
    payload["data"] = _decrypt_data_in_place(copy.deepcopy(payload.get("data")))
    return ToolConnectionModel.model_validate(payload)


class ToolConnectionTable:
    def name_exists(self, name: str, exclude_id: Optional[str] = None) -> bool:
        with get_db() as db:
            query = db.query(ToolConnection).filter(ToolConnection.name == name.strip())
            if exclude_id:
                query = query.filter(ToolConnection.id != exclude_id)
            return query.first() is not None

    def insert_new_tool_connection(
        self, user_id: str, form_data: ToolConnectionForm
    ) -> Optional[ToolConnectionModel]:
        with get_db() as db:
            payload = form_data.model_dump()
            payload["data"] = _encrypt_data_in_place(copy.deepcopy(payload.get("data")))

            tool_connection = ToolConnectionModel(
                **{
                    **payload,
                    "id": str(uuid.uuid4()),
                    "user_id": user_id,
                    "created_at": int(time.time()),
                    "updated_at": int(time.time()),
                }
            )

            try:
                result = ToolConnection(**tool_connection.model_dump())
                db.add(result)
                db.commit()
                db.refresh(result)
                if result:
                    return _to_model_decrypted(result)
                else:
                    return None
            except Exception:
                return None

    def get_tool_connections(self) -> list[ToolConnectionUserModel]:
        with get_db() as db:
            tool_connections = []
            for tool_connection in (
                db.query(ToolConnection)
                .order_by(ToolConnection.updated_at.desc())
                .all()
            ):
                user = Users.get_user_by_id(tool_connection.user_id)
                tool_connections.append(
                    ToolConnectionUserModel.model_validate(
                        {
                            **_to_model_decrypted(tool_connection).model_dump(),
                            "user": user.model_dump() if user else None,
                        }
                    )
                )
            return tool_connections

    def get_tool_connections_by_user_id(
        self, user_id: str, permission: str = "write"
    ) -> list[ToolConnectionUserModel]:
        tool_connections = self.get_tool_connections()
        return [
            tool_connection
            for tool_connection in tool_connections
            if tool_connection.user_id == user_id
            or has_access(user_id, permission, tool_connection.access_control)
        ]

    def get_tool_connection_by_id(self, id: str) -> Optional[ToolConnectionModel]:
        try:
            with get_db() as db:
                tool_connection = db.query(ToolConnection).filter_by(id=id).first()
                return _to_model_decrypted(tool_connection) if tool_connection else None
        except Exception:
            return None

    def update_tool_connection_by_id(
        self, id: str, form_data: ToolConnectionForm
    ) -> Optional[ToolConnectionModel]:
        try:
            with get_db() as db:
                tool_connection = db.query(ToolConnection).filter_by(id=id).first()
                if tool_connection:
                    payload = form_data.model_dump()
                    payload["data"] = _encrypt_data_in_place(
                        copy.deepcopy(payload.get("data"))
                    )
                    for key, value in payload.items():
                        setattr(tool_connection, key, value)
                    tool_connection.updated_at = int(time.time())
                    db.commit()
                    db.refresh(tool_connection)
                    return _to_model_decrypted(tool_connection)
                return None
        except Exception as e:
            log.exception(e)
            return None

    def delete_tool_connection_by_id(self, id: str) -> bool:
        try:
            with get_db() as db:
                tool_connection = db.query(ToolConnection).filter_by(id=id).first()
                if tool_connection:
                    db.delete(tool_connection)
                    db.commit()
                    return True
                return False
        except Exception:
            return False


ToolConnections = ToolConnectionTable()

import logging
import time
import uuid
from typing import List, Optional

from open_webui.env import SRC_LOG_LEVELS
from open_webui.internal.db import Base, get_db
from open_webui.models.users import UserResponse, Users
from open_webui.utils.access_control import has_access
from pydantic import BaseModel, ConfigDict
from sqlalchemy import JSON, BigInteger, Boolean, Column, Text

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])

####################
# Guardrail DB Schema
####################


class Guardrail(Base):
    __tablename__ = "guardrail"

    id = Column(Text, unique=True, primary_key=True)
    user_id = Column(Text)

    name = Column(Text)
    description = Column(Text, nullable=True)

    # Rule-based settings
    pii_types = Column(
        JSON, default=[]
    )  # ["email", "credit_card", "ip", "mac", "url", "api_key"]
    pii_strategy = Column(Text, default="redact")  # block, redact, mask, hash
    custom_patterns = Column(
        JSON, default=[]
    )  # [{"name": "api_key", "pattern": "sk-[a-zA-Z0-9]{32}"}]
    blocked_words = Column(JSON, default=[])  # ["password", "secret", ...]

    # Apply scope
    apply_to_input = Column(Boolean, default=True)
    apply_to_output = Column(Boolean, default=False)

    # LLM-as-a-Judge settings
    llm_judge_enabled = Column(Boolean, default=False)
    llm_judge_model = Column(Text, nullable=True)
    llm_judge_prompt = Column(Text, nullable=True)
    llm_judge_pass_examples = Column(JSON, default=[])
    llm_judge_block_examples = Column(JSON, default=[])
    llm_judge_apply_to_input = Column(Boolean, default=True)
    llm_judge_apply_to_output = Column(Boolean, default=False)

    # Access control
    access_control = Column(JSON, nullable=True)
    # - `None`: Public access, available to all users with the "user" role.
    # - `{}`: Private access, restricted exclusively to the owner.
    # - Custom permissions: Specific access control for reading and writing

    # Metadata
    created_at = Column(BigInteger)
    updated_at = Column(BigInteger)


class GuardrailModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str

    name: str
    description: Optional[str] = None

    # Rule-based settings
    pii_types: List[str] = []
    pii_strategy: str = "redact"
    custom_patterns: List[dict] = []
    blocked_words: List[str] = []

    # Apply scope
    apply_to_input: bool = True
    apply_to_output: bool = False

    # LLM-as-a-Judge settings
    llm_judge_enabled: bool = False
    llm_judge_model: Optional[str] = None
    llm_judge_prompt: Optional[str] = None
    llm_judge_pass_examples: List[str] = []
    llm_judge_block_examples: List[str] = []
    llm_judge_apply_to_input: bool = True
    llm_judge_apply_to_output: bool = False

    # Access control
    access_control: Optional[dict] = None

    # Metadata
    created_at: int  # timestamp in epoch
    updated_at: int  # timestamp in epoch


####################
# Forms
####################


class GuardrailUserModel(GuardrailModel):
    user: Optional[UserResponse] = None


class GuardrailForm(BaseModel):
    name: str
    description: Optional[str] = None

    # Rule-based settings
    pii_types: List[str] = []
    pii_strategy: str = "redact"
    custom_patterns: List[dict] = []
    blocked_words: List[str] = []

    # Apply scope
    apply_to_input: bool = True
    apply_to_output: bool = False

    # LLM-as-a-Judge settings
    llm_judge_enabled: bool = False
    llm_judge_model: Optional[str] = None
    llm_judge_prompt: Optional[str] = None
    llm_judge_pass_examples: List[str] = []
    llm_judge_block_examples: List[str] = []
    llm_judge_apply_to_input: bool = True
    llm_judge_apply_to_output: bool = False

    # Access control
    access_control: Optional[dict] = None


class GuardrailTestForm(BaseModel):
    guardrail_id: Optional[str] = None
    config: Optional[GuardrailForm] = None
    text: str


class GuardrailTestResponse(BaseModel):
    processed_text: str
    violations: List[dict]
    blocked: bool
    message: Optional[str] = None


class GuardrailsTable:
    def name_exists(self, name: str, exclude_id: Optional[str] = None) -> bool:
        with get_db() as db:
            query = db.query(Guardrail).filter(Guardrail.name == name.strip())
            if exclude_id:
                query = query.filter(Guardrail.id != exclude_id)
            return query.first() is not None

    def insert_new_guardrail(
        self, user_id: str, form_data: GuardrailForm
    ) -> Optional[GuardrailModel]:
        with get_db() as db:
            guardrail = GuardrailModel(
                **{
                    **form_data.model_dump(),
                    "id": str(uuid.uuid4()),
                    "user_id": user_id,
                    "created_at": int(time.time()),
                    "updated_at": int(time.time()),
                }
            )

            try:
                result = Guardrail(**guardrail.model_dump())
                db.add(result)
                db.commit()
                db.refresh(result)
                if result:
                    return GuardrailModel.model_validate(result)
                else:
                    return None
            except Exception as e:
                log.exception(e)
                return None

    def get_guardrails(self) -> list[GuardrailUserModel]:
        with get_db() as db:
            guardrails = []
            for guardrail in (
                db.query(Guardrail).order_by(Guardrail.updated_at.desc()).all()
            ):
                user = Users.get_user_by_id(guardrail.user_id)
                guardrails.append(
                    GuardrailUserModel.model_validate(
                        {
                            **GuardrailModel.model_validate(guardrail).model_dump(),
                            "user": user.model_dump() if user else None,
                        }
                    )
                )
            return guardrails

    def get_guardrails_by_user_id(
        self, user_id: str, permission: str = "write"
    ) -> list[GuardrailUserModel]:
        guardrails = self.get_guardrails()
        return [
            guardrail
            for guardrail in guardrails
            if guardrail.user_id == user_id
            or has_access(user_id, permission, guardrail.access_control)
        ]

    def get_guardrail_by_id(self, id: str) -> Optional[GuardrailModel]:
        try:
            with get_db() as db:
                guardrail = db.query(Guardrail).filter_by(id=id).first()
                return GuardrailModel.model_validate(guardrail) if guardrail else None
        except Exception:
            return None

    def get_guardrails_by_ids(self, ids: list[str]) -> list[GuardrailModel]:
        try:
            with get_db() as db:
                guardrails = db.query(Guardrail).filter(Guardrail.id.in_(ids)).all()
                return [GuardrailModel.model_validate(g) for g in guardrails]
        except Exception:
            return []

    def update_guardrail_by_id(
        self, id: str, form_data: GuardrailForm
    ) -> Optional[GuardrailModel]:
        try:
            with get_db() as db:
                guardrail = db.query(Guardrail).filter_by(id=id).first()
                if guardrail:
                    for key, value in form_data.model_dump().items():
                        setattr(guardrail, key, value)
                    guardrail.updated_at = int(time.time())
                    db.commit()
                    db.refresh(guardrail)
                    return GuardrailModel.model_validate(guardrail)
                return None
        except Exception as e:
            log.exception(e)
            return None

    def delete_guardrail_by_id(self, id: str) -> bool:
        try:
            with get_db() as db:
                guardrail = db.query(Guardrail).filter_by(id=id).first()
                if guardrail:
                    db.delete(guardrail)
                    db.commit()
                    return True
                return False
        except Exception:
            return False

    def delete_all_guardrails(self) -> bool:
        with get_db() as db:
            try:
                db.query(Guardrail).delete()
                db.commit()
                return True
            except Exception:
                return False


Guardrails = GuardrailsTable()

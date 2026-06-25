import logging
import time
import uuid
from typing import Optional

from open_webui.env import SRC_LOG_LEVELS
from open_webui.internal.db import Base, get_db
from pydantic import BaseModel, ConfigDict
from sqlalchemy import BigInteger, Column, String, Text

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])

####################
# Inquiry DB Schema
####################

# Type/Subtype constants
INQUIRY_TYPES = {
    "usage_limit": {
        "label": "Usage Limit",
        "subtypes": ["limit_increase", "limit_check"],
    },
    "feature": {
        "label": "Feature Inquiry",
        "subtypes": ["chat", "agent", "knowledge", "database", "tool"],
    },
    "bug": {
        "label": "Bug Report",
        "subtypes": ["chat_error", "agent_error", "upload_error", "other_error"],
    },
    "account": {
        "label": "Account / Permission",
        "subtypes": ["permission_request", "account_issue"],
    },
    "other": {
        "label": "Other",
        "subtypes": ["improvement", "other"],
    },
}


class Inquiry(Base):
    __tablename__ = "inquiry"

    id = Column(String, primary_key=True)
    user_id = Column(String, index=True)
    title = Column(String)
    type = Column(String, index=True)
    subtype = Column(String)
    content = Column(Text)
    status = Column(String, index=True)
    admin_note = Column(Text, nullable=True)
    created_at = Column(BigInteger, index=True)
    updated_at = Column(BigInteger)


class InquiryModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    user_id: str
    title: str
    type: str
    subtype: str
    content: str
    status: str
    admin_note: Optional[str] = None
    created_at: int
    updated_at: int


####################
# Forms
####################


class InquiryForm(BaseModel):
    title: str
    type: str
    subtype: str
    content: str


class InquiryUpdateForm(BaseModel):
    status: Optional[str] = None
    admin_note: Optional[str] = None


class InquiryResponse(InquiryModel):
    user_name: Optional[str] = None
    user_email: Optional[str] = None


####################
# Table Operations
####################


class InquiryTable:
    def insert_new_inquiry(
        self, user_id: str, form_data: InquiryForm
    ) -> Optional[InquiryModel]:
        with get_db() as db:
            inquiry = InquiryModel(
                id=str(uuid.uuid4()),
                user_id=user_id,
                title=form_data.title,
                type=form_data.type,
                subtype=form_data.subtype,
                content=form_data.content,
                status="open",
                admin_note=None,
                created_at=int(time.time()),
                updated_at=int(time.time()),
            )
            result = Inquiry(**inquiry.model_dump())
            db.add(result)
            db.commit()
            db.refresh(result)
            return InquiryModel.model_validate(result)

    def get_inquiries(
        self,
        status: Optional[str] = None,
        type: Optional[str] = None,
    ) -> list[InquiryModel]:
        with get_db() as db:
            query = db.query(Inquiry).order_by(Inquiry.created_at.desc())
            if status:
                query = query.filter(Inquiry.status == status)
            if type:
                query = query.filter(Inquiry.type == type)
            return [InquiryModel.model_validate(i) for i in query.all()]

    def get_inquiries_by_user_id(self, user_id: str) -> list[InquiryModel]:
        with get_db() as db:
            return [
                InquiryModel.model_validate(i)
                for i in db.query(Inquiry)
                .filter(Inquiry.user_id == user_id)
                .order_by(Inquiry.created_at.desc())
                .all()
            ]

    def get_inquiry_by_id(self, id: str) -> Optional[InquiryModel]:
        with get_db() as db:
            inquiry = db.query(Inquiry).filter_by(id=id).first()
            return InquiryModel.model_validate(inquiry) if inquiry else None

    def update_inquiry_by_id(
        self, id: str, form_data: InquiryUpdateForm
    ) -> Optional[InquiryModel]:
        with get_db() as db:
            inquiry = db.query(Inquiry).filter_by(id=id).first()
            if inquiry:
                for key, value in form_data.model_dump(exclude_none=True).items():
                    setattr(inquiry, key, value)
                inquiry.updated_at = int(time.time())
                db.commit()
                db.refresh(inquiry)
                return InquiryModel.model_validate(inquiry)
            return None

    def delete_inquiry_by_id(self, id: str) -> bool:
        with get_db() as db:
            inquiry = db.query(Inquiry).filter_by(id=id).first()
            if inquiry:
                db.delete(inquiry)
                db.commit()
                return True
            return False

    def get_inquiry_count_by_status(self) -> dict:
        """상태별 문의 수 조회"""
        with get_db() as db:
            from sqlalchemy import func

            results = (
                db.query(Inquiry.status, func.count(Inquiry.id))
                .group_by(Inquiry.status)
                .all()
            )
            return {status: count for status, count in results}


Inquiries = InquiryTable()

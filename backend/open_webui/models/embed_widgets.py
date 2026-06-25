import logging
import time
import uuid
from typing import Optional

from open_webui.env import SRC_LOG_LEVELS
from open_webui.internal.db import Base, get_db
from open_webui.models.users import UserResponse, Users
from pydantic import BaseModel, ConfigDict
from sqlalchemy import JSON, BigInteger, Boolean, Column, Text

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])

####################
# EmbedWidget DB Schema
####################


class EmbedWidget(Base):
    __tablename__ = "embed_widget"

    id = Column(Text, unique=True, primary_key=True)
    user_id = Column(Text)

    name = Column(Text)
    description = Column(Text, nullable=True)

    model_id = Column(Text)
    system_prompt = Column(Text, nullable=True)

    config = Column(JSON, nullable=True)
    # config structure:
    # {
    #   "theme": "auto",           # auto | light | dark
    #   "position": "bottom-right", # bottom-right | bottom-left (버블 모서리)
    #   "mode": "bubble",          # bubble | side-right | side-left | side-bottom | inline | fullscreen
    #   "bubble_open_style": "popup", # popup | side-right | side-left | side-bottom
    #   "allowed_domains": [],      # ["*.example.com"]
    #   "features": {
    #     "file_upload": true,
    #     "markdown": true,
    #     "code_highlight": true,
    #     "web_search": false
    #   },
    #   "max_messages_per_session": 0,  # 0 = unlimited
    #   "welcome_message": ""
    # }

    is_active = Column(Boolean, default=True)
    access_control = Column(JSON, nullable=True)

    created_at = Column(BigInteger)
    updated_at = Column(BigInteger)


class EmbedWidgetModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str

    name: str
    description: Optional[str] = None

    model_id: str
    system_prompt: Optional[str] = None

    config: Optional[dict] = None
    is_active: bool = True
    access_control: Optional[dict] = None

    created_at: int
    updated_at: int


####################
# Forms
####################


class EmbedWidgetUserModel(EmbedWidgetModel):
    user: Optional[UserResponse] = None


class EmbedWidgetForm(BaseModel):
    name: str
    description: Optional[str] = None
    model_id: str
    system_prompt: Optional[str] = None
    config: Optional[dict] = None
    is_active: bool = True
    access_control: Optional[dict] = None


class EmbedWidgetConfigResponse(BaseModel):
    """Public-facing config response (no sensitive data)."""

    id: str
    name: str
    model_id: str
    config: Optional[dict] = None
    is_active: bool


####################
# Table
####################


class EmbedWidgetsTable:
    def insert_new_widget(
        self, user_id: str, form_data: EmbedWidgetForm
    ) -> Optional[EmbedWidgetModel]:
        with get_db() as db:
            widget = EmbedWidgetModel(
                **{
                    **form_data.model_dump(),
                    "id": str(uuid.uuid4()),
                    "user_id": user_id,
                    "created_at": int(time.time()),
                    "updated_at": int(time.time()),
                }
            )

            try:
                result = EmbedWidget(**widget.model_dump())
                db.add(result)
                db.commit()
                db.refresh(result)
                if result:
                    return EmbedWidgetModel.model_validate(result)
                else:
                    return None
            except Exception as e:
                log.exception(e)
                return None

    def get_widgets(self) -> list[EmbedWidgetUserModel]:
        with get_db() as db:
            widgets = []
            for widget in (
                db.query(EmbedWidget).order_by(EmbedWidget.updated_at.desc()).all()
            ):
                user = Users.get_user_by_id(widget.user_id)
                widgets.append(
                    EmbedWidgetUserModel.model_validate(
                        {
                            **EmbedWidgetModel.model_validate(widget).model_dump(),
                            "user": user.model_dump() if user else None,
                        }
                    )
                )
            return widgets

    def get_widget_by_id(self, id: str) -> Optional[EmbedWidgetModel]:
        try:
            with get_db() as db:
                widget = db.query(EmbedWidget).filter_by(id=id).first()
                return EmbedWidgetModel.model_validate(widget) if widget else None
        except Exception:
            return None

    def update_widget_by_id(
        self, id: str, form_data: EmbedWidgetForm
    ) -> Optional[EmbedWidgetModel]:
        try:
            with get_db() as db:
                widget = db.query(EmbedWidget).filter_by(id=id).first()
                if widget:
                    for key, value in form_data.model_dump().items():
                        setattr(widget, key, value)
                    widget.updated_at = int(time.time())
                    db.commit()
                    db.refresh(widget)
                    return EmbedWidgetModel.model_validate(widget)
                return None
        except Exception as e:
            log.exception(e)
            return None

    def delete_widget_by_id(self, id: str) -> bool:
        try:
            with get_db() as db:
                widget = db.query(EmbedWidget).filter_by(id=id).first()
                if widget:
                    db.delete(widget)
                    db.commit()
                    return True
                return False
        except Exception:
            return False


EmbedWidgets = EmbedWidgetsTable()

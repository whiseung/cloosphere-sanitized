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
# BiDashboard DB Schema
####################


class BiDashboard(Base):
    __tablename__ = "bi_dashboard"

    id = Column(Text, unique=True, primary_key=True)
    user_id = Column(Text)

    name = Column(Text)
    description = Column(Text, nullable=True)

    data = Column(JSON, nullable=True)
    meta = Column(JSON, nullable=True)
    access_control = Column(JSON, nullable=True)
    share_id = Column(Text, unique=True, nullable=True)

    created_at = Column(BigInteger)
    updated_at = Column(BigInteger)


class BiPanel(Base):
    __tablename__ = "bi_panel"

    id = Column(Text, unique=True, primary_key=True)
    dashboard_id = Column(Text)
    user_id = Column(Text)

    name = Column(Text)
    description = Column(Text, nullable=True)
    dbsphere_id = Column(Text)

    data = Column(JSON, nullable=True)
    meta = Column(JSON, nullable=True)

    created_at = Column(BigInteger)
    updated_at = Column(BigInteger)


####################
# Pydantic Models
####################


class BiDashboardModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str

    name: str
    description: Optional[str] = None

    data: Optional[dict] = None
    meta: Optional[dict] = None
    access_control: Optional[dict] = None
    share_id: Optional[str] = None

    created_at: int
    updated_at: int


class BiPanelModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    dashboard_id: str
    user_id: str

    name: str
    description: Optional[str] = None
    dbsphere_id: str

    data: Optional[dict] = None
    meta: Optional[dict] = None

    created_at: int
    updated_at: int


####################
# Forms
####################


class BiDashboardForm(BaseModel):
    name: str
    description: Optional[str] = None
    data: Optional[dict] = None
    meta: Optional[dict] = None
    access_control: Optional[dict] = None


class BiPanelForm(BaseModel):
    name: str
    description: Optional[str] = None
    dbsphere_id: str
    data: Optional[dict] = None
    meta: Optional[dict] = None


####################
# Table Classes (CRUD)
####################


class BiDashboardTable:
    def name_exists(self, name: str, exclude_id: Optional[str] = None) -> bool:
        with get_db() as db:
            query = db.query(BiDashboard).filter(BiDashboard.name == name.strip())
            if exclude_id:
                query = query.filter(BiDashboard.id != exclude_id)
            return query.first() is not None

    def insert_new_dashboard(
        self, user_id: str, form_data: BiDashboardForm
    ) -> Optional[BiDashboardModel]:
        with get_db() as db:
            dashboard = BiDashboardModel(
                **{
                    **form_data.model_dump(),
                    "id": str(uuid.uuid4()),
                    "user_id": user_id,
                    "created_at": int(time.time()),
                    "updated_at": int(time.time()),
                }
            )
            try:
                result = BiDashboard(**dashboard.model_dump())
                db.add(result)
                db.commit()
                db.refresh(result)
                return BiDashboardModel.model_validate(result) if result else None
            except Exception:
                return None

    def get_dashboards(self) -> list[BiDashboardModel]:
        with get_db() as db:
            return [
                BiDashboardModel.model_validate(d)
                for d in db.query(BiDashboard)
                .order_by(BiDashboard.updated_at.desc())
                .all()
            ]

    def get_dashboards_by_user_id(self, user_id: str) -> list[BiDashboardModel]:
        with get_db() as db:
            return [
                BiDashboardModel.model_validate(d)
                for d in db.query(BiDashboard)
                .filter_by(user_id=user_id)
                .order_by(BiDashboard.updated_at.desc())
                .all()
            ]

    def get_dashboard_by_id(self, id: str) -> Optional[BiDashboardModel]:
        try:
            with get_db() as db:
                dashboard = db.query(BiDashboard).filter_by(id=id).first()
                return BiDashboardModel.model_validate(dashboard) if dashboard else None
        except Exception:
            return None

    def update_dashboard_by_id(
        self, id: str, form_data: BiDashboardForm
    ) -> Optional[BiDashboardModel]:
        try:
            with get_db() as db:
                dashboard = db.query(BiDashboard).filter_by(id=id).first()
                if dashboard:
                    for key, value in form_data.model_dump().items():
                        setattr(dashboard, key, value)
                    dashboard.updated_at = int(time.time())
                    db.commit()
                    db.refresh(dashboard)
                    return BiDashboardModel.model_validate(dashboard)
                return None
        except Exception:
            return None

    def get_dashboard_by_share_id(self, share_id: str) -> Optional[BiDashboardModel]:
        try:
            with get_db() as db:
                dashboard = db.query(BiDashboard).filter_by(share_id=share_id).first()
                return BiDashboardModel.model_validate(dashboard) if dashboard else None
        except Exception:
            return None

    def update_dashboard_share(
        self,
        id: str,
        share_id: Optional[str],
        access_control: Optional[dict] = None,
    ) -> Optional[BiDashboardModel]:
        try:
            with get_db() as db:
                dashboard = db.query(BiDashboard).filter_by(id=id).first()
                if dashboard:
                    dashboard.share_id = share_id
                    dashboard.access_control = access_control
                    dashboard.updated_at = int(time.time())
                    db.commit()
                    db.refresh(dashboard)
                    return BiDashboardModel.model_validate(dashboard)
                return None
        except Exception:
            return None

    def delete_dashboard_by_id(self, id: str) -> bool:
        try:
            with get_db() as db:
                db.query(BiDashboard).filter_by(id=id).delete()
                # 연결된 패널도 삭제
                db.query(BiPanel).filter_by(dashboard_id=id).delete()
                db.commit()
                return True
        except Exception:
            return False


class BiPanelTable:
    def insert_new_panel(
        self, user_id: str, dashboard_id: str, form_data: BiPanelForm
    ) -> Optional[BiPanelModel]:
        with get_db() as db:
            panel = BiPanelModel(
                **{
                    **form_data.model_dump(),
                    "id": str(uuid.uuid4()),
                    "dashboard_id": dashboard_id,
                    "user_id": user_id,
                    "created_at": int(time.time()),
                    "updated_at": int(time.time()),
                }
            )
            try:
                result = BiPanel(**panel.model_dump())
                db.add(result)
                db.commit()
                db.refresh(result)
                return BiPanelModel.model_validate(result) if result else None
            except Exception:
                return None

    def get_panels_by_dashboard_id(self, dashboard_id: str) -> list[BiPanelModel]:
        with get_db() as db:
            return [
                BiPanelModel.model_validate(p)
                for p in db.query(BiPanel)
                .filter_by(dashboard_id=dashboard_id)
                .order_by(BiPanel.created_at.asc())
                .all()
            ]

    def get_panel_by_id(self, id: str) -> Optional[BiPanelModel]:
        try:
            with get_db() as db:
                panel = db.query(BiPanel).filter_by(id=id).first()
                return BiPanelModel.model_validate(panel) if panel else None
        except Exception:
            return None

    def update_panel_by_id(
        self, id: str, form_data: BiPanelForm
    ) -> Optional[BiPanelModel]:
        try:
            with get_db() as db:
                panel = db.query(BiPanel).filter_by(id=id).first()
                if panel:
                    for key, value in form_data.model_dump().items():
                        setattr(panel, key, value)
                    panel.updated_at = int(time.time())
                    db.commit()
                    db.refresh(panel)
                    return BiPanelModel.model_validate(panel)
                return None
        except Exception:
            return None

    def update_panel_data_by_id(self, id: str, data: dict) -> Optional[BiPanelModel]:
        """패널의 data 필드만 부분 업데이트 (캐시 결과 저장 등)."""
        try:
            with get_db() as db:
                panel = db.query(BiPanel).filter_by(id=id).first()
                if panel:
                    current_data = panel.data or {}
                    current_data.update(data)
                    panel.data = current_data
                    panel.updated_at = int(time.time())
                    db.commit()
                    db.refresh(panel)
                    return BiPanelModel.model_validate(panel)
                return None
        except Exception:
            return None

    def delete_panel_by_id(self, id: str) -> bool:
        try:
            with get_db() as db:
                db.query(BiPanel).filter_by(id=id).delete()
                db.commit()
                return True
        except Exception:
            return False

    def delete_panels_by_dashboard_id(self, dashboard_id: str) -> bool:
        try:
            with get_db() as db:
                db.query(BiPanel).filter_by(dashboard_id=dashboard_id).delete()
                db.commit()
                return True
        except Exception:
            return False


BiDashboards = BiDashboardTable()
BiPanels = BiPanelTable()

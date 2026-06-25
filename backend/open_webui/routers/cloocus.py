"""
Cloocus Admin API Router

Cloocus 내부 전용 고객 라이선스 관리 API.
CLOOCUS_ADMIN_DATABASE_URL이 없으면 503 반환.
X-Cloocus-Secret 헤더 검증 (CLOOCUS_ADMIN_SECRET 환경변수 설정 시).
"""

import base64
import hashlib
import hmac
import logging
import os
import time
import uuid
from typing import Optional

import jwt
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse
from open_webui.env import SRC_LOG_LEVELS, WEBUI_SECRET_KEY
from open_webui.internal.cloocus_db import (
    get_cloocus_db,
    get_cloocus_session,
    is_cloocus_db_available,
)
from open_webui.models.cloocus_admin import (
    CloocusCustomer,
    CloocusFeatureKeyRecord,
    CloocusFeatureRegistry,
    CloocusLicenseRecord,
    CloocusRegistryToken,
    CloocusWorkCategory,
    CloocusWorkLog,
)
from open_webui.utils.auth import get_admin_user
from open_webui.utils.email import (
    AzureEmailSender,
    EmailSender,
    MSGraphEmailSender,
    SendGridSender,
)
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])

router = APIRouter()

CLOOCUS_ADMIN_SECRET: Optional[str] = os.environ.get("CLOOCUS_ADMIN_SECRET")
CLOOCUS_PUBLIC_URL: Optional[str] = os.environ.get("CLOOCUS_PUBLIC_URL")

# 키 생성용 RSA 개인키 (PEM 문자열 또는 파일 경로)
_CLOOCUS_PRIVATE_KEY: Optional[str] = None


def _load_private_key() -> Optional[str]:
    """CLOOCUS_PRIVATE_KEY 또는 CLOOCUS_PRIVATE_KEY_PATH에서 개인키 로드."""
    global _CLOOCUS_PRIVATE_KEY
    if _CLOOCUS_PRIVATE_KEY:
        return _CLOOCUS_PRIVATE_KEY

    # 환경변수에 PEM 직접 포함
    pem = os.environ.get("CLOOCUS_PRIVATE_KEY", "").strip()
    if pem:
        _CLOOCUS_PRIVATE_KEY = pem
        return _CLOOCUS_PRIVATE_KEY

    # 파일 경로
    key_path = os.environ.get("CLOOCUS_PRIVATE_KEY_PATH", "").strip()
    if key_path:
        try:
            _CLOOCUS_PRIVATE_KEY = open(key_path).read().strip()
            return _CLOOCUS_PRIVATE_KEY
        except Exception as e:
            log.warning(f"CLOOCUS_PRIVATE_KEY_PATH 로드 실패: {e}")

    return None


def is_key_generation_available() -> bool:
    return _load_private_key() is not None


def _derive_customer_secret_key(customer_id: int) -> str:
    """마스터 WEBUI_SECRET_KEY로부터 고객별 고유 키를 파생 생성."""
    message = f"cloosphere:customer:{customer_id}".encode()
    derived = hmac.new(WEBUI_SECRET_KEY.encode(), message, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(derived).rstrip(b"=").decode()


####################################
# Helpers
####################################


def _refresh_app_license_status(request: Request):
    """기능 레지스트리 변경 후 라이선스 상태 갱신."""
    try:
        from open_webui.routers.license import _refresh_license_status

        _refresh_license_status(request.app)
    except Exception as e:
        log.warning(f"Failed to refresh license status: {e}")


####################################
# Dependencies
####################################


async def get_cloocus_admin(
    user=Depends(get_admin_user),
    x_cloocus_secret: Optional[str] = Header(None, alias="X-Cloocus-Secret"),
):
    """Cloocus 전용 어드민 의존성.

    - get_admin_user: 앱 관리자 인증
    - CLOOCUS_ADMIN_SECRET 설정 시 X-Cloocus-Secret 헤더 검증
    - Cloocus DB 연결 여부 확인
    """
    if not is_cloocus_db_available():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Cloocus admin database is not configured (CLOOCUS_ADMIN_DATABASE_URL not set)",
        )
    if CLOOCUS_ADMIN_SECRET:
        if x_cloocus_secret != CLOOCUS_ADMIN_SECRET:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid Cloocus admin secret",
            )
    return user


####################################
# Request / Response Models
####################################


class CustomerForm(BaseModel):
    company_name: str
    contact_email: Optional[str] = None
    contact_name: Optional[str] = None
    admin_contact_name: Optional[str] = None
    sales_contact_name: Optional[str] = None
    web_url: Optional[str] = None
    notes: Optional[str] = None
    license_type: Optional[str] = None  # "poc" or "contract"
    start_date: Optional[int] = None  # Unix timestamp


class CustomerUpdateForm(BaseModel):
    company_name: Optional[str] = None
    contact_email: Optional[str] = None
    contact_name: Optional[str] = None
    admin_contact_name: Optional[str] = None
    sales_contact_name: Optional[str] = None
    web_url: Optional[str] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None
    license_type: Optional[str] = None
    start_date: Optional[int] = None


class LicenseRecordForm(BaseModel):
    customer_id: int
    tier: str
    max_users: int = 0
    expires_at: Optional[int] = None
    token: str
    notes: Optional[str] = None


class FeatureKeyRecordForm(BaseModel):
    customer_id: int
    module: str
    expires_at: Optional[int] = None
    token: str
    notes: Optional[str] = None


class FeatureRegistryForm(BaseModel):
    module_id: str
    display_name: str
    description: Optional[str] = None
    tier_minimum: Optional[str] = None
    is_active: bool = True


class FeatureRegistryUpdateForm(BaseModel):
    display_name: Optional[str] = None
    description: Optional[str] = None
    tier_minimum: Optional[str] = None
    is_active: Optional[bool] = None


class GenerateLicenseForm(BaseModel):
    customer_id: int
    tier: str
    max_users: int = 0
    expires: Optional[str] = None  # YYYY-MM-DD, None = 영구
    notes: Optional[str] = None


class GenerateFeatureKeyForm(BaseModel):
    customer_id: int
    module: str
    expires: Optional[str] = None  # YYYY-MM-DD, None = 영구
    notes: Optional[str] = None


class CustomerCreditForm(BaseModel):
    credit: int
    approval_email: Optional[str] = None
    email_channel: Optional[str] = None


class WorkCategoryForm(BaseModel):
    name: str
    sort_order: Optional[int] = 0


class WorkLogForm(BaseModel):
    customer_id: int
    category_id: int
    title: str
    description: Optional[str] = None
    work_hours: float = Field(gt=0, le=1000)
    work_date: int
    created_by: Optional[str] = None
    notes: Optional[str] = None


class WorkLogUpdateForm(BaseModel):
    category_id: Optional[int] = None
    title: Optional[str] = None
    description: Optional[str] = None
    work_hours: Optional[float] = Field(default=None, gt=0, le=1000)
    work_date: Optional[int] = None
    created_by: Optional[str] = None
    notes: Optional[str] = None


class RegistryTokenForm(BaseModel):
    customer_id: int
    token_name: str
    token_key: str
    notes: Optional[str] = None


class RegistryTokenUpdateForm(BaseModel):
    token_name: Optional[str] = None
    token_key: Optional[str] = None
    notes: Optional[str] = None


####################################
# Status
####################################


@router.get("/status")
async def get_cloocus_status(
    _user=Depends(get_cloocus_admin),
    db: Session = Depends(get_cloocus_session),
):
    """Cloocus DB 연결 상태 및 통계."""
    customer_count = db.query(CloocusCustomer).count()
    active_customer_count = (
        db.query(CloocusCustomer).filter(CloocusCustomer.is_active == True).count()  # noqa: E712
    )
    license_record_count = db.query(CloocusLicenseRecord).count()
    feature_registry_count = db.query(CloocusFeatureRegistry).count()

    return {
        "available": True,
        "customer_count": customer_count,
        "active_customer_count": active_customer_count,
        "license_record_count": license_record_count,
        "feature_registry_count": feature_registry_count,
        "key_generation_available": is_key_generation_available(),
    }


####################################
# Customers
####################################


@router.get("/customers")
async def list_customers(
    page: int = 1,
    search: Optional[str] = None,
    _user=Depends(get_cloocus_admin),
    db: Session = Depends(get_cloocus_session),
):
    """고객사 목록 조회 (페이지네이션, 검색)."""
    page_size = 20
    query = db.query(CloocusCustomer)
    if search:
        query = query.filter(
            CloocusCustomer.company_name.ilike(f"%{search}%")
            | CloocusCustomer.contact_email.ilike(f"%{search}%")
            | CloocusCustomer.contact_name.ilike(f"%{search}%")
        )
    total = query.count()
    items = (
        query.order_by(CloocusCustomer.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    def _to_dict(c: CloocusCustomer):
        # 활성 라이선스 수
        active_licenses = (
            db.query(CloocusLicenseRecord)
            .filter(
                CloocusLicenseRecord.customer_id == c.id,
                CloocusLicenseRecord.is_revoked == False,  # noqa: E712
            )
            .count()
        )
        latest_license = (
            db.query(CloocusLicenseRecord)
            .filter(CloocusLicenseRecord.customer_id == c.id)
            .order_by(CloocusLicenseRecord.expires_at.desc())
            .first()
        )
        return {
            "id": c.id,
            "company_name": c.company_name,
            "contact_email": c.contact_email,
            "contact_name": c.contact_name,
            "notes": c.notes,
            "is_active": c.is_active,
            "credit": c.credit,
            "approval_email": c.approval_email,
            "email_channel": c.email_channel,
            "license_type": c.license_type,
            "start_date": c.start_date,
            "created_at": c.created_at,
            "updated_at": c.updated_at,
            "active_license_count": active_licenses,
            "latest_expires_at": latest_license.expires_at if latest_license else None,
            "credit_summary": _get_credit_summary(db, c),
        }

    return {
        "items": [_to_dict(c) for c in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.post("/customers/create")
async def create_customer(
    form_data: CustomerForm,
    _user=Depends(get_cloocus_admin),
    db: Session = Depends(get_cloocus_session),
):
    """고객사 등록."""
    now = int(time.time())
    sr_key = f"sr-{uuid.uuid4().hex[:24]}"
    customer = CloocusCustomer(
        company_name=form_data.company_name,
        contact_email=form_data.contact_email,
        contact_name=form_data.contact_name,
        admin_contact_name=form_data.admin_contact_name,
        sales_contact_name=form_data.sales_contact_name,
        web_url=form_data.web_url,
        notes=form_data.notes,
        license_type=form_data.license_type,
        start_date=form_data.start_date,
        sr_key=sr_key,
        created_at=now,
        updated_at=now,
        is_active=True,
    )
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return {
        "id": customer.id,
        "company_name": customer.company_name,
        "contact_email": customer.contact_email,
        "contact_name": customer.contact_name,
        "admin_contact_name": customer.admin_contact_name,
        "sales_contact_name": customer.sales_contact_name,
        "web_url": customer.web_url,
        "notes": customer.notes,
        "is_active": customer.is_active,
        "credit": customer.credit,
        "approval_email": customer.approval_email,
        "email_channel": customer.email_channel,
        "license_type": customer.license_type,
        "start_date": customer.start_date,
        "sr_key": customer.sr_key,
        "secret_key": _derive_customer_secret_key(customer.id),
        "created_at": customer.created_at,
        "updated_at": customer.updated_at,
    }


@router.get("/customers/{customer_id}")
async def get_customer(
    customer_id: int,
    _user=Depends(get_cloocus_admin),
    db: Session = Depends(get_cloocus_session),
):
    """고객사 상세 + 라이선스 이력."""
    customer = (
        db.query(CloocusCustomer).filter(CloocusCustomer.id == customer_id).first()
    )
    if not customer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found"
        )

    licenses = (
        db.query(CloocusLicenseRecord)
        .filter(CloocusLicenseRecord.customer_id == customer_id)
        .order_by(CloocusLicenseRecord.created_at.desc())
        .all()
    )
    feature_keys = (
        db.query(CloocusFeatureKeyRecord)
        .filter(CloocusFeatureKeyRecord.customer_id == customer_id)
        .order_by(CloocusFeatureKeyRecord.created_at.desc())
        .all()
    )
    registry_tokens = (
        db.query(CloocusRegistryToken)
        .filter(CloocusRegistryToken.customer_id == customer_id)
        .order_by(CloocusRegistryToken.created_at.desc())
        .all()
    )

    return {
        "id": customer.id,
        "company_name": customer.company_name,
        "contact_email": customer.contact_email,
        "contact_name": customer.contact_name,
        "admin_contact_name": customer.admin_contact_name,
        "sales_contact_name": customer.sales_contact_name,
        "web_url": customer.web_url,
        "notes": customer.notes,
        "is_active": customer.is_active,
        "credit": customer.credit,
        "approval_email": customer.approval_email,
        "email_channel": customer.email_channel,
        "license_type": customer.license_type,
        "start_date": customer.start_date,
        "sr_key": customer.sr_key,
        "secret_key": _derive_customer_secret_key(customer.id),
        "created_at": customer.created_at,
        "updated_at": customer.updated_at,
        "licenses": [
            {
                "id": lic.id,
                "tier": lic.tier,
                "max_users": lic.max_users,
                "issued_at": lic.issued_at,
                "expires_at": lic.expires_at,
                "token": lic.token,
                "is_revoked": lic.is_revoked,
                "notes": lic.notes,
                "created_at": lic.created_at,
            }
            for lic in licenses
        ],
        "feature_keys": [
            {
                "id": fk.id,
                "module": fk.module,
                "issued_at": fk.issued_at,
                "expires_at": fk.expires_at,
                "token": fk.token,
                "is_revoked": fk.is_revoked,
                "notes": fk.notes,
                "created_at": fk.created_at,
            }
            for fk in feature_keys
        ],
        "registry_tokens": [
            {
                "id": rt.id,
                "token_name": rt.token_name,
                "token_key": rt.token_key,
                "notes": rt.notes,
                "created_at": rt.created_at,
                "updated_at": rt.updated_at,
            }
            for rt in registry_tokens
        ],
    }


@router.post("/customers/{customer_id}/update")
async def update_customer(
    customer_id: int,
    form_data: CustomerUpdateForm,
    _user=Depends(get_cloocus_admin),
    db: Session = Depends(get_cloocus_session),
):
    """고객사 정보 수정."""
    customer = (
        db.query(CloocusCustomer).filter(CloocusCustomer.id == customer_id).first()
    )
    if not customer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found"
        )

    if form_data.company_name is not None:
        customer.company_name = form_data.company_name
    if form_data.contact_email is not None:
        customer.contact_email = form_data.contact_email
    if form_data.contact_name is not None:
        customer.contact_name = form_data.contact_name
    if form_data.admin_contact_name is not None:
        customer.admin_contact_name = form_data.admin_contact_name
    if form_data.sales_contact_name is not None:
        customer.sales_contact_name = form_data.sales_contact_name
    if form_data.web_url is not None:
        customer.web_url = form_data.web_url
    if form_data.notes is not None:
        customer.notes = form_data.notes
    if form_data.is_active is not None:
        customer.is_active = form_data.is_active
    if form_data.license_type is not None:
        customer.license_type = form_data.license_type
    if form_data.start_date is not None:
        customer.start_date = form_data.start_date
    customer.updated_at = int(time.time())

    db.commit()
    db.refresh(customer)
    return {
        "id": customer.id,
        "company_name": customer.company_name,
        "contact_email": customer.contact_email,
        "contact_name": customer.contact_name,
        "admin_contact_name": customer.admin_contact_name,
        "sales_contact_name": customer.sales_contact_name,
        "web_url": customer.web_url,
        "notes": customer.notes,
        "is_active": customer.is_active,
        "credit": customer.credit,
        "approval_email": customer.approval_email,
        "email_channel": customer.email_channel,
        "license_type": customer.license_type,
        "start_date": customer.start_date,
        "sr_key": customer.sr_key,
        "secret_key": _derive_customer_secret_key(customer.id),
        "created_at": customer.created_at,
        "updated_at": customer.updated_at,
    }


@router.delete("/customers/{customer_id}/delete")
async def delete_customer(
    customer_id: int,
    hard: bool = False,
    _user=Depends(get_cloocus_admin),
    db: Session = Depends(get_cloocus_session),
):
    """고객사 삭제. hard=true이면 모든 키 이력 포함 완전 삭제, 기본은 소프트 삭제."""
    customer = (
        db.query(CloocusCustomer).filter(CloocusCustomer.id == customer_id).first()
    )
    if not customer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found"
        )
    if hard:
        db.query(CloocusLicenseRecord).filter(
            CloocusLicenseRecord.customer_id == customer_id
        ).delete()
        db.query(CloocusFeatureKeyRecord).filter(
            CloocusFeatureKeyRecord.customer_id == customer_id
        ).delete()
        db.query(CloocusRegistryToken).filter(
            CloocusRegistryToken.customer_id == customer_id
        ).delete()
        db.delete(customer)
    else:
        customer.is_active = False
        customer.updated_at = int(time.time())
    db.commit()
    return {"success": True}


####################################
# Licenses
####################################


@router.get("/customers/{customer_id}/licenses")
async def get_customer_licenses(
    customer_id: int,
    _user=Depends(get_cloocus_admin),
    db: Session = Depends(get_cloocus_session),
):
    """특정 고객 라이선스 이력."""
    customer = (
        db.query(CloocusCustomer).filter(CloocusCustomer.id == customer_id).first()
    )
    if not customer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found"
        )

    licenses = (
        db.query(CloocusLicenseRecord)
        .filter(CloocusLicenseRecord.customer_id == customer_id)
        .order_by(CloocusLicenseRecord.created_at.desc())
        .all()
    )
    return [
        {
            "id": lic.id,
            "customer_id": lic.customer_id,
            "tier": lic.tier,
            "max_users": lic.max_users,
            "issued_at": lic.issued_at,
            "expires_at": lic.expires_at,
            "token": lic.token,
            "is_revoked": lic.is_revoked,
            "notes": lic.notes,
            "created_at": lic.created_at,
        }
        for lic in licenses
    ]


@router.post("/licenses/record")
async def record_license(
    form_data: LicenseRecordForm,
    _user=Depends(get_cloocus_admin),
    db: Session = Depends(get_cloocus_session),
):
    """라이선스 발급 이력 기록."""
    customer = (
        db.query(CloocusCustomer)
        .filter(CloocusCustomer.id == form_data.customer_id)
        .first()
    )
    if not customer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found"
        )

    now = int(time.time())
    record = CloocusLicenseRecord(
        customer_id=form_data.customer_id,
        tier=form_data.tier,
        max_users=form_data.max_users,
        issued_at=now,
        expires_at=form_data.expires_at,
        token=form_data.token,
        is_revoked=False,
        notes=form_data.notes,
        created_at=now,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return {
        "id": record.id,
        "customer_id": record.customer_id,
        "tier": record.tier,
        "max_users": record.max_users,
        "issued_at": record.issued_at,
        "expires_at": record.expires_at,
        "token": record.token,
        "is_revoked": record.is_revoked,
        "notes": record.notes,
        "created_at": record.created_at,
    }


@router.post("/licenses/{license_id}/revoke")
async def revoke_license(
    license_id: int,
    _user=Depends(get_cloocus_admin),
    db: Session = Depends(get_cloocus_session),
):
    """라이선스 취소."""
    record = (
        db.query(CloocusLicenseRecord)
        .filter(CloocusLicenseRecord.id == license_id)
        .first()
    )
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="License record not found"
        )
    record.is_revoked = True
    db.commit()
    return {"success": True}


@router.delete("/licenses/{license_id}/delete")
async def delete_license(
    license_id: int,
    _user=Depends(get_cloocus_admin),
    db: Session = Depends(get_cloocus_session),
):
    """라이선스 레코드 삭제."""
    record = (
        db.query(CloocusLicenseRecord)
        .filter(CloocusLicenseRecord.id == license_id)
        .first()
    )
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="License record not found"
        )
    db.delete(record)
    db.commit()
    return {"success": True}


####################################
# Feature Keys (개별 기능 구매)
####################################


@router.post("/feature-keys/record")
async def record_feature_key(
    form_data: FeatureKeyRecordForm,
    _user=Depends(get_cloocus_admin),
    db: Session = Depends(get_cloocus_session),
):
    """개별 기능 키 발급 이력 기록."""
    customer = (
        db.query(CloocusCustomer)
        .filter(CloocusCustomer.id == form_data.customer_id)
        .first()
    )
    if not customer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found"
        )

    now = int(time.time())
    record = CloocusFeatureKeyRecord(
        customer_id=form_data.customer_id,
        module=form_data.module,
        issued_at=now,
        expires_at=form_data.expires_at,
        token=form_data.token,
        is_revoked=False,
        notes=form_data.notes,
        created_at=now,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return {
        "id": record.id,
        "customer_id": record.customer_id,
        "module": record.module,
        "issued_at": record.issued_at,
        "expires_at": record.expires_at,
        "token": record.token,
        "is_revoked": record.is_revoked,
        "notes": record.notes,
        "created_at": record.created_at,
    }


@router.post("/feature-keys/{record_id}/revoke")
async def revoke_feature_key(
    record_id: int,
    _user=Depends(get_cloocus_admin),
    db: Session = Depends(get_cloocus_session),
):
    """개별 기능 키 취소."""
    record = (
        db.query(CloocusFeatureKeyRecord)
        .filter(CloocusFeatureKeyRecord.id == record_id)
        .first()
    )
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Feature key record not found"
        )
    record.is_revoked = True
    db.commit()
    return {"success": True}


@router.delete("/feature-keys/{record_id}/delete")
async def delete_feature_key(
    record_id: int,
    _user=Depends(get_cloocus_admin),
    db: Session = Depends(get_cloocus_session),
):
    """개별 기능 키 레코드 삭제."""
    record = (
        db.query(CloocusFeatureKeyRecord)
        .filter(CloocusFeatureKeyRecord.id == record_id)
        .first()
    )
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Feature key record not found"
        )
    db.delete(record)
    db.commit()
    return {"success": True}


####################################
# Registry Tokens (컨테이너 레지스트리 토큰)
####################################


@router.post("/registry-tokens/create")
async def create_registry_token(
    form_data: RegistryTokenForm,
    _user=Depends(get_cloocus_admin),
    db: Session = Depends(get_cloocus_session),
):
    """레지스트리 토큰 생성."""
    customer = (
        db.query(CloocusCustomer)
        .filter(CloocusCustomer.id == form_data.customer_id)
        .first()
    )
    if not customer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found"
        )

    token = CloocusRegistryToken(
        customer_id=form_data.customer_id,
        token_name=form_data.token_name,
        token_key=form_data.token_key,
        notes=form_data.notes,
    )
    db.add(token)
    db.commit()
    db.refresh(token)
    return {
        "id": token.id,
        "customer_id": token.customer_id,
        "token_name": token.token_name,
        "token_key": token.token_key,
        "notes": token.notes,
        "created_at": token.created_at,
        "updated_at": token.updated_at,
    }


@router.post("/registry-tokens/{token_id}/update")
async def update_registry_token(
    token_id: int,
    form_data: RegistryTokenUpdateForm,
    _user=Depends(get_cloocus_admin),
    db: Session = Depends(get_cloocus_session),
):
    """레지스트리 토큰 수정."""
    token = (
        db.query(CloocusRegistryToken)
        .filter(CloocusRegistryToken.id == token_id)
        .first()
    )
    if not token:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Registry token not found",
        )

    if form_data.token_name is not None:
        token.token_name = form_data.token_name
    if form_data.token_key is not None:
        token.token_key = form_data.token_key
    if form_data.notes is not None:
        token.notes = form_data.notes
    token.updated_at = int(time.time())

    db.commit()
    db.refresh(token)
    return {
        "id": token.id,
        "customer_id": token.customer_id,
        "token_name": token.token_name,
        "token_key": token.token_key,
        "notes": token.notes,
        "created_at": token.created_at,
        "updated_at": token.updated_at,
    }


@router.delete("/registry-tokens/{token_id}/delete")
async def delete_registry_token(
    token_id: int,
    _user=Depends(get_cloocus_admin),
    db: Session = Depends(get_cloocus_session),
):
    """레지스트리 토큰 삭제."""
    token = (
        db.query(CloocusRegistryToken)
        .filter(CloocusRegistryToken.id == token_id)
        .first()
    )
    if not token:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Registry token not found",
        )
    db.delete(token)
    db.commit()
    return {"success": True}


####################################
# Feature Registry
####################################


@router.get("/features")
async def list_features(
    _user=Depends(get_cloocus_admin),
    db: Session = Depends(get_cloocus_session),
):
    """기능 레지스트리 목록."""
    features = (
        db.query(CloocusFeatureRegistry)
        .order_by(CloocusFeatureRegistry.module_id)
        .all()
    )
    return [
        {
            "module_id": f.module_id,
            "display_name": f.display_name,
            "description": f.description,
            "tier_minimum": f.tier_minimum,
            "is_active": f.is_active,
            "created_at": f.created_at,
        }
        for f in features
    ]


@router.post("/features/create")
async def create_feature(
    request: Request,
    form_data: FeatureRegistryForm,
    _user=Depends(get_cloocus_admin),
    db: Session = Depends(get_cloocus_session),
):
    """신규 기능 등록."""
    existing = (
        db.query(CloocusFeatureRegistry)
        .filter(CloocusFeatureRegistry.module_id == form_data.module_id)
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Feature '{form_data.module_id}' already exists",
        )

    feature = CloocusFeatureRegistry(
        module_id=form_data.module_id,
        display_name=form_data.display_name,
        description=form_data.description,
        tier_minimum=form_data.tier_minimum,
        is_active=form_data.is_active,
        created_at=int(time.time()),
    )
    db.add(feature)
    db.commit()
    db.refresh(feature)

    _refresh_app_license_status(request)

    return {
        "module_id": feature.module_id,
        "display_name": feature.display_name,
        "description": feature.description,
        "tier_minimum": feature.tier_minimum,
        "is_active": feature.is_active,
        "created_at": feature.created_at,
    }


@router.post("/features/{module_id}/update")
async def update_feature(
    module_id: str,
    request: Request,
    form_data: FeatureRegistryUpdateForm,
    _user=Depends(get_cloocus_admin),
    db: Session = Depends(get_cloocus_session),
):
    """기능 정보 수정."""
    feature = (
        db.query(CloocusFeatureRegistry)
        .filter(CloocusFeatureRegistry.module_id == module_id)
        .first()
    )
    if not feature:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Feature not found"
        )

    if form_data.display_name is not None:
        feature.display_name = form_data.display_name
    if form_data.description is not None:
        feature.description = form_data.description
    if form_data.tier_minimum is not None:
        feature.tier_minimum = form_data.tier_minimum
    if form_data.is_active is not None:
        feature.is_active = form_data.is_active

    db.commit()
    db.refresh(feature)

    _refresh_app_license_status(request)

    return {
        "module_id": feature.module_id,
        "display_name": feature.display_name,
        "description": feature.description,
        "tier_minimum": feature.tier_minimum,
        "is_active": feature.is_active,
        "created_at": feature.created_at,
    }


@router.delete("/features/{module_id}/delete")
async def delete_feature(
    module_id: str,
    request: Request,
    _user=Depends(get_cloocus_admin),
    db: Session = Depends(get_cloocus_session),
):
    """기능 레지스트리에서 완전 삭제."""
    feature = (
        db.query(CloocusFeatureRegistry)
        .filter(CloocusFeatureRegistry.module_id == module_id)
        .first()
    )
    if not feature:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Feature not found"
        )
    db.delete(feature)
    db.commit()

    _refresh_app_license_status(request)

    return {"success": True}


####################################
# Key Generation
####################################

JWT_ALGORITHM = "RS256"
JWT_ISSUER = "cloosphere"
VALID_TIERS = {"basic", "standard", "professional", "enterprise", "developer"}


def _parse_expires(expires_str: str) -> int:
    """YYYY-MM-DD → Unix timestamp (해당일 23:59:59 UTC)."""
    from datetime import datetime, timezone

    try:
        dt = datetime.strptime(expires_str, "%Y-%m-%d")
        dt = dt.replace(hour=23, minute=59, second=59, tzinfo=timezone.utc)
        return int(dt.timestamp())
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid date format: {expires_str} (use YYYY-MM-DD)",
        )


@router.post("/generate/license")
async def generate_license_key(
    form_data: GenerateLicenseForm,
    _user=Depends(get_cloocus_admin),
    db: Session = Depends(get_cloocus_session),
):
    """라이선스 키 생성 + 이력 자동 기록."""
    private_key = _load_private_key()
    if not private_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Key generation not available (CLOOCUS_PRIVATE_KEY not configured)",
        )

    customer = (
        db.query(CloocusCustomer)
        .filter(CloocusCustomer.id == form_data.customer_id)
        .first()
    )
    if not customer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found"
        )

    if form_data.tier not in VALID_TIERS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid tier: {form_data.tier}",
        )

    now = int(time.time())
    exp = _parse_expires(form_data.expires) if form_data.expires else None

    payload = {
        "iss": JWT_ISSUER,
        "type": "license",
        "tier": form_data.tier,
        "company": customer.company_name,
        "max_users": form_data.max_users,
        "iat": now,
    }
    if exp is not None:
        payload["exp"] = exp
    token = jwt.encode(payload, private_key, algorithm=JWT_ALGORITHM)

    record = CloocusLicenseRecord(
        customer_id=form_data.customer_id,
        tier=form_data.tier,
        max_users=form_data.max_users,
        issued_at=now,
        expires_at=exp,
        token=token,
        is_revoked=False,
        notes=form_data.notes,
        created_at=now,
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    return {
        "token": token,
        "record_id": record.id,
        "tier": form_data.tier,
        "company": customer.company_name,
        "max_users": form_data.max_users,
        "expires_at": exp,
    }


@router.post("/generate/feature-key")
async def generate_feature_key(
    form_data: GenerateFeatureKeyForm,
    _user=Depends(get_cloocus_admin),
    db: Session = Depends(get_cloocus_session),
):
    """기능 키 생성 + 이력 자동 기록."""
    private_key = _load_private_key()
    if not private_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Key generation not available (CLOOCUS_PRIVATE_KEY not configured)",
        )

    customer = (
        db.query(CloocusCustomer)
        .filter(CloocusCustomer.id == form_data.customer_id)
        .first()
    )
    if not customer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found"
        )

    now = int(time.time())
    exp = _parse_expires(form_data.expires) if form_data.expires else None

    payload = {
        "iss": JWT_ISSUER,
        "type": "feature",
        "module": form_data.module,
        "company": customer.company_name,
        "iat": now,
    }
    if exp is not None:
        payload["exp"] = exp
    token = jwt.encode(payload, private_key, algorithm=JWT_ALGORITHM)

    record = CloocusFeatureKeyRecord(
        customer_id=form_data.customer_id,
        module=form_data.module,
        issued_at=now,
        expires_at=exp,
        token=token,
        is_revoked=False,
        notes=form_data.notes,
        created_at=now,
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    return {
        "token": token,
        "record_id": record.id,
        "module": form_data.module,
        "company": customer.company_name,
        "expires_at": exp,
    }


####################################
# Customer Credit
####################################


@router.post("/customers/{customer_id}/credit")
async def update_customer_credit(
    customer_id: int,
    form_data: CustomerCreditForm,
    _user=Depends(get_cloocus_admin),
    db: Session = Depends(get_cloocus_session),
):
    """고객사 크레딧 및 승인 이메일 수정."""
    customer = (
        db.query(CloocusCustomer).filter(CloocusCustomer.id == customer_id).first()
    )
    if not customer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found"
        )
    customer.credit = form_data.credit
    if form_data.approval_email is not None:
        customer.approval_email = form_data.approval_email
    if form_data.email_channel is not None:
        customer.email_channel = form_data.email_channel
    customer.updated_at = int(time.time())
    db.commit()
    db.refresh(customer)
    return {
        "id": customer.id,
        "credit": customer.credit,
        "approval_email": customer.approval_email,
        "email_channel": customer.email_channel,
    }


@router.get("/customers/{customer_id}/credit-summary")
async def get_customer_credit_summary(
    customer_id: int,
    _user=Depends(get_cloocus_admin),
    db: Session = Depends(get_cloocus_session),
):
    """고객사 크레딧 요약 (보유/사용/대기/잔여)."""
    customer = (
        db.query(CloocusCustomer).filter(CloocusCustomer.id == customer_id).first()
    )
    if not customer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found"
        )

    return _get_credit_summary(db, customer)


####################################
# Work Categories
####################################


@router.get("/work-categories")
async def list_work_categories(
    _user=Depends(get_cloocus_admin),
    db: Session = Depends(get_cloocus_session),
):
    """작업 카테고리 목록."""
    categories = (
        db.query(CloocusWorkCategory)
        .order_by(CloocusWorkCategory.sort_order, CloocusWorkCategory.id)
        .all()
    )
    return [
        {
            "id": c.id,
            "name": c.name,
            "sort_order": c.sort_order,
            "is_active": c.is_active,
            "created_at": c.created_at,
            "updated_at": c.updated_at,
        }
        for c in categories
    ]


@router.post("/work-categories/create")
async def create_work_category(
    form_data: WorkCategoryForm,
    _user=Depends(get_cloocus_admin),
    db: Session = Depends(get_cloocus_session),
):
    """작업 카테고리 생성."""
    existing = (
        db.query(CloocusWorkCategory)
        .filter(CloocusWorkCategory.name == form_data.name)
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Category '{form_data.name}' already exists",
        )

    now = int(time.time())
    category = CloocusWorkCategory(
        name=form_data.name,
        sort_order=form_data.sort_order or 0,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    db.add(category)
    db.commit()
    db.refresh(category)
    return {
        "id": category.id,
        "name": category.name,
        "sort_order": category.sort_order,
        "is_active": category.is_active,
        "created_at": category.created_at,
        "updated_at": category.updated_at,
    }


@router.post("/work-categories/{category_id}/update")
async def update_work_category(
    category_id: int,
    form_data: WorkCategoryForm,
    _user=Depends(get_cloocus_admin),
    db: Session = Depends(get_cloocus_session),
):
    """작업 카테고리 수정."""
    category = (
        db.query(CloocusWorkCategory)
        .filter(CloocusWorkCategory.id == category_id)
        .first()
    )
    if not category:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Category not found"
        )

    # 이름 중복 체크 (자기 자신 제외)
    existing = (
        db.query(CloocusWorkCategory)
        .filter(
            CloocusWorkCategory.name == form_data.name,
            CloocusWorkCategory.id != category_id,
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Category '{form_data.name}' already exists",
        )

    category.name = form_data.name
    if form_data.sort_order is not None:
        category.sort_order = form_data.sort_order
    category.updated_at = int(time.time())

    db.commit()
    db.refresh(category)
    return {
        "id": category.id,
        "name": category.name,
        "sort_order": category.sort_order,
        "is_active": category.is_active,
        "created_at": category.created_at,
        "updated_at": category.updated_at,
    }


@router.delete("/work-categories/{category_id}/delete")
async def delete_work_category(
    category_id: int,
    _user=Depends(get_cloocus_admin),
    db: Session = Depends(get_cloocus_session),
):
    """작업 카테고리 삭제 (참조 중이면 비활성화)."""
    category = (
        db.query(CloocusWorkCategory)
        .filter(CloocusWorkCategory.id == category_id)
        .first()
    )
    if not category:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Category not found"
        )

    # 참조하는 work_log가 있으면 soft delete
    ref_count = (
        db.query(CloocusWorkLog)
        .filter(CloocusWorkLog.category_id == category_id)
        .count()
    )
    if ref_count > 0:
        category.is_active = False
        category.updated_at = int(time.time())
        db.commit()
        return {"success": True, "soft_deleted": True}
    else:
        db.delete(category)
        db.commit()
        return {"success": True, "soft_deleted": False}


####################################
# Work Logs
####################################


def _generate_approval_token(customer_id: int) -> str:
    """HMAC-SHA256 승인 토큰 생성."""
    from open_webui.env import WEBUI_SECRET_KEY

    data = f"{customer_id}:{int(time.time())}:{uuid.uuid4().hex}"
    return hmac.new(
        WEBUI_SECRET_KEY.encode(), data.encode(), hashlib.sha256
    ).hexdigest()


def _get_email_sender(request: Request, channel_name: str = None):
    """노티피케이션 채널에서 이메일 sender를 반환. channel_name이 있으면 해당 채널, 없으면 첫 번째."""
    try:
        channels = request.app.state.config.NOTIFICATION_EMAIL_CHANNELS
        if not channels:
            return None

        channel = None
        if channel_name:
            for ch in channels:
                ch_dict = (
                    ch
                    if isinstance(ch, dict)
                    else (ch.model_dump() if hasattr(ch, "model_dump") else dict(ch))
                )
                if ch_dict.get("name") == channel_name:
                    channel = ch
                    break
        if channel is None:
            channel = channels[0]
        if isinstance(channel, dict):
            ch = channel
        else:
            ch = (
                channel.model_dump()
                if hasattr(channel, "model_dump")
                else dict(channel)
            )

        engine = ch.get("engine", "")
        if engine == "smtp":
            smtp = ch.get("smtp", {})
            return EmailSender(
                server=smtp.get("server", ""),
                port=smtp.get("port", 587),
                username=smtp.get("username", ""),
                password=smtp.get("password", ""),
                use_tls=smtp.get("use_tls", True),
                use_ssl=smtp.get("use_ssl", False),
                from_address=smtp.get("from_address", ""),
                from_name=smtp.get("from_name", "Cloosphere"),
            )
        elif engine == "sendgrid":
            sg = ch.get("sendgrid", {})
            api_key = sg.get("api_key", "")
            from_addr = sg.get("from_address", "")
            log.warning(
                f"[DEBUG] SendGrid sender: from={from_addr}, "
                f"key_len={len(api_key)}, key_prefix={api_key[:8] if api_key else 'EMPTY'}"
            )
            return SendGridSender(
                api_key=api_key,
                from_address=from_addr,
                from_name=sg.get("from_name", "Cloosphere"),
            )
        elif engine == "msgraph":
            mg = ch.get("msgraph", {})
            return MSGraphEmailSender(
                tenant_id=mg.get("tenant_id", ""),
                client_id=mg.get("client_id", ""),
                client_secret=mg.get("client_secret", ""),
                sender_email=mg.get("sender_email", ""),
                from_name=mg.get("from_name", "Cloosphere"),
            )
        elif engine == "azure":
            az = ch.get("azure", {})
            return AzureEmailSender(
                connection_string=az.get("connection_string", ""),
                from_address=az.get("from_address", ""),
                from_name=az.get("from_name", "Cloosphere"),
            )
    except Exception as e:
        log.warning(f"Failed to get email sender: {e}")
    return None


def _fmt_hours(value) -> str:
    """0.5 단위 시간을 보기 좋게 포맷 (1.0 → '1', 1.5 → '1.5')."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return str(value)
    if f == int(f):
        return str(int(f))
    return f"{f:g}"


def _parse_tasks_from_description(description: str) -> list[dict]:
    """description에서 태스크/문구 목록 파싱.

    형식:
        - 제목 (Xh)
          상세 내역 줄1
        > 문구 텍스트
        - 다음 태스크 (Yh)
    """
    import re

    items = []
    if not description:
        return items
    current = None
    for line in description.split("\n"):
        task_match = re.match(r"^-\s*(.+?)\s*\((\d+(?:\.\d+)?)h\)\s*$", line.strip())
        note_match = re.match(r"^>\s*(.+)$", line.strip())
        if task_match:
            try:
                hours = float(task_match.group(2))
            except ValueError:
                continue
            if current:
                items.append(current)
            current = {
                "type": "task",
                "content": task_match.group(1),
                "hours": hours,
                "detail": "",
            }
        elif note_match:
            if current:
                items.append(current)
                current = None
            items.append(
                {
                    "type": "note",
                    "content": note_match.group(1),
                    "hours": 0,
                    "detail": "",
                }
            )
        elif current and line.strip():
            detail_line = re.sub(r"^  ", "", line)
            current["detail"] = (
                (current["detail"] + "\n" + detail_line)
                if current["detail"]
                else detail_line
            )
    if current:
        items.append(current)
    return items


def _get_credit_summary(db: Session, customer: CloocusCustomer) -> dict:
    """고객사 크레딧 요약 계산."""
    used = (
        db.query(func.coalesce(func.sum(CloocusWorkLog.work_hours), 0))
        .filter(
            CloocusWorkLog.customer_id == customer.id,
            CloocusWorkLog.status == "accepted",
        )
        .scalar()
    )
    pending = (
        db.query(func.coalesce(func.sum(CloocusWorkLog.work_hours), 0))
        .filter(
            CloocusWorkLog.customer_id == customer.id,
            CloocusWorkLog.status == "pending",
        )
        .scalar()
    )
    # SUM(Float) 결과가 dialect 별로 float/Decimal/int 혼재 → 응답·산술 일관성 위해 float 정규화
    used = float(used or 0)
    pending = float(pending or 0)
    total = float(customer.credit or 0)
    return {
        "total": total,
        "used": used,
        "pending": pending,
        "remaining": total - used,
    }


def _build_approval_email_html(
    work_log: CloocusWorkLog,
    customer: CloocusCustomer,
    category_name: str,
    base_url: str,
    credit_info: dict | None = None,
) -> str:
    """승인 요청 HTML 이메일 생성."""
    from datetime import datetime, timezone

    work_date_str = datetime.fromtimestamp(
        work_log.work_date, tz=timezone.utc
    ).strftime("%Y-%m-%d")

    accept_url = f"{base_url}/api/v1/cloocus/work-logs/approve?token={work_log.approval_token}&action=accept"
    reject_url = f"{base_url}/api/v1/cloocus/work-logs/reject-form?token={work_log.approval_token}"

    # 태스크/문구 목록 HTML 생성
    items = _parse_tasks_from_description(work_log.description)
    task_items = [t for t in items if t.get("type") != "note"]
    note_items = [t for t in items if t.get("type") == "note"]

    if task_items:
        task_rows = ""
        for i, t in enumerate(task_items, 1):
            hours_str = f"{_fmt_hours(t['hours'])}시간" if t["hours"] else ""
            detail_html = ""
            if t.get("detail"):
                detail_text = t["detail"].replace("\n", "<br>")
                detail_html = f'<div style="margin-top: 4px; font-size: 12px; color: #6b7280; line-height: 1.5;">{detail_text}</div>'
            task_rows += f"""
            <tr style="border-bottom: 1px solid #eee;">
                <td style="padding: 10px 12px; color: #666; text-align: center; width: 36px; vertical-align: top;">{i}</td>
                <td style="padding: 10px 12px; color: #333;">{t["content"]}{detail_html}</td>
                <td style="padding: 10px 12px; color: #333; text-align: right; white-space: nowrap; width: 70px; vertical-align: top;">{hours_str}</td>
            </tr>"""
        tasks_html = f"""
    <table style="width: 100%; border-collapse: collapse; margin: 16px 0; border: 1px solid #e5e7eb; border-radius: 8px;">
        <tr style="background-color: #f9fafb; border-bottom: 2px solid #e5e7eb;">
            <th style="padding: 10px 12px; text-align: center; font-size: 12px; color: #6b7280; width: 36px;">#</th>
            <th style="padding: 10px 12px; text-align: left; font-size: 12px; color: #6b7280;">작업 내용</th>
            <th style="padding: 10px 12px; text-align: right; font-size: 12px; color: #6b7280; white-space: nowrap; width: 70px;">시간</th>
        </tr>
        {task_rows}
        <tr style="background-color: #f9fafb;">
            <td colspan="2" style="padding: 10px 12px; font-weight: bold; color: #333; text-align: right;">합계</td>
            <td style="padding: 10px 12px; font-weight: bold; color: #333; text-align: right;">{_fmt_hours(work_log.work_hours)}시간</td>
        </tr>
    </table>"""
    else:
        tasks_html = f"""
    <p style="color: #333;"><strong>작업 시간:</strong> {_fmt_hours(work_log.work_hours)}시간</p>"""

    # 내용(Content) → 이메일 인사말 영역에 표시
    if note_items:
        greeting_html = "<br>".join(n["content"] for n in note_items)
    else:
        greeting_html = f'안녕하세요, <strong>"{customer.company_name}"</strong> 담당자님.<br>아래 작업에 대한 크레딧 차감 승인을 요청드립니다.'

    # 크레딧 현황 HTML
    if credit_info:
        remaining_after = credit_info["remaining"] - work_log.work_hours
        remaining_color = "#22c55e" if remaining_after >= 0 else "#ef4444"
        credit_html = f"""
    <div style="margin: 16px 0; padding: 16px 20px; background-color: #f0fdf4; border-radius: 8px; border: 1px solid #bbf7d0;">
        <div style="font-size: 12px; color: #6b7280; margin-bottom: 8px; font-weight: 600;">크레딧 현황</div>
        <table style="width: 100%; border-collapse: collapse;">
            <tr>
                <td style="padding: 3px 0; color: #6b7280; font-size: 13px;">보유 크레딧</td>
                <td style="padding: 3px 0; color: #111827; font-size: 13px; text-align: right; font-weight: 600;">{_fmt_hours(credit_info["total"])}시간</td>
            </tr>
            <tr>
                <td style="padding: 3px 0; color: #6b7280; font-size: 13px;">사용 크레딧</td>
                <td style="padding: 3px 0; color: #111827; font-size: 13px; text-align: right;">{_fmt_hours(credit_info["used"])}시간</td>
            </tr>
            <tr>
                <td style="padding: 3px 0; color: #6b7280; font-size: 13px;">이번 차감</td>
                <td style="padding: 3px 0; color: #111827; font-size: 13px; text-align: right;">-{_fmt_hours(work_log.work_hours)}시간</td>
            </tr>
            <tr style="border-top: 1px solid #bbf7d0;">
                <td style="padding: 6px 0 3px; color: #6b7280; font-size: 13px; font-weight: 600;">승인 후 잔여</td>
                <td style="padding: 6px 0 3px; font-size: 13px; text-align: right; font-weight: 600; color: {remaining_color};">{_fmt_hours(remaining_after)}시간</td>
            </tr>
        </table>
    </div>"""
    else:
        credit_html = ""

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: 0 auto; padding: 0; background-color: #f3f4f6;">
    <div style="background-color: #ffffff; border-radius: 12px; margin: 20px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1);">
        <!-- 헤더 -->
        <div style="background-color: #111827; padding: 24px 32px;">
            <h1 style="margin: 0; color: #ffffff; font-size: 18px; font-weight: 600;">Cloosphere</h1>
            <p style="margin: 6px 0 0 0; color: #9ca3af; font-size: 13px;">크레딧 차감 승인 요청</p>
        </div>

        <!-- 본문 -->
        <div style="padding: 28px 32px;">
            <p style="color: #374151; font-size: 14px; line-height: 1.6; margin: 0 0 20px 0;">
                {greeting_html}
            </p>

            <!-- 작업 요약 -->
            <div style="margin: 20px 0; padding: 16px 20px; background-color: #f9fafb; border-radius: 8px; border: 1px solid #e5e7eb;">
                <table style="width: 100%; border-collapse: collapse;">
                    <tr>
                        <td style="padding: 4px 0; color: #6b7280; font-size: 13px; width: 80px;">제목</td>
                        <td style="padding: 4px 0; color: #111827; font-size: 13px; font-weight: 600;">{work_log.title}</td>
                    </tr>
                    <tr>
                        <td style="padding: 4px 0; color: #6b7280; font-size: 13px;">카테고리</td>
                        <td style="padding: 4px 0; color: #111827; font-size: 13px;">{category_name}</td>
                    </tr>
                    <tr>
                        <td style="padding: 4px 0; color: #6b7280; font-size: 13px;">작업일</td>
                        <td style="padding: 4px 0; color: #111827; font-size: 13px;">{work_date_str}</td>
                    </tr>
                </table>
            </div>

            <!-- 태스크 목록 -->
            {tasks_html}

            {credit_html}

            <!-- 버튼 -->
            <div style="margin: 28px 0 8px 0; text-align: center;">
                <a href="{accept_url}"
                   style="display: inline-block; padding: 12px 36px; background-color: #22c55e; color: white;
                          text-decoration: none; border-radius: 8px; margin-right: 12px; font-weight: 600; font-size: 14px;">
                    승인
                </a>
                <a href="{reject_url}"
                   style="display: inline-block; padding: 12px 36px; background-color: #ef4444; color: white;
                          text-decoration: none; border-radius: 8px; font-weight: 600; font-size: 14px;">
                    거절
                </a>
            </div>
        </div>

        <!-- 푸터 -->
        <div style="padding: 16px 32px; background-color: #f9fafb; border-top: 1px solid #e5e7eb;">
            <p style="margin: 0; color: #9ca3af; font-size: 11px; text-align: center;">
                이 이메일은 Cloosphere 시스템에서 자동 발송되었습니다. 본 메일에 직접 회신하지 마세요.
            </p>
        </div>
    </div>
</body>
</html>"""


def _send_approval_email(
    request: Request,
    work_log: CloocusWorkLog,
    customer: CloocusCustomer,
    category_name: str,
    db: Session | None = None,
) -> bool:
    """승인 이메일 발송. 성공 여부 반환."""
    raw_emails = customer.approval_email or customer.contact_email
    if not raw_emails:
        return False

    # 콤마 구분 이메일 파싱 (공백 제거, 빈 문자열 무시)
    recipients = [e.strip() for e in raw_emails.split(",") if e.strip()]
    if not recipients:
        return False

    sender = _get_email_sender(request, channel_name=customer.email_channel)
    if not sender:
        return False

    # base_url 추출
    base_url = (CLOOCUS_PUBLIC_URL or str(request.base_url)).rstrip("/")

    credit_info = _get_credit_summary(db, customer) if db else None
    html_body = _build_approval_email_html(
        work_log, customer, category_name, base_url, credit_info
    )
    subject = work_log.title
    body = f"{work_log.title} ({_fmt_hours(work_log.work_hours)}시간)"

    # 작업 로그 승인 메일은 항상 support-cloosphere 주소로 사본 전달
    cc = ["support-cloosphere@cloocus.com"]
    cc = [c for c in cc if c not in recipients]

    return sender.send_email(
        to=recipients,
        subject=subject,
        body=body,
        html_body=html_body,
        cc=cc,
    )


@router.get("/work-logs")
async def list_work_logs(
    page: int = 1,
    customer_id: Optional[int] = None,
    category_id: Optional[int] = None,
    status_filter: Optional[str] = Query(None, alias="status"),
    _user=Depends(get_cloocus_admin),
    db: Session = Depends(get_cloocus_session),
):
    """작업 내역 목록 (페이지네이션, 필터)."""
    page_size = 20
    query = db.query(CloocusWorkLog)

    if customer_id is not None:
        query = query.filter(CloocusWorkLog.customer_id == customer_id)
    if category_id is not None:
        query = query.filter(CloocusWorkLog.category_id == category_id)
    if status_filter:
        query = query.filter(CloocusWorkLog.status == status_filter)

    total = query.count()
    items = (
        query.order_by(CloocusWorkLog.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    # 고객사/카테고리 이름 조인
    customer_ids = list({w.customer_id for w in items})
    category_ids = list({w.category_id for w in items})

    customers_map = {}
    if customer_ids:
        customers = (
            db.query(CloocusCustomer).filter(CloocusCustomer.id.in_(customer_ids)).all()
        )
        customers_map = {c.id: c.company_name for c in customers}

    categories_map = {}
    if category_ids:
        categories = (
            db.query(CloocusWorkCategory)
            .filter(CloocusWorkCategory.id.in_(category_ids))
            .all()
        )
        categories_map = {c.id: c.name for c in categories}

    return {
        "items": [
            {
                "id": w.id,
                "customer_id": w.customer_id,
                "customer_name": customers_map.get(w.customer_id, ""),
                "category_id": w.category_id,
                "category_name": categories_map.get(w.category_id, ""),
                "title": w.title,
                "description": w.description,
                "work_hours": w.work_hours,
                "work_date": w.work_date,
                "status": w.status,
                "approval_token": w.approval_token,
                "approved_at": w.approved_at,
                "reject_reason": w.reject_reason,
                "created_by": w.created_by,
                "notes": w.notes,
                "created_at": w.created_at,
                "updated_at": w.updated_at,
            }
            for w in items
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.post("/work-logs/preview-email")
async def preview_work_log_email(
    form_data: WorkLogForm,
    request: Request,
    _user=Depends(get_cloocus_admin),
    db: Session = Depends(get_cloocus_session),
):
    """작업 내역 이메일 미리보기 (실제 발송 없이 HTML 반환)."""
    customer = (
        db.query(CloocusCustomer)
        .filter(CloocusCustomer.id == form_data.customer_id)
        .first()
    )
    if not customer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found"
        )
    category = (
        db.query(CloocusWorkCategory)
        .filter(CloocusWorkCategory.id == form_data.category_id)
        .first()
    )
    if not category:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Category not found"
        )

    # 임시 work_log 객체 생성 (DB 저장 없음)
    preview_log = CloocusWorkLog(
        customer_id=form_data.customer_id,
        category_id=form_data.category_id,
        title=form_data.title,
        description=form_data.description,
        work_hours=form_data.work_hours,
        work_date=form_data.work_date,
        created_by=form_data.created_by,
        notes=form_data.notes,
        approval_token="PREVIEW_TOKEN",
    )

    base_url = (CLOOCUS_PUBLIC_URL or str(request.base_url)).rstrip("/")
    credit_info = _get_credit_summary(db, customer)
    html = _build_approval_email_html(
        preview_log, customer, category.name, base_url, credit_info
    )

    raw_emails = customer.approval_email or customer.contact_email or ""
    recipients = [e.strip() for e in raw_emails.split(",") if e.strip()]

    return {
        "html": html,
        "recipients": recipients,
        "subject": form_data.title,
    }


@router.post("/work-logs/create")
async def create_work_log(
    form_data: WorkLogForm,
    request: Request,
    _user=Depends(get_cloocus_admin),
    db: Session = Depends(get_cloocus_session),
):
    """작업 내역 생성 + 승인 이메일 발송."""
    customer = (
        db.query(CloocusCustomer)
        .filter(CloocusCustomer.id == form_data.customer_id)
        .first()
    )
    if not customer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found"
        )

    category = (
        db.query(CloocusWorkCategory)
        .filter(CloocusWorkCategory.id == form_data.category_id)
        .first()
    )
    if not category:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Category not found"
        )

    now = int(time.time())
    token = _generate_approval_token(form_data.customer_id)

    work_log = CloocusWorkLog(
        customer_id=form_data.customer_id,
        category_id=form_data.category_id,
        title=form_data.title,
        description=form_data.description,
        work_hours=form_data.work_hours,
        work_date=form_data.work_date,
        status="pending",
        approval_token=token,
        created_by=form_data.created_by,
        notes=form_data.notes,
        created_at=now,
        updated_at=now,
    )
    db.add(work_log)
    db.commit()
    db.refresh(work_log)

    # 이메일 발송
    email_sent = _send_approval_email(request, work_log, customer, category.name, db)

    return {
        "id": work_log.id,
        "customer_id": work_log.customer_id,
        "category_id": work_log.category_id,
        "title": work_log.title,
        "status": work_log.status,
        "email_sent": email_sent,
        "created_at": work_log.created_at,
    }


@router.post("/work-logs/{work_log_id}/update")
async def update_work_log(
    work_log_id: int,
    form_data: WorkLogUpdateForm,
    _user=Depends(get_cloocus_admin),
    db: Session = Depends(get_cloocus_session),
):
    """pending/rejected 상태 작업 내역 수정."""
    work_log = db.query(CloocusWorkLog).filter(CloocusWorkLog.id == work_log_id).first()
    if not work_log:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Work log not found"
        )
    if work_log.status not in ("pending", "rejected"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only pending or rejected work logs can be modified",
        )

    if form_data.category_id is not None:
        category = (
            db.query(CloocusWorkCategory)
            .filter(CloocusWorkCategory.id == form_data.category_id)
            .first()
        )
        if not category:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Category not found"
            )
        work_log.category_id = form_data.category_id
    if form_data.title is not None:
        work_log.title = form_data.title
    if form_data.description is not None:
        work_log.description = form_data.description
    if form_data.work_hours is not None:
        work_log.work_hours = form_data.work_hours
    if form_data.work_date is not None:
        work_log.work_date = form_data.work_date
    if form_data.created_by is not None:
        work_log.created_by = form_data.created_by
    if form_data.notes is not None:
        work_log.notes = form_data.notes

    work_log.updated_at = int(time.time())
    db.commit()
    db.refresh(work_log)

    return {
        "id": work_log.id,
        "customer_id": work_log.customer_id,
        "category_id": work_log.category_id,
        "title": work_log.title,
        "status": work_log.status,
        "updated_at": work_log.updated_at,
    }


@router.delete("/work-logs/{work_log_id}/delete")
async def delete_work_log(
    work_log_id: int,
    _user=Depends(get_cloocus_admin),
    db: Session = Depends(get_cloocus_session),
):
    """pending 상태 작업 내역 삭제."""
    work_log = db.query(CloocusWorkLog).filter(CloocusWorkLog.id == work_log_id).first()
    if not work_log:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Work log not found"
        )
    db.delete(work_log)
    db.commit()
    return {"success": True}


@router.get("/work-logs/{work_log_id}/preview-email")
async def preview_existing_work_log_email(
    work_log_id: int,
    request: Request,
    _user=Depends(get_cloocus_admin),
    db: Session = Depends(get_cloocus_session),
):
    """기존 작업 내역의 이메일 미리보기."""
    work_log = db.query(CloocusWorkLog).filter(CloocusWorkLog.id == work_log_id).first()
    if not work_log:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Work log not found"
        )
    customer = (
        db.query(CloocusCustomer)
        .filter(CloocusCustomer.id == work_log.customer_id)
        .first()
    )
    category = (
        db.query(CloocusWorkCategory)
        .filter(CloocusWorkCategory.id == work_log.category_id)
        .first()
    )
    category_name = category.name if category else ""

    base_url = (CLOOCUS_PUBLIC_URL or str(request.base_url)).rstrip("/")
    credit_info = _get_credit_summary(db, customer)
    html = _build_approval_email_html(
        work_log, customer, category_name, base_url, credit_info
    )

    raw_emails = customer.approval_email or customer.contact_email or ""
    recipients = [e.strip() for e in raw_emails.split(",") if e.strip()]

    return {
        "html": html,
        "recipients": recipients,
        "subject": work_log.title,
    }


@router.post("/work-logs/{work_log_id}/resend")
async def resend_work_log_email(
    work_log_id: int,
    request: Request,
    _user=Depends(get_cloocus_admin),
    db: Session = Depends(get_cloocus_session),
):
    """승인 이메일 재발송 (rejected → pending 전환 포함)."""
    work_log = db.query(CloocusWorkLog).filter(CloocusWorkLog.id == work_log_id).first()
    if not work_log:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Work log not found"
        )
    if work_log.status not in ("pending", "rejected"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only pending or rejected work logs can be resent",
        )

    # rejected → pending 전환
    if work_log.status == "rejected":
        work_log.status = "pending"
        work_log.reject_reason = None
        work_log.approved_at = None

    # 새 토큰 발급
    work_log.approval_token = _generate_approval_token(work_log.customer_id)
    work_log.updated_at = int(time.time())
    db.commit()
    db.refresh(work_log)

    customer = (
        db.query(CloocusCustomer)
        .filter(CloocusCustomer.id == work_log.customer_id)
        .first()
    )
    category = (
        db.query(CloocusWorkCategory)
        .filter(CloocusWorkCategory.id == work_log.category_id)
        .first()
    )

    email_sent = _send_approval_email(
        request, work_log, customer, category.name if category else "", db
    )

    if not email_sent:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to send approval email. Check email channel configuration.",
        )

    return {"success": True, "email_sent": email_sent}


####################################
# Work Log Approval (Public)
####################################


@router.get("/work-logs/approve")
async def approve_work_log(
    token: str = Query(...),
    action: str = Query(...),
    db: Session = Depends(get_cloocus_session),
):
    """이메일 승인 (인증 불필요, 토큰 기반). 거절은 reject-form 사용."""
    if action != "accept":
        return HTMLResponse(
            content=_approval_result_html("오류", "잘못된 요청입니다.", "#ef4444"),
            status_code=400,
        )

    work_log = (
        db.query(CloocusWorkLog).filter(CloocusWorkLog.approval_token == token).first()
    )

    if not work_log:
        return HTMLResponse(
            content=_approval_result_html(
                "이미 처리됨",
                "이 요청은 이미 처리되었거나 유효하지 않은 링크입니다.",
                "#6b7280",
            ),
            status_code=200,
        )

    if work_log.status != "pending":
        status_label = "수락됨" if work_log.status == "accepted" else "거절됨"
        return HTMLResponse(
            content=_approval_result_html(
                "이미 처리됨",
                f"이 작업은 이미 '{status_label}' 상태입니다.",
                "#6b7280",
            ),
            status_code=200,
        )

    now = int(time.time())
    work_log.status = "accepted"
    work_log.approved_at = now
    work_log.approval_token = None
    work_log.updated_at = now
    db.commit()

    return HTMLResponse(
        content=_approval_result_html(
            "승인 완료", "작업이 승인되었습니다. 크레딧이 차감됩니다.", "#22c55e"
        ),
        status_code=200,
    )


@router.get("/work-logs/reject-form")
async def reject_form(
    token: str = Query(...),
    db: Session = Depends(get_cloocus_session),
):
    """거절 사유 입력 폼 페이지."""
    work_log = (
        db.query(CloocusWorkLog).filter(CloocusWorkLog.approval_token == token).first()
    )

    if not work_log or work_log.status != "pending":
        return HTMLResponse(
            content=_approval_result_html(
                "이미 처리됨",
                "이 요청은 이미 처리되었거나 유효하지 않은 링크입니다.",
                "#6b7280",
            ),
            status_code=200,
        )

    return HTMLResponse(content=_reject_form_html(token, work_log.title))


@router.post("/work-logs/reject")
async def reject_work_log(
    request: Request,
    db: Session = Depends(get_cloocus_session),
):
    """거절 처리 (폼 POST)."""
    form = await request.form()
    token = form.get("token", "")
    reason = form.get("reason", "")

    work_log = (
        db.query(CloocusWorkLog).filter(CloocusWorkLog.approval_token == token).first()
    )

    if not work_log or work_log.status != "pending":
        return HTMLResponse(
            content=_approval_result_html(
                "이미 처리됨",
                "이 요청은 이미 처리되었거나 유효하지 않은 링크입니다.",
                "#6b7280",
            ),
            status_code=200,
        )

    now = int(time.time())
    work_log.status = "rejected"
    work_log.approved_at = now
    work_log.reject_reason = reason.strip() if reason else None
    work_log.approval_token = None
    work_log.updated_at = now
    db.commit()

    return HTMLResponse(
        content=_approval_result_html(
            "거절 완료", "작업이 거절되었습니다. 크레딧은 차감되지 않습니다.", "#ef4444"
        ),
        status_code=200,
    )


def _reject_form_html(token: str, work_title: str) -> str:
    """거절 사유 입력 폼 HTML."""
    return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Cloosphere - 작업 거절</title>
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
             display: flex; justify-content: center; align-items: center; min-height: 100vh;
             margin: 0; background: #f3f4f6;">
    <div style="padding: 32px; background: white; border-radius: 12px;
                box-shadow: 0 2px 8px rgba(0,0,0,0.1); max-width: 460px; width: 100%;">
        <h2 style="color: #111827; margin: 0 0 4px 0; font-size: 18px;">작업 거절</h2>
        <p style="color: #6b7280; margin: 0 0 20px 0; font-size: 14px;">{work_title}</p>
        <form method="POST" action="reject">
            <input type="hidden" name="token" value="{token}" />
            <label style="display: block; margin-bottom: 6px; font-size: 13px; color: #374151; font-weight: 500;">
                거절 사유 (선택)
            </label>
            <textarea name="reason" rows="4"
                style="width: 100%; box-sizing: border-box; padding: 10px 12px; border: 1px solid #d1d5db;
                       border-radius: 8px; font-size: 14px; font-family: inherit; resize: vertical;
                       outline: none;"
                placeholder="거절 사유를 입력해주세요"></textarea>
            <div style="display: flex; gap: 8px; margin-top: 16px;">
                <button type="button" onclick="history.back()"
                    style="flex: 1; padding: 10px; border: 1px solid #d1d5db; background: white;
                           border-radius: 8px; font-size: 14px; cursor: pointer; color: #374151;">
                    취소
                </button>
                <button type="submit"
                    style="flex: 1; padding: 10px; border: none; background: #ef4444; color: white;
                           border-radius: 8px; font-size: 14px; font-weight: 600; cursor: pointer;">
                    거절 확인
                </button>
            </div>
        </form>
    </div>
</body>
</html>"""


def _approval_result_html(title: str, message: str, color: str) -> str:
    """승인 결과 HTML 페이지."""
    return f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Cloosphere - {title}</title>
</head>
<body style="font-family: Arial, sans-serif; display: flex; justify-content: center;
             align-items: center; min-height: 100vh; margin: 0; background: #f9fafb;">
    <div style="text-align: center; padding: 40px; background: white; border-radius: 12px;
                box-shadow: 0 2px 8px rgba(0,0,0,0.1); max-width: 400px;">
        <div style="width: 64px; height: 64px; border-radius: 50%; background: {color};
                    display: flex; align-items: center; justify-content: center;
                    margin: 0 auto 20px;">
            <span style="color: white; font-size: 28px;">{"✓" if "완료" in title or "처리" in title else "✕"}</span>
        </div>
        <h2 style="color: #333; margin-bottom: 8px;">{title}</h2>
        <p style="color: #666;">{message}</p>
        <p style="color: #999; font-size: 12px; margin-top: 24px;">이 창을 닫으셔도 됩니다.</p>
    </div>
</body>
</html>"""


####################################
# SR (Service Request) API
####################################


class SRForm(BaseModel):
    title: str
    type: str = "other"  # usage_limit, feature, bug, account, other
    content: str
    user_name: Optional[str] = None
    user_email: Optional[str] = None


@router.post("/sr/submit")
async def submit_sr(
    request: Request,
    form_data: SRForm,
    x_sr_key: str = Header(..., alias="X-SR-Key"),
):
    """고객 인스턴스에서 SR 문의 제출. sr_key로 고객 식별 후 이메일 발송."""
    if not is_cloocus_db_available():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Cloocus admin DB not configured",
        )

    with get_cloocus_db() as db:
        customer = (
            db.query(CloocusCustomer)
            .filter(
                CloocusCustomer.sr_key == x_sr_key,
                CloocusCustomer.is_active == True,  # noqa: E712
            )
            .first()
        )
        if not customer:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid SR key",
            )

        # 이메일 발송
        email_channels = list(request.app.state.config.NOTIFICATION_EMAIL_CHANNELS)
        if not email_channels:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="No email channel configured",
            )

        ch = email_channels[0]
        engine = ch.get("engine", "")

        subject = f"[SR] {customer.company_name} - {form_data.title}"
        body = (
            f"고객사: {customer.company_name}\n"
            f"유형: {form_data.type}\n"
            f"제목: {form_data.title}\n"
            f"작성자: {form_data.user_name or '-'} ({form_data.user_email or '-'})\n"
            f"\n{form_data.content}"
        )
        html_body = f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; padding: 20px;">
    <h2 style="color: #333; margin-bottom: 4px;">[SR] {form_data.title}</h2>
    <table style="border-collapse: collapse; margin: 16px 0;">
        <tr><td style="padding: 4px 12px 4px 0; color: #666;">고객사</td><td><strong>{customer.company_name}</strong></td></tr>
        <tr><td style="padding: 4px 12px 4px 0; color: #666;">유형</td><td>{form_data.type}</td></tr>
        <tr><td style="padding: 4px 12px 4px 0; color: #666;">작성자</td><td>{form_data.user_name or "-"} ({form_data.user_email or "-"})</td></tr>
    </table>
    <hr style="border: none; border-top: 1px solid #eee; margin: 16px 0;">
    <div style="white-space: pre-wrap; line-height: 1.6;">{form_data.content}</div>
    <hr style="border: none; border-top: 1px solid #eee; margin: 20px 0;">
    <p style="color: #999; font-size: 12px;">Sent by Cloosphere SR System</p>
</body>
</html>
"""
        to_email = "support-cloosphere@cloocus.com"

        sender = _build_email_sender(ch, engine)
        if not sender:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Unsupported email engine: {engine}",
            )

        try:
            success = sender.send_email(
                to=[to_email],
                subject=subject,
                body=body,
                html_body=html_body,
            )
        except Exception as e:
            log.error(f"SR email send exception: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to send SR email: {str(e)}",
            )

        if success:
            return {"success": True, "message": "SR submitted successfully"}
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to send SR email. Check email channel configuration and server logs.",
            )


def _build_email_sender(ch: dict, engine: str):
    """알림 채널 설정에서 이메일 발송기 생성."""
    if engine == "smtp":
        smtp = ch.get("smtp", {})
        return EmailSender(
            server=smtp.get("server", ""),
            port=smtp.get("port", 587),
            username=smtp.get("username", ""),
            password=smtp.get("password", ""),
            use_tls=smtp.get("use_tls", True),
            use_ssl=smtp.get("use_ssl", False),
            from_address=smtp.get("from_address", ""),
            from_name=smtp.get("from_name", "Cloosphere"),
        )
    elif engine == "sendgrid":
        sg = ch.get("sendgrid", {})
        return SendGridSender(
            api_key=sg.get("api_key", ""),
            from_address=sg.get("from_address", ""),
            from_name=sg.get("from_name", "Cloosphere"),
        )
    elif engine == "azure":
        az = ch.get("azure", {})
        return AzureEmailSender(
            connection_string=az.get("connection_string", ""),
            from_address=az.get("from_address", ""),
            from_name=az.get("from_name", "Cloosphere"),
        )
    elif engine == "msgraph":
        mg = ch.get("msgraph", {})
        return MSGraphEmailSender(
            tenant_id=mg.get("tenant_id", ""),
            client_id=mg.get("client_id", ""),
            client_secret=mg.get("client_secret", ""),
            sender_email=mg.get("sender_email", ""),
            from_name=mg.get("from_name", "Cloosphere"),
        )
    return None

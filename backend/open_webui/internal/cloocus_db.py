"""
Cloocus Central Admin Database

별도의 CLOOCUS_ADMIN_DATABASE_URL 환경변수로 Cloocus 전용 SQLAlchemy 엔진을 생성.
앱의 Base와 완전 분리된 CloocusBase를 사용하여 전용 테이블을 관리.
CLOOCUS_ADMIN_DATABASE_URL이 없으면 모든 함수가 graceful하게 처리됨.
"""

import logging
import os
from contextlib import contextmanager
from typing import Optional

import sqlalchemy as sa
from sqlalchemy import create_engine, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

log = logging.getLogger(__name__)

CLOOCUS_ADMIN_DATABASE_URL: Optional[str] = os.environ.get("CLOOCUS_ADMIN_DATABASE_URL")

CloocusBase = declarative_base()

_cloocus_engine = None
_CloocusSessionLocal = None


def _get_engine():
    global _cloocus_engine
    if _cloocus_engine is None and CLOOCUS_ADMIN_DATABASE_URL:
        if "sqlite" in CLOOCUS_ADMIN_DATABASE_URL:
            _cloocus_engine = create_engine(
                CLOOCUS_ADMIN_DATABASE_URL,
                connect_args={"check_same_thread": False},
            )
        else:
            _cloocus_engine = create_engine(
                CLOOCUS_ADMIN_DATABASE_URL,
                pool_pre_ping=True,
                poolclass=NullPool,
            )
    return _cloocus_engine


def _get_session_factory():
    global _CloocusSessionLocal
    engine = _get_engine()
    if _CloocusSessionLocal is None and engine is not None:
        _CloocusSessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=engine,
            expire_on_commit=False,
        )
    return _CloocusSessionLocal


def is_cloocus_db_available() -> bool:
    """CLOOCUS_ADMIN_DATABASE_URL 설정 여부 확인."""
    return bool(CLOOCUS_ADMIN_DATABASE_URL)


def get_cloocus_session():
    """FastAPI Depends용 세션 제너레이터."""
    SessionFactory = _get_session_factory()
    if SessionFactory is None:
        raise RuntimeError("CLOOCUS_ADMIN_DATABASE_URL is not configured")
    db = SessionFactory()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def get_cloocus_db():
    """컨텍스트 매니저 방식 세션."""
    SessionFactory = _get_session_factory()
    if SessionFactory is None:
        raise RuntimeError("CLOOCUS_ADMIN_DATABASE_URL is not configured")
    db = SessionFactory()
    try:
        yield db
    finally:
        db.close()


def run_cloocus_migrations():
    """Cloocus DB 테이블 자동 생성 (alembic 대신 create_all 사용)."""
    engine = _get_engine()
    if engine is None:
        log.info(
            "CLOOCUS_ADMIN_DATABASE_URL not set, skipping Cloocus DB initialization"
        )
        return
    try:
        # 모델 임포트하여 메타데이터 등록
        from open_webui.models import cloocus_admin  # noqa: F401

        CloocusBase.metadata.create_all(bind=engine)

        # 기존 테이블에 신규 컬럼 추가 (이미 있으면 무시)
        inspector = sa.inspect(engine)
        if inspector.has_table("cloocus_customers"):
            columns = [c["name"] for c in inspector.get_columns("cloocus_customers")]
            with engine.begin() as conn:
                if "credit" not in columns:
                    conn.execute(
                        text(
                            "ALTER TABLE cloocus_customers ADD COLUMN credit INTEGER DEFAULT 0 NOT NULL"
                        )
                    )
                if "approval_email" not in columns:
                    conn.execute(
                        text(
                            "ALTER TABLE cloocus_customers ADD COLUMN approval_email VARCHAR(255)"
                        )
                    )
                if "email_channel" not in columns:
                    conn.execute(
                        text(
                            "ALTER TABLE cloocus_customers ADD COLUMN email_channel VARCHAR(100)"
                        )
                    )
                if "license_type" not in columns:
                    conn.execute(
                        text(
                            "ALTER TABLE cloocus_customers ADD COLUMN license_type VARCHAR(20)"
                        )
                    )
                if "start_date" not in columns:
                    conn.execute(
                        text(
                            "ALTER TABLE cloocus_customers ADD COLUMN start_date INTEGER"
                        )
                    )
                if "admin_contact_name" not in columns:
                    conn.execute(
                        text(
                            "ALTER TABLE cloocus_customers ADD COLUMN admin_contact_name VARCHAR(255)"
                        )
                    )
                if "sales_contact_name" not in columns:
                    conn.execute(
                        text(
                            "ALTER TABLE cloocus_customers ADD COLUMN sales_contact_name VARCHAR(255)"
                        )
                    )
                if "web_url" not in columns:
                    conn.execute(
                        text(
                            "ALTER TABLE cloocus_customers ADD COLUMN web_url VARCHAR(500)"
                        )
                    )
                if "sr_key" not in columns:
                    conn.execute(
                        text(
                            "ALTER TABLE cloocus_customers ADD COLUMN sr_key VARCHAR(255)"
                        )
                    )
                    # 기존 고객에게 sr_key 자동 발급
                    import uuid as _uuid

                    rows = conn.execute(
                        text("SELECT id FROM cloocus_customers WHERE sr_key IS NULL")
                    ).fetchall()
                    for row in rows:
                        conn.execute(
                            text(
                                "UPDATE cloocus_customers SET sr_key = :key WHERE id = :id"
                            ),
                            {"key": f"sr-{_uuid.uuid4().hex[:24]}", "id": row[0]},
                        )

        if inspector.has_table("cloocus_work_logs"):
            wl_columns = inspector.get_columns("cloocus_work_logs")
            columns = [c["name"] for c in wl_columns]
            with engine.begin() as conn:
                if "reject_reason" not in columns:
                    conn.execute(
                        text(
                            "ALTER TABLE cloocus_work_logs ADD COLUMN reject_reason TEXT"
                        )
                    )

                # work_hours: INTEGER → DOUBLE PRECISION (0.5 단위 시간 지원)
                # SQLite는 type affinity로 INTEGER 컬럼에 실수도 저장 가능 → ALTER 불필요
                dialect = engine.dialect.name
                if dialect == "postgresql":
                    work_hours_col = next(
                        (c for c in wl_columns if c["name"] == "work_hours"), None
                    )
                    if work_hours_col is not None:
                        existing_type = str(work_hours_col["type"]).upper()
                        if "INT" in existing_type:
                            conn.execute(
                                text(
                                    "ALTER TABLE cloocus_work_logs "
                                    "ALTER COLUMN work_hours TYPE DOUBLE PRECISION "
                                    "USING work_hours::double precision"
                                )
                            )

        log.info("Cloocus admin DB tables initialized successfully")
    except Exception as e:
        log.error(f"Failed to initialize Cloocus admin DB: {e}")


# 기능 레지스트리 시드 데이터
_FEATURE_REGISTRY_SEED = [
    # Standard tier
    {"module_id": "audit_log", "display_name": "Audit Log", "tier_minimum": "standard"},
    {
        "module_id": "code_gateway",
        "display_name": "Code Gateway",
        "tier_minimum": "enterprise",
    },
    {
        "module_id": "encryption",
        "display_name": "Encryption (KMS)",
        "tier_minimum": "enterprise",
    },
    {
        "module_id": "file_guardrail",
        "display_name": "File Guardrail",
        "tier_minimum": "enterprise",
    },
    {"module_id": "glossary", "display_name": "Glossary", "tier_minimum": "standard"},
    {"module_id": "guardrail", "display_name": "Guardrail", "tier_minimum": "standard"},
    {
        "module_id": "image_generation",
        "display_name": "Image Generation",
        "tier_minimum": "standard",
    },
    {
        "module_id": "kbsphere",
        "display_name": "Knowledge Base (KbSphere)",
        "tier_minimum": "standard",
    },
    {"module_id": "tools", "display_name": "Tools", "tier_minimum": "standard"},
    # Professional tier
    {
        "module_id": "agent_flow",
        "display_name": "Agent Flow",
        "tier_minimum": "professional",
    },
    {
        "module_id": "branding",
        "display_name": "Branding",
        "tier_minimum": "professional",
    },
    {
        "module_id": "dbsphere",
        "display_name": "DbSphere",
        "tier_minimum": "professional",
    },
    {
        "module_id": "evaluation",
        "display_name": "Evaluation",
        "tier_minimum": "professional",
    },
    {"module_id": "trace", "display_name": "Trace", "tier_minimum": "professional"},
]


_DEFAULT_WORK_CATEGORIES = [
    "환경 설정",
    "교육",
    "기능 수정",
    "버그 개선",
    "운영 지원",
    "개발 지원",
]


def seed_work_categories():
    """CloocusWorkCategory에 기본 카테고리 데이터를 삽입 (테이블이 비어있을 때만)."""
    SessionFactory = _get_session_factory()
    if SessionFactory is None:
        return
    try:
        import time

        from open_webui.models.cloocus_admin import CloocusWorkCategory

        with get_cloocus_db() as db:
            count = db.query(CloocusWorkCategory).count()
            if count == 0:
                now = int(time.time())
                for i, name in enumerate(_DEFAULT_WORK_CATEGORIES):
                    db.add(
                        CloocusWorkCategory(
                            name=name,
                            sort_order=i,
                            is_active=True,
                            created_at=now,
                            updated_at=now,
                        )
                    )
                db.commit()
        log.info("Cloocus work categories seeded successfully")
    except Exception as e:
        log.error(f"Failed to seed work categories: {e}")


def seed_feature_registry():
    """CloocusFeatureRegistry에 기본 모듈 데이터를 삽입 (없는 항목만)."""
    SessionFactory = _get_session_factory()
    if SessionFactory is None:
        return
    try:
        import time

        from open_webui.models.cloocus_admin import CloocusFeatureRegistry

        with get_cloocus_db() as db:
            for entry in _FEATURE_REGISTRY_SEED:
                existing = (
                    db.query(CloocusFeatureRegistry)
                    .filter_by(module_id=entry["module_id"])
                    .first()
                )
                if existing is None:
                    db.add(
                        CloocusFeatureRegistry(
                            module_id=entry["module_id"],
                            display_name=entry["display_name"],
                            tier_minimum=entry["tier_minimum"],
                            is_active=True,
                            created_at=int(time.time()),
                        )
                    )
            db.commit()
        log.info("Cloocus feature registry seeded successfully")
    except Exception as e:
        log.error(f"Failed to seed feature registry: {e}")

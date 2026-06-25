> Last Updated: 2026-04-08

# 데이터베이스 마이그레이션 가이드

Cloosphere 프로젝트의 Alembic 기반 데이터베이스 마이그레이션 가이드입니다.

> **신스타일 참고**: 이 폴더는 README.md 단일 파일로 유지됩니다 (feature가 아닌 개발 프로세스 문서이므로 01~05 번호 구조가 어울리지 않음).

## 목차

1. [개요](#개요)
2. [중요 규칙](#중요-규칙)
3. [마이그레이션 파일 생성](#마이그레이션-파일-생성)
4. [마이그레이션 실행](#마이그레이션-실행)
5. [모델 파일 작성](#모델-파일-작성)
6. [트러블슈팅](#트러블슈팅)

---

## 개요

Cloosphere는 **Alembic**을 사용하여 데이터베이스 스키마 버전을 관리합니다.

| 항목 | 경로 |
|------|------|
| 마이그레이션 파일 | `backend/open_webui/migrations/versions/` |
| Alembic 설정 | `backend/open_webui/alembic.ini` |
| 모델 파일 | `backend/open_webui/models/` |

---

## 중요 규칙

### 1. autogenerate 사용 금지

```bash
# ❌ 절대 사용 금지
alembic revision --autogenerate -m "description"

# ✅ 수동 작성
# 마이그레이션 파일을 직접 작성해야 합니다
```

**이유**: 자동 생성된 마이그레이션은 예상치 못한 테이블 삭제나 컬럼 변경을 포함할 수 있습니다.

### 2. 프로덕션 배포 전 백업

프로덕션 환경에서 마이그레이션 실행 전 반드시 데이터베이스를 백업하세요.

```bash
# PostgreSQL 예시
pg_dump -h localhost -U postgres cloosphere > backup_$(date +%Y%m%d_%H%M%S).sql

# SQLite 예시
cp /app/backend/data/webui.db /app/backend/data/webui_backup_$(date +%Y%m%d).db
```

### 3. 테스트 환경 우선 실행

마이그레이션은 항상 개발/테스트 환경에서 먼저 실행하여 검증하세요.

---

## 마이그레이션 파일 생성

### 1. 최신 리비전 확인

새 마이그레이션의 `down_revision`에 사용할 최신 리비전 ID를 확인합니다.

```bash
# 마이그레이션 히스토리 확인
cd /cloosphere/backend/open_webui && PYTHONPATH=/cloosphere/backend alembic history

# 또는 파일 직접 확인
ls -la backend/open_webui/migrations/versions/
```

### 2. 파일명 규칙

```
{revision_id}_{description}.py
```

| 항목 | 규칙 | 예시 |
|------|------|------|
| revision_id | 12자리 영숫자 | `b2c3d4e5f6a7` |
| description | snake_case | `add_audit_log_table` |

**전체 예시**: `b2c3d4e5f6a7_add_audit_log_table.py`

### 3. 파일 템플릿

```python
"""Add audit log table

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2025-01-30 10:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "a1b2c3d4e5f6"  # 이전 마이그레이션 ID
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    """스키마 업그레이드 - 변경 사항 적용"""
    pass


def downgrade():
    """스키마 다운그레이드 - 변경 사항 롤백 (upgrade의 역순)"""
    pass
```

### 4. 자주 사용하는 작업

#### 테이블 생성

```python
def upgrade():
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Text(), nullable=False, primary_key=True),
        sa.Column("user_id", sa.Text(), nullable=True),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("resource_type", sa.Text(), nullable=True),
        sa.Column("resource_id", sa.Text(), nullable=True),
        sa.Column("data", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.BigInteger(), nullable=True),
    )

def downgrade():
    op.drop_table("audit_log")
```

#### 컬럼 추가

```python
def upgrade():
    op.add_column(
        "user",
        sa.Column("department", sa.Text(), nullable=True),
    )

def downgrade():
    op.drop_column("user", "department")
```

#### 인덱스 생성

```python
def upgrade():
    op.create_index(
        "ix_audit_log_user_id",
        "audit_log",
        ["user_id"]
    )
    # 복합 인덱스
    op.create_index(
        "ix_audit_log_resource",
        "audit_log",
        ["resource_type", "resource_id"]
    )

def downgrade():
    op.drop_index("ix_audit_log_resource", table_name="audit_log")
    op.drop_index("ix_audit_log_user_id", table_name="audit_log")
```

#### 외래 키 추가

```python
def upgrade():
    op.create_foreign_key(
        "fk_audit_log_user",
        "audit_log", "user",
        ["user_id"], ["id"],
        ondelete="SET NULL"
    )

def downgrade():
    op.drop_constraint("fk_audit_log_user", "audit_log", type_="foreignkey")
```

### 5. 컬럼 타입 참조

| SQLAlchemy 타입 | 용도 | 비고 |
|-----------------|------|------|
| `sa.Text()` | 문자열 | VARCHAR 대신 권장 |
| `sa.String(50)` | 고정 길이 문자열 | 길이 제한 필요 시 |
| `sa.BigInteger()` | Unix timestamp | `created_at`, `updated_at` |
| `sa.Integer()` | 정수 | |
| `sa.JSON()` | JSON 데이터 | `meta`, `data` 등 |
| `sa.Boolean()` | 불리언 | |
| `sa.Float()` | 부동소수점 | |

---

## 마이그레이션 실행

### 기본 명령어

```bash
# 작업 디렉토리로 이동
cd /cloosphere/backend/open_webui

# 환경 변수 설정 (PYTHONPATH 필수)
export PYTHONPATH=/cloosphere/backend
```

### 마이그레이션 적용

```bash
# 최신 버전으로 업그레이드
alembic upgrade head

# 특정 버전으로 업그레이드
alembic upgrade b2c3d4e5f6a7
```

### 마이그레이션 롤백

```bash
# 한 단계 롤백
alembic downgrade -1

# 특정 버전으로 롤백
alembic downgrade a1b2c3d4e5f6

# 모든 마이그레이션 롤백 (주의!)
alembic downgrade base
```

### 상태 확인

```bash
# 현재 적용된 버전
alembic current

# 마이그레이션 히스토리
alembic history

# 상세 히스토리
alembic history --verbose
```

---

## 모델 파일 작성

마이그레이션과 함께 해당 모델 파일도 생성/수정해야 합니다.

### 파일 위치

```
backend/open_webui/models/{model_name}.py
```

### 모델 파일 구조

```python
"""
Audit Log Model

감사 로그를 저장하고 관리합니다.
"""

import logging
import time
import uuid
from typing import Optional

from open_webui.env import SRC_LOG_LEVELS
from open_webui.internal.db import Base, get_db
from pydantic import BaseModel, ConfigDict
from sqlalchemy import BigInteger, Column, Text, JSON

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])


####################
# SQLAlchemy Model
####################

class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(Text, primary_key=True)
    user_id = Column(Text, nullable=True)
    action = Column(Text, nullable=False)
    resource_type = Column(Text, nullable=True)
    resource_id = Column(Text, nullable=True)
    data = Column(JSON, nullable=True)
    created_at = Column(BigInteger)


####################
# Pydantic Models
####################

class AuditLogModel(BaseModel):
    """응답용 모델"""
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: Optional[str] = None
    action: str
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None
    data: Optional[dict] = None
    created_at: int


class AuditLogForm(BaseModel):
    """생성/수정 폼"""
    action: str
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None
    data: Optional[dict] = None


####################
# Table Operations
####################

class AuditLogTable:
    def insert_new_log(
        self,
        user_id: str,
        form_data: AuditLogForm
    ) -> Optional[AuditLogModel]:
        with get_db() as db:
            log_entry = AuditLog(
                id=str(uuid.uuid4()),
                user_id=user_id,
                action=form_data.action,
                resource_type=form_data.resource_type,
                resource_id=form_data.resource_id,
                data=form_data.data,
                created_at=int(time.time()),
            )
            db.add(log_entry)
            db.commit()
            db.refresh(log_entry)
            return AuditLogModel.model_validate(log_entry)

    def get_logs_by_user_id(self, user_id: str) -> list[AuditLogModel]:
        with get_db() as db:
            logs = db.query(AuditLog).filter_by(user_id=user_id).all()
            return [AuditLogModel.model_validate(log) for log in logs]

    def get_log_by_id(self, id: str) -> Optional[AuditLogModel]:
        with get_db() as db:
            log_entry = db.query(AuditLog).filter_by(id=id).first()
            return AuditLogModel.model_validate(log_entry) if log_entry else None


# Singleton instance
AuditLogs = AuditLogTable()
```

---

## 트러블슈팅

### "Target database is not up to date"

현재 데이터베이스가 마이그레이션 히스토리와 일치하지 않습니다.

```bash
# 현재 상태 확인
alembic current

# 강제로 특정 버전으로 스탬프 (주의: 실제 스키마는 변경 안 됨)
alembic stamp head
```

### "Can't locate revision"

`down_revision`에 지정된 리비전 ID가 존재하지 않습니다.

```bash
# 히스토리 확인
alembic history

# down_revision 값 수정
```

### 마이그레이션 충돌

여러 브랜치에서 마이그레이션이 생성된 경우:

```bash
# 헤드 확인 (multiple heads 표시됨)
alembic heads

# 머지 마이그레이션 생성
alembic merge -m "merge heads" head1 head2
```

### 롤백 후 재적용 안 됨

`alembic_version` 테이블에 잘못된 버전이 기록된 경우:

```sql
-- 직접 버전 확인
SELECT * FROM alembic_version;

-- 버전 수정 (주의해서 사용)
UPDATE alembic_version SET version_num = 'correct_revision_id';
```

---

## 체크리스트

마이그레이션 작업 완료 전 확인사항:

- [ ] `down_revision`이 올바른 이전 마이그레이션 ID인가?
- [ ] `upgrade()`와 `downgrade()`가 서로 역순으로 작성되었는가?
- [ ] 자주 조회되는 컬럼에 인덱스를 추가했는가?
- [ ] 모델 파일(`models/*.py`)이 마이그레이션과 일치하는가?
- [ ] 테스트 환경에서 `upgrade` → `downgrade` → `upgrade` 테스트를 했는가?
- [ ] 프로덕션 배포 전 데이터베이스 백업을 했는가?

---

## 참고 자료

- [Alembic 공식 문서](https://alembic.sqlalchemy.org/)
- [SQLAlchemy Column Types](https://docs.sqlalchemy.org/en/20/core/types.html)

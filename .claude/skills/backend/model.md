# SQLAlchemy 모델 작성 가이드

## 파일 위치

- **위치**: `backend/open_webui/models/{resource}.py`
- **예시**: `models/knowledge.py`, `models/organization.py`

## 모델 파일 구조

모든 모델 파일은 4개 섹션으로 구성됩니다:

```python
"""
Item Model

아이템을 저장하고 관리합니다.
"""

import logging
import time
import uuid
from typing import Optional

from open_webui.env import SRC_LOG_LEVELS
from open_webui.internal.db import Base, get_db
from pydantic import BaseModel, ConfigDict
from sqlalchemy import BigInteger, Column, Text, JSON, Boolean

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])


####################
# 1. SQLAlchemy ORM Model (DB 테이블 정의)
####################

class Item(Base):
    __tablename__ = "item"

    id = Column(Text, primary_key=True)
    user_id = Column(Text)
    name = Column(Text)
    description = Column(Text, nullable=True)
    data = Column(JSON, nullable=True)
    access_control = Column(JSON, nullable=True)
    created_at = Column(BigInteger)
    updated_at = Column(BigInteger)


####################
# 2. Pydantic Models (요청/응답 스키마)
####################

class ItemModel(BaseModel):
    """응답용 모델"""
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    name: str
    description: Optional[str] = None
    data: Optional[dict] = None
    access_control: Optional[dict] = None
    created_at: int
    updated_at: int


class ItemForm(BaseModel):
    """생성용 폼"""
    name: str
    description: Optional[str] = None
    data: Optional[dict] = None
    access_control: Optional[dict] = None


class ItemUpdateForm(BaseModel):
    """수정용 폼 (모든 필드 Optional)"""
    name: Optional[str] = None
    description: Optional[str] = None
    data: Optional[dict] = None
    access_control: Optional[dict] = None


####################
# 3. Table Operations (CRUD 로직)
####################

class ItemTable:
    def insert_new_item(
        self,
        user_id: str,
        form_data: ItemForm
    ) -> Optional[ItemModel]:
        with get_db() as db:
            item = Item(
                id=str(uuid.uuid4()),
                user_id=user_id,
                name=form_data.name,
                description=form_data.description,
                data=form_data.data,
                access_control=form_data.access_control,
                created_at=int(time.time()),
                updated_at=int(time.time()),
            )
            db.add(item)
            db.commit()
            db.refresh(item)
            return ItemModel.model_validate(item)

    def get_item_by_id(self, id: str) -> Optional[ItemModel]:
        with get_db() as db:
            item = db.query(Item).filter_by(id=id).first()
            return ItemModel.model_validate(item) if item else None

    def get_items_by_user_id(self, user_id: str) -> list[ItemModel]:
        with get_db() as db:
            items = (
                db.query(Item)
                .filter_by(user_id=user_id)
                .order_by(Item.updated_at.desc())
                .all()
            )
            return [ItemModel.model_validate(item) for item in items]

    def get_all_items(self) -> list[ItemModel]:
        with get_db() as db:
            items = db.query(Item).order_by(Item.updated_at.desc()).all()
            return [ItemModel.model_validate(item) for item in items]

    def update_item_by_id(
        self,
        id: str,
        form_data: ItemUpdateForm
    ) -> Optional[ItemModel]:
        with get_db() as db:
            item = db.query(Item).filter_by(id=id).first()
            if not item:
                return None

            # None이 아닌 필드만 업데이트
            update_data = form_data.model_dump(exclude_unset=True)
            for key, value in update_data.items():
                if value is not None:
                    setattr(item, key, value)

            item.updated_at = int(time.time())
            db.commit()
            db.refresh(item)
            return ItemModel.model_validate(item)

    def delete_item_by_id(self, id: str) -> bool:
        with get_db() as db:
            result = db.query(Item).filter_by(id=id).delete()
            db.commit()
            return result > 0


####################
# 4. Singleton Instance
####################

Items = ItemTable()
```

## 공통 필드 패턴

### 필수 필드

```python
class Item(Base):
    __tablename__ = "item"

    # Primary Key (UUID)
    id = Column(Text, primary_key=True)

    # 다중 테넌시 (사용자 격리)
    user_id = Column(Text)

    # 타임스탬프 (Unix epoch)
    created_at = Column(BigInteger)
    updated_at = Column(BigInteger)
```

### 선택적 필드

```python
    # 권한 제어 (그룹/사용자/조직 공유)
    access_control = Column(JSON, nullable=True)

    # 확장 가능한 메타데이터
    data = Column(JSON, nullable=True)
    meta = Column(JSON, nullable=True)

    # 상태/플래그
    is_active = Column(Boolean, default=True)
```

## 컬럼 타입

| SQLAlchemy 타입 | 용도 | 예시 |
|-----------------|------|------|
| `Text` | 문자열 (무제한) | name, description |
| `String(255)` | 고정 길이 문자열 | email, username |
| `BigInteger` | Unix timestamp | created_at |
| `Integer` | 정수 | count, level |
| `Boolean` | 불리언 | is_active |
| `JSON` | JSON 데이터 | data, meta, access_control |
| `Float` | 부동소수점 | score |
| `LargeBinary` | 바이너리 | 파일 내용 (권장하지 않음) |

## 접근 제어 필드 구조

```python
# access_control JSON 구조
access_control = {
    "read": {
        "user_ids": ["user-id-1", "user-id-2"],
        "group_ids": ["group-id-1"],
        "org_unit_ids": ["org-unit-id-1"]
    },
    "write": {
        "user_ids": ["user-id-1"],
        "group_ids": ["group-id-1"],
        "org_unit_ids": []
    }
}

# None이면 비공개 (소유자만 접근)
# 빈 dict {}면 공개
```

## 관계 설정

### 외래 키 (직접 사용)

```python
class Message(Base):
    __tablename__ = "message"

    id = Column(Text, primary_key=True)
    chat_id = Column(Text, nullable=False)  # Chat.id 참조
    user_id = Column(Text, nullable=False)  # User.id 참조
```

### 계층 구조 (자기 참조)

```python
class OrganizationalUnit(Base):
    __tablename__ = "organizational_unit"

    id = Column(Text, primary_key=True)
    organization_id = Column(Text)  # 소속 조직
    parent_id = Column(Text, nullable=True)  # 상위 조직 단위 (NULL이면 루트)
    level = Column(Integer, default=0)  # 계층 레벨
```

## Pydantic 모델 패턴

### 기본 응답 모델

```python
from pydantic import BaseModel, ConfigDict

class ItemModel(BaseModel):
    """DB에서 조회한 데이터 반환용"""
    model_config = ConfigDict(from_attributes=True)  # ORM 호환

    id: str
    user_id: str
    name: str
    description: Optional[str] = None
    created_at: int
    updated_at: int
```

### 생성 폼

```python
class ItemForm(BaseModel):
    """새 항목 생성용 (필수 필드만)"""
    name: str
    description: Optional[str] = None
```

### 수정 폼

```python
class ItemUpdateForm(BaseModel):
    """수정용 (모든 필드 Optional)"""
    name: Optional[str] = None
    description: Optional[str] = None
```

### 중첩 데이터

```python
class ItemWithDetails(ItemModel):
    """상세 정보 포함 응답"""
    files: list[FileModel] = []
    permissions: Optional[dict] = None
```

## CRUD 메서드 패턴

### 생성 (Create)

```python
def insert_new_item(self, user_id: str, form_data: ItemForm) -> Optional[ItemModel]:
    with get_db() as db:
        item = Item(
            id=str(uuid.uuid4()),
            user_id=user_id,
            created_at=int(time.time()),
            updated_at=int(time.time()),
            **form_data.model_dump()
        )
        db.add(item)
        db.commit()
        db.refresh(item)
        return ItemModel.model_validate(item)
```

### 조회 (Read)

```python
def get_item_by_id(self, id: str) -> Optional[ItemModel]:
    with get_db() as db:
        item = db.query(Item).filter_by(id=id).first()
        return ItemModel.model_validate(item) if item else None

def get_items_by_user_id(self, user_id: str) -> list[ItemModel]:
    with get_db() as db:
        items = (
            db.query(Item)
            .filter_by(user_id=user_id)
            .order_by(Item.updated_at.desc())
            .all()
        )
        return [ItemModel.model_validate(item) for item in items]
```

### 수정 (Update)

```python
def update_item_by_id(self, id: str, form_data: ItemUpdateForm) -> Optional[ItemModel]:
    with get_db() as db:
        item = db.query(Item).filter_by(id=id).first()
        if not item:
            return None

        # None이 아닌 필드만 업데이트
        update_data = form_data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            if value is not None:
                setattr(item, key, value)

        item.updated_at = int(time.time())
        db.commit()
        db.refresh(item)
        return ItemModel.model_validate(item)
```

### 삭제 (Delete)

```python
def delete_item_by_id(self, id: str) -> bool:
    with get_db() as db:
        result = db.query(Item).filter_by(id=id).delete()
        db.commit()
        return result > 0
```

## 고급 쿼리

### 필터링

```python
def get_items_with_access(self, user_id: str) -> list[ItemModel]:
    with get_db() as db:
        items = db.query(Item).filter(
            or_(
                Item.user_id == user_id,
                Item.access_control.isnot(None)
            )
        ).all()
        return [ItemModel.model_validate(item) for item in items]
```

### 페이지네이션

```python
def get_items_paginated(
    self,
    user_id: str,
    page: int = 1,
    limit: int = 20
) -> tuple[list[ItemModel], int]:
    with get_db() as db:
        query = db.query(Item).filter_by(user_id=user_id)
        total = query.count()
        items = (
            query
            .order_by(Item.updated_at.desc())
            .offset((page - 1) * limit)
            .limit(limit)
            .all()
        )
        return [ItemModel.model_validate(item) for item in items], total
```

### JSON 필드 쿼리

```python
# PostgreSQL JSON 쿼리
from sqlalchemy import func

def get_items_with_tag(self, tag: str) -> list[ItemModel]:
    with get_db() as db:
        items = db.query(Item).filter(
            func.json_contains(Item.data, f'"{tag}"', '$.tags')
        ).all()
        return [ItemModel.model_validate(item) for item in items]
```

## 마이그레이션 파일 작성

새 모델 추가 시 마이그레이션 파일을 수동으로 작성해야 합니다.

**파일 위치**: `backend/open_webui/migrations/versions/{revision_id}_{description}.py`

```python
"""Add item table

Revision ID: abc123def456
Revises: previous_revision_id
Create Date: 2025-01-30 10:00:00.000000

"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "abc123def456"
down_revision: Union[str, None] = "previous_revision_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.create_table(
        "item",
        sa.Column("id", sa.Text(), nullable=False, primary_key=True),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("data", sa.JSON(), nullable=True),
        sa.Column("access_control", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.BigInteger(), nullable=True),
        sa.Column("updated_at", sa.BigInteger(), nullable=True),
    )
    # 인덱스 추가
    op.create_index("ix_item_user_id", "item", ["user_id"])


def downgrade():
    op.drop_index("ix_item_user_id", table_name="item")
    op.drop_table("item")
```

## 참조 파일

| 모델 | 특징 |
|------|------|
| `models/knowledge.py` | 기본 CRUD + data JSON 활용 |
| `models/organization.py` | 계층 구조, 관계 |
| `models/chats.py` (31KB) | 복잡한 관계, 메시지 포함 |
| `models/groups.py` | member_ids 배열, permissions |
| `models/users.py` | 인증, 역할 관리 |

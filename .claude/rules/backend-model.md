---
paths:
  - "backend/open_webui/models/**/*.py"
  - "backend/open_webui/migrations/**/*.py"
---

# SQLAlchemy 모델 작성 규칙

## ORM 모델 클래스
```python
from sqlalchemy import JSON, BigInteger, Column, Text
from open_webui.internal.db import Base, get_db

class Resource(Base):
    __tablename__ = "resource"  # 소문자 단수형

    id = Column(Text, unique=True, primary_key=True)
    user_id = Column(Text)
    name = Column(Text)
    description = Column(Text, nullable=True)
    data = Column(JSON, nullable=True)
    meta = Column(JSON, nullable=True)
    access_control = Column(JSON, nullable=True)
    created_at = Column(BigInteger)
    updated_at = Column(BigInteger)
```

## 필수 컬럼
- `id`: Text PK — `str(uuid.uuid4())`로 생성
- `user_id`: Text — 다중 테넌시 필수
- `created_at`, `updated_at`: BigInteger — `int(time.time())`

## 선택 컬럼
- `name`, `description`: Text
- `data`, `meta`: JSON nullable — 유연한 데이터 저장
- `access_control`: JSON nullable — 그룹/조직 권한

## Pydantic 모델
```python
from pydantic import BaseModel, ConfigDict

class ResourceModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)  # 필수
    id: str
    user_id: str
    name: str
    created_at: int
    updated_at: int
```

## 응답 모델 계층
```
ResourceModel (기본)
  → ResourceUserModel(ResourceModel) + user: Optional[UserResponse]
  → ResourceResponse(ResourceModel) + files: Optional[list]
  → ResourceUserResponse(ResourceUserModel) + files: Optional[list]
```

## Form 모델 (입력 검증)
```python
class ResourceForm(BaseModel):
    name: str
    description: str
    data: Optional[dict] = None
    access_control: Optional[dict] = None
    # id, user_id, created_at, updated_at 제외
```

## Table 클래스 (CRUD)
```python
class ResourceTable:
    def insert_new_resource(self, user_id: str, form_data: ResourceForm) -> Optional[ResourceModel]:
        with get_db() as db:
            resource = ResourceModel(**{
                **form_data.model_dump(),
                "id": str(uuid.uuid4()),
                "user_id": user_id,
                "created_at": int(time.time()),
                "updated_at": int(time.time()),
            })
            result = Resource(**resource.model_dump())
            db.add(result)
            db.commit()
            db.refresh(result)
            return ResourceModel.model_validate(result)

Resources = ResourceTable()  # 모듈 레벨 싱글톤
```

## DB 세션 관리
- `with get_db() as db:` 컨텍스트 매니저 사용
- `db.commit()` 후 반드시 `db.refresh(result)`
- 예외 시 `return None` 또는 `return False`

## 수정 패턴
```python
for key, value in form_data.model_dump().items():
    setattr(resource, key, value)
resource.updated_at = int(time.time())
db.commit()
db.refresh(resource)
```

## 마이그레이션 규칙
- `alembic revision -m "desc"` — **--autogenerate 사용 금지**
- 수동으로 마이그레이션 파일 작성
- `alembic upgrade head`로 적용

### Idempotent DDL 필수 (고객사 배포 안전성)
운영/고객사 DB 는 alembic_version 이 알 수 없는 상태에 있을 수 있다 (수동
SQL 적용, 과거 silent auto-recovery, 부분 적용 등). 모든 DDL 은 **재실행해도
실패하지 않도록 idempotent** 하게 작성한다.

```python
# ❌ 비-멱등 — 이미 컬럼/테이블이 있으면 실패
op.add_column("user", sa.Column("oauth_oid", sa.Text()))
op.create_table("trusted_audience", ...)
op.create_index("ix_user_oauth_oid", "user", ["oauth_oid"])

# ✅ inspector 가드 — 항상 안전
def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    existing_columns = {col["name"] for col in inspector.get_columns("user")}
    if "oauth_oid" not in existing_columns:
        op.add_column("user", sa.Column("oauth_oid", sa.Text()))

    if "trusted_audience" not in set(inspector.get_table_names()):
        op.create_table("trusted_audience", ...)

    inspector = sa.inspect(conn)  # 새 테이블 반영
    if "trusted_audience" in set(inspector.get_table_names()):
        existing_idx = {idx["name"] for idx in inspector.get_indexes("trusted_audience")}
        if "ix_trusted_audience_audience" not in existing_idx:
            op.create_index("ix_trusted_audience_audience", "trusted_audience", ["audience"])
```

DELETE / UPDATE / 데이터 변경은 SQL 자체가 idempotent 하므로 별도 가드 불필요.

### Multi-parent merge migration 주의
두 branch 가 각자 head 까지 진행된 뒤 `down_revision = (head_a, head_b)` 형태로
merge 마이그레이션을 만들 때:

- 고객사 DB 는 한 branch 의 head 만 alembic_version 에 갖고 있을 가능성 높음
- 이때 alembic 은 다른 branch 를 walk back 해서 적용 시도
- **그 branch 의 마이그레이션이 비-idempotent 면 `relation already exists` 등으로 실패** → 운영 장애
- 위 idempotent 규칙을 지키지 않으면 절대 안전하지 않음

merge 마이그레이션 본체는 보통 빈 함수 (`pass`). 실제 DDL 은 두 branch 에 이미
들어가 있어야 한다.

### Multi-head 검출
새 마이그레이션 추가 후 다음 명령으로 head 가 1개인지 확인:
```python
from alembic.script import ScriptDirectory
from alembic.config import Config
cfg = Config("open_webui/alembic.ini")
cfg.set_main_option("script_location", "open_webui/migrations")
heads = ScriptDirectory.from_config(cfg).get_heads()
assert len(heads) == 1, f"Multiple heads: {heads}"
```
2개 이상이면 빈 merge 마이그레이션을 추가해 단일 head 로 수렴시킬 것
(예시: `migrations/versions/d2e3f4a5b6c7_merge_*.py`).

### config.py 의 fail-loud 정책
`config.py:run_migrations()` 는 마이그레이션 실패 시 startup 을 **중단**한다.
silent stamp 같은 자동 복구는 하지 않는다 — 좀비 schema (alembic_version 은
head, 실제 DDL 은 누락) 를 마스킹하기 때문. 마이그레이션 작성자는 모든 DDL 이
어떤 출발 상태에서도 성공할 수 있도록 idempotent 하게 작성할 책임이 있다.

`verify_schema_state()` 는 부팅 직후 핵심 테이블/컬럼 존재 여부를 점검해
좀비 상태를 잡는다. 새 핵심 스키마 추가 시 `required_tables` /
`required_columns` 에 등록할 것.

## 정렬
- 기본 정렬: `order_by(Resource.updated_at.desc())`

## 참조 파일
- 표준 모델: `models/knowledge.py`, `models/glossary.py`, `models/guardrails.py`
- 그룹 모델: `models/groups.py` (JSON 배열 필터링 패턴)
- DB 설정: `internal/db.py` (Base, get_db, engine)

# 워크스페이스 기능 가이드

워크스페이스는 사용자가 AI와 함께 사용할 수 있는 리소스들을 관리하는 기능입니다.

## 워크스페이스 구성 요소

| 기능 | 설명 | 모델 | 라우터 |
|------|------|------|--------|
| **Agents** | AI 에이전트 (기존 Models) | `models/models.py` | `routers/models.py` |
| **Knowledge** | 지식베이스 (RAG) | `models/knowledge.py` | `routers/knowledge.py` |
| **DbSphere** | 데이터베이스 연결 | `models/dbsphere.py` | `routers/dbsphere.py` |
| **Glossary** | 용어집 | `models/glossary.py` | `routers/glossary.py` |
| **Prompts** | 프롬프트 템플릿 | `models/prompts.py` | `routers/prompts.py` |
| **Tools** | 도구/플러그인 | `models/tools.py` | `routers/tools.py` |

---

## 1. Agents (AI 에이전트)

### 개요

워크스페이스 에이전트는 특정 도구(Knowledge, DbSphere, Glossary 등)와 연동된 AI 모델입니다.
기존 "Models"에서 "Agents"로 리네이밍되었습니다.

### 모델 구조

```python
# models/models.py

class Model(Base):
    __tablename__ = "model"

    id = Column(Text, primary_key=True)
    user_id = Column(Text)
    base_model_id = Column(Text, nullable=True)  # 기반 LLM 모델 ID (있으면 에이전트)
    name = Column(Text)
    meta = Column(JSON, nullable=True)
    params = Column(JSON, nullable=True)
    access_control = Column(JSON, nullable=True)
    created_at = Column(BigInteger)
    updated_at = Column(BigInteger)
```

### 에이전트 vs 모델 구분

```python
# base_model_id가 있으면 에이전트, 없으면 일반 모델
model_info = metadata.get("model", {})
base_model_id = model_info.get("info", {}).get("base_model_id")

if base_model_id:
    # 에이전트 - 워크스페이스에서 생성된 커스텀 에이전트
    agent_id = model_info.get("id")
else:
    # 일반 모델 - OpenAI, Ollama 등 기본 모델
    agent_id = None
```

### params 필드 구조 (에이전트)

```python
params = {
    "system": "시스템 프롬프트",
    "temperature": 0.7,
    "knowledge_ids": ["kb-1", "kb-2"],  # 연결된 지식베이스
    "dbsphere_ids": ["db-1"],           # 연결된 데이터베이스
    "glossary_ids": ["gl-1"],           # 연결된 용어집
    "tool_ids": ["tool-1"],             # 연결된 도구
}
```

### 주요 API 엔드포인트

```
GET    /api/v1/models/              # 목록 조회
GET    /api/v1/models/{id}          # 상세 조회
POST   /api/v1/models/              # 생성
POST   /api/v1/models/{id}          # 수정
DELETE /api/v1/models/{id}          # 삭제
```

---

## 2. Knowledge (지식베이스)

### 개요

문서를 업로드하고 벡터화하여 RAG(Retrieval Augmented Generation)에 사용합니다.

### 모델 구조

```python
# models/knowledge.py

class Knowledge(Base):
    __tablename__ = "knowledge"

    id = Column(Text, primary_key=True)
    user_id = Column(Text)
    name = Column(Text)
    description = Column(Text, nullable=True)
    data = Column(JSON, nullable=True)          # 파일 정보
    access_control = Column(JSON, nullable=True)
    created_at = Column(BigInteger)
    updated_at = Column(BigInteger)
```

### data 필드 구조

```python
data = {
    "file_ids": ["file-id-1", "file-id-2"],  # 연결된 파일 ID
    "metadata": {
        "total_chunks": 150,
        "total_tokens": 50000,
        "embedding_model": "text-embedding-ada-002"
    }
}
```

### 주요 API 엔드포인트

```
GET    /api/v1/knowledge/              # 목록 조회
GET    /api/v1/knowledge/{id}          # 상세 조회
POST   /api/v1/knowledge/              # 생성
POST   /api/v1/knowledge/{id}          # 수정
DELETE /api/v1/knowledge/{id}          # 삭제

# 파일 관리
POST   /api/v1/knowledge/{id}/file/add       # 파일 추가
DELETE /api/v1/knowledge/{id}/file/{file_id} # 파일 제거
POST   /api/v1/knowledge/{id}/reset          # 벡터 데이터 초기화
```

### RAG 연동

```python
# routers/retrieval.py

@router.post("/query")
async def query_knowledge(
    form_data: QueryForm,
    user=Depends(get_verified_user)
):
    """지식베이스에서 관련 문서 검색"""

    # 1. 사용자의 접근 가능한 지식베이스 확인
    knowledge = Knowledges.get_knowledge_by_id(form_data.collection_id)
    if not has_access(user.id, "read", knowledge.access_control):
        raise HTTPException(status_code=403)

    # 2. 벡터 검색
    results = vector_search(
        collection_id=knowledge.id,
        query=form_data.query,
        top_k=form_data.top_k or 3
    )

    # 3. 관련성 필터링
    filtered = [r for r in results if r.score >= RELEVANCE_THRESHOLD]

    return {"results": filtered}
```

### 파일 처리 플로우

```
파일 업로드
  ↓
POST /api/v1/retrieval/file
  ↓
문서 파싱 (PDF, DOCX, TXT 등)
  ↓
텍스트 청킹 (chunk_size=1024, overlap=20)
  ↓
임베딩 생성 (OpenAI, Azure, Local)
  ↓
벡터 DB 저장 (Qdrant, Milvus, pgvector)
  ↓
파일 메타데이터 저장 (Files 테이블)
  ↓
Knowledge.data.file_ids에 추가
```

---

## 3. DbSphere (데이터베이스 연결)

### 개요

외부 데이터베이스에 연결하여 AI가 SQL 쿼리를 생성하고 실행할 수 있게 합니다.

### 모델 구조

```python
# models/dbsphere.py

class DbSphere(Base):
    __tablename__ = "dbsphere"

    id = Column(Text, primary_key=True)
    user_id = Column(Text)
    name = Column(Text)
    description = Column(Text, nullable=True)
    data = Column(JSON, nullable=True)          # 연결 정보
    access_control = Column(JSON, nullable=True)
    created_at = Column(BigInteger)
    updated_at = Column(BigInteger)
```

### data 필드 구조

```python
data = {
    "connection": {
        "type": "postgresql",  # mysql, sqlite, mssql, oracle
        "host": "localhost",
        "port": 5432,
        "database": "mydb",
        "username": "user",
        "password": "encrypted_password",  # 암호화 저장
        "options": {
            "ssl": True,
            "timeout": 30
        }
    },
    "schema": {
        "tables": [
            {
                "name": "users",
                "columns": [
                    {"name": "id", "type": "integer", "primary_key": True},
                    {"name": "email", "type": "varchar(255)"}
                ]
            }
        ]
    },
    "metadata": {
        "last_sync": 1706000000,
        "table_count": 15
    }
}
```

### 주요 API 엔드포인트

```
GET    /api/v1/dbsphere/              # 목록 조회
GET    /api/v1/dbsphere/{id}          # 상세 조회
POST   /api/v1/dbsphere/              # 생성
POST   /api/v1/dbsphere/{id}          # 수정
DELETE /api/v1/dbsphere/{id}          # 삭제

# 데이터베이스 작업
POST   /api/v1/dbsphere/test          # 연결 테스트
POST   /api/v1/dbsphere/{id}/query    # 쿼리 실행
GET    /api/v1/dbsphere/{id}/schema   # 스키마 조회
POST   /api/v1/dbsphere/{id}/sync     # 스키마 동기화
GET    /api/v1/dbsphere/types         # 지원 DB 타입
```

### 연결 테스트

```python
# routers/dbsphere.py

@router.post("/test")
async def test_connection(
    form_data: DbConnectionTestForm,
    user=Depends(get_verified_user)
):
    """데이터베이스 연결 테스트"""
    try:
        connection = create_db_connection(form_data.connection)
        connection.execute("SELECT 1")
        return {"success": True, "message": "Connection successful"}
    except Exception as e:
        return {"success": False, "message": str(e)}
```

### 쿼리 실행 (안전하게)

```python
@router.post("/{id}/query")
async def execute_query(
    id: str,
    form_data: QueryForm,
    user=Depends(get_verified_user)
):
    """SQL 쿼리 실행"""
    dbsphere = DbSpheres.get_dbsphere_by_id(id)

    # 권한 검사
    if not has_access(user.id, "read", dbsphere.access_control):
        raise HTTPException(status_code=403)

    # 위험한 쿼리 차단 (SELECT만 허용)
    if not is_safe_query(form_data.query):
        raise HTTPException(
            status_code=400,
            detail="Only SELECT queries are allowed"
        )

    try:
        connection = create_db_connection(dbsphere.data["connection"])
        result = connection.execute(form_data.query)

        return {
            "success": True,
            "columns": result.keys(),
            "rows": result.fetchmany(100),  # 최대 100행
            "row_count": result.rowcount
        }
    except Exception as e:
        return {"success": False, "error": str(e)}
```

---

## 4. Glossary (용어집)

### 개요

도메인 특화 용어와 정의를 관리합니다. AI가 대화 중 용어를 자동으로 해석합니다.

### 모델 구조

```python
# models/glossary.py

class Glossary(Base):
    __tablename__ = "glossary"

    id = Column(Text, primary_key=True)
    user_id = Column(Text)
    name = Column(Text)
    description = Column(Text, nullable=True)
    data = Column(JSON, nullable=True)          # 용어 목록
    access_control = Column(JSON, nullable=True)
    created_at = Column(BigInteger)
    updated_at = Column(BigInteger)
```

### data 필드 구조

```python
data = {
    "terms": [
        {
            "term": "RAG",
            "definition": "Retrieval Augmented Generation의 약자로, 외부 지식을 검색하여 LLM 응답을 개선하는 기법",
            "category": "AI",
            "aliases": ["검색 증강 생성"]
        },
        {
            "term": "Embedding",
            "definition": "텍스트를 고차원 벡터로 변환하는 과정",
            "category": "AI",
            "aliases": ["임베딩", "벡터화"]
        }
    ],
    "metadata": {
        "term_count": 50,
        "last_updated": 1706000000
    }
}
```

### 주요 API 엔드포인트

```
GET    /api/v1/glossary/              # 목록 조회
GET    /api/v1/glossary/{id}          # 상세 조회
POST   /api/v1/glossary/              # 생성
POST   /api/v1/glossary/{id}          # 수정
DELETE /api/v1/glossary/{id}          # 삭제

# 용어 관리
POST   /api/v1/glossary/{id}/terms    # 용어 추가
DELETE /api/v1/glossary/{id}/terms/{term}  # 용어 삭제
GET    /api/v1/glossary/{id}/search   # 용어 검색
```

### 채팅에서 용어 활용

```python
# utils/middleware.py

async def inject_glossary_context(
    message: str,
    glossary_ids: list[str]
) -> str:
    """메시지에 관련 용어 정의 주입"""

    terms_found = []
    for glossary_id in glossary_ids:
        glossary = Glossaries.get_glossary_by_id(glossary_id)
        if glossary and glossary.data:
            for term_data in glossary.data.get("terms", []):
                term = term_data["term"]
                aliases = term_data.get("aliases", [])
                all_terms = [term] + aliases

                for t in all_terms:
                    if t.lower() in message.lower():
                        terms_found.append(term_data)
                        break

    if terms_found:
        context = "참고할 용어 정의:\n"
        for t in terms_found:
            context += f"- {t['term']}: {t['definition']}\n"
        return context

    return ""
```

---

## 공통 패턴

### 모델 생성 패턴

모든 워크스페이스 리소스는 동일한 패턴을 따릅니다:

```python
class ResourceTable:
    def insert_new_resource(
        self,
        user_id: str,
        form_data: ResourceForm
    ) -> Optional[ResourceModel]:
        with get_db() as db:
            resource = Resource(
                id=str(uuid.uuid4()),
                user_id=user_id,
                name=form_data.name,
                description=form_data.description,
                data=form_data.data or {},
                access_control=form_data.access_control,
                created_at=int(time.time()),
                updated_at=int(time.time()),
            )
            db.add(resource)
            db.commit()
            db.refresh(resource)
            return ResourceModel.model_validate(resource)
```

### 라우터 패턴

```python
router = APIRouter()

@router.get("/", response_model=list[ResourceModel])
async def get_resources(user=Depends(get_verified_user)):
    """접근 가능한 리소스 목록"""
    all_resources = Resources.get_all_resources()
    return [
        r for r in all_resources
        if r.user_id == user.id or has_access(
            user.id, "read", r.access_control
        )
    ]

@router.post("/", response_model=ResourceModel)
async def create_resource(
    form_data: ResourceForm,
    user=Depends(get_verified_user)
):
    return Resources.insert_new_resource(user.id, form_data)
```

### 접근 제어

모든 워크스페이스 리소스는 `access_control` 필드를 통해 공유됩니다:

```python
access_control = {
    "read": {
        "user_ids": [],
        "group_ids": ["team-a"],
        "org_unit_ids": ["engineering"]
    },
    "write": {
        "user_ids": [],
        "group_ids": ["team-a-leads"],
        "org_unit_ids": []
    }
}
```

---

## 프론트엔드 연동

### API 클라이언트

```typescript
// src/lib/apis/knowledge/index.ts

export const getKnowledgeBases = async (token: string) => {
  const res = await fetch(`${WEBUI_API_BASE_URL}/knowledge/`, {
    headers: { authorization: `Bearer ${token}` }
  });
  return res.json();
};

// src/lib/apis/dbsphere/index.ts

export const testDbConnection = async (token: string, connection: DbConnection) => {
  const res = await fetch(`${WEBUI_API_BASE_URL}/dbsphere/test`, {
    method: 'POST',
    headers: {
      authorization: `Bearer ${token}`,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({ connection })
  });
  return res.json();
};
```

### 채팅에서 사용

```python
# 채팅 요청 시 사용할 리소스 지정
{
    "model": "gpt-4",
    "messages": [...],
    "knowledge_ids": ["kb-1", "kb-2"],     # RAG 검색
    "dbsphere_ids": ["db-1"],               # SQL 쿼리 허용
    "glossary_ids": ["gl-1"]                # 용어 참조
}
```

---

## 참조 파일

| 카테고리 | 모델 | 라우터 |
|----------|------|--------|
| Knowledge | `models/knowledge.py` | `routers/knowledge.py` (23KB) |
| DbSphere | `models/dbsphere.py` | `routers/dbsphere.py` (24KB) |
| Glossary | `models/glossary.py` | `routers/glossary.py` (4.8KB) |
| RAG | - | `routers/retrieval.py` (72KB) |
| 파일 | `models/files.py` | `routers/files.py` (16KB) |

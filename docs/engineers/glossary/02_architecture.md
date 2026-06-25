# Glossary 아키텍처

## 1. 데이터베이스 모델

### ORM 모델

```python
# backend/open_webui/models/glossary.py

class Glossary(Base):
    __tablename__ = "glossary"

    id = Column(Text, primary_key=True)          # UUID
    user_id = Column(Text)                        # 소유자 ID
    name = Column(Text)                           # Glossary 이름
    description = Column(Text, nullable=True)     # 설명
    data = Column(JSON, nullable=True)            # 용어 데이터 (아래 구조 참조)
    access_control = Column(JSON, nullable=True)  # 접근 제어
    created_at = Column(BigInteger)               # 생성 시간 (Unix timestamp)
    updated_at = Column(BigInteger)               # 수정 시간 (Unix timestamp)
```

### data 필드 구조

```python
data = {
    "terms": [
        {
            "id": "term-uuid-1",
            "term": "RAG",
            "definition": "Retrieval Augmented Generation의 약자로...",
            "category": "AI",
            "aliases": ["검색 증강 생성"],
            "created_at": 1706000000,
            "updated_at": 1706000000
        },
        # ... 더 많은 용어
    ],
    "metadata": {
        "term_count": 50,
        "categories": ["AI", "마케팅", "재무"],
        "last_sync_at": 1706000000  # 검색 엔진 동기화 시간
    }
}
```

### access_control 필드 구조

```python
access_control = {
    "read": {
        "user_ids": [],
        "group_ids": ["team-a", "team-b"],
        "org_unit_ids": ["engineering"]
    },
    "write": {
        "user_ids": [],
        "group_ids": ["team-a-leads"],
        "org_unit_ids": []
    }
}
```

### Pydantic 스키마

```python
# 응답 모델
class GlossaryModel(BaseModel):
    id: str
    user_id: str
    name: str
    description: Optional[str] = None
    data: Optional[dict] = None
    access_control: Optional[dict] = None
    created_at: int
    updated_at: int

# 생성/수정 폼
class GlossaryForm(BaseModel):
    name: str
    description: Optional[str] = None
    data: Optional[dict] = None
    access_control: Optional[dict] = None

# 개별 용어
class TermForm(BaseModel):
    term: str
    definition: str
    category: Optional[str] = None
    aliases: Optional[list[str]] = None
```

## 2. API 엔드포인트

### 라우터 등록

```python
# backend/open_webui/main.py

from open_webui.routers import glossary

app.include_router(glossary.router, prefix="/api/v1/glossary", tags=["glossary"])
```

### 엔드포인트 목록

| 메서드 | 경로 | 설명 | 권한 |
|--------|------|------|------|
| GET | `/` | 접근 가능한 Glossary 목록 | 인증 |
| GET | `/{id}` | 상세 조회 | 읽기 권한 |
| POST | `/` | Glossary 생성 | 인증 |
| POST | `/{id}` | Glossary 수정 | 쓰기 권한 |
| DELETE | `/{id}` | Glossary 삭제 | 소유자/관리자 |
| POST | `/{id}/terms` | 용어 추가 | 쓰기 권한 |
| PUT | `/{id}/terms/{term_id}` | 용어 수정 | 쓰기 권한 |
| DELETE | `/{id}/terms/{term_id}` | 용어 삭제 | 쓰기 권한 |
| GET | `/{id}/search` | 용어 검색 | 읽기 권한 |
| POST | `/{id}/sync` | 검색 엔진 동기화 | 쓰기 권한 |
| POST | `/{id}/import` | CSV/JSON 가져오기 | 쓰기 권한 |
| GET | `/{id}/export` | CSV/JSON 내보내기 | 읽기 권한 |

### 핵심 엔드포인트 구현

```python
# backend/open_webui/routers/glossary.py

router = APIRouter()

@router.get("/", response_model=list[GlossaryModel])
async def get_glossaries(user=Depends(get_verified_user)):
    """접근 가능한 Glossary 목록 조회"""
    all_glossaries = Glossaries.get_all_glossaries()
    return [
        g for g in all_glossaries
        if g.user_id == user.id or has_access(
            user.id, "read", g.access_control
        )
    ]


@router.post("/{id}/terms", response_model=GlossaryModel)
async def add_term(
    id: str,
    form_data: TermForm,
    request: Request,
    user=Depends(get_verified_user)
):
    """용어 추가"""
    glossary = Glossaries.get_glossary_by_id(id)
    if not glossary:
        raise HTTPException(status_code=404, detail="Glossary not found")

    if not has_access(user.id, "write", glossary.access_control):
        raise HTTPException(status_code=403, detail="Permission denied")

    # 용어 추가
    term_data = {
        "id": str(uuid.uuid4()),
        "term": form_data.term,
        "definition": form_data.definition,
        "category": form_data.category,
        "aliases": form_data.aliases or [],
        "created_at": int(time.time()),
        "updated_at": int(time.time()),
    }

    data = glossary.data or {"terms": [], "metadata": {}}
    data["terms"].append(term_data)
    data["metadata"]["term_count"] = len(data["terms"])

    updated = Glossaries.update_glossary_by_id(id, {"data": data})

    # 검색 엔진에 색인 (비동기)
    await sync_term_to_search_engine(request.app, glossary.id, term_data)

    return updated


@router.get("/{id}/search")
async def search_terms(
    id: str,
    q: str = Query(..., min_length=1),
    request: Request,
    user=Depends(get_verified_user)
):
    """용어 검색 (벡터 검색 포함)"""
    glossary = Glossaries.get_glossary_by_id(id)
    if not has_access(user.id, "read", glossary.access_control):
        raise HTTPException(status_code=403)

    # 검색 엔진 사용
    engine = get_configured_search_engine(
        request.app,
        create_glossary_config(f"glossary_{id}")
    )

    if engine:
        # 벡터 검색
        query_embedding = await generate_embedding(q)
        results = await engine.search(
            SearchQuery(query=q, top_k=10),
            query_vector=query_embedding
        )
        return {"results": results}

    # Fallback: 로컬 검색
    terms = glossary.data.get("terms", [])
    results = [
        t for t in terms
        if q.lower() in t["term"].lower()
        or q.lower() in t["definition"].lower()
        or any(q.lower() in a.lower() for a in t.get("aliases", []))
    ]
    return {"results": results}
```

## 3. Extension Module

### 디렉토리 구조

```
backend/extension_modules/glossary/
├── __init__.py
├── glossary_agent.py      # 에이전트 메인 로직
└── tools.py               # LangChain 도구
```

### GlossaryAgent

```python
# extension_modules/glossary/glossary_agent.py

class GlossaryAgent:
    def __init__(self, metadata: dict):
        self.metadata = metadata
        self.glossary_ids = metadata.get("glossary_ids", [])

    async def run(self, payload: dict, event_emitter, event_call):
        # 검색 엔진 설정
        engine = get_configured_search_engine(
            self.metadata.get("app"),
            create_glossary_config(f"glossary_combined")
        )

        # 도구 생성
        tools = [
            GlossarySearchTool(
                glossary_ids=self.glossary_ids,
                search_engine=engine,
            ),
        ]

        # 미들웨어 설정
        middleware = MiddlewareBase(
            event_emitter, event_call, self.metadata
        )

        # LangGraph 에이전트 실행
        llm = get_llm(payload.get("model"))
        graph = create_react_agent(llm, tools, middleware=middleware)

        result = await graph.ainvoke({
            "messages": payload.get("messages", [])
        })

        return result
```

### GlossarySearchTool

```python
# extension_modules/glossary/tools.py

from langchain.tools import BaseTool

class GlossarySearchTool(BaseTool):
    name: str = "glossary_search"
    description: str = """
    조직 내 용어 정의를 검색합니다.
    도메인 특화 용어, 약어, 업무 규칙 등을 찾을 때 사용하세요.

    입력: 검색할 용어나 질문
    출력: 관련 용어와 정의 목록
    """

    glossary_ids: list[str]
    search_engine: Any

    async def _arun(self, query: str) -> str:
        if not self.search_engine:
            return "검색 엔진이 설정되지 않았습니다."

        # 임베딩 생성
        query_embedding = await generate_embedding(query)

        # 벡터 검색
        results = await self.search_engine.search(
            SearchQuery(query=query, top_k=5),
            query_vector=query_embedding
        )

        if not results:
            return "관련 용어를 찾을 수 없습니다."

        # 결과 포맷팅
        output = "## 관련 용어\n\n"
        for r in results:
            output += f"### {r.term}\n"
            output += f"{r.definition}\n"
            if r.category:
                output += f"- 카테고리: {r.category}\n"
            if r.aliases:
                output += f"- 별칭: {', '.join(r.aliases)}\n"
            output += "\n"

        return output
```

## 4. 프론트엔드

### API 클라이언트

```typescript
// src/lib/apis/glossary/index.ts

import { WEBUI_API_BASE_URL } from '$lib/constants';

export const getGlossaries = async (token: string) => {
  const res = await fetch(`${WEBUI_API_BASE_URL}/glossary/`, {
    headers: { authorization: `Bearer ${token}` }
  });
  if (!res.ok) throw await res.json();
  return res.json();
};

export const getGlossaryById = async (token: string, id: string) => {
  const res = await fetch(`${WEBUI_API_BASE_URL}/glossary/${id}`, {
    headers: { authorization: `Bearer ${token}` }
  });
  if (!res.ok) throw await res.json();
  return res.json();
};

export const createGlossary = async (token: string, data: GlossaryForm) => {
  const res = await fetch(`${WEBUI_API_BASE_URL}/glossary/`, {
    method: 'POST',
    headers: {
      authorization: `Bearer ${token}`,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(data)
  });
  if (!res.ok) throw await res.json();
  return res.json();
};

export const addTerm = async (
  token: string,
  glossaryId: string,
  term: TermForm
) => {
  const res = await fetch(`${WEBUI_API_BASE_URL}/glossary/${glossaryId}/terms`, {
    method: 'POST',
    headers: {
      authorization: `Bearer ${token}`,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(term)
  });
  if (!res.ok) throw await res.json();
  return res.json();
};

export const searchTerms = async (
  token: string,
  glossaryId: string,
  query: string
) => {
  const res = await fetch(
    `${WEBUI_API_BASE_URL}/glossary/${glossaryId}/search?q=${encodeURIComponent(query)}`,
    { headers: { authorization: `Bearer ${token}` } }
  );
  if (!res.ok) throw await res.json();
  return res.json();
};
```

### 컴포넌트 구조

```
src/lib/components/workspace/Glossary/
├── GlossaryDetail.svelte   # 상세/편집 페이지
├── CreateGlossary.svelte   # 생성 페이지
├── TermList.svelte         # 용어 목록 컴포넌트
├── TermForm.svelte         # 용어 입력 폼
└── ImportModal.svelte      # CSV/JSON 가져오기 모달
```

## 5. 검색 엔진 연동

### 인덱스 생성

```python
from extension_modules.search_engine import (
    get_configured_search_engine,
    create_glossary_config,
)

# 인덱스 설정
index_config = create_glossary_config(f"glossary_{glossary_id}")

# 엔진 생성 및 인덱스 생성
engine = get_configured_search_engine(request.app, index_config)
if engine:
    async with engine:
        await engine.create_index()
```

### 용어 색인

```python
async def sync_term_to_search_engine(app, glossary_id: str, term: dict):
    """용어를 검색 엔진에 색인"""
    engine = get_configured_search_engine(
        app,
        create_glossary_config(f"glossary_{glossary_id}")
    )

    if not engine:
        return

    # 임베딩 생성 (term + definition 조합)
    text = f"{term['term']}: {term['definition']}"
    embedding = await generate_embedding(text)

    # 문서 생성
    doc = DocumentItem(
        id=term["id"],
        content=text,
        vector=embedding,
        metadata={
            "term": term["term"],
            "definition": term["definition"],
            "category": term.get("category"),
            "aliases": ",".join(term.get("aliases", [])),
        }
    )

    # 색인
    async with engine:
        await engine.upsert([doc])
```

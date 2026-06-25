> Last Updated: 2026-04-08

# Glossary (용어집) 모듈

Cloosphere의 용어집(Glossary) 기능에 대한 기술 문서입니다.

> **데이터 스키마 주의**: 2026-03 이후 코드 기준 실제 필드명은 `data.entries[]`이며 각 entry는 `{id, term, synonyms, description, example, category}` 형태입니다. 과거 문서에 나오는 `data.terms[]`, `aliases`, `definition`은 **구 용어**로 현재 코드와 일치하지 않습니다.

## 목차

1. [개요](#개요)
2. [주요 기능](#주요-기능)
3. [상세 문서](#상세-문서)
4. [퀵 스타트](#퀵-스타트)

---

## 개요

Glossary는 조직 내 도메인 용어, 약어, 업무 규칙 등을 정의하고 관리하는 용어집입니다. 검색 엔진과 연동하여 AI가 대화 중 관련 용어를 자동으로 참조할 수 있습니다.

### 주요 개념

| 개념 | 설명 |
|------|------|
| **Glossary** | 용어집 컬렉션 (여러 용어를 포함) |
| **Term** | 개별 용어 (용어명, 정의, 카테고리, 별칭) |
| **Search Engine** | 용어 검색을 위한 벡터 DB 연동 |
| **Agent 연동** | 에이전트가 대화 중 용어 자동 참조 |

### 데이터 흐름

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  관리자/사용자   │────▶│  Glossary API   │────▶│  Search Engine  │
│  (프론트엔드)    │     │  (Backend)      │     │  (Vector DB)    │
└─────────────────┘     └─────────────────┘     └─────────────────┘
        │                       │                       │
        │  CRUD                 │  용어 색인             │  벡터 검색
        │                       │                       │
        ▼                       ▼                       ▼
   워크스페이스           PostgreSQL            Azure AI Search
   Glossary 페이지        glossary 테이블       / pgvector 등
```

### Agent 연동 흐름

```
사용자 질문: "RAG가 뭐야?"
        │
        ▼
┌─────────────────┐
│  Glossary Agent │  ← 검색 엔진에서 "RAG" 용어 검색
└─────────────────┘
        │
        ▼
용어 정의 반환: "RAG(Retrieval Augmented Generation)는
                외부 지식을 검색하여 LLM 응답을 개선하는 기법"
```

---

## 주요 기능

### 1. 용어 관리

- **용어 추가/수정/삭제**: 워크스페이스에서 용어 CRUD
- **별칭 지원**: 하나의 용어에 여러 별칭 등록 (예: RAG, 검색 증강 생성)
- **카테고리 분류**: 용어를 카테고리별로 분류
- **접근 제어**: 그룹/조직 단위별 접근 권한 설정

### 2. 검색 엔진 연동

- **자동 색인**: 용어 추가/수정 시 검색 엔진에 자동 색인
- **벡터 검색**: 임베딩 기반 유사 용어 검색
- **스키마 프리셋**: `create_glossary_config()` 함수로 인덱스 생성

### 3. Agent 도구

- **LangChain Tool**: `GlossarySearchTool`로 에이전트에서 용어 검색
- **자동 컨텍스트 주입**: 대화 중 관련 용어 자동 참조

### 4. 일괄 관리

- **CSV/JSON 가져오기**: 대량 용어 일괄 등록
- **내보내기**: 용어 목록 CSV/JSON 다운로드

---

## 상세 문서

| 문서 | 설명 |
|------|------|
| [01_overview.md](./01_overview.md) | 기능 상세 설명 및 사용 시나리오 |
| [02_architecture.md](./02_architecture.md) | 데이터베이스 모델, 라우터 구조, 검색 엔진 연동, 트러블슈팅 |
| [03_api.md](./03_api.md) | REST API 엔드포인트 (8개) |
| [04_frontend.md](./04_frontend.md) | 프론트엔드 컴포넌트 및 API 클라이언트 |
| [05_configuration.md](./05_configuration.md) | 환경 변수, 의존성, 라이선스 |

---

## 퀵 스타트

### 1. Glossary 생성

1. 워크스페이스 → Glossary 탭
2. **+ 새 용어집** 클릭
3. 이름, 설명 입력
4. **저장** 클릭

### 2. 용어 추가

1. 생성된 Glossary 클릭
2. **+ 용어 추가** 클릭
3. 용어 정보 입력:
   - **용어명**: RAG
   - **정의**: Retrieval Augmented Generation의 약자로...
   - **카테고리**: AI
   - **별칭**: 검색 증강 생성
4. **추가** 클릭

### 3. Agent에 연결

1. 워크스페이스 → Agents 탭
2. 에이전트 선택 또는 생성
3. **Glossary** 섹션에서 연결할 용어집 선택
4. **저장** 클릭

### 4. 코드에서 사용

```python
from extension_modules.glossary import GlossaryAgent

# Glossary 에이전트 생성
agent = GlossaryAgent(
    metadata={
        "glossary_ids": ["glossary-id-1"],
        "model": model_info,
        "user_id": user.id,
    }
)

# 용어 검색
result = await agent.search_terms("RAG란 무엇인가요?")
```

---

## 환경 변수

Glossary는 Search Engine 모듈을 사용하므로, 검색 엔진 설정이 필요합니다.

| 변수 | 설명 | 기본값 |
|------|------|--------|
| `SEARCH_ENGINE_TYPE` | 검색 엔진 타입 (azure_search, pgvector 등) | `""` |
| `SEARCH_ENGINE_AZURE_ENDPOINT` | Azure Search 엔드포인트 | `""` |
| `SEARCH_ENGINE_AZURE_API_KEY` | Azure Search API 키 | `""` |

> 전체 검색 엔진 설정은 [검색 엔진 문서](../search_engine/README.md) 참조

---

## 관련 파일

### Backend

- `backend/open_webui/models/glossary.py` - DB 모델
- `backend/open_webui/routers/glossary.py` - API 라우터
- `backend/extension_modules/glossary/` - Glossary 에이전트 모듈
  - `glossary_agent.py` - 에이전트 메인 로직
  - `tools.py` - LangChain 도구
- `backend/extension_modules/search_engine/schemas.py` - `create_glossary_config()` 함수

### Frontend

- `src/lib/apis/glossary/index.ts` - API 클라이언트
- `src/lib/components/workspace/Glossary/` - Glossary 컴포넌트
  - `GlossaryDetail.svelte` - 상세/편집 페이지
  - `CreateGlossary.svelte` - 생성 페이지
- `src/routes/(app)/workspace/glossary/` - 라우트

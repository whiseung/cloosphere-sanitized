---
paths:
  - "backend/open_webui/routers/glossary.py"
  - "backend/open_webui/models/glossary.py"
  - "backend/extension_modules/glossary/**/*.py"
  - "src/lib/components/workspace/Glossary/**/*.svelte"
  - "src/lib/apis/glossary/**/*.ts"
---

# 용어집 규칙

## 라우터 (routers/glossary.py)
- CRUD 표준 패턴 — `workspace.glossaries` 권한 (feature gate 401, resource gate 403)
- `/{id}/entries`: GET 페이지네이션 + POST 신규 (다중 카테고리 필터: `categories[]` + `include_uncategorized`)
- `/{id}/entries/{entry_id}`: PUT/DELETE 개별 항목
- `/{id}/entries/bulk-delete`: POST 다중 삭제 (body `{entry_ids}`)
- `/{id}/import/preview` + `/{id}/import/commit`: XLSX/CSV/MD 일괄 import (2-step, upload_token)
- `/{id}/categories`: GET 목록 + `/categories/rename` POST + `/categories/delete` POST (slash-safe)
- `/{id}/search`: POST 임베딩 기반 유사 용어 검색
- BackgroundTasks: 검색 엔진 인덱싱 비동기 처리

## 모델 스키마
```python
class Glossary(Base):
    __tablename__ = "glossary"
    id, user_id, name, description
    data(JSON), meta(JSON), access_control(JSON)
    created_at, updated_at
```
- `data.entries`: `[{id, term, synonyms: [...], description, example, category?, created_at, updated_at}]`
- `meta.categories`: 정렬된 카테고리 리스트 (data 갱신 시 `_set_categories_meta` 자동 재계산)
- `meta.extraction_sources` / `meta.category_definitions`: 카테고리별 추출 출처/정의 캐시
- `meta.extract_job`: LLM 카테고리/용어 추출 잡 상태 (status, phase, progress, result)

## 검색 엔진 연동
- `index_glossary_entries()`: 비동기 인덱싱
- SearchEngine 프리셋: `create_glossary_config()`
- 벡터 검색으로 유사 용어 찾기

## 에이전트 연동
- 에이전트 meta.glossary_ids에 용어집 연결
- 미들웨어에서 관련 용어 자동 주입

## 참조 파일
- `routers/glossary.py`: CRUD + 항목 관리 + 검색
- `models/glossary.py`: Glossary/GlossaryModel/GlossaryForm
- `extension_modules/glossary/`: 용어집 서비스

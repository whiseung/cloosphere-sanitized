---
paths:
  - "backend/open_webui/routers/retrieval.py"
  - "backend/open_webui/retrieval/**/*.py"
---

# RAG/벡터DB/임베딩 규칙

## 벡터DB 커넥터 (retrieval/vector/)
- 팩토리: `VECTOR_DB_CLIENT` 환경 변수로 선택
- 구현체: chroma, milvus, opensearch, pgvector, qdrant, elasticsearch, azure_search
- 공통 인터페이스: `has()`, `get()`, `insert()`, `upsert()`, `delete()`, `search()`, `reset()`

## 문서 로더 (retrieval/loaders/)
- `main.py`: 통합 로더 — PDF, DOCX, PPTX, TXT, Markdown, HTML, JSON, CSV, XLSX, XML
- `get_loader()`: Content-Type 기반 로더 선택
- 웹: Playwright, Jina, Firecrawl 백엔드 (WEB_LOADER_ENGINE)

## 웹 검색 (retrieval/web/)
- 16+ 프로바이더: brave, duckduckgo, google_pse, jina, kagi, mojeek, searchapi,
  searxng, serper, serpstack, tavily, bing, yep, baidu, naver, wolframalpha

## 청킹/임베딩 (retrieval/utils.py)
- `get_sources_from_files()`: 파일에서 관련 문서 검색
- `generate_openai_batch_embeddings()`: 배치 임베딩 생성 + usage 기록
- 매개변수: TOP_K, CHUNK_SIZE, CHUNK_OVERLAP
- 하이브리드 검색/리랭킹은 SearchEngine 모듈(pgvector RRF + Vertex AI Ranking)에서 처리

## retrieval.py 라우터 (72KB)
- `/process/file`: POST 파일 처리 (추출 + 청킹 + 임베딩 + 벡터DB 저장)
- `/query/doc`: POST 문서 쿼리
- `/config`: GET/POST RAG 설정 관리
- 임베딩 엔진: local, openai, azure, ollama

## 핵심 설정 (config)
- `RAG_EMBEDDING_ENGINE`, `RAG_EMBEDDING_MODEL`
- `RAG_TOP_K`
- `CHUNK_SIZE` (1500 기본), `CHUNK_OVERLAP` (100 기본)
- `RAG_TEMPLATE`: 컨텍스트 주입 템플릿

## Knowledge 벡터 저장 (search_engine 기반)
- `retrieval/knowledge_service.py`: `SearchEngineKnowledge` — search_engine 모듈 기반
- 인덱스: `default_knowledge` 고정, `collection` 필드로 지식기반 구분
- `save_docs_to_vector_db()` (retrieval.py): SearchEngineKnowledge 사용하여 청크 저장
- 기존 `VECTOR_DB_CLIENT`는 점진적 마이그레이션 중

## 백그라운드 파일 처리
- `process_file(background=True)`: ThreadPoolExecutor에서 `_run_file_processing_sync` 실행
- 완료 시 `send_notification_to_user()` → Socket.IO `file-processing-completed` 이벤트
- `processing_job` 상태: file.data에 저장 (`pending` → `processing` → `completed`/`failed`)

## 참조 파일
- `routers/retrieval.py` (72KB): RAG 엔드포인트, process_file
- `retrieval/knowledge_service.py`: SearchEngineKnowledge
- `retrieval/vector/connector.py`: 벡터DB 팩토리 (레거시)
- `retrieval/utils.py`: 청킹, 임베딩, 검색
- `retrieval/loaders/main.py`: 문서 로더

---
paths:
  - "backend/open_webui/routers/knowledge_graph.py"
  - "backend/open_webui/models/knowledge_graph.py"
  - "backend/extension_modules/knowledge_graph/**/*.py"
  - "src/lib/components/workspace/KnowledgeGraph/**/*.svelte"
  - "src/lib/apis/knowledge-graph/**/*.ts"
  - "src/routes/(app)/workspace/knowledge-graph/**/*"
---

# Knowledge Graph 규칙

DbSphere(DB) ↔ Knowledge(KB) ↔ Glossary(용어)를 엔티티 중심으로 연결하는
지식 그래프. PostgreSQL AGE 확장을 그래프 저장소로 사용하고, 검색 인덱스
(SearchEngine 모듈)에서 노드 임베딩/검색을 담당한다.

## 라우터 (routers/knowledge_graph.py — 46 엔드포인트)
- 기본 CRUD: `/`, `/list`, `/create`, `/{id}`, `/{id}/update`, `/{id}/delete`
- 활성 작업: `/active-jobs`, `/{id}/jobs`, `/{id}/jobs/{job_id}`, `/{id}/jobs/{job_id}/cancel`
- 동기화: `/{id}/sync` (용어집/참조 리소스 재매핑)
- 노드/엣지: `/{id}/nodes`, `/{id}/edges`, `/{id}/nodes/{node_id}/update`, `/{id}/nodes/{node_id}` (DELETE), `/{id}/nodes/merge`
- 엣지 타입 카탈로그: `/{id}/edge-types`, `/{id}/links/{link_id}/edge-types/catalog` (GET/PUT), `.../recommend`, `.../auto-generate`
- 시각화/탐색: `/{id}/graph`, `/{id}/stats`, `/{id}/neighbors`, `/{id}/search`, `/{id}/mappings`
- KB 추출: `/{id}/kb/extract/preview`, `/{id}/kb/extract`, `/{id}/candidates` (accept/reject)
- 링크 관리: `/{id}/links` (GET/POST), `/{id}/links/{link_id}` (DELETE) — 용어집/KB/DbSphere 연결

> 권한은 4단계 레벨 시스템 사용 (`has_permission_min_level` + `workspace.knowledge_graph`).

## 모델 (models/knowledge_graph.py)
- `KnowledgeGraph`: KG 인스턴스 (id, user_id, name, description, data, meta, access_control)
- `KGNode`, `KGEdge`: 노드/엣지 메타 (AGE와 병행 — 검색/조회 용도)
- `KGKnowledgeLink`: KG↔(Glossary|KB|DbSphere) 연결 (link_id 단위)
- `KGCandidate`: KB 추출 후보 (accept/reject 대기)
- `KGExtractJob`, `KGExtractState`: 백그라운드 작업 상태
- `KGAgePending`: AGE 쓰기 실패 재시도 큐
- 상수: `NodeType`, `EdgeType`, `EdgeSource`, `CandidateStatus`, `JobKind`, `JobStatus`, `LinkSourceType`, `LinkTargetType`

## Extension Module (extension_modules/knowledge_graph/)
- `service.py`: `KGService` — 통계 갱신/동기화 cross-cutting 래퍼
- `age_service.py`: `AGEService` — psycopg2로 AGE Cypher 직접 실행 (SQLAlchemy와 분리)
- `index_service.py`: `KGNodeIndexService` — 검색 엔진 기반 노드 임베딩/검색
- `edge_type_recommender.py`: 링크 컨텍스트 → LLM으로 엣지 타입 카탈로그 추천 (INTRA/CROSS/MERGE)
- `tools.py`: UnifiedAgent에 노출되는 LangChain 도구 (`kg_resolve_term`, `kg_search_concepts`, `kg_neighbors`, `kg_find_related_tables`, `kg_explore_context`, `kg_search_documents`, `kg_fetch_data`, `kg_fetch_document`)
- `source_sync_worker.py`: 용어집 sync fan-out 워커 (`kg_glossary_sync` / `kg_dbsphere_sync_one` / `kg_glossary_entries_chunk` / `kg_kb_match_file`)
- `kb_chunk_worker.py`: KB 청크 단위 엔티티 추출 워커 (`kg_kb_chunk` + parent job finalization)
- `sync/`: 동기화 로직 — `glossary_sync`, `dbsphere_sync`, `kb_sync`, `db_derivation`, `_kb_hierarchy`, `_age_helpers`, `_node_ids`

## 백그라운드 워커 패턴
- Redis Streams 기반 내부 consumer — 외부 워커 프로세스 제거됨
- parent job + fan-out child tasks + counter 방식으로 진행률 추적
- `increment_job_progress` → Socket.IO `kg-job-progress` 이벤트
- 마지막 child 완료 시 `try_claim_job_finalization` → finalize (stats + 부분 재인덱싱 + `kg-job-completed`)
- Watchdog: `kg_job_watchdog()` — sync/candidate_extract는 5분, kb_extract는 2시간 타임아웃

## KG 도구 (UnifiedAgent 통합)
- **kg_resolve_term**: 비즈니스 용어 → 컬럼/테이블 매핑 (NL-to-SQL 정확도 핵심)
- **kg_search_concepts**: 시맨틱 노드 검색 (검색 엔진 필요)
- **kg_neighbors**: 1~N hop 이웃 트래버설
- **kg_find_related_tables**: FK 연결된 테이블 발견 (JOIN 후보)
- **kg_explore_context**: 노드 주변 맥락 요약
- **kg_search_documents**: KB 문서 검색
- **kg_fetch_data**: DB에서 실제 데이터 조회 (SQL 실행)
- **kg_fetch_document**: 특정 문서 본문 반환

> KG-only 에이전트에서는 KbSphere/DbSphere 독립 도구가 활성화되지 않아야 함 — KG 연결 리소스는 KG 도구가 내부적으로만 접근.

## 프론트엔드
- 워크스페이스 경로: `/workspace/knowledge-graph`
- 주요 페이지: 목록 / `[id]/+page.svelte` (시각화 + 노드/엣지 관리 + 추출 후보 리뷰)
- API 클라이언트: `src/lib/apis/knowledge-graph/index.ts`
- 진행률 알림: 우측 상단 Toast 이력 센터(ToastHistory)에 Socket.IO `kg-job-progress` / `kg-job-completed` 수렴

## 참조 파일
- `routers/knowledge_graph.py`: 46 엔드포인트
- `models/knowledge_graph.py`: 테이블/Pydantic 모델 + 상수
- `extension_modules/knowledge_graph/service.py`: KGService
- `extension_modules/knowledge_graph/age_service.py`: AGE Cypher 실행
- `extension_modules/knowledge_graph/tools.py`: UnifiedAgent KG 도구
- `extension_modules/knowledge_graph/sync/`: 동기화 구현

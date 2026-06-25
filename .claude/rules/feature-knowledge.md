---
paths:
  - "backend/open_webui/routers/knowledge.py"
  - "backend/open_webui/models/knowledge.py"
  - "backend/open_webui/retrieval/knowledge_service.py"
  - "src/lib/components/workspace/Knowledge/**/*.svelte"
  - "src/lib/apis/knowledge/**/*.ts"
---

# 지식베이스 관리 규칙

## 라우터 (routers/knowledge.py)
- CRUD 표준 패턴 따름 (backend-router.md 참조)
- `/create`: POST — `workspace.knowledge` 권한
- `/{id}/clone`: POST KB Deep Clone — 메타/파일/벡터 모두 독립 복제. 동기 단계는 새 KB row + clone_state="cloning" 만 만들고 즉시 응답, task_queue worker (`kb_clone`) 가 Storage 복사 + 새 File row + 새 collection 재인덱싱. caller 가 새 owner, `access_control={}` (private), 이름은 locale-aware suffix (`(Clone)` / `(복제본)`) + 충돌 시 incrementing. KG 자동 sync 안 함 (의도적 독립 단위).
- `/{id}/file/add`: POST 파일 추가 (백그라운드 처리)
- `/{id}/file/update`: POST 파일 업데이트
- `/{id}/file/remove`: POST 파일 제거 + 벡터DB 클린업
- `/reset`: POST 전체 초기화

## 모델 스키마
```python
class Knowledge(Base):
    __tablename__ = "knowledge"
    id, user_id, name, description
    data(JSON), meta(JSON), access_control(JSON)
    created_at, updated_at
```
- `data`: `{"file_ids": [...]}` — 연결된 파일 ID 목록
- 응답 계층: KnowledgeModel → KnowledgeUserModel → KnowledgeResponse (+ files) → KnowledgeUserResponse

## 벡터DB 서비스 (knowledge_service.py)
- `SearchEngineKnowledge`: search_engine 모듈 기반 knowledge 서비스
- 인덱스: `default_knowledge` 고정, `collection` 필드로 지식기반(knowledge_id) 구분
- VECTOR_DB_CLIENT 대신 사용 (retrieval.py의 save_docs_to_vector_db에서 활용)

## 파일 업로드 & 백그라운드 처리
1. 프론트엔드: `uploadFile(token, file, 'local', false)` — `process=false`로 업로드 (처리 안 함)
2. 프론트엔드: `addFileToKnowledgeById(token, id, fileId)` 호출
3. 백엔드 `add_file_to_knowledge_by_id`:
   - content 없음 → `process_file(background=True)` → `FileProcessingStatusResponse(status="processing_started")`
   - content 있음 → 동기 처리 (이미 처리된 파일)
4. 프론트엔드: toast 표시 ("파일을 처리 중입니다")
5. 백그라운드 완료 시: Socket.IO `file-processing-completed` 알림 → toast + 데이터 새로고침
6. 재방문 시: `pending_files`에서 처리 중 파일 표시

**주의**: 채팅 파일 업로드는 `process=true`(기본값)로 동기 처리해야 함.

## 프론트엔드
- `KnowledgeBase.svelte`: Fuse.js 검색, 파일 관리, AddContentMenu, 백그라운드 처리 상태
- `processingFileIds`: 처리 중인 파일 ID 추적 (Set)
- Socket.IO `notification` 이벤트 리스너: `file-processing-completed`, `file-processing-failed`
- `src/lib/apis/knowledge/index.ts`: API 클라이언트

## 참조 파일
- `routers/knowledge.py`: CRUD + 파일 관리
- `models/knowledge.py`: 모델/스키마 정의
- `routers/retrieval.py`: RAG 파이프라인, process_file (sync/background)
- `retrieval/knowledge_service.py`: SearchEngineKnowledge
- `routers/files.py`: 파일 업로드 (process 쿼리 파라미터)

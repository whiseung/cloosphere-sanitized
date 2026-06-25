# KB Search Settings — Runtime Audit

> 작성: 2026-04-28 (commit 0 사전 검증 결과)
> 브랜치: `feat/kb-filter-ux-audit`
> 입력: `dev/active/kb-filter-ux-audit/initial-issues.md` issue #8

---

## TL;DR

**12개 search settings 중 dead path 는 1개 (#9 `question_generation_model`).**
나머지 11개는 정상 작동 — Phase 1 audit 의 ❌ 5건 판단은 react agent 경로 (`tools_base.py`) 를 놓쳐서 나온 오판이었다.

| # | Param | Status | Read Site |
|---|---|---|---|
| 1 | document_profile_id | ✅ | retrieval.py:1771 (indexing) |
| 2 | enable_file_summary | ✅ | retrieval.py:2376 (indexing) |
| 3 | file_summary_model | ✅ | retrieval.py:2378 (indexing) |
| 4 | top_k | ✅ react agent | tools_base.py:468-469 |
| 5 | reranker enable | ✅ react agent | tools_base.py:459 (effective_question_vector default) |
| 6 | reranker_top_k | ✅ react agent | tools_base.py:470-473 |
| 7 | reranker_threshold | ✅ react agent | tools_base.py:474-483 |
| 8 | enable_question_generation | ✅ | retrieval.py:1659 (indexing) |
| 9 | **question_generation_model** | ❌ **dead path** | retrieval.py:1673 — `generate_chunk_questions` 호출 시 `model_id` 인자 미전달, 글로벌 `KB_QUESTION_GENERATION_MODEL` 만 사용 |
| 10 | max_questions_per_chunk | ✅ | retrieval.py:1662 (indexing) |
| 11 | question_vector_weight | ✅ react agent | tools_base.py:484-485 |
| 12 | filter_extraction_model | ✅ | task_queue.py:814 (extraction worker) |

---

## 핵심 read 경로 정리

### Indexing-time (파일 처리 시 — `routers/retrieval.py`)
- `document_profile_id`, `enable_file_summary`, `file_summary_model`, `enable_question_generation`, `max_questions_per_chunk` 모두 KB.meta.search_settings 에서 read OK
- `question_generation_model` 은 read 코드 없음 — fix 필요 (line 1673)

### Retrieval-time (chat 시 — `extension_modules/react/tools_base.py:455-485`)
```python
for kb_info in self.knowledges:
    kb = Knowledges.get_knowledge_by_id(kb_info.get("id"))
    if not kb or not kb.meta:
        continue
    ss = kb.meta.get("search_settings") or {}
    if ss.get("top_k") is not None:
        effective_top_k = max(effective_top_k, ss["top_k"])
    if ss.get("reranker_top_k") is not None:
        effective_reranker_top_k = max(
            effective_reranker_top_k, ss["reranker_top_k"]
        )
    if ss.get("reranker_threshold") is not None:
        # ... per-KB 우선, 여러 KB 면 min
    if ss.get("question_vector_weight") is not None:
        effective_question_weight = ss["question_vector_weight"]
```
→ react agent (UnifiedAgent) 가 chat 의 표준 retrieval 경로. KB.meta 정상 적용.

### `/query/collection`, `/query/doc` 직접 호출
- `routers/retrieval.py:3624, 3594` — KB.meta 미참조 (`form_data.k > config.TOP_K`)
- 이는 admin/debug endpoint. 일반 chat 경로 아님.
- **별도 조치 불필요** (사용 빈도 낮고 의도적으로 글로벌 우선)

### Filter extraction (`task_queue.py:814`)
```python
model_id = kb.meta.get("filter_extraction_model", "")
```
→ AI 모드 추출 시 KB.meta 우선. 정상.

---

## 유일한 fix 대상 — #9 `question_generation_model`

### 현재 (broken)
```python
# routers/retrieval.py:1673
sample_questions_list = await generate_chunk_questions(
    app=request.app,
    chunks=texts,
    filename=filename,
    max_questions=kb_max_questions,
    skip_enabled_check=kb_overridden,
)
```
`model_id` 인자 없음 → `question_generator.py:236` 에서 글로벌 fallback.

### Fix
```python
# Per-knowledge 모델 override
kb_question_model = None
if knowledge_id:
    kb = Knowledges.get_knowledge_by_id(knowledge_id)
    if kb and kb.meta:
        ss = kb.meta.get("search_settings") or {}
        kb_question_model = ss.get("question_generation_model") or None

sample_questions_list = await generate_chunk_questions(
    app=request.app,
    chunks=texts,
    filename=filename,
    model_id=kb_question_model,  # ← 추가
    max_questions=kb_max_questions,
    skip_enabled_check=kb_overridden,
)
```
- `None` 이면 `question_generator.py:236` 가 글로벌 fallback (기존 동작 유지)
- 명시값 있으면 per-KB 우선

기존 KB.meta override 블록 (line 1652-1663) 에 model 항목만 추가하면 됨:
```python
if ss.get("question_generation_model"):
    kb_question_model = ss["question_generation_model"]
```

### Null tolerance
- `ss.get("question_generation_model")` 가 `None / "" / 누락` 이면 → 글로벌 fallback
- PR163 의 `isFilled()` 정책과 동일

---

## filter_metadata 저장 위치 (commit 0 Task 0.1 결과)

`Knowledges.patch_knowledge_file_metadata(kb_id, file_id, delta)` (`models/knowledge.py:316`):

```
knowledge.data["file_metadata"][file_id] = {
    "f_str_<label>": <value>,
    "f_int_<label>": <int>,
    "f_date_<label>": <ISO date>,
    "f_col_<label>": [<...>],
    ...기타 키
}
```

- slot 키는 `f_str_*`, `f_int_*`, `f_date_*`, `f_col_*` 4종 prefix
- `delta` 의 slot 키 값이 `None` 이면 해당 slot 만 pop (clear)
- 비-slot 키 (예: `last_extracted_at`) 는 `None` 으로 보낼 수 없고, 명시 값으로만 덮어씀

### 벡터 인덱스 동시 갱신
`filter_extract_worker.py:158-168`:
```python
knowledge_svc = SearchEngineKnowledge(app=app, collection_name=kb_id)
slot_values = { k: v for k, v in extracted.items()
                if k.startswith(("f_str_", "f_int_", "f_date_", "f_col_")) }
if slot_values:
    await knowledge_svc.update_file_filter_slots(
        file_id=file_id, slot_values=slot_values,
    )
```
- SQL + 벡터 인덱스 동시 갱신 (slot 키만 벡터에 반영)

### Metadata-only clear 설계 (commit 4)

신규 메서드 `clear_knowledge_file_metadata(kb_id, file_id)`:

```python
def clear_knowledge_file_metadata(self, id: str, file_id: str) -> Optional[KnowledgeModel]:
    """파일의 filter slot (f_str_*, f_int_*, f_date_*, f_col_*) 만 모두 제거.
    chunk / embedding / 비-slot 키 (last_extracted_at 등) 는 보존."""
    with get_db() as db:
        knowledge = (
            db.query(Knowledge).filter_by(id=id).with_for_update().first()
        )
        if not knowledge:
            return None
        data = dict(knowledge.data) if knowledge.data else {}
        file_metadata = dict(data.get("file_metadata", {}))
        current = dict(file_metadata.get(file_id, {}))
        # slot 키만 제거
        cleared = {k: v for k, v in current.items()
                   if not k.startswith(("f_str_", "f_int_", "f_date_", "f_col_"))}
        file_metadata[file_id] = cleared
        data["file_metadata"] = file_metadata
        knowledge.data = data
        knowledge.updated_at = int(time.time())
        db.commit()
        db.refresh(knowledge)
        return KnowledgeModel.model_validate(knowledge)
```

벡터 인덱스 clear:
```python
# router 안에서, model 메서드 호출 후
slot_keys = ["f_str_*", "f_int_*", "f_date_*", "f_col_*"]  # 모든 slot
await knowledge_svc.update_file_filter_slots(
    file_id=file_id,
    slot_values={k: None for k in actual_slot_keys_present},
)
```

---

## 결론 — Plan/Commit 7 보정 사항

**commit 7 scope 대폭 축소:**
- 기존: 5개 dead path fix + feature flag
- 보정: **#9 question_generation_model 만 fix** (5줄 변경) + **`/query/collection`, `/query/doc` 보강 여부는 별도 결정**
- feature flag (`KB_META_OVERRIDES_GLOBAL`) **불필요** — 기존 react agent 경로는 이미 KB.meta 우선이고 사용자 시나리오 변경 없음
- 베타 검증 단계도 단순화 — 인덱싱 시 KB-level 모델 사용 여부만 확인

**ADO Issue 등록 (commit 8):**
- 1개 sub-issue 만 (#9). Phase 1 의 "5개 dead path" 는 잘못된 audit 으로 결론.

---

## React-agent 외 retrieval 경로 점검 (선택)

UnifiedAgent / react agent 가 아닌 retrieval 호출처:

| 호출처 | KB.meta 적용? | 조치 |
|---|---|---|
| `/query/collection` (admin/debug) | ❌ | optional — admin 전용이므로 보존 |
| `/query/doc` (admin/debug) | ❌ | 동일 |
| RetrievalSearchTool (legacy) | TBD | grep 후 결정 |
| AgentFlow KB 노드 | TBD | grep 후 결정 |

이 부분은 별도 audit cycle (다음 PR) 에서 처리 권고.

---
paths:
  - "backend/open_webui/routers/models.py"
  - "backend/open_webui/models/models.py"
  - "src/lib/components/workspace/Agents/**/*.svelte"
  - "src/lib/apis/agents/**/*.ts"
  - "src/routes/(app)/workspace/agents/**/*"
---

# 에이전트/모델 관리 규칙

## 라우터 (routers/models.py)
- `/`: GET 모델 목록 (admin=전체, user=접근 가능 항목)
- `/base`: GET 기반 모델 목록 (admin 전용)
- `/create`: POST 생성 — `workspace.agents` 권한
- `/model`: GET 단일 조회 (query param, '/' 포함 ID 지원)
- `/model/toggle`: POST 활성/비활성
- `/model/update`: POST 수정
- `/model/delete`: DELETE 삭제

## 에이전트 설정 구조
```python
{
    "id": "agent-id",
    "name": "Agent Name",
    "base_model_id": "gpt-4",  # 기반 LLM (있으면 UnifiedAgent로 라우팅)
    "params": {
        "system": "작업 프롬프트 (system)",
        "format_prompt": "답변 포멧 프롬프트 (optional)",
        "temperature": 0.7,
    },
    "meta": {
        "knowledge": [],          # 연결된 지식베이스 [{id, name, ...}]
        "dbspheres": [],          # 연결된 데이터베이스 [{id, name}]
        "knowledge_graphs": [],   # 연결된 KG [{id, name}]
        "glossaries": [],         # 연결된 용어집 [{id, name}]
        "toolConnections": [],    # 연결된 도구 [{id, name, connection}]
        "guardrails": [],         # 연결된 가드레일 [{id}]
    },
    "access_control": {...}
}
```

> `enable_kbsphere` / `enable_dbsphere` 플래그는 제거됨 (legacy). `AgentEditor.svelte` 저장 시 `delete info.params.enable_*`로 정리.

## AgentConfig (통합 설정)
- `main.py`에서 `AgentConfig.from_model_info(params, meta)` → `metadata["agent_config"]`에 주입
- 에이전트에서: `self.agent_config.get_first_dbsphere_id()`, `self.agent_config.get_knowledge_ids()`, `has_knowledge()`, `has_dbsphere()` 등
- 리소스 기반 자동 감지: 플래그 대신 `meta`의 리소스 연결 여부로 기능 활성화 판단
- 상세: `ext-react-agent.md` 참조

## 에이전트 라우팅 (openai.py / main.py)
- `model_info.base_model_id`가 있는 모든 에이전트 → **UnifiedAgent**로 라우팅
- UnifiedAgent가 내부적으로 리소스 유무에 따라 기능 자동 활성화:
  - `agent_config.has_dbsphere()` → SQL 도구 등록
  - `agent_config.has_knowledge()` → KbSphere 검색 도구 등록
  - `agent_config.knowledge_graphs` 존재 → KG 도구 등록 (kg_resolve_term, kg_search_concepts, kg_neighbors, kg_find_related_tables 등)

## 프론트엔드
- `AgentEditor.svelte`: 기능 체크박스 없음 — "작업 프롬프트" + "답변 포멧 프롬프트" 항상 표시
- knowledge/dbsphere/knowledge_graph/tool/glossary/guardrail 연결 UI (섹션별 Selector + FileItem)
- 워크스페이스 경로: `/workspace/agents`

## 참조 파일
- `routers/models.py`: 에이전트 CRUD (query param ID 패턴)
- `models/models.py`: ModelForm, ModelModel, ModelResponse
- `models/agent_config.py`: AgentConfig Pydantic 모델

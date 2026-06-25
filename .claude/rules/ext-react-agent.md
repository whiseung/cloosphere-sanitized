---
paths:
  - "backend/extension_modules/react/**/*.py"
  - "backend/extension_modules/kbsphere/**/*.py"
  - "backend/extension_modules/agent/**/*.py"
  - "backend/open_webui/models/agent_config.py"
---

# ReAct 에이전트 프레임워크 규칙

## AgentConfig (통합 에이전트 설정)
```python
from open_webui.models.agent_config import AgentConfig

# main.py에서 metadata에 주입됨
agent_config = AgentConfig.from_model_info(
    params=model_info.params.model_dump(),
    meta=model_info.meta.model_dump(),
    model_id=model_info.id,
    base_model_id=model_info.base_model_id,
)
metadata["agent_config"] = agent_config
```
- **주요 필드**: `knowledge_bases`, `dbspheres`, `knowledge_graphs`, `glossaries`, `guardrail_ids`, `tool_connections`
- **헬퍼**: `get_first_dbsphere_id()`, `get_knowledge_ids()`, `has_knowledge()`, `has_dbsphere()`
- **기능 감지**: 리소스 기반 자동 감지 (legacy `enable_kbsphere`/`enable_dbsphere` 플래그 제거됨 — 체크박스 없이 연결된 리소스 유무로 판단)
- **접근**: `self.agent_config` property (ReactAgentBase에 정의)

## ReactAgentBase(ABC)
- `agent_config` property: metadata에서 AgentConfig 추출 (캐싱, dict→인스턴스 자동 변환)
- `run()`: 메인 실행 루프
- `rewrite_question()`: 질문 정규화/재작성
- `_run_final_stream()`: 최종 스트리밍 출력

## AgentStateBase(AgentState)
```python
class AgentStateBase(AgentState):
    normalized_question: str      # 정규화된 질문
    language: str                 # 감지된 언어
    eval_score: int               # 평가 점수
    answerable: bool              # 답변 가능 여부
    attached_files: list          # 첨부 파일
```

## ReactToolsBase(ReactAgentBase)
KbSphere 기능을 제공하는 도구 기반 에이전트.
- `knowledge_handler()`: search_engine 모듈로 지식기반 검색 (hybrid_search / multi_vector_search)
- `_get_knowledge_list()`: agent_config 우선, legacy fallback
- `_get_search_engine()`: `get_configured_search_engine(app, index_config)` 사용
- `_generate_query_embedding()`: `generate_embedding_async()` 사용
- 임베딩 설정: `get_embedding_config_from_app(app)` (관리자 설정 기반)
- 인덱스: `default_knowledge` (모든 지식기반 공유), `collection` 필드로 구분

## UnifiedAgent(ReactToolsBase)
DbSphere + KbSphere + KG + 도구/메모리 결합 에이전트 (`extension_modules/agent/unified_agent.py`).
- `model_info.base_model_id`가 있는 모든 에이전트는 UnifiedAgent로 라우팅됨
- 리소스 기반 자동 감지: `agent_config.has_knowledge()`, `agent_config.has_dbsphere()`, `knowledge_graphs` 존재 여부
- DbSphere: SQL 생성/실행/시각화 도구 (`extension_modules/dbsphere/tools/`), 메모리 pre-load
- KbSphere: 지식기반 검색, 웹 검색 (on-demand)
- KG: `kg_resolve_term`, `kg_search_concepts`, `kg_neighbors`, `kg_find_related_tables`, `kg_explore_context`, `kg_search_documents`, `kg_fetch_data`, `kg_fetch_document` (`extension_modules/knowledge_graph/tools.py`)
- 도구 연결: `tool_connection_tools.py` + `code_interpreter_tool.py` + `image_tool.py` + `ui_action_tools.py`
- State: `UnifiedAgentState(AgentStateBase)` — 양쪽 필드 통합

## 메모리/압축 유틸 (`extension_modules/agent/`)
- `memory_extractor.py`: 대화에서 장기 기억 엔티티 추출
- `memory_consolidator.py`: 중복/유사 기억 병합
- `memory_retention_worker.py`: 보존 기간 정책 적용 (data_retention 연동)
- `memory_tools.py`: UnifiedAgent용 메모리 CRUD 도구
- `message_compressor.py`: 긴 대화 이력 압축 (context window 관리)

## MiddlewareBase
- 계층적 트레이싱: `1`, `1.1`, `1.1.1` 점 표기법
- `_run_stack`: 실행 스택 추적
- usage 추적, 이벤트 발행
- `openai_chat_chunk_message_template` 사용 (SSE 스트리밍)

## 설정 접근 패턴
```python
# 새 패턴 (권장)
if self.agent_config:
    dbsphere_id = self.agent_config.get_first_dbsphere_id()
    knowledge_ids = self.agent_config.get_knowledge_ids()

# Legacy fallback (하위 호환)
model_info = self.metadata.get("model", {})
meta = model_info.get("info", {}).get("meta", {})
dbspheres = meta.get("dbspheres", [])
```

## 참조 파일
- `react/react_base.py`: AgentStateBase, ReactAgentBase, agent_config property
- `react/tools_base.py`: ReactToolsBase, knowledge_handler, search_engine 연동
- `react/react_middleware_base.py`: MiddlewareBase, 트레이싱
- `agent/unified_agent.py`: UnifiedAgent
- `agent/unified_state.py`: UnifiedAgentState
- `agent/prompts.py`: 통합 시스템/최종 답변 프롬프트
- `agent/memory_*.py`, `message_compressor.py`: 메모리/압축 유틸
- `models/agent_config.py`: AgentConfig Pydantic 모델

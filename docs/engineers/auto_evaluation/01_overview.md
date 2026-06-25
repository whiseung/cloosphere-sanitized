# Auto Evaluation (자동 평가) 개요

`auto_evaluation`은 LLM-as-a-Judge 방식으로 모델/에이전트 응답을 자동으로 평가하는 시스템입니다. 품질 모니터링, 성능 분석, 지속적 개선을 위한 데이터를 제공합니다.

## 주요 목적

- **응답 품질 모니터링**: 모델/에이전트 응답의 품질을 자동으로 평가
- **RAG 품질 측정**: 검색 품질(Retrieval) 및 충실도(Faithfulness) 평가
- **성능 분석**: 모델별, 평가 유형별 통계 및 트렌드 분석
- **데이터 기반 개선**: 평가 결과를 바탕으로 프롬프트/설정 최적화

## 구현 범위 (Phase 1)

```
[Phase 1 - 구현 완료]
├── DB 모델 + Alembic 마이그레이션
├── 백엔드 API (CRUD, 통계, 내보내기)
├── 에이전트 설정 UI (샘플링, 평가 유형, 심사 모델)
└── 관리자 결과 조회 UI (필터, 상세, 페이지네이션)

[Phase 2 - 향후 구현]
└── 평가 실행 로직 (middleware 통합, Judge 호출)
```

## 평가 유형

| 유형 | 설명 |
|------|------|
| `retrieval` | RAG 검색 품질 - 검색된 문서의 관련성 평가 |
| `faithfulness` | 충실도 - 응답이 검색된 컨텍스트에 충실한지 평가 |
| `quality` | 응답 품질 - 유용성, 정확성, 완성도 종합 평가 |

## 주요 구성 요소

### 백엔드

- **`models/auto_evaluations.py`**: SQLAlchemy DB 모델 및 Pydantic 스키마
- **`routers/auto_evaluations.py`**: REST API 엔드포인트
- **`migrations/versions/e5f6a7b8c9d0_*`**: Alembic 마이그레이션

### 프론트엔드

- **에이전트 설정**: `components/workspace/Agents/AutoEvaluation.svelte`
- **결과 조회**: `components/admin/Evaluations/AutoResults.svelte`
- **상세 모달**: `components/admin/Evaluations/AutoResultDetail.svelte`
- **API 클라이언트**: `apis/auto-evaluations/index.ts`

## 기술 스택

- **Framework**: FastAPI (Python), SvelteKit (Frontend)
- **Database**: SQLAlchemy (PostgreSQL/SQLite)
- **LLM**: Azure OpenAI / OpenAI (Judge Model)
- **UI Components**: bits-ui DropdownMenu, Pagination

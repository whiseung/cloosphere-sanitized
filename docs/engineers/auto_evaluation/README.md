> Last Updated: 2026-04-08

# Auto Evaluation (자동 평가)

LLM-as-a-Judge 방식으로 모델/에이전트 응답을 자동으로 평가하는 시스템입니다.

## 문서 목록

1. [개요](./01_overview.md) - 자동 평가 시스템 소개
2. [아키텍처](./02_architecture.md) - 데이터 모델 및 통계 쿼리
3. [API](./03_api.md) - REST API 엔드포인트 (10개)
4. [프론트엔드](./04_frontend.md) - UI 컴포넌트
5. [설정](./05_configuration.md) - 라이선스, retention, 환경 변수

## 빠른 시작

### 1. 마이그레이션 실행

```bash
cd backend
alembic upgrade head
```

### 2. 에이전트 설정

워크스페이스 > 에이전트 > 편집 > Auto Evaluation 섹션

### 3. 결과 확인

관리자 > 평가 > 평가결과 탭

## 평가 유형

| 유형 | 설명 |
|------|------|
| `retrieval` | RAG 검색 품질 평가 |
| `faithfulness` | 응답 충실도 평가 |
| `quality` | 전반적 응답 품질 평가 |

## 파일 구조

```
backend/open_webui/
├── models/auto_evaluations.py           # DB 모델
├── routers/auto_evaluations.py          # API 라우터
└── migrations/versions/
    └── e5f6a7b8c9d0_add_auto_evaluation_table.py

src/lib/
├── apis/auto-evaluations/index.ts       # API 클라이언트
├── components/
│   ├── workspace/Agents/
│   │   └── AutoEvaluation.svelte        # 설정 UI
│   └── admin/Evaluations/
│       ├── AutoResults.svelte           # 결과 목록
│       └── AutoResultDetail.svelte      # 상세 모달
└── routes/(app)/admin/evaluations/      # 페이지 (기존 활용)
```

## 구현 상태

- [x] Phase 1: DB 모델 + API + UI
- [ ] Phase 2: 평가 실행 로직 (middleware 통합)

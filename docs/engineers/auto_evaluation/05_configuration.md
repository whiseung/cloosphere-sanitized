> Last Updated: 2026-04-08

# 05. Auto Evaluation 설정

## 1. License Feature Gate

| 설정 | 값 |
|---|---|
| **Feature key** | `evaluation` (`FeatureModule.EVALUATION`) |
| **Tier** | **PROFESSIONAL** 이상 |
| **Enforcement** | `require_feature("evaluation")` — 라우터 전체 |

## 2. 환경 변수

| 변수 | 기본값 | 설명 |
|---|---|---|
| `RETENTION_DAYS_AUTO_EVALUATION` | (config.py 기본값 참조) | 자동 평가 레코드 보존 기간. 만료된 레코드는 retention worker에서 자동 삭제 |

## 3. DB 스키마

테이블: `auto_evaluation` (`backend/open_webui/models/auto_evaluations.py`)

### Indexes

실제 인덱스 5개:
- PK (`id`)
- `user_id`
- `chat_id`
- `message_id`
- `created_at`

## 4. 프론트엔드 연동

### 컴포넌트 계층

```
src/lib/components/admin/Evaluations.svelte                    # 부모 (탭 스위칭)
└── src/lib/components/admin/Evaluations/
    ├── AutoEvaluations.svelte                                  # 자동 평가 탭
    └── (기타 평가 관련 탭들)

src/lib/components/workspace/Agents/AutoEvaluation.svelte      # Agent 편집기의 자동 평가 설정 섹션
```

- `admin/Evaluations.svelte`는 탭 스위칭 부모 컴포넌트 (자동 평가 / 수동 평가 / 설정 등 분리)
- `admin/Evaluations/AutoEvaluations.svelte`는 실제 목록/필터/차트 표시
- `workspace/Agents/AutoEvaluation.svelte`는 Agent 편집 화면에서 평가 활성화 설정

## 5. 의존성

- Judge LLM: 평가 실행에 사용되는 LLM. `AutoEvaluationForm.judge_model_id`로 지정
- Retention Worker: `extension_modules/agent/memory_retention_worker.py`와 동일한 패턴으로 구현 가능 (또는 통합됨)
- Audit Log: 평가 생성/삭제 시 공통 `audit_log` 테이블에 기록

## 6. 트러블슈팅

| 증상 | 원인 | 해결 |
|---|---|---|
| 403 on endpoints | License feature `evaluation` 비활성 | PROFESSIONAL 이상 license 등록 |
| 평가 생성 시 LLM 호출 실패 | `judge_model_id`가 존재하지 않거나 접근 불가 | Model ID 재확인, 해당 모델이 active 상태인지 확인 |
| 응답에 user 정보 없음 | `/{id}` GET이 아닌 `/{id}/simple` 등 구 경로 사용 | `GET /{id}` (response_model=`AutoEvaluationWithUserResponse`) 사용 |
| 대량 삭제 응답 느림 | `DELETE /` (bulk) 시 vector search sync까지 포함 | 작은 배치로 분할 또는 직접 DB 정리 |

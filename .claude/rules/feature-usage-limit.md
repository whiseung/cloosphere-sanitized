---
paths:
  - "backend/open_webui/utils/usage_limit.py"
  - "backend/open_webui/models/usage.py"
  - "backend/open_webui/routers/users.py"
  - "backend/open_webui/routers/groups.py"
  - "backend/open_webui/routers/organizations.py"
  - "backend/open_webui/routers/models.py"
  - "src/lib/components/common/TokenInput.svelte"
  - "src/lib/components/admin/Settings/Models.svelte"
  - "src/lib/components/admin/Settings/Models/UsageLimitModal.svelte"
  - "src/lib/components/admin/Settings/Models/OverrideManagerModal.svelte"
---

# 사용량 제한(Usage Limit) 규칙 — Per-Model

토큰 한도는 **Model 행 단위 (base LLM + 워크스페이스 agent 동일 취급)** 로 키잉.
모든 한도 관리는 **관리자 > 설정 > 모델** 페이지로 통합.

## 데이터 모델

| 위치 | JSON 경로 | 의미 |
|------|-----------|------|
| `config` 테이블 | `usage_limit.default_daily_tokens` | 모든 모델 fallback (전역) |
| `config` 테이블 | `usage_limit.per_model.{model_id}` | 모델별 base 한도 (전역) |
| `user.info` | `usage_limit.per_model.{model_id}` | 사용자 per-model override |
| `group.meta` | `usage_limit.per_model.{model_id}` | 그룹 per-model override |
| `organizational_unit.meta` | `usage_limit.per_model.{model_id}` | 조직 단위 per-model override |

값 의미:
- `null`/키 없음 = 상속 (상위 계층 값 사용)
- `0` = 명시적 무제한 (즉시 반환)
- 양수 = 일일 토큰 한도

> **legacy `usage_limit.daily_tokens`** (사용자/그룹/조직 단일 한도) 는 `f0e1d2c3b4a5`
> 마이그레이션에서 폐기되었음. 신규 시스템에서 재설정 필요.

## API 엔드포인트

### routers/users.py
| 메서드 | 경로 | 권한 | 설명 |
|--------|------|------|------|
| GET | `/user/usage-limit/check?model_id=...` | 인증됨 | 현재 사용자 한도 실시간 체크 (모델별) |
| GET | `/{user_id}/usage-limit` | admin (read) | 사용자 per_model 조회 (`{per_model: {...}, daily_used}`) |
| POST | `/{user_id}/usage-limit` | admin (write) | 사용자 per_model 변경 (`body: {per_model: {model_id: tokens}}`) |

### routers/groups.py
| 메서드 | 경로 | 권한 |
|--------|------|------|
| GET/POST | `/id/{id}/usage-limit` | admin |

### routers/organizations.py
| 메서드 | 경로 | 권한 |
|--------|------|------|
| GET/POST | `/units/{id}/usage-limit` | admin |

### routers/models.py (모델별 오버라이드 집계)
| 메서드 | 경로 | 응답 |
|--------|------|------|
| GET | `/usage-limit/overrides/counts?id={model_id}` | `{users, groups, org_units}` 카운트 |
| GET | `/usage-limit/overrides/list?id={model_id}&tier={users\|groups\|org_units}&q=&skip=&limit=` | `OverrideEntry[]` |

## 핵심 로직 (utils/usage_limit.py)

### `get_effective_daily_limit_for_model(request, user_id, model_id) → (limit, source)`
주어진 모델에 대해 4계층 후보 중 **max(가장 관대한 값)** 적용:
1. 전역: `config.usage_limit.per_model[M]` ?? `config.usage_limit.default_daily_tokens`
2. 사용자: `user.info.usage_limit.per_model[M]` (없으면 후보 안 넣음)
3. 그룹: `group.meta.usage_limit.per_model[M]`
4. 조직 단위: `org_unit.meta.usage_limit.per_model[M]`

> **정책 의도**: per-model override 는 "**더 큰 한도 부여(boost)**" 용도. premium 사용자/그룹에게 한도를 늘려주는 슬롯이며, "특정 사용자만 더 빡빡하게 제한" 시나리오는 본 시스템 범위 밖 (별도 tighten 모드 도입 필요).

### `check_quota_for_model_row(request, user_id, model_row) → UsageLimitResult`
단일 Model 행 게이트 (base/agent 분기 없는 통합 함수):
- agent 행 (`base_model_id` non-null): `log_usage` 에서 `agent_id == row.id` 합계
- base 행: `model_id == row.id` 합계 (모든 호출 sum — agent 경유 + 직접)

### `enforce_usage_limit(request, user_id, user_role, called_model_id) → UsageLimitResult`
호출 진입점. **agent 호출이면 base 행만**, 그 외엔 호출 행만 게이트 체크 (단일 행).

> **정책 의도**: agent 호출도 `model_id=base` 로 카운팅되므로 base 한도 하나로
> agent 경유 + 직접 호출을 모두 한 풀로 게이트 가능. agent 행에 등록된
> per-model 한도는 chat enforce 대상에서 제외 (사용자에게 한 번의 메시지만
> 노출, agent vs base 중복 차단 방지). agent row 의 한도 등록 UI 자체는
> 운영 관점 표기/감사 용으로 남아 있을 수 있으나 chat 게이트엔 영향 없음.

```python
# 사용 (routers/openai.py)
from open_webui.utils.usage_limit import enforce_usage_limit
result = enforce_usage_limit(request, user.id, user.role, model_id)
if not result.allowed:
    raise HTTPException(status_code=429, detail=result.message)
```

## Config 설정 (config.py)
```python
ENABLE_USAGE_LIMIT = PersistentConfig(...)              # bool
USAGE_LIMIT_DEFAULT_DAILY_TOKENS = PersistentConfig(...)  # int (모든 모델 fallback)
USAGE_LIMIT_EXCEED_ACTION = PersistentConfig(...)        # "warn" | "block"
USAGE_LIMIT_PER_MODEL = PersistentConfig(...)            # dict[str, int] (모델별 base)
```

## 일일 리셋 기준
- **KST 자정** (`Asia/Seoul`, UTC+9) — `models/usage.py:get_today_start_ts()`
- 매일 한국 시간 00:00 에 일일 카운터 리셋 (= UTC 15:00 전일)
- UTC 기준이면 한국 사용자가 KST 00:00~09:00 사이에 어제 사용분이 그대로 잡혀
  사용률이 리셋 안 된 것처럼 보이는 문제 회피
- week/month 는 rolling window (now - N\*86400) — 타임존 영향 없음

## 카운터 (models/usage.py)

```python
Usages.get_user_daily_token_usage(user_id)                       # 모델 무관 합계
Usages.get_user_daily_token_usage_for_model_row(
    user_id, model, message_types=USER_QUOTA_MESSAGE_TYPES,      # ← 사용자 quota 경로 필수
)
```

### `USER_QUOTA_MESSAGE_TYPES`
사용자 일일 한도 카운트 대상 화이트리스트 (의도적 사용). 현재 포함: `chat`,
`generation`, `agent_state`, `reasoning`, `tool_call`, `function_calling`,
`image_generation`, `code_gateway`, `moa_response_generation`, `embedding`.

명시 제외: `title_generation`, `tags_generation`, `emoji_generation`,
`query_generation`, `image_prompt_generation`, `autocomplete_generation`, `system`.

→ 자동 title/tags/emoji 등 백그라운드 task 가 사용자 quota 를 잠식하지 않음.

**필수 호출 위치** (사용자 한도 의미를 가진 카운터 사용처):
- `utils/usage_limit.check_quota_for_model_row` — 채팅 게이트
- `routers/users.py /usage-by-model` — 사용자 정보 Usage 탭
- `routers/models.py _gather_user_overrides` — 모델 예외 등록 모달의 `used_today`

**미호출 위치** (운영 모니터링 — 전체 보임):
- `routers/usage.py` 전체 — 관리자 모니터링 탭은 message_type 필터 없이
  모든 호출 포함 (운영 관점 전체 가시성 유지).

## 프론트엔드 (Chat.svelte 한도 초과 토스트)
| 사용량 | 동작 |
|--------|------|
| 80%+   | 경고 토스트 |
| 95%+   | 오류 토스트 ("곧 한도 도달") |
| 100%+ (warn)  | 오류 토스트 ("관리자에게 문의") |
| 100%+ (block) | 요청 차단 ("내일 다시 시도") |

## TokenInput.svelte (공용)
- 천단위 콤마 자동 포맷 (`1234567` → `1,234,567`)
- Props: `value`, `placeholder`, `disabled`
- 빈 값 = `null` (상속), `0` = 명시적 무제한

## 설정 UI 위치 (모두 관리자 > 설정 > 모델 페이지로 통합)
- **전역 토글/기본값/초과동작**: `[Token Limit]` 헤더 버튼 → `UsageLimitModal.svelte`
- **모델별 base 한도**: 모델 행 chevron 펼침 → 인라인 TokenInput
- **사용자/그룹/조직 오버라이드**: 모델 행 accordion → `[관리]` 버튼 → `OverrideManagerModal.svelte`
  - 검색 + 페이징 + 행마다 TokenInput + 추가 picker

> 기존 4곳 (Settings/General, EditUserModal, EditGroupModal, Organizations Unit 모달) 의 토큰 한도 UI 는 모두 제거됨 (per-model 통합 후).

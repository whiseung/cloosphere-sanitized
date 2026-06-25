> Last Updated: 2026-04-08

# License (라이선스 기반 기능 제어) 모듈

Cloosphere의 라이선스 발급 및 기능 게이팅(Feature Gating) 시스템 기술 문서입니다.

> **문서 구조 참고**: 이 폴더는 토픽 기반 네이밍 (`01_architecture`, `02_feature_control`, `03_backend`, `04_frontend`, `05_adding_new_feature`)을 사용합니다. 일반 `01_overview / 02_architecture / ...` 구조보다 주제 분리가 더 적합합니다.

## 목차

1. [개요](#개요)
2. [상세 문서](#상세-문서)
3. [퀵 레퍼런스](#퀵-레퍼런스)

---

## 개요

Cloosphere 라이선스 시스템은 **오프라인 JWT RS256** 방식으로 동작합니다.
클루커스가 private key로 JWT를 발급하고, 고객 환경이 내장된 public key로 검증합니다.
외부 서버 통신이 전혀 없으므로 폐쇄망 환경에서도 동작합니다.

### 핵심 개념

| 개념 | 설명 |
|------|------|
| **License Key** | 티어(Basic/Standard/Professional/Enterprise/Developer)를 부여하는 JWT |
| **Feature Key** | 개별 모듈을 추가 활성화하는 JWT |
| **Tier** | 라이선스 등급. 티어에 포함된 모듈 전체를 허용 |
| **Module** | 기능 단위 식별자 (예: `kbsphere`, `dbsphere`) |
| **Enforcement** | 라이선스 검사 활성화 여부. OFF면 모든 기능 허용 |
| **has_all_features** | ENTERPRISE/DEVELOPER tier가 자동 활성화하는 플래그 — 현재 및 **미래 추가 모듈까지 자동 포함** |

### 티어 등급 (5단계)

`LicenseTier` enum (`backend/open_webui/utils/license.py`):

| Tier | Priority | 설명 |
|---|---|---|
| `basic` | 1 | 기본 (license 없음 또는 만료 시 fallback). 모듈 없음 |
| `standard` | 2 | 기본 워크스페이스 기능 6개 모듈 |
| `professional` | 3 | standard + 고급 기능 5개 |
| `enterprise` | 4 | **모든 현재 모듈 + 향후 추가 모듈 자동 포함** (`has_all_features=True`) |
| `developer` | 5 | Cloocus 내부 개발자 전용. ENTERPRISE와 동일하게 모든 모듈 자동 포함 |

`TIER_ALL_FEATURES_THRESHOLD = 4` (ENTERPRISE 이상) — 이 priority 이상은 `has_all_features=True`.

### 모듈 목록 (13개)

`FeatureModule` enum에 정의된 **13개 기능 모듈**. 티어별 포함 관계는 `TIER_INCLUDED_MODULES` 딕셔너리에서 관리.

| module_id | 티어 | 기능 | 비고 |
|-----------|---|------|---|
| `audit_log` | STANDARD | 감사 로그 | |
| `glossary` | STANDARD | 용어집 | |
| `guardrail` | STANDARD | 가드레일 (PII, 콘텐츠 필터) | |
| `image_generation` | STANDARD | 이미지 생성 | |
| `kbsphere` | STANDARD | 지식베이스 (KbSphere) | |
| `tools` | STANDARD | 도구 | |
| `agent_flow` | PROFESSIONAL | 에이전트 플로우 | |
| `branding` | PROFESSIONAL | 브랜딩 커스터마이징 | |
| `dbsphere` | PROFESSIONAL | 데이터베이스 (DbSphere) | |
| `evaluation` | PROFESSIONAL | 자동 평가 | |
| `trace` | PROFESSIONAL | 트레이싱 | |
| `code_gateway` | **ENTERPRISE 전용** | 코드 게이트웨이 | `TIER_INCLUDED_MODULES`에 명시적으로 없음 — `has_all_features=True` 적용 (line 115 코드 주석 기준) |
| `file_guardrail` | **ENTERPRISE 전용** | 파일 가드레일 | 동일 |

> **중요 — enum 주석과 실제 mapping의 차이**: `license.py::FeatureModule` enum의 line 68 주석 `# Standard tier (8개)`는 enum 멤버 8개를 가리킬 뿐 실제 **티어 배정**과 무관합니다. 실제 배정은 `TIER_INCLUDED_MODULES` 딕셔너리에서 이루어지며, `CODE_GATEWAY`와 `FILE_GUARDRAIL`은 STANDARD에도 PROFESSIONAL에도 포함되지 않습니다. Line 115 주석(`# CODE_GATEWAY, FILE_GUARDRAIL은 Enterprise 전용 (DB fallback 기준)`)이 실제 정책입니다.

### 두 개의 환경

```
┌─────────────────────────────────┐    ┌─────────────────────────────────┐
│         고객 환경               │    │      클루커스 내부 환경          │
│                                 │    │                                 │
│  - 관리자 페이지 포함 전체 기능  │    │  - 개발자 모드 (라이선스 발급)   │
│  - JWT public key로 오프라인 검증│    │  - CLOOCUS_ADMIN_DB 접근        │
│  - CLOOCUS_ADMIN_DB 없음        │    │  - Private key 보유              │
│  - 개발자 모드 없음             │    │                                 │
└─────────────────────────────────┘    └─────────────────────────────────┘
         ▲                                          │
         │         JWT 키 전달 (이메일 등)           │
         └──────────────────────────────────────────┘
```

---

## 상세 문서

| 문서 | 설명 |
|------|------|
| [01_architecture.md](./01_architecture.md) | 전체 아키텍처 및 JWT 흐름 |
| [02_feature_control.md](./02_feature_control.md) | 기능 제어 3단계 레이어 |
| [03_backend.md](./03_backend.md) | 백엔드 구현 상세 |
| [04_frontend.md](./04_frontend.md) | 프론트엔드 구현 상세 |
| [05_adding_new_feature.md](./05_adding_new_feature.md) | 신규 기능 게이팅 추가 가이드 |

---

## 퀵 레퍼런스

### 새 기능에 라이선스 게이팅 추가 (5단계)

```
1. license.py     → FeatureModule enum에 추가
2. license.py     → TIER_INCLUDED_MODULES에 티어 배정
3. router.py      → require_feature("module_id") 추가
4. layout.svelte  → isFeatureAllowed($config, 'module_id') 추가
5. cloocus_db.py  → seed 데이터에 추가 (클루커스 내부용)
```

### 배포에서 특정 기능 완전히 끄기

```typescript
// src/lib/config/menuConfig.ts
export const hiddenMenus: string[] = [
    'feature-id',  // 추가하면 모든 고객에게 숨겨짐
];
```

### 라이선스 검사 비활성화 (개발용)

```bash
# .env 또는 환경변수
ENABLE_LICENSE_ENFORCEMENT=false  # 기본값 - 모든 기능 허용
```

---

## 관련 파일

### Backend

- `backend/open_webui/utils/license.py` — 핵심 로직 (JWT 검증, 권한 계산)
- `backend/open_webui/routers/license.py` — 키 등록/삭제/조회 API
- `backend/open_webui/internal/cloocus_db.py` — 클루커스 내부 DB (발급 이력)
- `backend/open_webui/models/cloocus_admin.py` — 클루커스 내부 DB 모델
- `backend/open_webui/routers/cloocus.py` — 클루커스 내부 관리 API

### Frontend

- `src/lib/utils/license.ts` — `isFeatureAllowed()` 헬퍼
- `src/lib/config/menuConfig.ts` — 정적 메뉴 가시성 설정
- `src/lib/components/admin/Settings/License.svelte` — 관리자용 라이선스 등록 UI
- `src/lib/components/admin/Developer/LicenseManagement.svelte` — 클루커스 내부용 발급 UI

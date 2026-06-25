> Last Updated: 2026-04-08

# 조직(Organization) 관리 기능

Cloosphere의 조직 관리 기능에 대한 기술 문서입니다.

> **Migration**: `backend/open_webui/migrations/versions/8b1c2d3e4f5a_add_organization_tables.py` 에서 `organization`, `organizational_unit` 테이블 생성.
> **라우터 규모**: `organizations.py` **705 lines, 19 endpoints** (CRUD + tree + sync + permissions + guardrails)
> **프론트엔드**: `Organizations.svelte` **58KB** — 단일 파일로 모든 관리 UI 담당 (sync modal, tree view, member list, permission assignment)

## 목차

1. [개요](#개요)
2. [주요 기능](#주요-기능)
3. [상세 문서](#상세-문서)
4. [퀵 스타트](#퀵-스타트)

---

## 개요

조직 관리 기능은 Microsoft Entra ID (Azure AD) 등의 IdP(Identity Provider)에서 조직 구조를 가져와 Cloosphere의 접근 제어에 활용할 수 있게 해주는 기능입니다.

### 주요 개념

| 개념 | 설명 |
|------|------|
| **Organization** | 최상위 조직 (예: 회사, 테넌트) |
| **Organizational Unit** | 조직 단위 (예: 부서, 팀, Administrative Unit) |
| **Access Control** | 리소스별 접근 권한 (그룹 + 조직 단위 기반) |

### 데이터 흐름

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  Microsoft      │────▶│  Cloosphere     │────▶│  Access         │
│  Entra ID       │     │  Organization   │     │  Control        │
│  (IdP)          │     │  DB             │     │  (Resources)    │
└─────────────────┘     └─────────────────┘     └─────────────────┘
        │                       │                       │
        │  동기화               │  멤버십               │  권한
        │  (수동/자동)          │  관리                 │  체크
        ▼                       ▼                       ▼
   Administrative         User ↔ Org Unit          Knowledge
   Units, Groups,         매핑                     Tools
   Departments                                     Models 등
```

---

## 주요 기능

### 1. 조직 동기화 (3개 Provider)

- **수동 동기화**: 관리자 페이지에서 IdP를 통해 조직 구조 가져오기
  - **Microsoft Graph** (`POST /sync/msgraph`) — Entra ID / Azure AD
  - **Keycloak** (`POST /sync/keycloak`) — Keycloak realm/group 매핑 (2026-03 신규)
  - **JSON 파일** (`POST /sync/json`) — 수동 JSON 업로드 (IdP 미연동 환경용)
- **자동 동기화**: 사용자 OAuth 로그인 시 부서(department) 정보 기반 자동 배치 (`ENABLE_OAUTH_ORG_UNIT_MANAGEMENT=true`)
- **Provider 목록 조회**: `GET /sync/providers` — 사용 가능한 provider 및 설정 상태

### 2. 조직 단위 관리

- 계층 구조 트리 형태로 조직 단위 표시
- 각 조직 단위별 멤버 조회
- 조직 단위별 할당된 권한(리소스) 조회

### 3. 접근 제어 연동

- 기존 그룹(Group) 기반 접근 제어에 조직 단위(Org Unit) 추가
- `AccessControl` 컴포넌트에서 그룹과 조직 단위 동시 선택 가능
- 리소스별 `access_control.read.org_unit_ids`, `access_control.write.org_unit_ids` 필드 지원
- 조직 단위별 권한 조회: `GET /units/{unit_id}/permissions`
- 조직 단위별 guardrail 할당: `GET /units/{unit_id}/guardrails`, `POST /units/{unit_id}/guardrails`

### 4. 권한 상속

- 상위 조직 단위의 권한을 하위 조직 단위가 상속
- 권한 조회 시 상속된 권한도 함께 표시 (Inherited 표시)
- 상속 계산 로직은 `utils/access_control.py::get_user_org_units_with_ancestors()` 에서 조직 트리를 거슬러 올라가며 수집

### 5. 조직 트리 조회

- `GET /{org_id}/units/tree` — 특정 조직의 조직 단위 계층을 트리 구조 JSON으로 반환 (프론트엔드 트리 뷰용)

---

## 상세 문서

| 문서 | 설명 |
|------|------|
| [01_overview.md](./01_overview.md) | 기능 상세 설명 및 사용 시나리오 |
| [02_architecture.md](./02_architecture.md) | 데이터베이스 모델, API 구조 |
| [03_frontend.md](./03_frontend.md) | 프론트엔드 컴포넌트 및 API 클라이언트 |
| [04_oauth_sync.md](./04_oauth_sync.md) | OAuth 로그인 시 자동 조직 배치 |

---

## 퀵 스타트

### 1. 환경 변수 설정

```env
# Microsoft OAuth (필수 - Entra ID 연동)
MICROSOFT_CLIENT_ID=your-client-id
MICROSOFT_CLIENT_SECRET=your-client-secret
MICROSOFT_CLIENT_TENANT_ID=your-tenant-id
MICROSOFT_OAUTH_SCOPE=openid email profile User.Read Directory.Read.All    # 기본값은 코드 참조

# 부서 정보를 매핑할 OAuth claim (Microsoft는 "department" 기본)
OAUTH_DEPARTMENT_CLAIM=department

# 조직 자동 동기화 (선택, 기본값: true)
ENABLE_OAUTH_ORG_UNIT_MANAGEMENT=true
```

자세한 OAuth 설정: [entra_id/README.md](../entra_id/README.md) 참조

### 2. Azure AD 권한 설정

**애플리케이션 권한** (조직 동기화용):
- `Organization.Read.All`
- `User.Read.All`
- `Directory.Read.All`

> 자세한 내용은 [Entra ID 연동 가이드](../entra_id/README.md) 참조

### 3. 조직 동기화

1. 관리자 페이지 → 사용자 → 조직 탭
2. 동기화 버튼 클릭
3. Microsoft Graph 선택 후 옵션 설정
4. 동기화 실행

### 4. 리소스에 조직 단위 권한 할당

1. 워크스페이스 → 원하는 리소스 (지식, 도구 등)
2. 접근 제어 섹션에서 조직 단위 선택
3. 저장

---

## 관련 파일

### Backend
- `backend/open_webui/models/organization.py` - DB 모델
- `backend/open_webui/routers/organizations.py` - API 라우터
- `backend/open_webui/services/organization_providers/` - 동기화 Provider
- `backend/open_webui/utils/oauth.py` - OAuth 자동 동기화
- `backend/open_webui/utils/access_control.py` - 접근 제어 유틸리티

### Frontend
- `src/lib/apis/organizations/index.ts` - API 클라이언트
- `src/lib/components/admin/Users/Organizations.svelte` - 관리 페이지
- `src/lib/components/workspace/common/AccessControl.svelte` - 접근 제어 컴포넌트

> Last Updated: 2026-04-08

# Microsoft Entra ID 연동 가이드

Cloosphere에서 Microsoft Entra ID (구 Azure AD)를 연동하는 방법을 설명합니다.

## 목차

1. [개요](#개요)
2. [Azure Portal 앱 등록](#azure-portal-앱-등록)
3. [로그인 연동 (SSO)](#로그인-연동-sso)
4. [SharePoint 연동](#sharepoint-연동)
5. [조직 동기화](#조직-동기화)
6. [권한 요약표](#권한-요약표)
7. [문제 해결](#문제-해결)

---

## 개요

Cloosphere는 Microsoft Entra ID와 다음 기능들을 연동합니다:

| 기능 | 설명 | 인증 방식 |
|------|------|----------|
| **SSO 로그인** | Microsoft 계정으로 로그인 | OAuth 2.0 (위임된 권한) |
| **SharePoint 연동** | SharePoint/OneDrive 파일 첨부 | OAuth 2.0 (위임된 권한) |
| **조직 동기화** | 조직 구조 자동 가져오기 | Client Credentials (애플리케이션 권한) |

각 기능별로 필요한 **권한(Permission)**이 다르며, 일부는 **관리자 동의(Admin Consent)**가 필요합니다.

---

## Azure Portal 앱 등록

### 1. 앱 등록 생성

1. [Azure Portal](https://portal.azure.com) 접속
2. **Microsoft Entra ID** → **앱 등록** → **새 등록**
3. 앱 정보 입력:
   - **이름**: `Cloosphere` (또는 원하는 이름)
   - **지원되는 계정 유형**: 조직에 맞게 선택
     - 단일 테넌트: "이 조직 디렉터리의 계정만"
     - 멀티 테넌트: "모든 조직 디렉터리의 계정"
   - **리디렉션 URI**: `Web` → `https://your-domain.com/oauth/microsoft/callback`
4. **등록** 클릭

### 2. 클라이언트 시크릿 생성

1. 앱 등록 → **인증서 및 비밀** → **새 클라이언트 암호**
2. 설명 입력 (예: `Cloosphere Production`)
3. 만료 기간 선택 (권장: 24개월)
4. **추가** 클릭 후 **값(Value)** 복사 (한 번만 표시됨!)

### 3. 필수 정보 확인

앱 등록 **개요** 페이지에서:

| 항목 | 환경 변수 |
|------|----------|
| 애플리케이션(클라이언트) ID | `MICROSOFT_CLIENT_ID` |
| 디렉터리(테넌트) ID | `MICROSOFT_CLIENT_TENANT_ID` |
| 클라이언트 시크릿 값 | `MICROSOFT_CLIENT_SECRET` |

---

## 로그인 연동 (SSO)

Microsoft 계정으로 Cloosphere에 로그인하는 기능입니다.

### 필요한 권한

**API 권한** → **권한 추가** → **Microsoft Graph** → **위임된 권한**:

| 권한 | 설명 | 관리자 동의 |
|------|------|------------|
| `openid` | OpenID Connect 로그인 | 불필요 |
| `email` | 이메일 주소 읽기 | 불필요 |
| `profile` | 기본 프로필 읽기 | 불필요 |

> 기본 권한이므로 별도 추가 없이 사용 가능합니다.

### 환경 변수 설정

```env
# Microsoft OAuth (로그인용)
MICROSOFT_CLIENT_ID=your-client-id
MICROSOFT_CLIENT_SECRET=your-client-secret
MICROSOFT_CLIENT_TENANT_ID=your-tenant-id

# 선택: 리디렉션 URI (기본값 사용 권장)
# MICROSOFT_REDIRECT_URI=https://your-domain.com/oauth/microsoft/callback

# OAuth scope (필수 — 조직 자동 동기화를 쓰려면 User.Read + Directory.Read.All 추가)
MICROSOFT_OAUTH_SCOPE="openid email profile User.Read"

# OAuth 로그인 시 부서 매핑에 사용할 claim (Microsoft Graph 기본: "department")
OAUTH_DEPARTMENT_CLAIM=department

# 조직 자동 동기화 (사용자 로그인 시 department → OrganizationalUnit 자동 배치)
ENABLE_OAUTH_ORG_UNIT_MANAGEMENT=true
```

### `MICROSOFT_OAUTH_SCOPE` 설명

`config.py::MICROSOFT_OAUTH_SCOPE`로 관리되는 PersistentConfig. 기본 scope는 `openid email profile User.Read` 이며, 조직 자동 동기화까지 활용하려면 `Directory.Read.All`을 추가해야 합니다. Admin Portal의 Settings → Auth 화면에서도 변경 가능.

### Microsoft Graph 호출 시 사용되는 `$select` 필드

`backend/open_webui/utils/oauth.py::OAuthManager`가 Microsoft Graph API `/me` 호출 시 다음 필드를 명시적으로 요청합니다:

```
$select=id,displayName,jobTitle,department,companyName,officeLocation
```

- `department` → `OAUTH_DEPARTMENT_CLAIM`과 매핑되어 `OrganizationalUnit` 자동 배치에 사용
- 나머지 필드는 `User` 모델의 프로필 정보로 저장

**주의**: `department` 필드는 Azure Portal에서 사용자에게 명시적으로 설정되어 있어야 합니다. 설정되지 않은 사용자는 자동 배치 대상에서 제외됩니다 (조직 없음 상태).

### 로그인 시 조직 자동 동기화 흐름

```
사용자 OAuth 로그인 (Microsoft 콜백)
  │
  ▼
OAuthManager.handle_callback(request)
  ├─▶ access_token 교환
  ├─▶ GET https://graph.microsoft.com/v1.0/me?$select=id,displayName,jobTitle,department,...
  │     → user_info (department 포함)
  │
  ├─▶ User 생성 또는 업데이트 (기본 프로필)
  │
  └─▶ if ENABLE_OAUTH_ORG_UNIT_MANAGEMENT == True:
        update_user_org_units(user_id, user_info)
          │
          ├─▶ department_claim = user_info[OAUTH_DEPARTMENT_CLAIM]
          ├─▶ OrganizationalUnit을 이름으로 조회 (없으면 조직 root에 자동 생성)
          └─▶ User ↔ OrganizationalUnit 매핑 upsert
```

이 흐름은 **별도 수동 sync를 호출하지 않아도** 사용자 로그인 시점에 실시간으로 동작합니다. `POST /sync/msgraph`는 "모든 Entra 사용자를 한 번에 가져오기" 용도로 별도입니다 (로그인 전 사전 미러링).

### 리디렉션 URI 설정

Azure Portal에서 **인증** → **플랫폼 구성** → **웹**:

```
https://your-domain.com/oauth/microsoft/callback
```

개발 환경:
```
http://localhost:5173/oauth/microsoft/callback
http://localhost:8080/oauth/microsoft/callback
```

---

## SharePoint 연동

채팅에서 SharePoint/OneDrive 파일을 첨부하는 기능입니다.

### 필요한 권한

**API 권한** → **권한 추가** → **Microsoft Graph** → **위임된 권한**:

| 권한 | 설명 | 관리자 동의 |
|------|------|------------|
| `Sites.Read.All` | 모든 사이트 읽기 | **필요** |
| `Files.Read.All` | 모든 파일 읽기 | **필요** |
| `User.Read` | 로그인한 사용자 프로필 | 불필요 |

> ⚠️ `Sites.Read.All`, `Files.Read.All`은 **관리자 동의**가 필요합니다.

### 관리자 동의 허용

1. **API 권한** 페이지에서 권한 추가 후
2. **"(테넌트명)에 대한 관리자 동의 허용"** 버튼 클릭
3. 권한 상태가 "허용됨"으로 변경되었는지 확인

### 환경 변수 설정 — Dual-Naming 주의

SharePoint 설정은 **PersistentConfig 이름(SHAREPOINT_*)과 env var 소스 이름(ONEDRIVE_*)이 다릅니다.** `.env` 파일에는 `ONEDRIVE_*` 이름을 써야 하고, Admin UI의 Settings → Integrations 화면에서는 `SHAREPOINT_*`로 표시됩니다.

```env
# SharePoint 연동 (env 파일에서는 ONEDRIVE_* 이름 사용)
ENABLE_SHAREPOINT_INTEGRATION=true
ONEDRIVE_CLIENT_ID_BUSINESS=your-client-id          # → PersistentConfig "SHAREPOINT_CLIENT_ID"
ONEDRIVE_SHAREPOINT_TENANT_ID=your-tenant-id        # → PersistentConfig "SHAREPOINT_TENANT_ID"
ONEDRIVE_SHAREPOINT_URL=https://your-company.sharepoint.com/sites/your-site  # → PersistentConfig "SHAREPOINT_SITE_URL"
```

| `.env` (env var 소스) | PersistentConfig (DB/Admin UI) | `config.py` 위치 |
|---|---|---|
| `ENABLE_SHAREPOINT_INTEGRATION` | `ENABLE_SHAREPOINT_INTEGRATION` | line 2613 |
| `ONEDRIVE_CLIENT_ID_BUSINESS` | `SHAREPOINT_CLIENT_ID` | line 2619 |
| `ONEDRIVE_SHAREPOINT_TENANT_ID` | `SHAREPOINT_TENANT_ID` | line 2625 |
| `ONEDRIVE_SHAREPOINT_URL` | `SHAREPOINT_SITE_URL` | line 2631 |

**왜 다른가**: SharePoint 통합은 원래 OneDrive 통합의 하위 기능으로 구현되었고, env var 이름은 호환성을 위해 유지된 반면 PersistentConfig는 기능 단위로 `SHAREPOINT_*`로 명명되었습니다. 향후 통합 예정 (uniform naming).

별도 `ONEDRIVE_CLIENT_ID` env var도 있으며, 이는 개인용 OneDrive (business 아님) 통합에 사용됩니다 (`ENABLE_ONEDRIVE_INTEGRATION`, line 2600).

---

## 조직 동기화

Microsoft Entra ID의 조직 구조를 Cloosphere로 가져오는 기능입니다.

### 인증 방식

조직 동기화는 **사용자 로그인 없이** 백그라운드에서 실행되므로, **애플리케이션 권한(Application Permissions)**이 필요합니다.

> ⚠️ **중요**: 위임된 권한(Delegated Permissions)이 아닌 **애플리케이션 권한**을 추가해야 합니다!

### 필요한 권한

**API 권한** → **권한 추가** → **Microsoft Graph** → **애플리케이션 권한**:

| 권한 | 설명 | 용도 |
|------|------|------|
| `Organization.Read.All` | 조직 정보 읽기 | 테넌트/조직 정보 |
| `User.Read.All` | 모든 사용자 읽기 | 부서(Department) 동기화 |
| `Directory.Read.All` | 디렉터리 읽기 | Administrative Units, 그룹 동기화 |
| `GroupMember.Read.All` | 그룹 멤버 읽기 | 그룹 멤버십 동기화 (선택) |

### 관리자 동의 허용

**애플리케이션 권한은 반드시 관리자 동의가 필요합니다:**

1. **API 권한** 페이지에서 위 권한들 추가
2. **"(테넌트명)에 대한 관리자 동의 허용"** 버튼 클릭
3. 모든 권한의 상태가 "허용됨"인지 확인

### 환경 변수 설정

로그인 연동과 동일한 환경 변수를 사용합니다:

```env
MICROSOFT_CLIENT_ID=your-client-id
MICROSOFT_CLIENT_SECRET=your-client-secret
MICROSOFT_CLIENT_TENANT_ID=your-tenant-id
```

### 동기화 옵션

관리자 페이지 → 사용자 → 조직 → 동기화에서:

| 옵션 | 설명 | 권장 |
|------|------|------|
| **Administrative Units** | Entra ID의 관리 단위 가져오기 | Azure에서 설정한 경우 |
| **Security Groups** | 보안 그룹을 조직 단위로 활용 | 그룹 기반 조직인 경우 |
| **Departments** | 사용자 프로필의 부서 필드 추출 | ✅ 대부분의 경우 권장 |

---

## 권한 요약표

### 위임된 권한 (Delegated Permissions)

사용자가 로그인한 상태에서 사용자 대신 작업 수행:

| 권한 | 로그인 | SharePoint | 관리자 동의 |
|------|:------:|:----------:|:----------:|
| `openid` | ✅ | | 불필요 |
| `email` | ✅ | | 불필요 |
| `profile` | ✅ | | 불필요 |
| `User.Read` | | ✅ | 불필요 |
| `Sites.Read.All` | | ✅ | **필요** |
| `Files.Read.All` | | ✅ | **필요** |

### 애플리케이션 권한 (Application Permissions)

앱이 사용자 없이 직접 API 호출 (백그라운드 작업):

| 권한 | 조직 동기화 | 관리자 동의 |
|------|:----------:|:----------:|
| `Organization.Read.All` | ✅ | **필요** |
| `User.Read.All` | ✅ | **필요** |
| `Directory.Read.All` | ✅ | **필요** |
| `GroupMember.Read.All` | 선택 | **필요** |

---

## 문제 해결

### 403 Authorization_RequestDenied

```
MS Graph API error: 403 - {"error":{"code":"Authorization_RequestDenied",
"message":"Insufficient privileges to complete the operation."}}
```

**원인**: 필요한 권한이 없거나 관리자 동의가 되지 않음

**해결**:
1. Azure Portal에서 필요한 권한이 추가되었는지 확인
2. **위임된 권한** vs **애플리케이션 권한** 구분 확인
3. **관리자 동의 허용** 버튼 클릭 여부 확인

### 401 Unauthorized

```
MS Graph API error: 401 - Unauthorized
```

**원인**: 토큰이 유효하지 않거나 만료됨

**해결**:
1. 클라이언트 시크릿이 만료되지 않았는지 확인
2. 환경 변수가 올바르게 설정되었는지 확인
3. 테넌트 ID가 정확한지 확인

### 조직 동기화 시 데이터 없음

```
Sync completed but no data was found.
```

**원인**: 선택한 옵션에 해당하는 데이터가 Entra ID에 없음

**해결**:
1. **Departments** 옵션을 활성화해보세요 (가장 일반적)
2. Administrative Units는 Azure Portal에서 별도 생성 필요
3. 백엔드 로그에서 상세 정보 확인

### 로그 확인

백엔드 로그에서 MS Graph API 호출 확인:

```bash
# Docker 환경
docker logs open-webui 2>&1 | grep -i "MS Graph"

# 직접 실행
# 로그에서 다음 내용 확인:
# INFO: MS Graph API request: https://graph.microsoft.com/v1.0/...
# INFO: MS Graph API response: X items
# ERROR: MS Graph API error: 403 - ...
```

---

## 참고 자료

- [Microsoft Graph 권한 참조](https://learn.microsoft.com/ko-kr/graph/permissions-reference)
- [앱에 권한 부여](https://learn.microsoft.com/ko-kr/entra/identity-platform/quickstart-configure-app-access-web-apis)
- [관리자 동의 흐름](https://learn.microsoft.com/ko-kr/entra/identity-platform/v2-admin-consent)

> Last Updated: 2026-04-08

# SharePoint 통합

Microsoft Graph API를 사용하여 **SharePoint Online 문서 라이브러리의 파일을 Cloosphere 채팅에 직접 첨부**할 수 있게 해주는 기능입니다. 기존의 `ONEDRIVE_*` 레거시 환경변수를 SharePoint 통합에 재사용하는 구조로 구현되어 있습니다.

## 문서 목록

| # | 파일 | 내용 |
|---|---|---|
| 1 | [개요](./01_overview.md) | 기능 목적, 구성요소, 인증 방식, 데이터 흐름 |
| 2 | [설정](./02_setup.md) | Azure AD 앱 등록, env var, dual-naming, Admin UI 토글 |
| 3 | [아키텍처](./03_architecture.md) | Graph API 엔드포인트, 파일 다운로드 흐름, 멀티 셀렉트 |
| 4 | [프론트엔드 통합](./04_frontend_integration.md) | 컴포넌트, 이벤트, 확장 방법 |

## 퀵 스타트

1. [Azure Portal](https://portal.azure.com)에서 Entra ID 앱 등록 (또는 기존 앱 재사용)
2. Microsoft Graph의 **Delegated permissions** 추가: `Sites.Read.All`, `Files.Read.All`, `User.Read` (Admin consent 필요)
3. `.env`에 환경 변수 설정 (아래 **Dual-Naming** 주의)
4. Cloosphere 재시작
5. **Admin Settings → Documents → SharePoint Integration** 토글 ON
6. 사용자: 채팅 입력창 → `+` 버튼 → **SharePoint** → 파일 브라우저 → 파일 선택 → 첨부

## ⚠️ Dual-Naming 주의

SharePoint 설정은 **`.env` 파일의 환경변수 이름**과 **PersistentConfig(DB/Admin UI에 표시되는 이름)이 서로 다릅니다**. 이는 초기에 OneDrive 통합 코드를 재사용한 것의 유산입니다.

| `.env` (env var 소스) | PersistentConfig (DB/Admin UI) | config.py 위치 |
|---|---|---|
| `ENABLE_SHAREPOINT_INTEGRATION` | `ENABLE_SHAREPOINT_INTEGRATION` | line 2613 |
| `ONEDRIVE_CLIENT_ID_BUSINESS` | **`SHAREPOINT_CLIENT_ID`** | line 2619 |
| `ONEDRIVE_SHAREPOINT_TENANT_ID` | **`SHAREPOINT_TENANT_ID`** | line 2625 |
| `ONEDRIVE_SHAREPOINT_URL` | **`SHAREPOINT_SITE_URL`** | line 2631 |

**`.env` 예시**:
```env
ENABLE_SHAREPOINT_INTEGRATION=true
ONEDRIVE_CLIENT_ID_BUSINESS=your-entra-app-client-id
ONEDRIVE_SHAREPOINT_TENANT_ID=your-tenant-id
ONEDRIVE_SHAREPOINT_URL=https://your-company.sharepoint.com/sites/your-site
```

> **별도 구분**: `ONEDRIVE_CLIENT_ID` (접미사 없음)는 **개인용 OneDrive (Consumers)** 통합에 사용되며 별도 `ENABLE_ONEDRIVE_INTEGRATION` 토글로 관리됩니다 (`config.py` line 2600–2611).

## 주요 기능

| 기능 | 설명 |
|---|---|
| **사이트/라이브러리 탐색** | 등록된 Tenant의 SharePoint 사이트 목록 조회, 사이트 내 문서 라이브러리 탐색 |
| **파일 브라우저 UI** | 폴더 트리 + 파일 목록, 멀티 셀렉트, 재귀적 폴더 다운로드 |
| **채팅 첨부** | 선택한 파일을 다운로드하여 현재 채팅의 첨부 파일로 추가 (RAG 또는 일반) |
| **Admin 토글** | Admin Settings → Documents에서 통합 활성화/비활성화 |
| **MSAL 인증** | Microsoft Authentication Library (Tenant-based authority) |
| **Graph API 호출** | 백엔드 경유 없이 **프론트엔드에서 직접** Graph API 호출 (delegated token) |

## 아키텍처 요약

```
[User] SharePoint 버튼 클릭
   │
   ▼
┌─────────────────────────┐
│ SharePointBrowser.svelte │
│ (Frontend)               │
└─────────────────────────┘
   │
   ├─▶ MSAL 로그인 (popup)
   │      → delegated access token
   │
   ├─▶ GET /sites (Graph)
   ├─▶ GET /sites/{id}/drives
   ├─▶ GET /drives/{id}/items/{item-id}/children
   │
   ├─▶ 파일 선택
   │
   └─▶ GET /drives/{id}/items/{item-id}/content
         → Blob 다운로드 → 채팅 첨부
```

- **백엔드 역할**: Admin 설정 (`ENABLE_SHAREPOINT_INTEGRATION` 토글) 관리, `/api/config`에 feature flag 노출
- **프론트엔드 역할**: MSAL 인증, Graph API 직접 호출, 파일 브라우저 UI, 채팅 첨부 연동

## Backend Config 노출

`main.py::get_app_config()` 가 `/api/config` 응답에 SharePoint feature flag를 포함:

```python
{
  "features": {
    "enable_sharepoint_integration": bool(ENABLE_SHAREPOINT_INTEGRATION.value),
    ...
  }
}
```

프론트엔드의 `InputMenu.svelte`는 `$config?.features?.enable_sharepoint_integration` 을 체크하여 SharePoint 버튼 표시 여부를 결정합니다.

## 관련 파일

- **Backend**:
  - `backend/open_webui/config.py` line 2613–2635 (PersistentConfig)
  - `backend/open_webui/main.py` (config 노출)
  - `backend/open_webui/routers/retrieval.py` (RAGConfig 통합)
- **Frontend**:
  - `src/lib/utils/sharepoint-client.ts` — Graph API 클라이언트 + MSAL
  - `src/lib/components/common/SharePointBrowser.svelte` — 파일 브라우저 UI
  - `src/lib/components/admin/Settings/Documents.svelte` — Admin 토글
  - `src/lib/components/chat/MessageInput.svelte` — 채팅 입력 통합
  - `src/lib/components/chat/MessageInput/InputMenu.svelte` — `+` 버튼 메뉴

## 관련 문서

- [entra_id/README.md](../entra_id/README.md) — Entra ID 앱 등록, Graph API 권한, SharePoint vs 조직 동기화 vs 로그인 권한 구분

## 변경 이력

| 날짜 | 변경 |
|---|---|
| 2026-04-08 | 신스타일 마이그레이션 (README 추가) + dual-naming 명시 + Last Updated | `docs/eng-docs-refresh` |
| 2026-01-30 | 초기 문서 작성 (구스타일) | |

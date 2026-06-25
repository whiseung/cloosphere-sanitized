> Last Updated: 2026-04-08

# SharePoint 통합 개요

SharePoint 통합 모듈은 Microsoft Graph API를 사용하여 SharePoint Online 문서 라이브러리의 파일을 Cloosphere 채팅에 직접 첨부할 수 있게 해주는 기능입니다.

## 주요 목적

- **조직 문서 접근**: Microsoft 365/Business 환경의 SharePoint 사이트에 저장된 문서에 접근
- **파일/폴더 탐색**: 사이트, 문서 라이브러리, 폴더 구조를 탐색하여 필요한 파일 선택
- **채팅 첨부**: 선택한 파일을 다운로드하여 채팅에 첨부 (RAG 또는 일반 첨부)

## 주요 구성 요소

### Backend
- **config.py** (line 2613–2635): SharePoint 관련 PersistentConfig. **Dual-naming 주의**:
  - `ENABLE_SHAREPOINT_INTEGRATION` ← env var: `ENABLE_SHAREPOINT_INTEGRATION` (동일)
  - `SHAREPOINT_CLIENT_ID` ← env var: **`ONEDRIVE_CLIENT_ID_BUSINESS`** (구 이름 재사용)
  - `SHAREPOINT_TENANT_ID` ← env var: **`ONEDRIVE_SHAREPOINT_TENANT_ID`**
  - `SHAREPOINT_SITE_URL` ← env var: **`ONEDRIVE_SHAREPOINT_URL`** (선택)

  자세한 내용: [README.md의 Dual-Naming 섹션](./README.md#️-dual-naming-주의)

- **main.py**: API config에 SharePoint 설정 노출

- **routers/retrieval.py**: Admin 설정 API
  - `ENABLE_SHAREPOINT_INTEGRATION` 설정 읽기/쓰기
  - RAGConfig를 통한 런타임 설정 변경

### Frontend
- **sharepoint-client.ts**: Microsoft Graph API 클라이언트
  - MSAL 인증 (Tenant 기반)
  - 사이트/드라이브/파일 조회 API 호출

- **SharePointBrowser.svelte**: 파일 브라우저 UI 컴포넌트
  - 사이트/라이브러리 선택 드롭다운
  - 파일/폴더 목록 표시
  - 멀티 셀렉트 지원
  - 재귀적 폴더 다운로드 지원

- **MessageInput.svelte**: 채팅 입력창 통합
- **InputMenu.svelte**: SharePoint 버튼 추가 (Admin 설정 연동)

- **admin/Settings/Documents.svelte**: Admin 설정 패널
  - SharePoint 통합 활성화/비활성화 토글

## 기술 스택

- **인증**: MSAL.js (Microsoft Authentication Library)
- **API**: Microsoft Graph API v1.0
- **UI**: Svelte + Tailwind CSS
- **권한**: Delegated permissions (Sites.Read.All, Files.Read.All, User.Read)

## OneDrive vs SharePoint

| 구분 | OneDrive (Consumers) | SharePoint (Business) |
|------|----------|------------|
| 대상 | 개인 클라우드 스토리지 | 조직 문서 라이브러리 |
| 인증 | consumers authority | Tenant 기반 authority |
| **env var** | `ONEDRIVE_CLIENT_ID` | **`ONEDRIVE_CLIENT_ID_BUSINESS`** |
| **PersistentConfig** | `ONEDRIVE_CLIENT_ID` | **`SHAREPOINT_CLIENT_ID`** |
| **토글** | `ENABLE_ONEDRIVE_INTEGRATION` | `ENABLE_SHAREPOINT_INTEGRATION` |
| 사용 사례 | 개인 파일 첨부 | 팀/조직 문서 첨부 |

> SharePoint 쪽은 env var 이름이 `ONEDRIVE_*_BUSINESS`로 레거시지만, PersistentConfig와 Admin UI에서는 `SHAREPOINT_*`로 표시됩니다.

## 데이터 흐름

```
┌─────────────┐     ┌──────────────┐     ┌─────────────────┐
│  사용자     │────▶│  Frontend    │────▶│  Microsoft      │
│  (브라우저) │     │  (MSAL)      │     │  Graph API      │
└─────────────┘     └──────────────┘     └─────────────────┘
                           │
                           ▼
                    ┌──────────────┐
                    │  SharePoint  │
                    │  Online      │
                    └──────────────┘
```

1. Admin이 Documents 설정에서 SharePoint 통합 활성화
2. 사용자가 채팅에서 SharePoint 버튼 클릭
3. MSAL 팝업으로 Microsoft 계정 로그인 (조직 계정)
4. Access Token 획득
5. Graph API로 사이트/드라이브/파일 조회
6. 파일/폴더 선택 시 다운로드 (폴더는 재귀적으로 모든 파일 다운로드)
7. File 객체 배열로 변환하여 채팅에 첨부

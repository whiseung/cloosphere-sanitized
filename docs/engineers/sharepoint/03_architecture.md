# 기술 아키텍처

SharePoint 통합의 상세 기술 구조와 코드 흐름을 설명합니다.

## 1. 파일 구조

```
backend/open_webui/
├── config.py                    # SharePoint 환경변수 정의
├── main.py                      # API config 노출
└── routers/
    └── retrieval.py             # Admin 설정 API (RAGConfig)

src/lib/
├── utils/
│   └── sharepoint-client.ts     # Graph API 클라이언트
├── components/
│   ├── common/
│   │   └── SharePointBrowser.svelte  # 파일 브라우저 UI
│   ├── admin/
│   │   └── Settings/
│   │       └── Documents.svelte      # Admin 설정 (토글)
│   └── chat/
│       ├── MessageInput.svelte       # 채팅 입력 (통합)
│       └── MessageInput/
│           └── InputMenu.svelte      # 입력 메뉴 (버튼)
├── stores/
│   └── index.ts                 # Config 타입 정의
└── i18n/locales/
    ├── en-US/translation.json   # 영문 번역
    └── ko-KR/translation.json   # 한국어 번역
```

## 2. Backend 구성

### config.py

```python
# SharePoint 통합 설정
ENABLE_SHAREPOINT_INTEGRATION = PersistentConfig(
    "ENABLE_SHAREPOINT_INTEGRATION",
    "sharepoint.enable",
    os.getenv("ENABLE_SHAREPOINT_INTEGRATION", "False").lower() == "true",
)

SHAREPOINT_CLIENT_ID = PersistentConfig(
    "SHAREPOINT_CLIENT_ID",
    "sharepoint.client_id",
    os.environ.get("ONEDRIVE_CLIENT_ID_BUSINESS", ""),
)

SHAREPOINT_TENANT_ID = PersistentConfig(
    "SHAREPOINT_TENANT_ID",
    "sharepoint.tenant_id",
    os.environ.get("ONEDRIVE_SHAREPOINT_TENANT_ID", ""),
)

SHAREPOINT_SITE_URL = PersistentConfig(
    "SHAREPOINT_SITE_URL",
    "sharepoint.site_url",
    os.environ.get("ONEDRIVE_SHAREPOINT_URL", ""),
)
```

### main.py API 응답

```python
# /api/config 응답에 포함
{
    "features": {
        "enable_sharepoint_integration": True
    },
    "sharepoint": {
        "client_id": "xxx",
        "tenant_id": "yyy",
        "site_url": "https://..."
    }
}
```

### retrieval.py Admin 설정 API

RAGConfig를 통해 Admin 패널에서 런타임 설정 변경이 가능합니다.

```python
# ConfigForm 클래스
class ConfigForm(BaseModel):
    # ... 기타 설정
    ENABLE_SHAREPOINT_INTEGRATION: Optional[bool] = None

# getRAGConfig 응답에 포함
{
    "ENABLE_SHAREPOINT_INTEGRATION": True,
    # ... 기타 RAG 설정
}

# updateRAGConfig에서 처리
request.app.state.config.ENABLE_SHAREPOINT_INTEGRATION = (
    form_data.ENABLE_SHAREPOINT_INTEGRATION
    if form_data.ENABLE_SHAREPOINT_INTEGRATION is not None
    else request.app.state.config.ENABLE_SHAREPOINT_INTEGRATION
)
```

## 3. Frontend 구성

### sharepoint-client.ts

MSAL 기반 인증 및 Graph API 호출을 담당합니다.

#### 주요 함수

| 함수 | 설명 |
|------|------|
| `initializeMsal()` | MSAL 인스턴스 초기화 (Tenant authority) |
| `getAccessToken()` | Silent → Popup 방식으로 토큰 획득 |
| `getSites()` | SharePoint 사이트 목록 조회 |
| `getDrives(siteId)` | 문서 라이브러리 목록 조회 |
| `getItems(driveId, folderId?)` | 파일/폴더 목록 조회 |
| `downloadFile(driveId, itemId)` | 파일 다운로드 (Blob) |

#### MSAL 설정

```typescript
const msalConfig = {
    auth: {
        clientId: cfg.clientId,
        authority: `https://login.microsoftonline.com/${cfg.tenantId}`,
        redirectUri: window.location.origin
    },
    cache: {
        cacheLocation: 'sessionStorage',
        storeAuthStateInCookie: false
    }
};
```

#### Graph API 스코프

```typescript
const scopes = ['Sites.Read.All', 'Files.Read.All', 'User.Read'];
```

### SharePointBrowser.svelte

파일 탐색 UI 컴포넌트입니다.

#### 상태 관리

> ⚠️ **중요**: Svelte 반응성 문제로 `Set` 대신 `Array`를 사용합니다.
> Set의 `add()`, `delete()` 메서드는 Svelte 반응성을 트리거하지 않습니다.

```typescript
let sites: Site[] = [];              // SharePoint 사이트 목록
let drives: Drive[] = [];            // 문서 라이브러리 목록
let items: DriveItem[] = [];         // 현재 폴더의 항목들
let selectedSite: Site | null;       // 선택된 사이트
let selectedDrive: Drive | null;     // 선택된 라이브러리
let selectedItemIds: string[] = [];  // 선택된 항목 ID들 (Array!)
let navigationStack: {id, name}[];   // 브레드크럼 경로

// 반응형 선택 개수 계산
$: selectedCount = selectedItemIds.length;
```

#### 선택 토글 함수 (반응성 보장)

```typescript
function toggleItemSelection(itemId: string) {
    const idx = selectedItemIds.indexOf(itemId);
    if (idx >= 0) {
        // 배열에서 제거 - 새 배열 할당으로 반응성 트리거
        selectedItemIds = selectedItemIds.filter((id) => id !== itemId);
    } else {
        // 배열에 추가 - 스프레드로 새 배열 생성
        selectedItemIds = [...selectedItemIds, itemId];
    }
}
```

#### 이벤트 (v2 - 변경됨)

```typescript
// 새로운 이벤트 형식: File 배열 반환
dispatch('select', {
    files: File[]    // 다운로드된 파일들 (폴더 선택 시 재귀적으로 수집)
});

dispatch('cancel');   // 취소 시
```

#### 폴더 재귀 다운로드

```typescript
async function collectFilesFromFolder(
    driveId: string,
    folderId: string,
    folderName: string
): Promise<File[]> {
    const folderItems = await getItems(driveId, folderId);
    const files: File[] = [];

    for (const item of folderItems) {
        if (item.folder) {
            // 하위 폴더 재귀 처리
            const subFiles = await collectFilesFromFolder(
                driveId,
                item.id,
                `${folderName}/${item.name}`
            );
            files.push(...subFiles);
        } else {
            // 파일 다운로드
            const blob = await downloadFile(driveId, item.id);
            files.push(new File(
                [blob],
                item.name,
                { type: blob.type || 'application/octet-stream' }
            ));
        }
    }
    return files;
}
```

## 4. Graph API 엔드포인트

| 용도 | 엔드포인트 |
|------|-----------|
| 사이트 검색 | `GET /sites?search=*` |
| 특정 사이트 | `GET /sites/{hostname}:/sites/{siteName}` |
| 팔로우 사이트 | `GET /me/followedSites` |
| 드라이브 목록 | `GET /sites/{siteId}/drives` |
| 루트 항목 | `GET /drives/{driveId}/root/children` |
| 폴더 내 항목 | `GET /drives/{driveId}/items/{itemId}/children` |
| 파일 정보 | `GET /drives/{driveId}/items/{itemId}` |

파일 다운로드는 파일 정보 응답의 `@microsoft.graph.downloadUrl` 필드를 사용합니다.

## 5. 시퀀스 다이어그램

```
┌────────┐    ┌───────────────┐    ┌────────┐    ┌─────────────┐
│ User   │    │ SharePoint    │    │ MSAL   │    │ Graph API   │
│        │    │ Browser       │    │        │    │             │
└───┬────┘    └──────┬────────┘    └───┬────┘    └──────┬──────┘
    │                │                  │                │
    │ Click Button   │                  │                │
    │───────────────▶│                  │                │
    │                │ getAccessToken() │                │
    │                │─────────────────▶│                │
    │                │                  │ acquireTokenSilent()
    │                │                  │───────────────▶│
    │                │                  │     (cached)   │
    │                │   token          │◀───────────────│
    │                │◀─────────────────│                │
    │                │                  │                │
    │                │ getSites()       │                │
    │                │──────────────────┼───────────────▶│
    │                │                  │      sites     │
    │                │◀─────────────────┼────────────────│
    │  Show Sites    │                  │                │
    │◀───────────────│                  │                │
    │                │                  │                │
    │ Select File    │                  │                │
    │───────────────▶│                  │                │
    │                │ downloadFile()   │                │
    │                │──────────────────┼───────────────▶│
    │                │                  │      blob      │
    │                │◀─────────────────┼────────────────│
    │                │                  │                │
    │                │ dispatch('select', {blob, name})  │
    │◀───────────────│                  │                │
```

## 6. 에러 처리

### 인증 에러

```typescript
try {
    const response = await msal.loginPopup(scopes);
} catch (error) {
    // 사용자가 팝업 취소 또는 권한 거부
    throw new Error('Failed to authenticate with SharePoint');
}
```

### API 에러

```typescript
if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Graph API error (${response.status}): ${errorText}`);
}
```

### 사이트 없음

여러 방법으로 사이트 조회를 시도합니다:
1. 설정된 사이트 URL로 직접 조회
2. `/sites?search=*`로 전체 검색
3. `/me/followedSites`로 팔로우 사이트 조회

모두 실패하면 사용자에게 권한 확인 메시지를 표시합니다.

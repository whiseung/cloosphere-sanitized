# 설정 및 구성

SharePoint 통합을 사용하기 위한 Azure AD 앱 등록 및 환경 변수 설정 가이드입니다.

## 1. Azure AD 앱 등록

### 1.1 앱 등록 생성

1. [Azure Portal](https://portal.azure.com) → Azure Active Directory → 앱 등록
2. **새 등록** 클릭
3. 앱 정보 입력:
   - **이름**: `Cloosphere SharePoint Integration` (또는 원하는 이름)
   - **지원되는 계정 유형**: "이 조직 디렉터리의 계정만" (Single tenant)
   - **리디렉션 URI**: 아래 SPA 설정에서 추가

### 1.2 플랫폼 구성 (중요!)

**인증** 메뉴에서 플랫폼 추가:

1. **단일 페이지 애플리케이션(SPA)** 선택 (⚠️ 웹이 아님!)
2. 리디렉션 URI 추가:
   ```
   http://localhost:5173    (개발 환경)
   https://your-domain.com  (프로덕션)
   ```

> ⚠️ **주의**: 같은 URI를 "웹" 플랫폼에도 추가하면 `AADSTS9002326` 오류가 발생합니다. SPA에만 추가하세요.

### 1.3 API 권한 추가

**API 권한** 메뉴에서 다음 권한 추가:

| API | 권한 | 유형 | 설명 |
|-----|------|------|------|
| Microsoft Graph | `User.Read` | Delegated | 사용자 프로필 읽기 |
| Microsoft Graph | `Sites.Read.All` | Delegated | SharePoint 사이트 읽기 |
| Microsoft Graph | `Files.Read.All` | Delegated | 모든 파일 읽기 |

권한 추가 후 **관리자 동의 부여** 클릭 (테넌트 관리자 권한 필요)

### 1.4 앱 정보 복사

**개요** 페이지에서 다음 정보 복사:
- **애플리케이션(클라이언트) ID**: `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`
- **디렉터리(테넌트) ID**: `yyyyyyyy-yyyy-yyyy-yyyy-yyyyyyyyyyyy`

## 2. 환경 변수 설정 (.env)

```bash
# SharePoint 통합 활성화
ENABLE_SHAREPOINT_INTEGRATION=true

# Azure AD 앱 정보
ONEDRIVE_CLIENT_ID_BUSINESS=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
ONEDRIVE_SHAREPOINT_TENANT_ID=yyyyyyyy-yyyy-yyyy-yyyy-yyyyyyyyyyyy

# (선택) 기본 SharePoint 사이트 URL
# 설정하면 해당 사이트가 목록에 우선 표시됨
ONEDRIVE_SHAREPOINT_URL=https://contoso.sharepoint.com/sites/TeamSite
```

## 3. 설정 확인

### 3.1 백엔드 API 확인

```bash
curl http://localhost:8080/api/config | jq '.sharepoint'
```

예상 응답:
```json
{
  "client_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "tenant_id": "yyyyyyyy-yyyy-yyyy-yyyy-yyyyyyyyyyyy",
  "site_url": "https://contoso.sharepoint.com/sites/TeamSite"
}
```

### 3.2 features 확인

```bash
curl http://localhost:8080/api/config | jq '.features.enable_sharepoint_integration'
```

`true`가 반환되어야 합니다.

## 4. 트러블슈팅

### AADSTS9002326 오류
```
Cross-origin token redemption is permitted only for the 'Single-Page Application'
```
**원인**: 리디렉션 URI가 "웹" 플랫폼에 등록됨
**해결**: Azure AD 앱 → 인증 → 웹 플랫폼의 URI 삭제 → SPA에만 등록

### 사이트 목록이 비어있음
**가능한 원인**:
1. `Sites.Read.All` 권한에 관리자 동의가 없음
2. 사용자가 접근 가능한 SharePoint 사이트가 없음
3. 테넌트에 SharePoint Online 라이선스가 없음

**확인 방법**: 브라우저 개발자 도구 콘솔에서 로그 확인
```
SharePoint: Getting sites with config: {...}
SharePoint: Fetching configured site: /sites/...
SharePoint: Search response: {...}
```

### 인증 팝업이 차단됨
**해결**: 브라우저 팝업 차단 해제 또는 예외 추가

## 5. 기존 OneDrive 앱과의 관계

OneDrive Personal과 SharePoint Business는 **별도의 앱을 사용하는 것을 권장**합니다:

| 용도 | 환경변수 | Authority |
|------|----------|-----------|
| OneDrive Personal | `ONEDRIVE_CLIENT_ID` | `consumers` |
| SharePoint Business | `ONEDRIVE_CLIENT_ID_BUSINESS` | `{tenant_id}` |

동일한 앱을 사용할 경우 multi-tenant 설정이 필요하며, 권한 관리가 복잡해집니다.

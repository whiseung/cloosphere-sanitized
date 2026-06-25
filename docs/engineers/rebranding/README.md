> Last Updated: 2026-04-08

# 고객사 리브랜딩 가이드

고객사별로 앱 이름, 로고 등을 변경하기 위한 가이드입니다.

> **두 가지 리브랜딩 방식**:
> 1. **빌드 타임** (이 문서의 상단) — 고객사별로 이미지를 `static/`에 넣고 `.env`에 이름 설정. 빌드 후 배포.
> 2. **런타임** (이 문서의 하단 "Runtime Branding API" 섹션) — 실제 고객 환경에서 **Admin Settings → Branding** UI로 로고/파비콘을 업로드하고 DB에 저장 (`branding.py` 라우터, `DATA_DIR/brand/` 폴더). License feature `branding` 필요.

## Claude Code 커맨드 (권장)

가장 빠른 방법:

```bash
/system_rename 삼성전자, Samsung
```

이 커맨드가 자동으로 처리하는 항목:
- `src/app.html` - meta/title 변경
- `.env` - WEBUI_NAME 변경
- i18n 번역 파일 - 제품명 변경
- 빌드/로고 안내

---

## 수동 변경 가이드

### 1. 앱 이름 변경

**방법 A: 환경변수 (권장)**

빌드 시 환경변수로 앱 이름 지정:

```bash
# 빌드 시 (영문명)
APP_NAME="Samsung" npm run build
```

**방법 B: 런타임 설정**

백엔드 `.env` 파일에서 설정 (한글명):

```bash
WEBUI_NAME=삼성전자
```

> ⚠️ 방법 A는 프론트엔드 빌드 시 적용, 방법 B는 백엔드에서 API로 전달

### 2. 정적 HTML 변경

`src/app.html` 파일에서 직접 변경 필요 (영문명 사용):

```html
<!-- 변경할 부분 (4곳) -->
<meta name="apple-mobile-web-app-title" content="Samsung" />
<meta name="description" content="Samsung" />
<link ... title="Samsung" href="/opensearch.xml" />
<title>Samsung</title>
```

### 3. i18n 번역 변경

제품명으로 사용된 "Open WebUI"를 고객사명으로 변경:

```bash
# 변경 대상 검색
grep -r "Open WebUI" src/lib/i18n/locales/
```

**변경할 항목**:
- `"Open WebUI uses faster-whisper internally"`
- `"CORS must be properly configured ... from Open WebUI"`

**유지할 항목** (외부 커뮤니티 참조):
- `"Share to Open WebUI Community"`
- `"Made by Open WebUI Community"`

### 4. 로고/파비콘 변경

`static/` 폴더의 파일 교체:

| 파일 | 용도 | 크기 |
|------|------|------|
| `static/favicon.png` | 브라우저 탭 아이콘 | 32x32 |
| `static/favicon-96x96.png` | 고해상도 아이콘 | 96x96 |
| `static/favicon.ico` | 레거시 아이콘 | 16x16, 32x32 |
| `static/favicon.svg` | SVG 아이콘 | 벡터 |
| `static/apple-touch-icon.png` | iOS 홈 화면 | 180x180 |
| `static/splash.png` | 로딩 화면 (라이트) | 권장 200x200 |
| `static/splash-dark.png` | 로딩 화면 (다크) | 권장 200x200 |

---

## 상세 설정

### 변경 포인트 체크리스트

| 구분 | 파일 | 변경 방법 |
|------|------|----------|
| **앱 이름 (빌드)** | `vite.config.ts` | `APP_NAME` 환경변수 |
| **앱 이름 (런타임)** | `.env` | `WEBUI_NAME` 환경변수 |
| **HTML 메타** | `src/app.html` | 직접 수정 (4곳) |
| **로고** | `static/` | 파일 교체 |
| **PWA 매니페스트** | 백엔드 `/manifest.json` | `WEBUI_NAME` 자동 적용 |

### 파일별 상세

#### vite.config.ts

```typescript
define: {
    // ...
    APP_NAME: JSON.stringify(process.env.APP_NAME || 'Cloosphere')
},
```

#### src/lib/constants.ts

```typescript
// APP_NAME은 vite.config.ts에서 빌드 시 주입됨
const _APP_NAME: string = APP_NAME;
export { _APP_NAME as APP_NAME };
```

#### backend/.env

```bash
# 런타임 앱 이름 (API /api/config 응답에 포함)
WEBUI_NAME=고객사이름
```

---

## Runtime Branding API

빌드 타임이 아닌, **운영 중에 Admin Settings → Branding에서 로고/파비콘을 업로드**할 수 있는 API. `branding` license feature가 필요하다.

### 라우터 (`/api/v1/branding`, 5 endpoints)

**파일**: `backend/open_webui/routers/branding.py` (181 lines)

| Method | Path | Auth + Gate | 설명 |
|---|---|---|---|
| GET | `/config` | `require_feature("branding")` | 현재 branding 설정 조회 (asset URL + 앱 이름) |
| POST | `/app-name` | `require_feature("branding")` + admin | 앱 이름 업데이트 |
| GET | `/{asset_type}` | (인증 없음, 퍼블릭 이미지) | Asset 파일 반환 (fallback 포함) |
| POST | `/upload/{asset_type}` | `require_feature("branding")` + admin | Asset 업로드 (multipart) |
| DELETE | `/{asset_type}` | `require_feature("branding")` + admin | Asset 삭제 (fallback 복원) |

### Asset Types (`ASSET_MAP`)

| asset_type | 용도 |
|---|---|
| `favicon` | 기본 favicon (라이트 모드) |
| `favicon-dark` | 다크 모드 favicon |
| `logo` | 사이드바/상단 로고 |
| `splash` | 로딩 화면 (라이트) |
| `splash-dark` | 로딩 화면 (다크) |
| `browser-favicon` | 브라우저 탭 전용 (high-dpi) |

### 저장 경로

업로드된 파일은 `DATA_DIR/brand/` 디렉토리에 저장된다 (`DATA_DIR`는 `WEBUI_DATA_DIR` env var 또는 기본 `./data`). 런타임 경로로 디스크에 영속화되며, 컨테이너 재시작 후에도 유지된다 (volume mount 필요).

### Fallback

Asset이 업로드되지 않은 경우, `static/` 폴더의 정적 파일이 fallback으로 서빙된다:

| Asset | Fallback 파일 |
|---|---|
| `favicon` | `static/favicon.png` → `favicon-96x96.png` → `favicon.ico` → `favicon.svg` |
| `logo` | (기본 Cloosphere 로고) |
| `splash` | `static/splash.png` |
| `splash-dark` | `static/splash-dark.png` |

### 환경 변수 (BRANDING_*)

`config.py`에 정의된 runtime branding PersistentConfig:

| 변수 | 설명 |
|---|---|
| `BRANDING_FAVICON_URL` | 외부 URL로 favicon 지정 (CDN 등) |
| `BRANDING_LOGO_URL` | 외부 URL로 logo |
| `BRANDING_SPLASH_URL` | 외부 URL로 splash |
| `BRANDING_FAVICON_DARK_URL` | 외부 URL로 favicon-dark |
| `BRANDING_SPLASH_DARK_URL` | 외부 URL로 splash-dark |
| `BRANDING_BROWSER_FAVICON_URL` | 외부 URL로 browser-favicon |

**우선순위**: `BRANDING_*_URL` 환경변수 > 업로드된 `DATA_DIR/brand/` 파일 > `static/` fallback.

### 프론트엔드 Store (`src/lib/stores/branding.ts`)

```typescript
import { writable, derived } from 'svelte/store';

// 캐시 버스팅용 버전 카운터
export const brandingVersion = writable<number>(Date.now());

// Asset type → URL 매핑 (derived store)
export const brandingUrls = derived(
  [config, brandingVersion],
  ([$config, $version]) => ({
    favicon: `/api/v1/branding/favicon?v=${$version}`,
    logo: `/api/v1/branding/logo?v=${$version}`,
    splash: `/api/v1/branding/splash?v=${$version}`,
    // ...
  })
);
```

**캐시 버스팅**: 업로드/삭제 후 `brandingVersion.set(Date.now())` 호출하여 브라우저 캐시 무효화. URL에 `?v=timestamp` 쿼리 자동 추가.

### 프론트엔드 컴포넌트

`src/lib/components/admin/Settings/Branding.svelte` — 관리자 UI:
- 앱 이름 입력 + 저장 (`POST /app-name`)
- Asset 업로드 (drag&drop or file picker) → `POST /upload/{asset_type}`
- 현재 asset 미리보기 + 삭제 버튼 → `DELETE /{asset_type}`
- 업로드/삭제 후 `brandingVersion` store 갱신

### `/api/config` 응답에 포함

`main.py::get_app_config()`에서 `/api/config` 응답에 branding 정보를 포함 (프론트엔드가 초기 로드 시 사용).

```json
{
  "name": "Cloosphere",
  "branding": {
    "favicon_url": "...",
    "logo_url": "...",
    ...
  }
}
```

---

## 자동화 스크립트 예시

고객사별 빌드 자동화:

```bash
#!/bin/bash
# scripts/build-customer.sh

CUSTOMER_NAME=$1
CUSTOMER_DIR="customers/${CUSTOMER_NAME}"

# 1. 로고 복사
cp "${CUSTOMER_DIR}/favicon.png" static/favicon.png
cp "${CUSTOMER_DIR}/splash.png" static/splash.png

# 2. app.html 치환
sed -i "s/Cloosphere/${CUSTOMER_NAME}/g" src/app.html

# 3. 빌드
APP_NAME="${CUSTOMER_NAME}" npm run build

# 4. 원복 (git에서)
git checkout src/app.html static/
```

사용법:
```bash
./scripts/build-customer.sh "삼성전자"
```

---

## 주의사항

### 변경되지 않는 항목

다음 항목들은 **의도적으로 유지**됩니다:

1. **i18n 번역 키**: `"Open WebUI version..."` 등은 내부 키로 사용
2. **코드 내 기술 참조**: `required_open_webui_version` 등 호환성 체크
3. **외부 링크**: `openwebui.com`, `docs.openwebui.com` - 커뮤니티 링크

### 다국어 번역 값

번역 파일의 **값**에서 "Open WebUI"를 변경하려면:

```json
// src/lib/i18n/locales/ko-KR/translation.json
{
    "Made by Open WebUI Community": "Cloosphere 팀 제작",
    // ...
}
```

---

## 고객사별 저장소 관리 전략

### 옵션 1: 브랜치 방식

```
main (Cloosphere 기본)
├── customer/samsung
├── customer/lg
└── customer/sk
```

### 옵션 2: 설정 파일 방식 (권장)

```
customers/
├── samsung/
│   ├── .env
│   ├── favicon.png
│   └── splash.png
├── lg/
│   └── ...
```

빌드 시 고객사 디렉토리 지정:
```bash
CUSTOMER=samsung ./scripts/build-customer.sh
```

---

## 관련 파일

| 파일 | 역할 |
|------|------|
| `vite.config.ts` | 빌드 시 APP_NAME 주입 |
| `src/app.d.ts` | TypeScript 타입 선언 |
| `src/lib/constants.ts` | APP_NAME export |
| `src/lib/stores/index.ts` | WEBUI_NAME 스토어 |
| `src/app.html` | 정적 HTML 메타 |
| `backend/open_webui/config.py` | WEBUI_NAME 환경변수 |
| `backend/open_webui/main.py` | /api/config 응답 |

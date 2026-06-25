# 임베드 위젯 — 호스트 사이트 통합 가이드

이 문서는 Cloosphere 임베드 위젯을 자신의 웹사이트에 연결하려는 **호스트 사이트의 개발자와 관리자**를 위한 가이드입니다. Cloosphere 측 위젯 생성/설정은 [임베드 위젯 관리](embed-widgets.md) 문서를 먼저 참고하세요.

## 이 가이드의 독자

- 사내 그룹웨어/포털/홈페이지에 Cloosphere AI 챗봇을 임베드하려는 **개발자**
- 임베드된 위젯이 호스트 사이트의 사용자 정보와 자연스럽게 연동되길 원하는 **시스템 관리자**

## 통합 시나리오 결정

먼저 어떤 통합 수준이 필요한지 결정해야 합니다.

| 시나리오 | 위젯 동작 | 호스트 사이트 작업량 |
|---|---|---|
| **A. 익명 챗봇** | 위젯이 자체 로그인 화면 표시, 누구나 사용 | `<script>` 태그 한 줄 |
| **B. 호스트 SSO 자동 로그인** | 호스트에서 이미 로그인한 사용자가 위젯에서도 자동 로그인 | SSO 토큰 획득 + 위젯에 전달 |
| **C. AI가 호스트 페이지 조작** | AI가 호스트 사이트의 폼/버튼을 직접 조작 | 위에 더해 권한 화이트리스트 설정 |

대부분의 사내 통합은 **B**가 가장 가치가 큽니다. 사용자가 별도 로그인을 두 번 하지 않아도 되니까요. 이 가이드는 B를 중심으로 설명합니다.

## 1단계: 위젯 스크립트 임베드

가장 기본 형태:

```html
<!DOCTYPE html>
<html>
  <body>
    <!-- 호스트 사이트의 본문 -->

    <!-- Cloosphere 임베드 위젯 -->
    <script
      src="https://your-cloosphere.com/static/embed/embed.js"
      data-widget-id="abc12345-..."
    ></script>
  </body>
</html>
```

이렇게만 해도 우측 하단(또는 위젯 설정에 따라)에 채팅 버블이 뜨고 클릭하면 위젯이 열립니다. 단, 사용자는 위젯에서 별도로 로그인해야 합니다.

### 위젯 ID 받기

Cloosphere 관리자에게 위젯 ID를 요청하세요. 관리자가 **설정 → 임베드 위젯**에서 위젯을 만든 후 ID(`abc12345-...` 형태)를 알려줍니다. 위젯 ID는 공개 정보이므로 HTML에 그대로 노출돼도 됩니다.

### 허용 도메인 설정 요청

운영 환경에서는 Cloosphere 관리자에게 **허용 도메인**에 본인의 사이트 도메인(`portal.example.com` 등)을 추가해 달라고 요청하세요. 그러지 않으면 다른 사이트에서도 같은 위젯 ID로 임베드할 수 있습니다.

## 2단계: SSO 자동 로그인 통합 (시나리오 B)

호스트 사이트의 사용자가 이미 자신의 SSO(Microsoft Entra ID, Google, Okta 등)로 로그인해 있다면, 그 토큰을 위젯에 전달해 위젯에서도 자동으로 로그인되게 할 수 있습니다.

### 동작 흐름

```
[호스트 사이트]                          [Cloosphere]
1. 사용자가 사내 SSO로 로그인
2. id_token 획득 (이미 호스트 로그인 흐름의 일부)
3. CloosphereEmbed.ssoLogin({
     provider: 'microsoft',
     id_token: '...'
   })                          ─────►   POST /embed-widgets/{id}/auth/sso-exchange
                                        - id_token 검증 (issuer/서명/만료)
                                        - 이메일로 사용자 매칭
                                        - 없으면 자동 가입 (정책에 따라)
                                        - Cloosphere JWT 발급
                               ◄─────   { token: 'eyJ...' }
4. 위젯 iframe이 토큰 받아 자동 로그인
5. 사용자는 클릭만 하면 채팅 가능
```

### 위젯에 토큰 전달하는 3가지 방법

호스트 사이트가 SSO 토큰을 가지게 되는 시점은 사이트 구조에 따라 다릅니다. 다음 세 가지 패턴 중 환경에 맞는 것을 사용하세요.

#### 방법 1: pre-init 큐 (권장 — 페이지 로드 전부터 토큰을 알고 있을 때)

```html
<script>
  // 호스트 사이트의 SSO 토큰을 전역에 등록
  // (서버 사이드 렌더링이라면 SSR에서 토큰을 주입해도 됨)
  window.CloosphereEmbedQ = window.CloosphereEmbedQ || {};
  window.CloosphereEmbedQ['abc12345-...'] = {
    sso: {
      provider: 'microsoft',
      id_token: '<사용자의 id_token>'
    }
  };
</script>
<script
  src="https://your-cloosphere.com/static/embed/embed.js"
  data-widget-id="abc12345-..."
></script>
```

embed.js가 로드되면 큐를 자동으로 읽어 SSO 교환을 진행합니다. 사용자가 위젯 버블을 클릭했을 때 이미 로그인된 상태로 떠 있습니다.

#### 방법 2: 동적 호출 (페이지 로드 후 토큰을 받았을 때)

호스트 사이트에서 사용자가 나중에 로그인하거나, 토큰이 비동기로 도착하는 경우:

```javascript
// 호스트 사이트가 SSO 토큰을 받은 시점에 호출
window.CloosphereEmbed.ssoLogin({
  provider: 'microsoft',
  id_token: msalAccount.idToken
}).then((jwt) => {
  if (jwt) {
    console.log('Cloosphere 자동 로그인 성공');
  } else {
    console.warn('자동 로그인 실패 — 위젯이 로그인 화면을 표시합니다');
  }
});
```

`CloosphereEmbed.ssoLogin()`은 `Promise<string | null>`을 반환합니다. 성공 시 Cloosphere JWT 문자열, 실패 시 `null`. 실패해도 throw하지 않고, 위젯은 자체 로그인 화면으로 fallback합니다.

#### 방법 3: 토큰 갱신 (이미 로그인됐는데 토큰이 새로 발급됐을 때)

토큰이 만료되어 호스트가 새 토큰을 받았을 때:

```javascript
window.CloosphereEmbed.updateToken(newJwt);
// 또는 SSO 교환을 다시 트리거하려면:
window.CloosphereEmbed.ssoLogin({ provider: 'microsoft', id_token: newIdToken });
```

### Provider별 통합 코드 예시

#### Microsoft Entra ID (MSAL.js)

```bash
npm install @azure/msal-browser @azure/msal-react
```

**msal 설정**:
```typescript
// lib/msal.ts
import { Configuration, PopupRequest } from '@azure/msal-browser';

export const msalConfig: Configuration = {
  auth: {
    clientId: '<호스트 사이트의 Azure AD 앱 client_id>',
    authority: 'https://login.microsoftonline.com/<tenant_id>',
    redirectUri: window.location.origin + '/auth/callback.html',
  },
  cache: { cacheLocation: 'localStorage' }
};

export const loginRequest: PopupRequest = {
  scopes: ['openid', 'profile', 'email', 'User.Read']
};
```

**popup callback 페이지** (`public/auth/callback.html`):
```html
<!doctype html>
<html>
  <head><title>Signing in…</title></head>
  <body>
    Signing you in…
    <script src="https://cdn.jsdelivr.net/npm/@azure/msal-browser@5.6.3/lib/redirect-bridge/msal-redirect-bridge.min.js"></script>
    <script>
      window.msalRedirectBridge.broadcastResponseToMainFrame()
        .catch(e => document.body.textContent = 'Auth error: ' + e.message);
    </script>
  </body>
</html>
```

> Microsoft Entra ID를 호스트 사이트에서 사용하려면 Azure 앱 등록의 **Authentication → Single-page application** 플랫폼에 위 콜백 URL을 등록해야 합니다.

**로그인 + 위젯 토큰 전달**:
```typescript
import { useMsal } from '@azure/msal-react';
import { loginRequest } from './lib/msal';

function LoginButton() {
  const { instance } = useMsal();

  const handleLogin = async () => {
    const result = await instance.loginPopup(loginRequest);
    // SSO 토큰을 위젯에 전달
    window.CloosphereEmbed.ssoLogin({
      provider: 'microsoft',
      id_token: result.idToken
    });
  };

  return <button onClick={handleLogin}>Microsoft 로그인</button>;
}
```

#### Google Sign-In

```html
<script src="https://accounts.google.com/gsi/client" async defer></script>
<div id="g_id_onload"
     data-client_id="<호스트 사이트의 Google client_id>"
     data-callback="handleGoogleCredential">
</div>

<script>
function handleGoogleCredential(response) {
  // response.credential은 Google이 발급한 id_token (JWT)
  window.CloosphereEmbed.ssoLogin({
    provider: 'google',
    id_token: response.credential
  });
}
</script>
```

#### GitHub OAuth

GitHub는 OIDC를 지원하지 않으므로 access_token을 사용합니다. GitHub OAuth 흐름은 호스트 사이트 백엔드가 처리해야 합니다 (client_secret 보호 때문).

```javascript
// 호스트 백엔드에서 GitHub OAuth 코드 → access_token 교환 후
// 그 토큰을 프론트엔드로 전달했다고 가정
window.CloosphereEmbed.ssoLogin({
  provider: 'github',
  access_token: githubAccessToken
});
```

#### Generic OIDC (Keycloak, Auth0, Okta 등)

Keycloak 예시:

```javascript
import Keycloak from 'keycloak-js';

const keycloak = new Keycloak({
  url: 'https://your-keycloak.example.com',
  realm: 'myrealm',
  clientId: 'my-client'
});

await keycloak.init({ onLoad: 'check-sso' });

if (keycloak.authenticated) {
  window.CloosphereEmbed.ssoLogin({
    provider: 'oidc',
    id_token: keycloak.idToken,
    issuer: 'https://your-keycloak.example.com/realms/myrealm'
  });
}
```

OIDC provider는 `issuer` URL이 필수입니다. 위젯이 그 issuer의 `.well-known/openid-configuration`을 자동으로 fetch해서 검증합니다.

> **Cloosphere 관리자가 위젯의 SSO 탭에서 해당 issuer를 trusted_issuers에 등록해야 합니다.**

## 3단계: AI가 호스트 페이지 조작 (시나리오 C)

위젯의 AI가 호스트 사이트의 폼이나 버튼을 직접 조작할 수 있습니다. 예를 들어 "내일부터 3일 연차 신청해줘"라고 말하면 AI가 휴가 신청 폼을 자동으로 채워줄 수 있습니다.

### 사용 가능한 도구

위젯에 연결된 에이전트가 다음 도구를 사용할 수 있습니다:

| 도구 | 설명 |
|---|---|
| `get_page_info` | 사용자가 보고 있는 페이지 URL과 폼 정보 조회 |
| `fill_form_field` | 단일 폼 필드에 값 입력 |
| `fill_form` | 여러 필드를 한 번에 입력 |
| `click_element` | 버튼/링크 클릭 |
| `read_form` | 폼의 현재 값 읽기 |
| `highlight_element` | 요소 강조 표시 |
| `navigate_to` | 페이지 이동 |

### 호스트 사이트가 해야 할 일

기본적으로 위젯은 호스트 페이지를 자동으로 인식할 수 있습니다. 추가 작업은 거의 없지만, 다음 두 가지를 권장합니다:

#### Soft Navigation 지원 (SPA 전용)

위젯이 `navigate_to`를 호출할 때, SPA 라우터를 사용한다면 페이지 새로고침 없이 부드럽게 이동하도록 리스너를 추가하세요.

**Next.js (App Router)**:
```typescript
'use client';
import { useEffect } from 'react';
import { useRouter } from 'next/navigation';

export default function CloosphereBridge() {
  const router = useRouter();

  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent).detail;
      if (!detail?.url) return;
      const url = new URL(detail.url, window.location.href);
      if (url.origin !== window.location.origin) return;
      router.push(url.pathname + url.search);
      window.postMessage({ type: 'cloosphere:navigation-handled' }, '*');
    };
    window.addEventListener('cloosphere:navigate', handler);
    return () => window.removeEventListener('cloosphere:navigate', handler);
  }, [router]);

  return null;
}
```

**Vue Router**, **SvelteKit**, **React Router** 등도 같은 패턴으로 구현 가능합니다.

리스너가 없으면 일반 페이지 이동(`window.location.href = ...`)으로 자동 폴백되므로, 도입을 안 해도 동작은 합니다.

#### 의미 있는 폼 필드 식별자

AI가 폼 필드를 정확하게 식별하려면 `name`, `id`, `aria-label` 등을 의미 있게 부여하세요:

```html
<!-- 좋음 -->
<input name="leaveStartDate" aria-label="휴가 시작일" type="date" />

<!-- 나쁨 — AI가 어느 필드인지 추측하기 어려움 -->
<input name="f1" type="date" />
```

## 4단계: 디자인 커스터마이징 (선택)

위젯의 시각적 디자인은 기본적으로 Cloosphere 관리자가 결정하지만, 필요하다면 호스트 사이트가 일부 속성을 오버라이드할 수 있습니다:

```html
<script
  src="https://your-cloosphere.com/static/embed/embed.js"
  data-widget-id="abc12345-..."
  data-theme="dark"
  data-mode="bubble"
  data-position="bottom-right"
  data-primary-color="#0f172a"
  data-width="400px"
  data-height="600px"
></script>
```

전체 디자인 옵션 목록은 [임베드 위젯 관리](embed-widgets.md) 문서의 "디자인 커스터마이징" 섹션을 참고하세요.

## 보안 체크리스트

운영 환경에 배포하기 전 확인해야 할 사항:

- [ ] **Cloosphere 관리자에게 호스트 도메인을 허용 도메인에 등록 요청** — 운영에서 필수
- [ ] **HTTPS 사용** — embed.js와 호스트 사이트 모두. SSO 토큰을 평문으로 전송하면 안 됩니다
- [ ] **CSP (Content Security Policy)** — 호스트 사이트의 CSP에 다음을 허용:
  - `script-src https://your-cloosphere.com`
  - `connect-src https://your-cloosphere.com wss://your-cloosphere.com`
  - `frame-src https://your-cloosphere.com`
- [ ] **id_token 노출 주의** — id_token을 콘솔에 로그하거나 외부로 보내지 마세요
- [ ] **자동 가입 정책 검토** — Cloosphere 관리자가 위젯 SSO 탭에서 `auto_signup`을 활성화한 경우, 그 테넌트의 누구든 토큰만 있으면 자동으로 Cloosphere 사용자가 됩니다. 의도된 동작인지 확인하세요
- [ ] **default_role 검토** — 자동 가입된 사용자의 기본 역할이 적절한지 확인 (`pending`이면 admin 승인 필요)

## 트러블슈팅

### `Widget not found` 에러

```
[CloosphereEmbed] Widget not found
```

- 위젯 ID 오타 확인
- Cloosphere 백엔드가 동작 중인지 확인
- 위젯이 비활성화된 상태일 수 있음 — 관리자에게 활성화 요청

### `403 — domain not allowed`

호스트 사이트 도메인이 위젯의 허용 도메인에 등록되지 않음. Cloosphere 관리자에게 추가 요청.

### `SSO is not enabled for this widget`

위젯의 SSO 탭이 비활성화 상태. Cloosphere 관리자에게 활성화 요청.

### `Provider 'xxx' is not allowed for this widget`

위젯이 해당 SSO provider를 허용하지 않음. Cloosphere 관리자에게 위젯 SSO 탭에서 provider를 추가하도록 요청.

### `Token verification failed: Issuer not trusted`

OIDC provider의 issuer가 위젯의 `trusted_issuers`에 등록되지 않음. Microsoft Entra ID라면 `tenant_id` 설정 확인.

### `Token verification failed: ... aud ... mismatch`

호스트 사이트의 client_id가 위젯의 `trusted_audiences`에 포함되지 않음. 두 가지 해결책:
1. 관리자에게 위젯 SSO 탭에서 호스트의 client_id를 trusted_audiences에 추가하도록 요청
2. 또는 trusted_audiences를 비워달라고 요청 (해당 테넌트의 모든 앱 토큰 허용)

### CORS 에러

```
Access to fetch ... blocked by CORS policy
```

Cloosphere 백엔드의 임베드 위젯 엔드포인트는 모든 origin에서 접근 가능하도록 설정되어 있어야 합니다. 만약 이 에러가 나면 Cloosphere 관리자에게 백엔드 버전과 미들웨어 설정을 확인 요청하세요.

### 위젯 iframe 안에 빈 화면 / 404

embed.js와 위젯 iframe의 base URL이 다르게 설정된 경우입니다. 일반 운영 환경에서는 두 URL이 같으므로 발생하지 않지만, 로컬 개발에서 백엔드(포트 8080)와 프론트엔드(포트 5173)를 분리해서 띄울 때 발생할 수 있습니다. 이 경우:

```html
<script>
  window.__CLOOSPHERE_EMBED_BASE_URL__ = 'http://localhost:5173';
</script>
<script src="http://localhost:8080/static/embed/embed.js" data-widget-id="..."></script>
```

## 자주 묻는 질문

**Q. 호스트 사이트가 SSO를 안 쓰면 어떻게 되나요?**
A. 위젯이 자체 로그인 화면을 표시합니다. 사용자는 위젯 안에서 Cloosphere 계정으로 직접 로그인하면 됩니다. SSO 통합은 선택사항이지만 사용자 경험을 크게 개선합니다.

**Q. 한 번 SSO 로그인하면 계속 유지되나요?**
A. id_token의 유효 기간(보통 1시간) 동안 유지됩니다. 호스트 사이트의 silent refresh(MSAL의 `acquireTokenSilent` 등)가 동작하면 자동으로 갱신되므로 사용자는 신경 쓸 필요 없습니다.

**Q. 호스트 사이트 사용자가 Cloosphere 사용자와 어떻게 매핑되나요?**
A. 기본적으로 **이메일**로 매핑됩니다. 호스트 SSO 토큰의 email claim과 일치하는 Cloosphere 사용자가 있으면 해당 계정으로 로그인됩니다. 없으면(자동 가입이 켜진 경우) 새 계정이 자동 생성됩니다.

**Q. 호스트가 다른 SSO 공급자(예: Auth0)도 쓸 수 있나요?**
A. 네. Auth0, Okta, Keycloak 등 OIDC 호환 공급자는 모두 `provider: 'oidc'`로 사용 가능합니다. Cloosphere 관리자가 위젯 SSO 탭에서 해당 공급자의 issuer를 등록만 하면 됩니다.

**Q. 같은 위젯을 여러 호스트 사이트에서 쓸 수 있나요?**
A. 네. 단 운영 환경에서는 보안을 위해 위젯의 허용 도메인에 모든 호스트 도메인을 명시적으로 등록하는 것을 권장합니다.

**Q. id_token을 위젯에 보내면 그 토큰이 외부로 유출되나요?**
A. 토큰은 호스트 사이트와 Cloosphere 백엔드 간에 HTTPS로만 전송되며, Cloosphere는 검증 후 즉시 폐기하고 자체 JWT를 새로 발급합니다. id_token은 어디에도 저장되지 않습니다.

## 다음 단계

- [임베드 위젯 관리](embed-widgets.md) — Cloosphere 관리자용 위젯 생성/설정 가이드
- [에이전트 만들기](../workspace/agents.md) — 위젯에 연결할 AI 에이전트 구성
- [도구 연결 (MCP)](../workspace/tools.md) — 호스트 사이트의 백엔드 API와 위젯 연동

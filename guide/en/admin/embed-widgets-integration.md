# Embed Widget — Host Site Integration Guide

This document is for **developers and administrators of host sites** that want to integrate the Cloosphere embed widget. For Cloosphere-side widget creation and configuration, start with the [Embed Widgets](embed-widgets.md) guide.

## Audience

- **Developers** integrating a Cloosphere AI chatbot into an internal groupware, portal, or marketing site
- **System administrators** who want the embedded widget to feel naturally tied to the host site's user identity

## Choose Your Integration Scenario

Decide which level of integration you need before writing code.

| Scenario | Widget behavior | Host effort |
|---|---|---|
| **A. Anonymous chatbot** | Widget shows its own login screen; anyone can use it | One `<script>` tag |
| **B. Host SSO auto-login** | Users already signed in via host SSO are auto-logged into the widget | Acquire SSO token + pass to widget |
| **C. AI manipulates host pages** | The AI can directly fill forms / click buttons on the host page | B + selector allow-list |

For most internal integrations, **scenario B** delivers the most value — users don't need to log in twice. This guide focuses on B.

## Step 1: Embed the Widget Script

Minimal embed:

```html
<!DOCTYPE html>
<html>
  <body>
    <!-- Host site content -->

    <!-- Cloosphere embed widget -->
    <script
      src="https://your-cloosphere.com/static/embed/embed.js"
      data-widget-id="abc12345-..."
    ></script>
  </body>
</html>
```

That's it — a chat bubble appears (typically bottom-right) and clicking opens the widget. Users will need to log in inside the widget unless you complete step 2.

### Get the widget ID

Ask your Cloosphere admin for a widget ID. They'll create one in **Settings → Embed Widgets** and share the resulting `abc12345-...` UUID. The widget ID is public and safe to include in HTML.

### Request your domain in the allow-list

For production, ask the Cloosphere admin to add your host site's domain (`portal.example.com`, etc.) to the widget's **Allowed Domains**. Otherwise, anyone with the widget ID could embed it on their own site.

## Step 2: SSO Auto-Login Integration (Scenario B)

If users are already signed in to your host site via your own SSO (Microsoft Entra ID, Google, Okta, etc.), you can pass their token to the widget so they're auto-logged-in there too.

### Flow

```
[Host site]                              [Cloosphere]
1. User signs in via internal SSO
2. Acquire id_token (already part of host login flow)
3. CloosphereEmbed.ssoLogin({
     provider: 'microsoft',
     id_token: '...'
   })                          ─────►   POST /embed-widgets/{id}/auth/sso-exchange
                                        - Verify id_token (issuer/signature/expiry)
                                        - Match user by email
                                        - Auto-create if missing (per policy)
                                        - Issue Cloosphere JWT
                               ◄─────   { token: 'eyJ...' }
4. Widget iframe receives token, auto-logs in
5. User just clicks the bubble to chat
```

### Three ways to forward the token

Choose the pattern that fits when your site obtains the SSO token.

#### Method 1: Pre-init queue (recommended — token known before page load)

```html
<script>
  // Register the host's SSO token globally
  // (in SSR you can inject this from the server response)
  window.CloosphereEmbedQ = window.CloosphereEmbedQ || {};
  window.CloosphereEmbedQ['abc12345-...'] = {
    sso: {
      provider: 'microsoft',
      id_token: '<the user id_token>'
    }
  };
</script>
<script
  src="https://your-cloosphere.com/static/embed/embed.js"
  data-widget-id="abc12345-..."
></script>
```

embed.js reads the queue automatically and performs the SSO exchange before the user even clicks the bubble.

#### Method 2: Dynamic call (token arrives after page load)

For apps where the user signs in later or the token is fetched asynchronously:

```javascript
// Call this whenever your host site has the SSO token ready
window.CloosphereEmbed.ssoLogin({
  provider: 'microsoft',
  id_token: msalAccount.idToken
}).then((jwt) => {
  if (jwt) {
    console.log('Cloosphere auto-login succeeded');
  } else {
    console.warn('Auto-login failed — widget will show its own login screen');
  }
});
```

`CloosphereEmbed.ssoLogin()` returns `Promise<string | null>` — the Cloosphere JWT on success, `null` on failure. It never throws; on failure, the widget falls back to its built-in login screen.

#### Method 3: Token refresh (already logged in but token rotated)

When the host site obtains a fresh token (e.g., after expiry):

```javascript
window.CloosphereEmbed.updateToken(newJwt);
// or to re-trigger SSO exchange:
window.CloosphereEmbed.ssoLogin({ provider: 'microsoft', id_token: newIdToken });
```

### Per-provider integration examples

#### Microsoft Entra ID (MSAL.js)

```bash
npm install @azure/msal-browser @azure/msal-react
```

**MSAL config:**
```typescript
// lib/msal.ts
import { Configuration, PopupRequest } from '@azure/msal-browser';

export const msalConfig: Configuration = {
  auth: {
    clientId: '<your Azure AD app client_id>',
    authority: 'https://login.microsoftonline.com/<tenant_id>',
    redirectUri: window.location.origin + '/auth/callback.html',
  },
  cache: { cacheLocation: 'localStorage' }
};

export const loginRequest: PopupRequest = {
  scopes: ['openid', 'profile', 'email', 'User.Read']
};
```

**Popup callback page** (`public/auth/callback.html`):
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

> Register the callback URL above under **Authentication → Single-page application** in your Azure app registration.

**Login button + token forwarding:**
```typescript
import { useMsal } from '@azure/msal-react';
import { loginRequest } from './lib/msal';

function LoginButton() {
  const { instance } = useMsal();

  const handleLogin = async () => {
    const result = await instance.loginPopup(loginRequest);
    window.CloosphereEmbed.ssoLogin({
      provider: 'microsoft',
      id_token: result.idToken
    });
  };

  return <button onClick={handleLogin}>Sign in with Microsoft</button>;
}
```

#### Google Sign-In

```html
<script src="https://accounts.google.com/gsi/client" async defer></script>
<div id="g_id_onload"
     data-client_id="<your Google client_id>"
     data-callback="handleGoogleCredential">
</div>

<script>
function handleGoogleCredential(response) {
  // response.credential is the Google-issued id_token (JWT)
  window.CloosphereEmbed.ssoLogin({
    provider: 'google',
    id_token: response.credential
  });
}
</script>
```

#### GitHub OAuth

GitHub doesn't support OIDC, so use the access token instead. The OAuth code → token exchange must happen on your backend (to protect the client secret).

```javascript
// Assume your backend has exchanged the GitHub OAuth code for an access_token
// and forwarded it to your frontend
window.CloosphereEmbed.ssoLogin({
  provider: 'github',
  access_token: githubAccessToken
});
```

#### Generic OIDC (Keycloak, Auth0, Okta, etc.)

Keycloak example:

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

OIDC providers require the `issuer` URL. The widget fetches the issuer's `.well-known/openid-configuration` automatically to validate the token.

> **The Cloosphere admin must register that issuer in the widget's SSO tab under `trusted_issuers`.**

## Step 3: AI Manipulating Host Pages (Scenario C)

The widget AI can directly manipulate forms and buttons on your host site. For example, when a user says "request 3 days off starting tomorrow", the AI can fill out the leave request form for them.

### Available tools

The agent connected to the widget has access to:

| Tool | Description |
|---|---|
| `get_page_info` | Read the current page URL and form info |
| `fill_form_field` | Set a single form field value |
| `fill_form` | Fill multiple fields at once |
| `click_element` | Click a button/link |
| `read_form` | Read current form values |
| `highlight_element` | Visually highlight an element |
| `navigate_to` | Navigate to a different page |

### What the host site needs to do

By default the widget can introspect the host page automatically. Two recommended additions:

#### Soft navigation (SPA only)

When the widget calls `navigate_to`, listen for the custom event so you can use your SPA router instead of a full page reload.

**Next.js (App Router):**
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

The same pattern works for **Vue Router**, **SvelteKit**, **React Router**, etc. Without a listener, the widget falls back to a regular `window.location.href` navigation, so it still works.

#### Meaningful form field identifiers

Help the AI identify form fields by giving them clear `name`, `id`, and `aria-label` attributes:

```html
<!-- Good -->
<input name="leaveStartDate" aria-label="Leave start date" type="date" />

<!-- Bad — AI has to guess -->
<input name="f1" type="date" />
```

## Step 4: Customizing Widget Appearance (Optional)

Visual design is mostly configured by the Cloosphere admin, but the host can override some attributes:

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

For the full list of design options, see the "Design Customization" section of the [Embed Widgets](embed-widgets.md) admin guide.

## Security Checklist

Verify before going to production:

- [ ] **Ask the Cloosphere admin to add your domain to the widget's allow-list** — required in production
- [ ] **Use HTTPS** for both embed.js and your host site. SSO tokens must never travel in plaintext
- [ ] **Update your CSP (Content Security Policy)**:
  - `script-src https://your-cloosphere.com`
  - `connect-src https://your-cloosphere.com wss://your-cloosphere.com`
  - `frame-src https://your-cloosphere.com`
- [ ] **Don't log id_token** to the console or external services
- [ ] **Review the auto-signup policy** — when `auto_signup` is on in the widget's SSO tab, anyone in your tenant with a valid token can become a Cloosphere user. Confirm this is intentional
- [ ] **Review default_role** — if it's `pending`, new users will need admin approval before using the widget

## Troubleshooting

### `Widget not found`

```
[CloosphereEmbed] Widget not found
```

- Check the widget ID for typos
- Make sure the Cloosphere backend is reachable
- The widget may be deactivated — ask the admin to enable it

### `403 — domain not allowed`

Your host domain isn't in the widget's allow-list. Ask the Cloosphere admin to add it.

### `SSO is not enabled for this widget`

The widget's SSO tab is off. Ask the admin to enable it.

### `Provider 'xxx' is not allowed for this widget`

The widget doesn't allow your SSO provider. Ask the admin to add it under the SSO tab.

### `Token verification failed: Issuer not trusted`

Your OIDC provider's issuer isn't registered. For Microsoft Entra ID, double-check the `tenant_id` setting.

### `Token verification failed: ... aud ... mismatch`

Your host site's client_id isn't in the widget's `trusted_audiences` list. Two options:
1. Ask the admin to add your client_id to the SSO tab's trusted audiences
2. Or ask them to leave trusted_audiences empty (accept any app token from the tenant)

### CORS errors

```
Access to fetch ... blocked by CORS policy
```

Cloosphere's embed widget endpoints are designed to be reachable from any origin. If you see this error, ask the Cloosphere admin to verify the backend version and middleware configuration.

### Empty / 404 inside the widget iframe

embed.js and the widget iframe are using different base URLs. This shouldn't happen in normal production, but it can occur in local development when the backend (port 8080) and frontend (port 5173) are split. In that case:

```html
<script>
  window.__CLOOSPHERE_EMBED_BASE_URL__ = 'http://localhost:5173';
</script>
<script src="http://localhost:8080/static/embed/embed.js" data-widget-id="..."></script>
```

## FAQ

**Q. What if our host site doesn't use SSO?**
A. The widget shows its own login screen. Users sign in with their Cloosphere account directly. SSO integration is optional but greatly improves UX.

**Q. How long does an SSO login last?**
A. As long as the id_token is valid (typically 1 hour). If your host site supports silent refresh (e.g., MSAL's `acquireTokenSilent`), it's automatically renewed and the user never notices.

**Q. How are host users mapped to Cloosphere users?**
A. By **email**. The widget matches the SSO token's `email` claim against existing Cloosphere users. If none exists and auto-signup is on, a new account is created.

**Q. Can we use other SSO providers like Auth0?**
A. Yes. Auth0, Okta, Keycloak, and any OIDC-compatible provider work with `provider: 'oidc'`. The Cloosphere admin just needs to register the issuer in the widget's SSO tab.

**Q. Can we embed the same widget on multiple host sites?**
A. Yes. For production, we recommend explicitly listing every host domain in the widget's allowed domains for security.

**Q. Is the id_token leaked somewhere when forwarded to the widget?**
A. The token only travels between your host site and the Cloosphere backend over HTTPS. Cloosphere validates it, immediately discards it, and issues its own JWT. The id_token is never persisted.

## Next Steps

- [Embed Widgets (admin guide)](embed-widgets.md) — Cloosphere admin guide for creating/configuring widgets
- [Creating Agents](../workspace/agents.md) — configure the AI agent that powers the widget
- [Tool Connections (MCP)](../workspace/tools.md) — connect host site backend APIs to the widget

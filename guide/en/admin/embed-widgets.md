# Embed Widgets

Embed Cloosphere AI chat into any external website with a simple script tag. Add an AI assistant to your groupware, internal portal, marketing site, or any other web property in seconds.

## Overview

The embed widget enables scenarios like:

- **Internal Groupware/Portal Integration**: Help employees fill out leave requests, approval forms, etc.
- **Customer Support Chatbot**: Add a 24/7 AI advisor to your company website
- **Internal Wiki/Documentation Sites**: Let users ask AI questions while reading docs
- **Demo/Marketing Pages**: Showcase AI solution capabilities

<!-- Screenshot: Embed widget on an external site (bottom-right bubble + open panel)
     Filename: images/embed-widget-overview.png
-->

## Creating a Widget

### 1. Create the Widget

Go to **Admin → Settings → Embed Widgets** and click **Create Widget**.

Fill in the basic information:

| Field | Description |
|-------|-------------|
| **Widget Name** | Display name in the admin panel |
| **Description** | Optional notes about the widget's purpose |
| **Model** | The default agent or model to use |
| **Additional agents (/ to switch)** | Optional list of additional agents that users can switch to by typing `/` in the chat input |
| **System Prompt** | Optional additional instructions for the agent |
| **Welcome Message** | Greeting shown when users first open the chat |
| **Allowed Domains** | Comma-separated list of domains where the widget can run (leave empty to allow all) |
| **Active** | Enable or disable the widget |

After saving, the widget ID and embed code snippet are generated.

#### Switching Agents via Slash Commands

Use the **Additional agents** checkboxes in the widget editor to register secondary agents users can switch to. When a user types `/` as the first character in the chat input, a picker shows the registered agents. Navigate with arrow keys / Tab / Enter / Esc. The currently active agent is shown as an indicator above the input box.

<!-- Screenshot: Slash command picker in the embed widget input
     Filename: images/embed-widget-slash-picker.png
-->

<!-- Screenshot: Widget creation modal
     Filename: images/embed-widget-create-modal.png
-->

### 2. Copy the Embed Code

Click the **`</>` icon** in the widget list to view the embed code:

```html
<script
  src="https://your-cloosphere.com/static/embed/embed.js"
  data-widget-id="abc12345-..."
></script>
```

Add this single line inside the `<body>` of your external website's HTML, and a chat bubble will appear in the bottom-right corner.

### 3. Customize the Design

Click the **design icon** in the widget list to open the design editor. Configure settings on the left and see live preview on the right.

#### Layout Tab

| Setting | Description |
|---------|-------------|
| **Display Mode** | Bubble / Side Left / Side Right / Side Bottom / Inline / Fullscreen |
| **Theme** | Auto / Light / Dark |
| **Position** | Bottom-right / Bottom-left (bubble mode only) |
| **Bubble Open Style** | Popup / Side Right / Side Left / Side Bottom (bubble mode only) |
| **Draggable Bubble** | Allow users to drag the bubble button to a new position (saved per browser) |
| **Resizable** | Let users drag the widget edge to resize it. In side modes the host page content is automatically pushed aside so it never gets covered as the widget grows |
| **Bubble Size** | 40~96px slider |
| **Width/Height** | Custom widget dimensions (e.g., `400px`, `100%`, `80vh`) |

**Bubble Open Style details:**

- **Popup** (default): A small panel appears above the bubble; the bubble turns into an X icon and clicking again closes it
- **Side (Right/Left/Bottom)**: Clicking the bubble opens a full-size panel anchored to the side or bottom of the viewport and hides the bubble. Can only be closed via the header X button. Recommended when more workspace is needed

**6 Display Modes:**

- **Bubble**: Floating button in the bottom corner that opens a panel on click (Intercom/Zendesk style)
- **Side Panel (Left/Right)**: Fixed panel anchored to the left or right of the screen
- **Side Bottom**: Fixed panel anchored to the bottom of the screen, useful as a persistent assistant on long pages
- **Inline**: Embedded directly into a specific area of the page
- **Fullscreen**: Takes over the entire viewport

#### Icons Tab

- **Bubble Icon**: 7 presets (chat, sparkles, message, robot, headset, help, bolt) + custom upload
- **Send Button Icon**: 7 presets (paper plane, arrows, star, rocket, etc.) + custom upload

> Preset icons (SVG) support color customization. Uploaded images preserve their original colors.

#### Header Tab

- **Show Header**: Toggle the header area on/off
- **Show Close Button in Header**: Display an X button in the top-right of the header (default ON). Required for side modes since it's the only way to close the widget there
- **Header Text**: Title displayed at the top of the widget (defaults to widget name)
- **Header Background / Header Text Color**

#### Colors Tab

**Theme Presets** (top of Colors tab):

Click any of 12 pre-designed color combinations to apply all colors and the light/dark mode at once:

| Preset | Mood | Light/Dark |
|---|---|---|
| **Light** / **Dark** | Framework defaults (no custom colors) | each |
| **Slate** | Minimal black & white | Light |
| **Midnight** | Slate + indigo, calm dark | Dark |
| **Ocean** | Corporate blue | Light |
| **Aurora** | Violet + pink | Light |
| **Sunset** | Warm orange | Light |
| **Forest** | Natural green | Light |
| **Rose** | Elegant rose | Light |
| **Cyberpunk** | Dark + neon cyan | Dark |
| **Ember** | Warm dark + amber glow | Dark |
| **Mono** | Pure black & white | Light |

You can fine-tune individual colors after applying a preset.

**Individual color settings:**

- **Bubble Background / Bubble Icon Color**: Floating button colors
- **Background Color**: Overall chat area background
- **Message Text Color**: Unified text color for user and bot messages
- **Send Button Background / Icon Color**

#### Chat Tab

- **Welcome Message**: Shown when the chat is first opened
- **Max Messages Per Session**: Message count limit (0 = unlimited)
- **Show Bot Icon**: Toggle the agent icon next to response messages

#### Features Tab

- **File Upload**: Allow users to attach files
- **Markdown**: Enable markdown rendering
- **Code Highlighting**: Syntax highlighting for code blocks
- **Web Search**: Enable web search tools in the widget

#### SSO Tab

Lets the host site authenticate users with its own SSO (Microsoft Entra ID, Google, GitHub, OIDC-compatible IdPs, etc.) and pass the resulting token to the widget. The widget exchanges it for a Cloosphere JWT, so users do not need to log in again inside the widget.

| Setting | Description |
|---|---|
| **Enable SSO Token Exchange** | Allows the widget to receive external SSO tokens and exchange them for a Cloosphere JWT |
| **Auto Sign-Up Unknown Users** | Automatically create a Cloosphere account if the token's email doesn't match any existing user |
| **Default Role for New Users** | Initial role for auto-provisioned users (User / Pending / Admin) |
| **Allowed Providers** | Whitelist of SSO providers the host site is allowed to use (Microsoft / Google / GitHub / OIDC) |

**Per-provider options:**

- **Microsoft Entra ID**: `Tenant ID` (specific tenant GUID or `common`), `Trusted Audiences` (whitelist of host client IDs; leave empty to accept tokens from any app in the tenant)
- **Google**: `Trusted Audiences` (host site Google client IDs, optional)
- **GitHub**: No additional options
- **Generic OIDC**: `Trusted Issuers` (issuer URLs for Keycloak / Auth0 / Okta etc., required), `Trusted Audiences` (optional)

> **For host site developers integrating this widget**, see the [Embed Widget Host Integration Guide](embed-widgets-integration.md). It covers SSO token forwarding, soft navigation, troubleshooting, and everything else needed for integration.

#### Guest Tab

Configure **guest mode**, which allows unauthenticated visitors to use the widget. Useful when embedding the chatbot on public websites or marketing pages.

| Setting | Description |
|---|---|
| **Enable Guest Access** | Allow visitors to use the widget without signing in |
| **Collect Visitor Info** | Ask for basic info (name/email, etc.) before starting the chat |
| **Required Fields** | Fields the visitor must fill in (e.g., name) |
| **Optional Fields** | Fields the visitor may optionally fill in (e.g., email) |
| **Auto-Proceed** | Skip the info modal and start an anonymous guest session immediately |
| **Session Expiry** | Lifetime of the guest token (e.g., `24h`) |

> **Note:** Guest mode and SSO mode are mutually exclusive. A single widget can use only one of Login / Guest / SSO authentication flows at a time.

<!-- Screenshot: Design editor modal (settings on left + preview on right)
     Filename: images/embed-widget-design-editor.png
-->

> **Expanded design options:** Fine-grained design options for colors, icons, and buttons continue to expand so you can match the widget more closely to the host site's brand.

## User Authentication

The widget supports five authentication methods (in priority order):

### 1. SSO Token Exchange (Recommended for host SSO integration)

The host site authenticates the user via its own SSO (Microsoft Entra ID, Google, OIDC, etc.) and passes the id_token to the widget. The widget verifies, maps, and exchanges it for a Cloosphere JWT in the backend, so the user is auto-logged-in without ever seeing the widget login screen.

To enable this, turn on the **SSO tab** and register the providers, then point the host site developer to the [Host Integration Guide](embed-widgets-integration.md).

### 2. External Service Passes Cloosphere JWT Directly

If the host site already has a Cloosphere JWT (e.g., issued from its own backend), it can be passed directly via the `data-token` attribute:

```html
<script
  src="https://your-cloosphere.com/static/embed/embed.js"
  data-widget-id="..."
  data-token="JWT_TOKEN_HERE"
></script>
```

Best when the host can perform user mapping and JWT issuance on its side. For typical SSO integrations, method 1 is simpler.

### 3. Guest Mode

If guest mode is enabled on the widget's **Guest tab**, visitors can start chatting without signing in.

- First-time visitors are prompted for minimal info (name/email, optional), or the session starts silently if auto-proceed is on
- The server issues a short-lived guest token that is valid only for that session
- Best for 24/7 chatbots on public websites or marketing pages

### 4. Built-in Login (Automatic)

If none of the above is available, the widget automatically displays a **login screen** when first opened:

- **OAuth Buttons**: If Cloosphere has OAuth providers configured (Microsoft, Google, GitHub, etc.), buttons are automatically shown. Clicking opens a popup window for the OAuth flow.
- **Email/Password Form**: Standard login form for Cloosphere accounts.

The acquired token is stored in the browser's sessionStorage on a per-widget basis, so users don't need to log in again within the same session.

### 5. Session Reuse

If the user has previously logged in via the widget, the token is automatically reused within the same browser session.

<!-- Screenshot: Widget login screen (OAuth buttons + email/password)
     Filename: images/embed-widget-login.png
-->

## Security

The embed widget includes the following security mechanisms for production use:

### Allowed Domain Restriction

When creating or editing a widget, specify the domains where the widget can be loaded in the **Allowed Domains** field:

```
*.example.com, app.mycompany.com
```

The widget will be rejected if loaded from any other domain. Wildcards (`*.example.com`) are supported.

### Page Manipulation Security

When the embed widget AI manipulates forms or buttons on the host page:

- Domain validation prevents unauthorized page manipulation
- Per-widget allow-list of selectors limits which areas the AI can modify
- All actions execute in the user's browser, where the user can directly observe and verify them

### CORS Policy

The widget config endpoint and **SSO token exchange endpoint** are exposed cross-origin so external sites can call them, but both are protected by **widget ID, allowed-domain checks, and provider/audience whitelists**. Requests from unapproved origins or with tokens from unregistered providers are rejected.

## Operations Notes

### Mobile Responsiveness

On mobile (viewport width ≤ 480px), the widget automatically renders as a full-screen overlay with the host page's body margins removed so it can use the entire viewport. iOS Safari's address-bar height changes are handled via `100dvh`, so side/fullscreen modes do not jump or get clipped. No configuration is required.

<!-- Screenshot: Widget full-screen overlay on mobile
     Filename: images/embed-widget-mobile.png
-->

### Chat Log Monitoring

Conversations originating from embed widgets appear in **Admin > Monitoring > Conversation Logs**, marked with a dedicated **purple "Widget" badge** in the platform column. Hovering the badge shows a tooltip with the widget name. This makes widget traffic clearly distinguishable from other platforms (Web, API, Cursor, Claude Code, etc.) for source-based analysis.

<!-- Screenshot: Widget badge in Monitoring > Conversation Logs
     Filename: images/admin-conversation-logs-widget-badge.png
-->

### Public/Admin API Separation

Embed-widget backend endpoints are split into two groups:

| Group | Prefix | Purpose |
|-------|--------|---------|
| **Public** | `/api/embed/v1/*` (or legacy `/api/v1/embed-widgets/*`) | Config / auth / sso / guest endpoints called by external host sites. CORS-enabled |
| **Admin** | `/api/v1/embed-widgets/*` (CRUD) | Admin-only create / update / delete endpoints for widget management |

The legacy prefix is mounted alongside the new one for backward compatibility with existing host-site builds. New integrations should use `/api/embed/v1/*`. For details, see the [Embed Widget Host Integration Guide](embed-widgets-integration.md).

---

## External Site Integration

### Interactive Page Manipulation

The most powerful feature of the embed widget is the AI's ability to directly manipulate the page the user is viewing. For example:

- A user on a leave request page says: "Apply for 3 days of annual leave starting tomorrow"
- The AI inspects the form structure and fills the fields automatically
- After user review, it clicks the submit button

This works through the following tools:

| Tool | Description |
|------|-------------|
| `get_page_info` | Get the URL and forms of the user's current page |
| `fill_form_field` | Set the value of a single form field |
| `fill_form` | Fill multiple fields at once |
| `click_element` | Click a button or link |
| `read_form` | Read current form values |
| `highlight_element` | Highlight an element |
| `navigate_to` | Navigate to a different page |

These tools should be referenced in the agent's system prompt with usage guidance.

### MCP Integration

To integrate with the external site's backend API, use **Tool Connections (MCP)**. Expose form schemas, user info, and business data from the groupware system through an MCP server, and the embed widget AI can use them for more accurate operations.

See the [Tool Connections](../workspace/tools.md) guide for details.

### Soft Navigation Support

When the widget calls `navigate_to`, you can support smooth navigation without page reload if your external site uses an SPA router. Add the following listener to your external site:

```javascript
window.addEventListener('cloosphere:navigate', (e) => {
  const { url } = e.detail;
  router.push(url); // Next.js example
  window.postMessage({ type: 'cloosphere:navigation-handled' }, '*');
});
```

If the listener is absent, it automatically falls back to a regular page navigation.

## Best Practices

### Widget Design

- **Match Host Site Branding**: Adjust color tokens to fit your brand
- **Choose the Right Display Mode**: Use **Bubble** for occasional chatbots and **Side Panel** for always-visible work assistants
- **Leverage Welcome Messages**: Tell users what kinds of tasks they can request

### Agent Configuration

- If using page manipulation, mention the available capabilities in the system prompt
- Always confirm sensitive actions (submit, delete, etc.) before execution
- Define a workflow that calls `get_page_info` first to understand the current page context

### Operations

- **Always Set Allowed Domains**: In production, always restrict allowed domains to prevent unauthorized use
- **Monitor Usage**: Regularly check widget usage statistics
- **Version Management**: Consider browser caching when changing widget designs

## FAQ

**Q. Can I display multiple widgets on the same page?**
A. Not recommended. It's most stable to use one widget per page. If different widgets are needed for different pages, use different embed codes per page.

**Q. Are widget design changes reflected immediately?**
A. Yes. When users refresh the page, the new design takes effect.

**Q. Where are chat histories from the widget stored?**
A. They're stored under the user's account just like regular Cloosphere chats. Admins can review them in monitoring.

**Q. Can widget users log in with their own Cloosphere accounts?**
A. Yes. The widget provides its own login screen, so users can sign in with their Cloosphere credentials without any external integration.

**Q. Do background tasks (auto title generation, etc.) run in the embed widget?**
A. Some background tasks like chat title and tag auto-generation are disabled in the embed widget to prevent host site notifications from leaking through.

**Q. When I save the design editor modal, my Guest/SSO/display-mode settings seem to reset. Why?**
A. A previous build had an issue where saving from the design modal would overwrite auth-tab settings (Guest/SSO) that are not exposed in that modal. This has been fixed, so any Guest/SSO/display-mode configuration not shown in the design modal is now preserved across saves.

**Q. Has the typing animation for streamed responses been improved?**
A. Yes. Streaming rendering has been smoothed so long responses flow into the widget more naturally.

## Next Steps

- [Embed Widget Host Integration Guide](embed-widgets-integration.md) — share with host site developers
- [Creating Agents](../workspace/agents.md)
- [Tool Connections (MCP)](../workspace/tools.md)
- [Monitoring](monitoring.md)

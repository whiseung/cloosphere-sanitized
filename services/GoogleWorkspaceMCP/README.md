# Google Workspace MCP (Gmail · Calendar)

Cloosphere 에 **Gmail / Google Calendar** 도구를 붙이기 위한 **독립 MCP 서버**.
[`taylorwilsdon/google_workspace_mcp`](https://github.com/taylorwilsdon/google_workspace_mcp)
를 **external OAuth 2.1 passthrough** 모드로 띄운다.

Cloosphere 와 **완전 별개**로 배포되며, Cloosphere 는 이 컨테이너의 `/mcp` 엔드포인트에
기존 **워크스페이스 > 도구**의 Tool Connection 으로만 연결한다 → **Cloosphere 백엔드 코드 변경 0**.

---

## 왜 이 구조인가 (passthrough 동작 원리)

```
[사용자] --Google 로그인--> [Cloosphere]
                               │  access_token(gmail/calendar 스코프) 저장
                               │  (user_oauth_token, refresh 자동 갱신)
                               ▼
[에이전트] --도구 호출--> [Cloosphere MCPClient]
                               │  매 호출 Authorization: Bearer <그 사용자의 Google 토큰> 주입
                               ▼
                        [이 서버 /mcp]  ← 자체 OAuth 안 돌림
                               │  인바운드 Bearer 를 Google userinfo 로 검증
                               ▼
                        [Gmail / Calendar API]  ← 그 토큰으로 직접 호출
```

- **사용자별 위임 접근**: 각자 자기 Gmail/캘린더에만 접근. 서버는 자격증명을 저장하지 않음(per-request stateless).
- Cloosphere 쪽 토큰 주입/갱신/격리는 이미 구현돼 있음:
  - `backend/open_webui/utils/oauth_tokens.py` — `get_valid_access_token`, `resolver_for_auth_type`
  - `backend/open_webui/utils/mcp_client.py` — `token_resolver` 로 매 호출 Bearer 주입
  - `MCPConnectionForm.svelte` — `OAuth 2.0 (User SSO)` + Provider=Google 옵션

> ⚠️ **stateful 모드 금지**: 이 서버를 `MCP_ENABLE_OAUTH21`/`EXTERNAL_OAUTH21_PROVIDER`
> 없이(= 자체 `client_secret.json` 저장 모드로) 돌리면 과거 멀티유저 데이터 격리 이슈가
> 있었다. 반드시 본 compose 의 external provider 모드로만 운용할 것.

---

## 사전 준비 (한 번만)

1. **Cloosphere Google OAuth 가 전체 GWS 스코프로 로그인하도록 되어 있어야 함.**
   - `backend/open_webui/config.py` 의 `GMAIL_DELEGATED_SCOPES` 에 10개 서비스 스코프가
     이미 정의돼 있고 로그인 스코프에 자동 병합됨 (gmail·calendar·drive·docs·sheets·
     slides·forms·tasks·contacts·chat). 이 서버 `--tools` (Dockerfile CMD) 목록과 정합.
   - 스코프 출처: `taylorwilsdon/google_workspace_mcp@1.21.0` 의 `auth/scopes.py` SCOPE_GROUPS.
   - 서비스 추가/제거 시: `GMAIL_DELEGATED_SCOPES` + Dockerfile `--tools` +
     `backend/open_webui/utils/marketplace_tool_meta.py` 의 google-workspace 카테고리 맵을 함께 갱신.
   - **주의**: `drive`(full)는 Google "restricted scope" — 외부 게시 OAuth 앱이면 별도 검증
     (CASA security assessment)이 필요하다. 내부 org(Internal) 앱은 검증 면제.
2. **refresh_token 발급(offline access)** 이 되도록 Google OAuth 앱이 설정돼 있어야 함
   (없으면 1시간 뒤 토큰 만료 시 재연결 필요).
3. **기존 사용자는 재로그인 필요**: 스코프가 추가되기 *전*에 로그인한 사용자의 저장된 토큰엔
   새 스코프가 없다 → Google 재로그인 + 동의해야 도구가 동작. `prompt=consent` 설정으로
   다음 로그인 시 자동으로 새 동의 화면이 뜬다.

---

## 배포

```bash
cd services/GoogleWorkspaceMCP
cp .env.example .env
#  .env 편집:
#   - GOOGLE_OAUTH_CLIENT_ID = Cloosphere 로그인과 "동일한" 클라이언트 ID
#   - GOOGLE_OAUTH_CLIENT_SECRET = (confidential 이면) 동일한 시크릿
make up        # 빌드 + 기동
make ps        # healthcheck 확인
make health    # 포트 응답 점검 (401/406 이면 정상)
make mcp-url   # Cloosphere 에 넣을 URL 출력
```

- 엔드포인트: `http://localhost:8000/mcp` (**끝 슬래시 없이**, streamable HTTP).
  ⚠️ `/mcp/` (끝 슬래시) 는 307 redirect 인데 Cloosphere MCPClient 는 POST redirect 를
  따라가지 않으므로 반드시 슬래시 없는 `/mcp` 로 등록할 것.
- ⚠️ 항상 Bearer 를 요구하는 서버지만, 그래도 **내부망/리버스 프록시 뒤**에 두는 것을 권장.

---

## Cloosphere 에 연결 (워크스페이스 > 도구)

새 **MCP** Tool Connection 생성:

| 항목 | 값 |
|---|---|
| **MCP Server URL** | `http://<호스트>:8000/mcp` (Cloosphere 가 docker 안이면 `http://host.docker.internal:8000/mcp`) |
| **Auth Type** | `OAuth 2.0 (User SSO)` |
| **Provider** | `Google` |

저장하면 `auth_type=oauth_google` 로 기록되고, 이후 호출은 각 사용자의 Google 토큰이
자동 주입된다. **Key/시크릿 입력 불필요.**

> 💡 편의 프리셋: 백엔드 `MCP_PRESETS` 에 `google-workspace` 항목을 추가해 두었다
> (`GET /api/v1/tool_connections/mcp/presets`). 다만 현재 이 프리셋을 렌더링하는 UI 가
> 없으므로(미노출), 실제 연결은 위 표대로 **수동 생성**한다.

연결 후 워크스페이스 > 에이전트에서 이 Tool Connection 을 리소스로 붙이면 에이전트가
Gmail/Calendar 도구를 사용한다.

---

## 도구 목록 조회/테스트 시 주의

이 서버는 **`initialize`/`tools/list` 에도 Bearer 를 요구**한다. 즉 도구 목록을 불러오는
동작도 *요청한 사용자가 Google 연동돼 있어야* 한다. Google 로그인 안 된 admin 이
연결을 테스트하면 **401** 이 난다 → 도구 목록 조회는 Google 로그인된 계정으로.

---

## 트러블슈팅

| 증상 | 원인/해결 |
|---|---|
| 도구 목록/호출 401 | 요청 사용자가 Google 미연동 또는 토큰 만료/스코프 부족 → Google 재로그인+동의 |
| Gmail/Calendar 호출 403 | 로그인 시 동의한 스코프에 해당 권한 없음 → `GMAIL_DELEGATED_SCOPES`/Console 확인 후 재로그인 |
| `make up` 에서 client id 에러 | `.env` 의 `GOOGLE_OAUTH_CLIENT_ID` 누락 |
| `make health` 가 000 | 컨테이너 미기동 → `make logs` |
| 토큰 검증 실패(invalid) | `GOOGLE_OAUTH_CLIENT_ID` 가 Cloosphere 로그인 클라이언트와 불일치 |

---

## 참조

- 서버: <https://github.com/taylorwilsdon/google_workspace_mcp> · <https://pypi.org/project/workspace-mcp/>
- 사용 가능한 도구군: `gmail` `drive` `calendar` `docs` `sheets` `forms` `tasks` `contacts` `chat` `search` `slides`
  (이 배포는 `--tools gmail calendar` 만 활성화 — Dockerfile CMD)

# Microsoft 365 MCP (Outlook · Calendar · Teams · SharePoint · OneDrive)

Cloosphere 에 **Microsoft 365 / Microsoft Graph** 도구를 붙이기 위한 **독립 MCP 서버**.
[`softeria/ms-365-mcp-server`](https://github.com/softeria/ms-365-mcp-server) (MIT) 를
**external OAuth passthrough** 모드로 띄운다.

Cloosphere 와 **완전 별개**로 배포되며, Cloosphere 는 이 컨테이너의 `/mcp` 엔드포인트에
기존 **워크스페이스 > 도구**의 Tool Connection 으로만 연결한다 → **Cloosphere 백엔드 코드 변경 0**.
(Google 측 `services/GoogleWorkspaceMCP` 와 대칭 구조)

---

## 왜 이 구조인가 (passthrough 동작 원리)

```
[사용자] --Microsoft 로그인--> [Cloosphere]
                               │  access_token(Graph delegated 스코프 포함) 저장
                               │  (user_oauth_token, refresh 자동 갱신)
                               ▼
[에이전트] --도구 호출--> [Cloosphere MCPClient]
                               │  매 호출 Authorization: Bearer <그 사용자의 Microsoft 토큰> 주입
                               ▼
                        [이 서버 /mcp]  ← 자체 OAuth 안 돌림
                               │  인바운드 Bearer 의 만료(exp)만 확인하고 그대로 전달
                               ▼
                        [Microsoft Graph API]  ← 그 토큰으로 직접 호출 (per-request stateless)
```

- **사용자별 위임 접근**: 각자 자기 메일/캘린더/파일에만 접근. 서버는 자격증명을 저장하지 않음.
- 멀티유저 격리: `--http` 모드는 stateless(`sessionIdGenerator: undefined`) + 요청별 토큰 격리.
- Cloosphere 쪽 토큰 주입/갱신/격리는 이미 구현돼 있음:
  - `backend/open_webui/utils/oauth_tokens.py` — `get_valid_access_token`, `resolver_for_auth_type` (`oauth_microsoft → microsoft`, `_refresh_microsoft`)
  - `backend/open_webui/utils/mcp_client.py` — `token_resolver` 로 매 호출 Bearer 주입
  - `MCPConnectionForm.svelte` — `OAuth 2.0 (User SSO)` + Provider=Microsoft 옵션

> ⚠️ **단일유저/자체OAuth 모드 금지**: 아래 "절대 설정 금지" 항목(`MS365_MCP_OAUTH_TOKEN`,
> `--obo`, `--trust-proxy-auth`)을 켜면 멀티유저 격리가 깨지거나 토큰 audience 가 맞지 않는다.
> 반드시 본 compose 의 plain `--http` passthrough 모드로만 운용할 것.

---

## 사전 준비 (한 번만)

1. **Cloosphere Microsoft OAuth 가 Graph delegated 스코프로 로그인하도록 되어 있어야 함.**
   - `backend/open_webui/config.py` 의 `GRAPH_DELEGATED_SCOPES` 에 이미
     `Mail.Read`, `Mail.Send`, `Calendars.ReadWrite`, `Files.Read.All`, `Sites.Read.All`,
     `Contacts.Read`, `Tasks.ReadWrite`, `Notes.ReadWrite`, `User.ReadBasic.All`,
     `offline_access` 가 정의돼 있고 Microsoft 로그인 스코프(`MICROSOFT_OAUTH_SCOPE`)에 자동 병합됨.
   - **Teams chat/channel · 온라인미팅** 도구를 쓰려면 여기에 `ChannelMessage.Read.All`,
     `Chat.Read`, `OnlineMeetings.Read`, `Presence.Read` 등을 추가하고 Entra 앱 등록에도 동의 추가 후
     사용자 재로그인 필요(기본 스코프로는 해당 도구가 Graph 403).
2. **refresh_token 발급(`offline_access`)** 이 되도록 Microsoft OAuth 앱이 설정돼 있어야 함
   (없으면 1시간 뒤 토큰 만료 시 재연결 필요). Cloosphere 는 `offline_access` 누락 시 경고 로깅함.
3. **기존 사용자는 재로그인 필요**: Graph 스코프가 추가되기 *전*에 로그인한 사용자의
   저장된 토큰엔 그 스코프가 없다 → Microsoft 재로그인 + 동의해야 도구가 동작.

---

## 배포

```bash
cd services/Microsoft365MCP
cp .env.example .env
#  .env 편집(전부 선택사항 — passthrough 모드는 시크릿 불필요):
#   - M365_MCP_PORT          = 호스트 노출 포트(기본 8001, 마켓플레이스 기본 URL 과 정합)
#   - M365_MCP_ORG_MODE      = Teams/SharePoint/공유메일함 도구 노출 여부(기본 true)
#   - MS365_MCP_CLIENT_ID    = (선택) Cloosphere 의 MICROSOFT_CLIENT_ID 와 동일하게
#   - MS365_MCP_TENANT_ID    = (선택) Cloosphere 의 MICROSOFT_CLIENT_TENANT_ID 와 동일하게
make up        # 빌드 + 기동
make ps        # healthcheck 확인
make health    # 포트 응답 점검 (401 이면 정상)
make mcp-url   # Cloosphere 에 넣을 URL 출력
```

- 엔드포인트: `http://localhost:8001/mcp` (**끝 슬래시 없이**, streamable HTTP).
  ⚠️ Cloosphere MCPClient 는 POST redirect 를 따라가지 않으므로 반드시 슬래시 없는 `/mcp` 로 등록.
- ⚠️ 항상 Bearer 를 요구하는 서버지만, 그래도 **내부망/리버스 프록시 뒤**에 두는 것을 권장.

---

## Cloosphere 에 연결

### A) 마켓플레이스 (권장)

**관리자 > 설정 > 마켓플레이스 > Microsoft 365** 카드에서 **Service URL** 에 위 `/mcp` URL 을
넣고 **연결**하면 끝. 내부적으로 `auth_type=oauth_microsoft` Tool Connection 이 생성된다
(`meta.source=marketplace`). 해제도 카드에서.

### B) 워크스페이스 > 도구 (수동)

새 **MCP** Tool Connection 생성:

| 항목 | 값 |
|---|---|
| **MCP Server URL** | `http://<호스트>:8001/mcp` (Cloosphere 가 docker 안이면 `http://host.docker.internal:8001/mcp`) |
| **Auth Type** | `OAuth 2.0 (User SSO)` |
| **Provider** | `Microsoft` |

저장하면 `auth_type=oauth_microsoft` 로 기록되고, 이후 호출은 각 사용자의 Microsoft 토큰이
자동 주입된다. **Key/시크릿 입력 불필요.**

연결 후 워크스페이스 > 에이전트에서 이 Tool Connection 을 리소스로 붙이면 에이전트가
Outlook/Calendar/Teams/SharePoint/OneDrive 도구를 사용한다.

---

## 도구 목록 조회/테스트 시 주의

이 서버는 **`initialize`/`tools/list` 에도 Bearer 를 요구**한다. 즉 도구 목록을 불러오는
동작도 *요청한 사용자가 Microsoft 연동돼 있어야* 한다. Microsoft 로그인 안 된 admin 이
연결을 테스트하면 **401** 이 난다 → 도구 목록 조회는 Microsoft 로그인된 계정으로.

---

## 트러블슈팅

| 증상 | 원인/해결 |
|---|---|
| 도구 목록/호출 401 | 요청 사용자가 Microsoft 미연동 또는 토큰 만료/스코프 부족 → Microsoft 재로그인+동의 |
| Graph 호출 403 | 로그인 시 동의한 스코프에 해당 권한 없음 → `GRAPH_DELEGATED_SCOPES`/Entra 앱 등록 확인 후 재로그인 |
| Teams/채널/온라인미팅 도구만 403 | 해당 스코프(`ChannelMessage.Read.All`/`Chat.Read`/`OnlineMeetings.Read`) 미동의 → 스코프 추가 후 재로그인 |
| `make health` 가 000 | 컨테이너 미기동 → `make logs` |
| 토큰 검증/Graph 인증 실패 | `MS365_MCP_OAUTH_TOKEN` 이 켜져 있지 않은지 확인(반드시 비울 것) / 인바운드 토큰이 graph audience 인지 확인 |
| 모든 사용자가 같은 사서함을 봄 | `MS365_MCP_OAUTH_TOKEN` 또는 `--trust-proxy-auth` 가 켜진 것 → 끄고 재기동(멀티유저 격리 깨짐) |

---

## ⚠️ 절대 설정 금지 (멀티유저/audience 가 깨짐)

| 설정 | 왜 금지 |
|---|---|
| `MS365_MCP_OAUTH_TOKEN` | startup 시 읽는 **정적 단일 토큰** = 모든 사용자가 한 계정 공유(단일유저화) |
| `MS365_MCP_CLIENT_SECRET` | passthrough 에 **불필요**. 설정 시 confidential/OBO 경로로 빠질 수 있음 |
| `--obo` (On-Behalf-Of) | confidential client + `api://<clientId>/access_as_user` audience 토큰 필요 — Cloosphere 가 가진 **graph audience 토큰과 불일치** (`--org-mode`/`--work-mode` 는 별개로 허용·권장) |
| `--trust-proxy-auth` | Bearer 검사를 건너뛰고 **로컬 MSAL 단일계정 캐시**로 fallback(멀티유저 깨짐) |

> public client 기본이라 `MS365_MCP_CLIENT_SECRET` 없이 동작한다. 토큰 검증 일관성을 위해
> `MS365_MCP_CLIENT_ID`/`MS365_MCP_TENANT_ID` 만 Cloosphere 와 맞춰주면 충분(선택).

---

## 배포 전 staging 검증 (권장)

코드 정독상 아래는 성립하지만, 프로덕션 전 실제 컨테이너에서 한 번 확인할 것:

1. **토큰 verbatim 전달**: `--http` + (token env 미설정)에서 Cloosphere 발급 graph-audience
   Bearer 로 `list-mail-messages` 같은 도구를 호출하고, 컨테이너→`graph.microsoft.com`
   네트워크 트레이스로 **그 토큰이 변환 없이** 전달되는지 확인 (참고 issue: softeria#304).
2. **동시 멀티유저 격리**: 서로 다른 두 사용자 토큰으로 **동시** 호출해 A 가 B 의 사서함을
   절대 못 보는지 확인 (가장 중요한 정확성 테스트).
3. **로컬 캐시 fallback 없음**: 요청을 처리한 뒤 컨테이너에 MSAL 캐시 파일이 남지 않는지,
   `--trust-proxy-auth`/account 관리 플래그를 안 넘겼는지 확인.
4. **401 → refresh 루프**: 만료 토큰에 서버가 401 을 주면 Cloosphere 가 fresh 토큰으로
   재주입하는지(이미 refresh 구현됨) 확인.

---

## 참조

- 서버: <https://github.com/softeria/ms-365-mcp-server> · <https://www.npmjs.com/package/@softeria/ms-365-mcp-server>
- 이 배포 버전: `@softeria/ms-365-mcp-server@0.114.0` (`.env` / Dockerfile ARG `MS365_MCP_VERSION` 로 핀)
- 주요 플래그: `--http [port]`(기본 3000, 여기선 8001) · `--org-mode`(=`MS365_MCP_ORG_MODE=true`) ·
  `--read-only`(=`READ_ONLY`) · `--enabled-tools <regex>`(도구 필터)
- 대칭 참조: `services/GoogleWorkspaceMCP/README.md`

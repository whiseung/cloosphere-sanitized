# E2E Test Command

현재 세션에서 작업한 백엔드 변경사항을 실제 API로 검증합니다.

## 테스트 환경

- **Backend**: `http://localhost:8080`
- **JWT Token**: `<REDACTED>`
- **API Key**: `<REDACTED>`
- **Test User ID**: `09b0e2de-64fc-4ba0-b01c-bcc0beff9beb`

## 실행 단계

### 0단계: 백엔드 상태 확인

```bash
# 백엔드가 실행 중인지 확인
curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/api/v1/users/ \
  -H "Authorization: Bearer $JWT_TOKEN"
```

- **200**: 정상 → 다음 단계 진행
- **그 외**: 사용자에게 백엔드 시작 요청

### 1단계: 세션 작업 분석

현재 대화에서 작업한 내용을 분석하여 테스트 대상을 파악합니다.

- 어떤 API/기능이 변경되었는지
- 어떤 모델/라우터가 추가/수정되었는지
- 의존하는 외부 서비스가 있는지 (MCP, DB 등)

### 2단계: 테스트 계획 수립

변경 내용에 따라 테스트 시나리오를 작성합니다.

| 유형 | 테스트 방법 |
|------|------------|
| **모델/헬퍼 변경** | `uv run python -c "..."` 로 직접 import 및 검증 |
| **API 엔드포인트** | `curl` 로 요청/응답 확인 |
| **에이전트 기능** | 브라우저 흐름과 동일한 form_data 로 chat completion 호출 (5단계 참조) |
| **프론트엔드 연동** | API 호출로 데이터 흐름 확인 |

### 3단계: 단위 테스트 실행

변경된 모듈을 직접 import하여 검증합니다.

```bash
cd /cloosphere/backend && uv run python -c "
# 모듈 import 확인
from {module} import {class_or_function}

# 기본 동작 확인
result = ...
assert result == expected, f'Expected {expected}, got {result}'

print('OK')
"
```

**주의사항:**
- `uv run python`으로 실행 (가상환경 활성화)
- 작업 디렉토리는 `/cloosphere/backend`
- stderr의 INFO/WARNING 로그는 무시하고 결과만 확인
- 비동기 함수는 `asyncio.run()` 사용

### 4단계: API 통합 테스트

실제 API 엔드포인트를 호출하여 검증합니다.

```bash
AUTH="Authorization: Bearer <REDACTED>"

# GET 요청
curl -s http://localhost:8080/api/v1/{endpoint} -H "$AUTH" | python3 -m json.tool

# POST 요청
curl -s -X POST http://localhost:8080/api/v1/{endpoint} \
  -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"key": "value"}'
```

**주요 엔드포인트:**

| 리소스 | 목록 | 생성 | 조회 | 수정 | 삭제 |
|--------|------|------|------|------|------|
| 모델(에이전트) | GET /models/ | POST /models/create | - | POST /models/model/update?id={id} | DELETE /models/delete?id={id} |
| 지식기반 | GET /knowledge/ | POST /knowledge/create | GET /knowledge/{id} | POST /knowledge/{id}/update | DELETE /knowledge/{id}/delete |
| 도구 연결 | GET /tool_connections/ | POST /tool_connections/create | GET /tool_connections/{id} | POST /tool_connections/{id}/update | DELETE /tool_connections/{id}/delete |
| DbSphere | GET /dbsphere/ | POST /dbsphere/create | GET /dbsphere/{id} | POST /dbsphere/{id}/update | DELETE /dbsphere/{id}/delete |
| 채팅 | GET /chats/ | POST /chats/new | GET /chats/{id} | - | DELETE /chats/{id} |
| 트레이스 | GET /traces/?chat_id={id} | - | - | - | - |
| HITL resume | - | POST /chats/{chat_id}/resume | - | - | - |

### 5단계: 에이전트 채팅 테스트 — 브라우저 흐름과 동일하게

**핵심 — `/api/chat/completions` 의 main.py 핸들러는 form_data 의 top-level 에서**
`chat_id` / `id` / `session_id` 를 추출합니다 (`form_data.pop("chat_id", None)`,
`form_data.pop("id", None)`). metadata 안에 박으면 무시되어 `metadata.chat_id=None`
이 되고, 그 결과 일부 흐름 (트레이스 / event_emitter / 권한 컨텍스트 등) 이
정상 동작하지 않을 수 있습니다.

따라서 **반드시 chat 을 미리 생성하고, chat_id + message_id 를 top-level 에 박아 호출**:

```bash
JWT='<REDACTED>'
USER_ID="09b0e2de-64fc-4ba0-b01c-bcc0beff9beb"

# 1) chat + 첫 user message 미리 생성 — 브라우저의 sendPromptSocket 흐름 모사
CHAT_ID=$(python3 -c "import uuid; print(uuid.uuid4())")
MSG_ID=$(python3 -c "import uuid; print(uuid.uuid4())")
curl -sS -m 10 -X POST -H "Authorization: Bearer $JWT" -H 'Content-Type: application/json' \
  http://localhost:8080/api/v1/chats/new \
  -d "{\"chat\":{\"id\":\"$CHAT_ID\",\"title\":\"e2e\",\"models\":[\"{agent_id}\"],\"history\":{\"currentId\":\"$MSG_ID\",\"messages\":{\"$MSG_ID\":{\"id\":\"$MSG_ID\",\"role\":\"user\",\"content\":\"{질문}\",\"timestamp\":$(date +%s)}}}}}" > /dev/null
echo "chat_id=$CHAT_ID msg_id=$MSG_ID"

# 2) chat completion — chat_id / id 는 top-level (브라우저 형식 필수)
PAYLOAD=$(python3 <<EOF
import json
print(json.dumps({
  "model": "{agent_id}",
  "stream": True,
  "chat_id": "$CHAT_ID",
  "id": "$MSG_ID",
  "session_id": None,
  "messages": [{"role":"user","content":"{질문}"}]
}))
EOF
)
WM=$(wc -l < /tmp/backend.log)  # 로그 watermark
curl -sS -N -m 90 -o /tmp/e2e_chat.sse -H "Authorization: Bearer $JWT" -H 'Content-Type: application/json' \
  -X POST http://localhost:8080/api/chat/completions -d "$PAYLOAD"

# 3) 응답 + 백엔드 로그 + 트레이스 동시 확인
sleep 2
echo "--- assembled content ---"
python3 -c "
import json
text = open('/tmp/e2e_chat.sse').read()
content = ''
for line in text.split('\n'):
    if not line.startswith('data: '): continue
    p = line[6:]
    if p == '[DONE]': continue
    try:
        d = json.loads(p)
        c = d.get('choices',[{}])[0].get('delta',{}).get('content','')
        if c: content += c
    except: pass
print(content[:1000])
"
echo "--- agent log (이번 호출만) ---"
grep -E "UnifiedAgent|HITL|Error" <(tail -n +$WM /tmp/backend.log) | head -10
```

**참고:**
- `stream: true`여야 UnifiedAgent 경로를 탐
- **`chat_id` / `id` 가 top-level 에 없으면 metadata 가 비어 unified_agent 의 일부 분기가 잘못 동작** (event_emitter 의 user_id 누락 등)
- 백엔드 dev.sh 의 stdout 경로는 `/tmp/hitl_live.log` 또는 사용자가 띄울 때 redirect 한 파일 — `tail -f` 또는 `wc -l` watermark 로 호출별 로그 분리
- API Key (`sk-...`) + 자동 chat_id 생성 흐름은 일부 unified_agent 기능 (트레이스, socket event_emitter 등) 이 제대로 안 되니 **검증용으로는 위 chat 생성 패턴 권장**

### 5-1단계: HITL 흐름 검증 (도구 승인 모달)

`ENABLE_HITL=true` + write 도구 (`run_sql_write`, `use_tool_server_write`) 가 있는
에이전트의 경우 — interrupt 발생 → `/resume` 으로 사용자 결정 전달 → graph 재개
까지 e2e 검증.

```bash
# 위 5단계의 chat completion 후, interrupt 가 발생했는지 백엔드 로그에서 확인
THREAD_ID=$(grep "HITL interrupt emitted" <(tail -n +$WM /tmp/backend.log) \
  | tail -1 | grep -oE "thread_id=[a-f0-9-]+" | cut -d= -f2)
echo "thread_id=$THREAD_ID"

# 트레이스 통합 확인 — 첫 invocation 의 chain_run_id, trace_id 추출
# (resume 시 같은 chain 의 child 로 이어가도록 클라이언트가 보내는 값)
read CHAIN_RUN_ID TRACE_ID <<< $(curl -sS -m 5 -H "Authorization: Bearer $JWT" \
  "http://localhost:8080/api/v1/traces/?chat_id=$CHAT_ID" | python3 -c "
import json, sys
d = json.loads(sys.stdin.read())
for t in d.get('traces', []):
    if t.get('run_type') == 'chain':
        print(t.get('id'), t.get('trace_id'))
        break
")
echo "first chain_run_id=$CHAIN_RUN_ID  trace_id=$TRACE_ID"

# resume — APPROVE 결정 + chain_run_id/trace_id 재사용
RPAYLOAD=$(python3 <<EOF
import json
print(json.dumps({
  "thread_id": "$THREAD_ID",
  "decisions": [{"type": "approve"}],
  "chain_run_id": "$CHAIN_RUN_ID",
  "trace_id": "$TRACE_ID",
  "payload": {
    "model": "{agent_id}",
    "stream": True,
    "chat_id": "$CHAT_ID",
    "id": "$MSG_ID",
    "session_id": None,
    "messages": [{"role":"user","content":"{질문}"}]
  }
}))
EOF
)
curl -sS -N -m 120 -o /tmp/e2e_resume.sse -X POST \
  -H "Authorization: Bearer $JWT" -H 'Content-Type: application/json' \
  "http://localhost:8080/api/v1/chats/$CHAT_ID/resume" -d "$RPAYLOAD"

# 결과
echo "--- resume 응답 ---"
python3 -c "
import json
text = open('/tmp/e2e_resume.sse').read()
content = ''
for line in text.split('\n'):
    if not line.startswith('data: '): continue
    p = line[6:]
    if p == '[DONE]': continue
    try:
        d = json.loads(p)
        c = d.get('choices',[{}])[0].get('delta',{}).get('content','')
        if c: content += c
    except: pass
print(content[:1000] or '(empty)')
"
```

**HITL 검증 포인트:**
- 백엔드 로그에 `HITL middleware enabled — interrupt_required=[..., 'use_tool_server_write']` 와 `ALL_TOOLS=[...]` 가 표시되는지 (정책과 실제 등록 도구 일치 확인)
- `HITL interrupt emitted (thread_id=...)` 가 발행되는지
- `tool_connections_context build: ... tool_msg_names=[...] ctx_len=...` 로그에서 도구 결과가 final_answer 컨텍스트에 들어갔는지
- resume 응답의 LLM 텍스트가 "도구 없다" 가 아닌 실제 결과 반영 (예: "epsilon 아이템이 생성되었습니다")
- LLM 비결정성으로 도구를 안 부르는 경우가 있음 — 명시적 지시 ("use_tool_server_write 도구로 호출") 권장

### 6단계: 트레이스 검증

채팅 테스트 후 트레이스로 내부 동작을 확인합니다.

```bash
AUTH="Authorization: Bearer <REDACTED>"
curl -s "http://localhost:8080/api/v1/traces/?chat_id=$CHAT_ID" -H "$AUTH" \
  | python3 -c "
import json, sys
data = json.load(sys.stdin)
ts = sorted(data.get('traces', []), key=lambda x: x.get('dotted_order',''))
print(f'total: {len(ts)}, distinct trace_ids: {len({t.get(\"trace_id\") for t in ts})}, '
      f'distinct chains: {len([t for t in ts if t.get(\"run_type\") == \"chain\"])}')
for t in ts:
    tid = (t.get('trace_id') or '')[-8:]
    name = t.get('name','?')
    rt = t.get('run_type','?')
    status = t.get('status','?')
    latency = t.get('latency_ms', 0)
    print(f'  trace=...{tid} [{t.get(\"dotted_order\",\"\"):20s}] {rt:8s} {name:30s} {status:10s} ({latency}ms)')
"
```

**확인 항목:**
- `chain Cloosphere` (또는 에이전트 이름): total_steps, status (`success` / `running` 잔존 X)
- `react_agent`: total_steps, 도구 호출 여부
- `final_answer`: system_prompt에 수집 데이터 포함 여부, 응답 내용
- 도구별 run: 입력/출력, 에러 여부
- **HITL 시나리오에서 trace 통합 확인**: `distinct chains: 1` (resume 후에도 chain 1개 유지). 2개 이상이면 chain_run_id/trace_id 재사용이 실패한 것

### 7단계: 결과 보고

```markdown
## E2E 테스트 결과

| 테스트 | 결과 | 비고 |
|--------|------|------|
| 모듈 import | OK/FAIL | |
| API 호출 | OK/FAIL | |
| 에이전트 채팅 | OK/FAIL | |
| HITL interrupt+resume | OK/FAIL | (해당 시) |
| 트레이스 통합 | OK/FAIL | distinct chains == 1 |

**발견된 이슈:** (있으면 기술)
```

## 외부 서비스 테스트

### MCP 서버 테스트

MCP 도구 연결 기능을 테스트할 때 경량 MCP 서버가 필요한 경우:

```bash
# test_mcp_server.py 실행 (프로젝트 루트에 있음 — 없으면 사용자에게 생성 요청)
cd /cloosphere && python test_mcp_server.py &
sleep 1

# 연결 확인
curl -s -X POST http://localhost:3100/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

**제공 도구:** get_time, list_items, create_item, delete_item (HITL R/W 분류 검증용)

### 도구 연결 E2E 플로우

```bash
AUTH="Authorization: Bearer $JWT_TOKEN"

# 1. 도구 연결 등록
TC_ID=$(curl -s -X POST http://localhost:8080/api/v1/tool_connections/create \
  -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"name":"Test MCP","description":"Test","data":{"connection":{"type":"mcp","url":"http://localhost:3100/mcp","auth_type":"none","key":"","headers":{},"enabled":true}},"meta":{},"access_control":{}}' \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['id'])")

# 2. 에이전트 생성 (도구 연결 포함). meta 키는 brower 포맷에 맞게 toolConnections (camelCase) 도 가능
curl -s -X POST http://localhost:8080/api/v1/models/create \
  -H "$AUTH" -H 'Content-Type: application/json' \
  -d "{\"id\":\"e2e-test-agent\",\"base_model_id\":\"gpt-5.2\",\"name\":\"E2E Test\",\"params\":{},\"meta\":{\"tool_connections\":[{\"id\":\"$TC_ID\"}]}}"

# 3. ToolConnectionManager 검증
uv run python -c "
import asyncio
from open_webui.models.agent_config import ToolConnectionRef
from extension_modules.agent.tool_connection_tools import ToolConnectionManager
tc = ToolConnectionManager(tool_connections=[ToolConnectionRef(id='$TC_ID')])
async def test():
    print(await tc._list_tool_servers())
    print(await tc._list_server_tools(server_id='$TC_ID'))
    # read 경로
    print(await tc._use_tool_server_read(server_id='$TC_ID', action='call', tool_name='get_time'))
    # write 경로
    print(await tc._use_tool_server_write(server_id='$TC_ID', tool_name='create_item', arguments={'name':'demo'}))
asyncio.run(test())
"

# 4. 정리
curl -s -X DELETE "http://localhost:8080/api/v1/models/delete?id=e2e-test-agent" -H "$AUTH"
curl -s -X DELETE "http://localhost:8080/api/v1/tool_connections/$TC_ID/delete" -H "$AUTH"
```

## 주의사항

1. **백엔드 재시작**: 백엔드 코드 변경 후에는 반드시 재시작 필요 (dev.sh에 `--reload` 있으면 자동)
2. **프론트엔드**: 프론트엔드 변경은 API 테스트로 직접 검증 불가 → `npm run dev` + 브라우저 확인
3. **정리**: 테스트로 생성한 리소스(에이전트, 도구 연결, chat 등) 는 반드시 정리 (`DELETE /api/v1/chats/{chat_id}` 등)
4. **타임아웃**: 에이전트 채팅은 30초+ 소요될 수 있으므로 `timeout 180000` 설정. HITL resume 도 LLM 호출 두 번 (interrupt + resume) 이라 더 김
5. **stderr 무시**: `uv run python`의 INFO 로그는 `2>&1 | grep -E "^(결과패턴)"` 로 필터링
6. **사용자 환경 동등성**: `/api/chat/completions` 호출 시 `chat_id` / `id` / `session_id` 는 **반드시 form_data top-level**. metadata 안에 박으면 main.py 의 `pop("chat_id")` 가 못 찾아 빈 metadata 로 unified_agent 가 잘못 동작
7. **HITL 검증의 LLM 비결정성**: cloosphere 같은 에이전트가 같은 질문에도 도구를 안 부르는 경우 있음. 명시적 지시 ("use_tool_server_write 로 호출", "dbsphere_info → run_sql_read 순서로") 가 안정적
8. **로그 파일 경로**: `dev.sh` 가 어디로 redirect 했는지에 따라 다름 (`/tmp/hitl_live.log`, `/tmp/backend.log` 등). 호출 전 watermark 잡고 호출 후 `tail -n +$WM` 로 분리

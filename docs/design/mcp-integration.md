# MCP (Model Context Protocol) Integration Design

## 개요

Tool Connections에 MCP 서버 연결 지원을 추가하여 OpenAPI와 MCP 두 가지 방식으로 외부 도구를 연결할 수 있도록 합니다.

---

## MCP 프로토콜 요약

### 핵심 개념
- **Model Context Protocol**: Anthropic이 개발한 LLM-도구 통합 오픈 프로토콜
- **JSON-RPC 2.0**: 메시지 형식
- **양방향 통신**: 클라이언트 ↔ 서버

### 전송 방식 (Transports)
1. **stdio**: 서브프로세스로 MCP 서버 실행, stdin/stdout으로 통신
2. **Streamable HTTP**: HTTP 엔드포인트로 MCP 서버와 통신

### MCP 서버 제공 기능
- **Tools**: 호출 가능한 함수들
- **Resources**: 읽기 전용 데이터 (파일, DB 등)
- **Prompts**: 재사용 가능한 프롬프트 템플릿

---

## 데이터 구조 설계

### Connection Type 확장

기존 OpenAPI 연결:
```json
{
  "connection": {
    "type": "openapi",
    "url": "https://api.example.com",
    "path": "openapi.json",
    "auth_type": "bearer",
    "key": "xxx",
    "enabled": true
  }
}
```

MCP stdio 연결 (신규):
```json
{
  "connection": {
    "type": "mcp",
    "transport": "stdio",
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/dir"],
    "env": {
      "CUSTOM_VAR": "value"
    },
    "enabled": true
  }
}
```

MCP HTTP 연결 (신규):
```json
{
  "connection": {
    "type": "mcp",
    "transport": "http",
    "url": "https://mcp-server.example.com/mcp",
    "headers": {
      "Authorization": "Bearer xxx"
    },
    "enabled": true
  }
}
```

### TypeScript 타입 정의

```typescript
// src/lib/types/tool-connection.ts

interface OpenAPIConnection {
  type: 'openapi';
  url: string;
  path: string;
  auth_type: 'none' | 'bearer' | 'api_key' | 'basic';
  key?: string;
  enabled: boolean;
}

interface MCPStdioConnection {
  type: 'mcp';
  transport: 'stdio';
  command: string;
  args?: string[];
  env?: Record<string, string>;
  enabled: boolean;
}

interface MCPHttpConnection {
  type: 'mcp';
  transport: 'http';
  url: string;
  headers?: Record<string, string>;
  enabled: boolean;
}

type ToolConnection = OpenAPIConnection | MCPStdioConnection | MCPHttpConnection;
```

---

## 백엔드 구현

### 1. MCP 클라이언트 서비스

**파일**: `backend/open_webui/utils/mcp_client.py`

```python
import asyncio
import json
from typing import Optional
from dataclasses import dataclass

@dataclass
class MCPTool:
    name: str
    description: str
    input_schema: dict

class MCPClient:
    """MCP 서버와 통신하는 클라이언트"""

    def __init__(self, connection_config: dict):
        self.config = connection_config
        self.transport = connection_config.get('transport', 'stdio')

    async def connect(self):
        """MCP 서버에 연결"""
        if self.transport == 'stdio':
            return await self._connect_stdio()
        elif self.transport == 'http':
            return await self._connect_http()

    async def _connect_stdio(self):
        """stdio 전송으로 연결 (서브프로세스)"""
        command = self.config['command']
        args = self.config.get('args', [])
        env = self.config.get('env', {})

        self.process = await asyncio.create_subprocess_exec(
            command, *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ, **env}
        )

        # Initialize connection
        await self._send_request('initialize', {
            'protocolVersion': '2024-11-05',
            'capabilities': {},
            'clientInfo': {'name': 'cloosphere', 'version': '1.0.0'}
        })

        await self._send_notification('notifications/initialized', {})

    async def _connect_http(self):
        """HTTP 전송으로 연결"""
        # HTTP 연결은 stateless, 별도 초기화 불필요
        pass

    async def list_tools(self) -> list[MCPTool]:
        """사용 가능한 도구 목록 조회"""
        result = await self._send_request('tools/list', {})
        return [
            MCPTool(
                name=tool['name'],
                description=tool.get('description', ''),
                input_schema=tool.get('inputSchema', {})
            )
            for tool in result.get('tools', [])
        ]

    async def call_tool(self, name: str, arguments: dict) -> dict:
        """도구 호출"""
        result = await self._send_request('tools/call', {
            'name': name,
            'arguments': arguments
        })
        return result

    async def _send_request(self, method: str, params: dict) -> dict:
        """JSON-RPC 요청 전송"""
        request = {
            'jsonrpc': '2.0',
            'id': self._next_id(),
            'method': method,
            'params': params
        }

        if self.transport == 'stdio':
            return await self._send_stdio(request)
        else:
            return await self._send_http(request)

    async def close(self):
        """연결 종료"""
        if self.transport == 'stdio' and hasattr(self, 'process'):
            self.process.terminate()
            await self.process.wait()
```

### 2. Tool Connection Router 확장

**파일**: `backend/open_webui/routers/tool_connections.py`

```python
# 기존 라우터에 추가

@router.get("/{id}/tools")
async def get_connection_tools(
    id: str,
    user=Depends(get_verified_user)
):
    """연결된 서버의 도구 목록 조회"""
    tool_connection = ToolConnections.get_tool_connection_by_id(id)
    if not tool_connection:
        raise HTTPException(status_code=404, detail="Tool connection not found")

    connection = tool_connection.data.get('connection', {})
    conn_type = connection.get('type')

    if conn_type == 'openapi':
        return await get_openapi_tools(connection)
    elif conn_type == 'mcp':
        return await get_mcp_tools(connection)
    else:
        raise HTTPException(status_code=400, detail="Unknown connection type")

async def get_mcp_tools(connection: dict) -> list[dict]:
    """MCP 서버에서 도구 목록 가져오기"""
    client = MCPClient(connection)
    try:
        await client.connect()
        tools = await client.list_tools()
        return [
            {
                'name': tool.name,
                'description': tool.description,
                'parameters': tool.input_schema
            }
            for tool in tools
        ]
    finally:
        await client.close()

@router.post("/{id}/tools/{tool_name}/call")
async def call_tool(
    id: str,
    tool_name: str,
    arguments: dict,
    user=Depends(get_verified_user)
):
    """도구 호출"""
    tool_connection = ToolConnections.get_tool_connection_by_id(id)
    if not tool_connection:
        raise HTTPException(status_code=404, detail="Tool connection not found")

    connection = tool_connection.data.get('connection', {})

    if connection.get('type') == 'mcp':
        client = MCPClient(connection)
        try:
            await client.connect()
            result = await client.call_tool(tool_name, arguments)
            return result
        finally:
            await client.close()
```

### 3. MCP 프로세스 관리자 (장기 실행용)

stdio MCP 서버는 연결 유지가 필요하므로 프로세스 관리자가 필요합니다:

**파일**: `backend/open_webui/utils/mcp_manager.py`

```python
class MCPProcessManager:
    """MCP stdio 프로세스 풀 관리"""

    _instances: dict[str, MCPClient] = {}

    @classmethod
    async def get_or_create(cls, connection_id: str, config: dict) -> MCPClient:
        """연결 ID로 클라이언트 가져오기 (없으면 생성)"""
        if connection_id not in cls._instances:
            client = MCPClient(config)
            await client.connect()
            cls._instances[connection_id] = client
        return cls._instances[connection_id]

    @classmethod
    async def close(cls, connection_id: str):
        """특정 연결 종료"""
        if connection_id in cls._instances:
            await cls._instances[connection_id].close()
            del cls._instances[connection_id]

    @classmethod
    async def close_all(cls):
        """모든 연결 종료"""
        for client in cls._instances.values():
            await client.close()
        cls._instances.clear()
```

---

## 프론트엔드 구현

### 1. Connection Type 선택 UI

**수정 파일**: `src/lib/components/workspace/Tools/ToolDetail.svelte`

```svelte
<!-- Connection Type 선택 -->
<div class="mb-4">
  <label class="text-sm mb-2">{$i18n.t('Connection Type')}</label>
  <select bind:value={connectionType} class="...">
    <option value="openapi">OpenAPI</option>
    <option value="mcp">MCP (Model Context Protocol)</option>
  </select>
</div>

{#if connectionType === 'openapi'}
  <!-- 기존 OpenAPI 설정 UI -->
{:else if connectionType === 'mcp'}
  <!-- MCP 설정 UI -->
  <MCPConnectionForm bind:connection={tool.data.connection} />
{/if}
```

### 2. MCP Connection Form 컴포넌트

**새 파일**: `src/lib/components/workspace/Tools/MCPConnectionForm.svelte`

```svelte
<script lang="ts">
  import { getContext } from 'svelte';
  const i18n = getContext('i18n');

  export let connection = {
    type: 'mcp',
    transport: 'stdio',
    command: '',
    args: [],
    env: {},
    enabled: true
  };

  let argsText = '';

  $: {
    connection.args = argsText.split('\n').filter(a => a.trim());
  }
</script>

<div class="space-y-4">
  <!-- Transport Type -->
  <div>
    <label class="text-sm mb-2">{$i18n.t('Transport')}</label>
    <select bind:value={connection.transport} class="...">
      <option value="stdio">stdio (Subprocess)</option>
      <option value="http">HTTP</option>
    </select>
  </div>

  {#if connection.transport === 'stdio'}
    <!-- Command -->
    <div>
      <label class="text-sm mb-2">{$i18n.t('Command')}</label>
      <input
        type="text"
        bind:value={connection.command}
        placeholder="npx, python, node..."
        class="..."
      />
    </div>

    <!-- Arguments -->
    <div>
      <label class="text-sm mb-2">{$i18n.t('Arguments (one per line)')}</label>
      <textarea
        bind:value={argsText}
        placeholder="-y
@modelcontextprotocol/server-filesystem
/path/to/dir"
        rows="4"
        class="..."
      />
    </div>
  {:else}
    <!-- HTTP URL -->
    <div>
      <label class="text-sm mb-2">{$i18n.t('MCP Server URL')}</label>
      <input
        type="url"
        bind:value={connection.url}
        placeholder="https://mcp-server.example.com/mcp"
        class="..."
      />
    </div>
  {/if}
</div>
```

### 3. 도구 목록 표시

**수정 파일**: `src/lib/components/workspace/Tools/ToolDetail.svelte`

```svelte
<script lang="ts">
  let availableTools = [];
  let loadingTools = false;

  async function fetchTools() {
    loadingTools = true;
    try {
      const res = await fetch(`/api/v1/tool_connections/${tool.id}/tools`, {
        headers: { Authorization: `Bearer ${localStorage.token}` }
      });
      availableTools = await res.json();
    } catch (e) {
      toast.error($i18n.t('Failed to fetch tools'));
    }
    loadingTools = false;
  }
</script>

<!-- Available Tools Section -->
<div class="mt-6">
  <div class="flex items-center justify-between mb-2">
    <h3 class="text-sm font-medium">{$i18n.t('Available Tools')}</h3>
    <button on:click={fetchTools} class="...">
      {$i18n.t('Refresh')}
    </button>
  </div>

  {#if loadingTools}
    <div class="animate-pulse">...</div>
  {:else if availableTools.length > 0}
    <div class="space-y-2">
      {#each availableTools as tool}
        <div class="p-3 bg-gray-50 dark:bg-gray-800 rounded-lg">
          <div class="font-medium">{tool.name}</div>
          <div class="text-sm text-gray-500">{tool.description}</div>
        </div>
      {/each}
    </div>
  {:else}
    <div class="text-gray-500">{$i18n.t('No tools found')}</div>
  {/if}
</div>
```

---

## 인기 MCP 서버 프리셋

사용자 편의를 위한 프리셋 제공:

```typescript
const MCP_PRESETS = [
  {
    name: 'Filesystem',
    description: 'Read/write files on the local filesystem',
    connection: {
      type: 'mcp',
      transport: 'stdio',
      command: 'npx',
      args: ['-y', '@modelcontextprotocol/server-filesystem', '/path']
    }
  },
  {
    name: 'GitHub',
    description: 'Interact with GitHub repositories',
    connection: {
      type: 'mcp',
      transport: 'stdio',
      command: 'npx',
      args: ['-y', '@modelcontextprotocol/server-github'],
      env: { GITHUB_TOKEN: '' }
    }
  },
  {
    name: 'Slack',
    description: 'Read/send Slack messages',
    connection: {
      type: 'mcp',
      transport: 'stdio',
      command: 'npx',
      args: ['-y', '@modelcontextprotocol/server-slack'],
      env: { SLACK_TOKEN: '' }
    }
  },
  {
    name: 'PostgreSQL',
    description: 'Query PostgreSQL databases',
    connection: {
      type: 'mcp',
      transport: 'stdio',
      command: 'npx',
      args: ['-y', '@modelcontextprotocol/server-postgres'],
      env: { DATABASE_URL: '' }
    }
  }
];
```

---

## 보안 고려사항

### 1. stdio 명령어 제한
- 화이트리스트 명령어만 허용 (npx, node, python, uv)
- 셸 인젝션 방지
- 작업 디렉토리 제한

### 2. 환경 변수 보안
- 민감한 값 암호화 저장
- API 응답에서 민감 정보 마스킹

### 3. 프로세스 격리
- 리소스 제한 (CPU, 메모리, 시간)
- 네트워크 접근 제한 (선택적)

---

## 구현 순서

### Phase 1: 기본 연결
1. `MCPClient` 클래스 구현
2. Tool connection 데이터 구조 확장
3. MCP 연결 폼 UI 구현
4. 도구 목록 조회 API

### Phase 2: 도구 호출
1. 도구 호출 API 엔드포인트
2. Chat completion에서 MCP 도구 연동
3. 스트리밍 응답 지원

### Phase 3: 고급 기능
1. 프리셋 제공
2. 프로세스 관리자 (연결 풀)
3. Resources, Prompts 지원

---

## 의존성

### Backend
```txt
# requirements.txt에 추가
mcp>=1.0.0  # Anthropic MCP Python SDK
```

### Frontend
```bash
# package.json에 추가 (선택적, HTTP 연결 시)
# 별도 패키지 불필요 - fetch API 사용
```

---

## 참고 자료

- [MCP Specification](https://modelcontextprotocol.io/specification/2025-11-25)
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [MCP Servers Registry](https://github.com/modelcontextprotocol/servers)

# Agent Flow 프론트엔드

## 컴포넌트 구조

```
src/lib/components/workspace/
├── AgentFlows/
│   ├── FlowBuilder.svelte      # 메인 캔버스
│   ├── FlowToolbar.svelte      # 상단 툴바
│   ├── NodePalette.svelte      # 노드 팔레트 (좌측)
│   ├── NodeConfigPanel.svelte  # 설정 패널 (우측)
│   └── nodes/
│       ├── InputNode.svelte
│       ├── OutputNode.svelte
│       ├── AgentNode.svelte
│       ├── ModelNode.svelte
│       ├── KnowledgeNode.svelte
│       ├── ConditionNode.svelte
│       ├── TransformNode.svelte
│       ├── GuardrailNode.svelte
│       ├── ToolNode.svelte
│       └── ...
└── Flows/
    ├── Flows.svelte            # 플로우 목록
    ├── FlowEditor.svelte       # 플로우 편집기
    └── FlowMenu.svelte         # 플로우 메뉴
```

## XYFlow 통합

### 설치된 패키지

```json
{
    "@xyflow/svelte": "^0.1.x"
}
```

### FlowBuilder.svelte

```svelte
<script lang="ts">
    import { SvelteFlow, Background, Controls, MiniMap } from '@xyflow/svelte';
    import '@xyflow/svelte/dist/style.css';

    import InputNode from './nodes/InputNode.svelte';
    import OutputNode from './nodes/OutputNode.svelte';
    import AgentNode from './nodes/AgentNode.svelte';
    // ...

    export let flowData: FlowData = { nodes: [], edges: [], variables: {} };

    // 노드 타입 매핑
    const nodeTypes = {
        flowInput: InputNode,
        flowOutput: OutputNode,
        agent: AgentNode,
        model: ModelNode,
        knowledge: KnowledgeNode,
        condition: ConditionNode,
        transform: TransformNode,
        guardrail: GuardrailNode,
        tool: ToolNode,
    };

    let nodes = writable(flowData.nodes);
    let edges = writable(flowData.edges);
</script>

<div class="h-full w-full">
    <SvelteFlow
        {nodes}
        {edges}
        {nodeTypes}
        on:nodeschange={handleNodesChange}
        on:edgeschange={handleEdgesChange}
        on:connect={handleConnect}
    >
        <Background />
        <Controls />
        <MiniMap />
    </SvelteFlow>
</div>
```

## 노드 컴포넌트

### 기본 구조

```svelte
<!-- nodes/AgentNode.svelte -->
<script lang="ts">
    import { Handle, Position } from '@xyflow/svelte';

    export let id: string;
    export let data: NodeData;
    export let selected: boolean = false;
</script>

<div
    class="node-container"
    class:selected
>
    <!-- 입력 핸들 -->
    <Handle type="target" position={Position.Left} />

    <!-- 노드 내용 -->
    <div class="node-header">
        <span class="icon">🤖</span>
        <span class="label">{data.label || 'Agent'}</span>
    </div>
    <div class="node-body">
        <span class="resource-name">{data.resourceName || '선택 안됨'}</span>
    </div>

    <!-- 출력 핸들 -->
    <Handle type="source" position={Position.Right} />
</div>

<style>
    .node-container {
        @apply bg-white dark:bg-gray-800 rounded-lg border-2;
        @apply border-gray-200 dark:border-gray-600;
        @apply shadow-sm min-w-40 p-2;
    }
    .node-container.selected {
        @apply border-blue-500;
    }
</style>
```

### Condition 노드 (다중 출력)

```svelte
<!-- nodes/ConditionNode.svelte -->
<script lang="ts">
    import { Handle, Position } from '@xyflow/svelte';
</script>

<div class="node-container">
    <Handle type="target" position={Position.Left} />

    <div class="node-content">
        <span>🔀 Condition</span>
        <span class="condition-type">{data.config?.conditionType}</span>
    </div>

    <!-- True 출력 -->
    <Handle
        type="source"
        position={Position.Right}
        id="true"
        style="top: 30%"
    />
    <span class="handle-label true">True</span>

    <!-- False 출력 -->
    <Handle
        type="source"
        position={Position.Right}
        id="false"
        style="top: 70%"
    />
    <span class="handle-label false">False</span>
</div>
```

## NodePalette (노드 팔레트)

```svelte
<script lang="ts">
    const nodeCategories = [
        {
            name: '기본',
            nodes: [
                { type: 'flowInput', label: 'Input', icon: '📥' },
                { type: 'flowOutput', label: 'Output', icon: '📤' },
            ]
        },
        {
            name: '처리',
            nodes: [
                { type: 'agent', label: 'Agent', icon: '🤖' },
                { type: 'model', label: 'Model', icon: '🧠' },
                { type: 'knowledge', label: 'Knowledge', icon: '📚' },
                { type: 'tool', label: 'Tool', icon: '🔧' },
            ]
        },
        {
            name: '제어',
            nodes: [
                { type: 'condition', label: 'Condition', icon: '🔀' },
                { type: 'transform', label: 'Transform', icon: '✏️' },
                { type: 'guardrail', label: 'Guardrail', icon: '🛡️' },
            ]
        }
    ];

    function onDragStart(event, nodeType) {
        event.dataTransfer.setData('application/reactflow', nodeType);
        event.dataTransfer.effectAllowed = 'move';
    }
</script>

<div class="palette">
    {#each nodeCategories as category}
        <div class="category">
            <h3>{category.name}</h3>
            {#each category.nodes as node}
                <div
                    class="palette-node"
                    draggable="true"
                    on:dragstart={(e) => onDragStart(e, node.type)}
                >
                    <span>{node.icon}</span>
                    <span>{node.label}</span>
                </div>
            {/each}
        </div>
    {/each}
</div>
```

## NodeConfigPanel (설정 패널)

```svelte
<script lang="ts">
    export let selectedNode: Node | null = null;

    $: nodeConfig = selectedNode?.data?.config || {};
</script>

{#if selectedNode}
    <div class="config-panel">
        <h3>노드 설정</h3>

        {#if selectedNode.type === 'agent'}
            <AgentConfig bind:config={nodeConfig} />
        {:else if selectedNode.type === 'model'}
            <ModelConfig bind:config={nodeConfig} />
        {:else if selectedNode.type === 'condition'}
            <ConditionConfig bind:config={nodeConfig} />
        {:else if selectedNode.type === 'transform'}
            <TransformConfig bind:config={nodeConfig} />
        {/if}
    </div>
{:else}
    <div class="empty-state">
        노드를 선택하세요
    </div>
{/if}
```

### Agent 설정

```svelte
<!-- AgentConfig -->
<script>
    import { models } from '$lib/stores';

    export let config;
    export let data;

    $: agents = $models.filter(m =>
        m.info?.meta?.type !== 'agent_flow' && m.owned_by !== 'arena'
    );
</script>

<div class="config-section">
    <label>에이전트 선택</label>
    <select bind:value={data.resourceId}>
        <option value="">선택...</option>
        {#each agents as agent}
            <option value={agent.id}>{agent.name}</option>
        {/each}
    </select>
</div>

<div class="config-section">
    <label>온도 (Temperature)</label>
    <input
        type="range"
        min="0"
        max="1"
        step="0.1"
        bind:value={config.temperature}
    />
    <span>{config.temperature || 0.7}</span>
</div>
```

## 페이지 라우팅

### 파일 구조

```
src/routes/(app)/workspace/flows/
├── +page.svelte        # 플로우 목록
├── +page.ts            # 데이터 로더
├── create/
│   ├── +page.svelte    # 새 플로우 생성
│   └── +page.ts
└── [id]/
    ├── +page.svelte    # 플로우 편집
    └── +page.ts
```

### 플로우 목록 페이지

```svelte
<!-- flows/+page.svelte -->
<script lang="ts">
    import Flows from '$lib/components/workspace/Flows.svelte';
</script>

<Flows />
```

### 플로우 편집 페이지

```svelte
<!-- flows/[id]/+page.svelte -->
<script lang="ts">
    import { page } from '$app/stores';
    import FlowEditor from '$lib/components/workspace/Flows/FlowEditor.svelte';

    $: flowId = $page.params.id;
</script>

<FlowEditor {flowId} />
```

## 워크스페이스 레이아웃

### Flows 탭 추가

```svelte
<!-- workspace/+layout.svelte -->
<script>
    const tabs = [
        { id: 'agents', label: 'Agents', href: '/workspace/models' },
        { id: 'flows', label: 'Flows', href: '/workspace/flows' },
        { id: 'knowledge', label: 'Knowledge', href: '/workspace/knowledge' },
        // ...
    ];
</script>
```

## 모델 선택기 통합

플로우가 모델 선택기에 표시되도록 처리:

```svelte
<!-- ModelSelector/Selector.svelte -->
<script>
    $: flowModels = $models.filter(m => m.owned_by === 'agent_flow');
</script>

{#if flowModels.length > 0}
    <div class="category">
        <span class="category-label">플로우</span>
        {#each flowModels as flow}
            <button on:click={() => selectModel(flow)}>
                <span>🔄</span>
                <span>{flow.name}</span>
            </button>
        {/each}
    </div>
{/if}
```

## 스타일 가이드

### 노드 색상

| 노드 타입 | 테두리 색상 | 아이콘 |
|----------|------------|--------|
| Input | green-500 | 📥 |
| Output | red-500 | 📤 |
| Agent | blue-500 | 🤖 |
| Model | purple-500 | 🧠 |
| Knowledge | yellow-500 | 📚 |
| Condition | orange-500 | 🔀 |
| Transform | pink-500 | ✏️ |
| Guardrail | gray-500 | 🛡️ |

### 반응형

- 모바일에서는 팔레트와 설정 패널이 드로어로 전환
- 캔버스는 터치 제스처 지원

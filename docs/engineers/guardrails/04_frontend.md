# Guardrails 프론트엔드

## 1. 컴포넌트 구조

```
src/lib/components/workspace/
├── Guardrails/                    # 워크스페이스 가드레일 관리
│   ├── CreateGuardrail.svelte     # 가드레일 생성 페이지
│   └── GuardrailEditor.svelte     # 가드레일 편집기
│
└── Agents/
    └── Guardrails/                # 에이전트용 가드레일 선택
        └── Selector.svelte        # 가드레일 선택 컴포넌트
```

## 2. 워크스페이스 가드레일 관리

### CreateGuardrail.svelte

새 가드레일 생성 페이지:

```svelte
<script lang="ts">
  import { createGuardrail } from '$lib/apis/guardrails';
  import { goto } from '$app/navigation';

  let form = {
    name: '',
    description: '',
    pii_types: [],
    pii_strategy: 'redact',
    custom_patterns: [],
    blocked_words: [],
    apply_to_input: true,
    apply_to_output: false,
    llm_judge_enabled: false,
    llm_judge_model: null,
    llm_judge_prompt: '',
    access_control: null
  };

  async function handleSubmit() {
    const guardrail = await createGuardrail(localStorage.token, form);
    goto(`/workspace/guardrails/${guardrail.id}`);
  }
</script>
```

### GuardrailEditor.svelte

가드레일 편집 인터페이스:

```svelte
<script lang="ts">
  export let guardrail;

  // PII 유형 옵션
  const piiTypeOptions = [
    { id: 'email', name: 'Email', description: '이메일 주소' },
    { id: 'credit_card', name: 'Credit Card', description: '신용카드 번호' },
    { id: 'ip', name: 'IP Address', description: 'IPv4 주소' },
    { id: 'mac', name: 'MAC Address', description: 'MAC 주소' },
    { id: 'url', name: 'URL', description: 'HTTP/HTTPS 링크' },
    { id: 'api_key', name: 'API Key', description: 'API 키 (sk-xxx)' }
  ];

  // 처리 전략 옵션
  const strategyOptions = [
    { id: 'block', name: 'Block', description: '콘텐츠 전체 차단' },
    { id: 'redact', name: 'Redact', description: '탐지된 부분 삭제' },
    { id: 'mask', name: 'Mask', description: '부분 마스킹 (j***@***)' },
    { id: 'hash', name: 'Hash', description: '해시값으로 대체' }
  ];
</script>

<!-- 기본 정보 -->
<div class="section">
  <input bind:value={guardrail.name} placeholder="가드레일 이름" />
  <textarea bind:value={guardrail.description} placeholder="설명" />
</div>

<!-- PII 탐지 설정 -->
<div class="section">
  <h3>PII 탐지</h3>
  {#each piiTypeOptions as option}
    <Checkbox
      checked={guardrail.pii_types.includes(option.id)}
      on:change={() => togglePiiType(option.id)}
    >
      {option.name} - {option.description}
    </Checkbox>
  {/each}
</div>

<!-- 처리 전략 -->
<div class="section">
  <h3>처리 전략</h3>
  <Select bind:value={guardrail.pii_strategy} options={strategyOptions} />
</div>

<!-- 커스텀 패턴 -->
<div class="section">
  <h3>커스텀 패턴</h3>
  {#each guardrail.custom_patterns as pattern, i}
    <div class="pattern-row">
      <input bind:value={pattern.name} placeholder="패턴 이름" />
      <input bind:value={pattern.pattern} placeholder="정규식 패턴" />
      <button on:click={() => removePattern(i)}>삭제</button>
    </div>
  {/each}
  <button on:click={addPattern}>패턴 추가</button>
</div>

<!-- 금지어 -->
<div class="section">
  <h3>금지어</h3>
  <TagInput bind:tags={guardrail.blocked_words} placeholder="금지어 입력 후 Enter" />
</div>

<!-- LLM Judge -->
<div class="section">
  <h3>LLM 기반 심사</h3>
  <Toggle bind:checked={guardrail.llm_judge_enabled}>LLM Judge 활성화</Toggle>

  {#if guardrail.llm_judge_enabled}
    <Select
      bind:value={guardrail.llm_judge_model}
      options={judgeModels}
      placeholder="심사 모델 선택"
    />
    <textarea
      bind:value={guardrail.llm_judge_prompt}
      placeholder="심사 기준 프롬프트"
    />
  {/if}
</div>
```

## 3. 에이전트 가드레일 연동

### Selector.svelte

에이전트 편집기에서 가드레일 선택:

```svelte
<script lang="ts">
  import { getGuardrails } from '$lib/apis/guardrails';

  export let selectedGuardrails: string[] = [];

  let guardrails = [];

  onMount(async () => {
    guardrails = await getGuardrails(localStorage.token);
  });

  function toggleGuardrail(id: string) {
    if (selectedGuardrails.includes(id)) {
      selectedGuardrails = selectedGuardrails.filter(g => g !== id);
    } else {
      selectedGuardrails = [...selectedGuardrails, id];
    }
  }
</script>

<div class="guardrail-selector">
  <h4>가드레일 선택</h4>
  <p class="description">
    에이전트에 적용할 가드레일을 선택합니다.
    선택된 가드레일은 입/출력 시 자동으로 적용됩니다.
  </p>

  <div class="guardrail-list">
    {#each guardrails as guardrail}
      <div
        class="guardrail-item"
        class:selected={selectedGuardrails.includes(guardrail.id)}
        on:click={() => toggleGuardrail(guardrail.id)}
      >
        <Checkbox checked={selectedGuardrails.includes(guardrail.id)} />
        <div class="info">
          <div class="name">{guardrail.name}</div>
          <div class="description">{guardrail.description}</div>
        </div>
      </div>
    {/each}
  </div>
</div>
```

### AgentEditor.svelte 통합

```svelte
<script lang="ts">
  import GuardrailSelector from './Guardrails/Selector.svelte';

  // 에이전트 메타에서 가드레일 ID 목록 관리
  let guardrails = model?.meta?.guardrails ?? [];
</script>

<!-- 가드레일 섹션 -->
<div class="section">
  <GuardrailSelector bind:selectedGuardrails={guardrails} />
</div>

<!-- 저장 시 -->
<script>
  function handleSave() {
    const info = {
      ...modelInfo,
      meta: {
        ...modelInfo.meta,
        guardrails: guardrails  // 가드레일 ID 목록 저장
      }
    };
    // API 호출
  }
</script>
```

## 4. 라우팅

```
src/routes/(app)/workspace/guardrails/
├── +page.svelte          # 가드레일 목록
├── create/
│   └── +page.svelte      # 새 가드레일 생성
└── [id]/
    └── +page.svelte      # 가드레일 편집
```

## 5. 테스트 기능

```svelte
<!-- GuardrailEditor.svelte 내 테스트 섹션 -->
<div class="test-section">
  <h3>가드레일 테스트</h3>
  <textarea
    bind:value={testText}
    placeholder="테스트할 텍스트를 입력하세요..."
  />
  <button on:click={handleTest}>테스트 실행</button>

  {#if testResult}
    <div class="test-result" class:blocked={testResult.blocked}>
      {#if testResult.blocked}
        <div class="blocked-message">차단됨: {testResult.message}</div>
      {:else}
        <div class="processed">
          <h4>처리된 텍스트:</h4>
          <pre>{testResult.processed_text}</pre>
        </div>
      {/if}

      {#if testResult.violations.length > 0}
        <div class="violations">
          <h4>탐지된 항목 ({testResult.violations.length}개):</h4>
          {#each testResult.violations as violation}
            <div class="violation-item">
              <span class="type">{violation.type}</span>
              <span class="matched">{violation.matched}</span>
            </div>
          {/each}
        </div>
      {/if}
    </div>
  {/if}
</div>
```

# Auto Evaluation 프론트엔드

## 1. 컴포넌트 구조

```
src/lib/components/
├── workspace/Agents/
│   └── AutoEvaluation.svelte      # 에이전트 설정 UI
│
└── admin/Evaluations/
    ├── AutoResults.svelte         # 결과 목록/필터
    └── AutoResultDetail.svelte    # 상세 모달
```

## 2. 에이전트 설정 UI

### AutoEvaluation.svelte

```svelte
<script lang="ts">
  import { models } from '$lib/stores';
  import Checkbox from '$lib/components/common/Checkbox.svelte';

  export let autoEvaluation = {
    enabled: false,
    samplingRate: 0.1,
    evaluationTypes: [],
    judgeModelId: null
  };

  const evaluationTypeOptions = [
    { id: 'retrieval', name: 'Retrieval Quality', description: '검색 품질 평가' },
    { id: 'faithfulness', name: 'Faithfulness', description: '충실도 평가' },
    { id: 'quality', name: 'Response Quality', description: '응답 품질 평가' }
  ];

  // 심사 모델은 에이전트(preset) 제외
  $: judgeModels = $models.filter(m => !m?.preset && !(m?.arena ?? false));
</script>

<div>
  <!-- 활성화 토글 -->
  <div class="header">
    <span>자동 평가</span>
    <Checkbox
      state={autoEvaluation.enabled ? 'checked' : 'unchecked'}
      on:change={(e) => autoEvaluation.enabled = e.detail === 'checked'}
    />
  </div>

  {#if autoEvaluation.enabled}
    <div class="settings">
      <!-- 샘플링 비율 -->
      <div class="field">
        <label>샘플링 비율: {Math.round(autoEvaluation.samplingRate * 100)}%</label>
        <input
          type="range"
          min="0.01" max="1" step="0.01"
          bind:value={autoEvaluation.samplingRate}
        />
      </div>

      <!-- 평가 유형 선택 -->
      <div class="field">
        <label>평가 유형</label>
        {#each evaluationTypeOptions as option}
          <Checkbox
            state={autoEvaluation.evaluationTypes.includes(option.id) ? 'checked' : 'unchecked'}
            on:change={() => toggleType(option.id)}
          >
            {option.name} - {option.description}
          </Checkbox>
        {/each}
      </div>

      <!-- 심사 모델 선택 -->
      <div class="field">
        <label>심사 모델</label>
        <select bind:value={autoEvaluation.judgeModelId}>
          <option value={null}>모델 선택...</option>
          {#each judgeModels as model}
            <option value={model.id}>{model.name || model.id}</option>
          {/each}
        </select>
      </div>
    </div>
  {/if}
</div>
```

### AgentEditor.svelte 통합

```svelte
<script lang="ts">
  import AutoEvaluationSection from './AutoEvaluation.svelte';

  // 상태 관리
  let autoEvaluation = {
    enabled: false,
    samplingRate: 0.1,
    evaluationTypes: [],
    judgeModelId: null
  };

  onMount(() => {
    // 기존 설정 로드
    autoEvaluation = model?.meta?.autoEvaluation ?? {
      enabled: false,
      samplingRate: 0.1,
      evaluationTypes: [],
      judgeModelId: null
    };
  });

  function handleSave() {
    const info = {
      ...modelInfo,
      meta: {
        ...modelInfo.meta,
        autoEvaluation: autoEvaluation.enabled ? autoEvaluation : undefined
      }
    };
    // 저장 API 호출
  }
</script>

<!-- 가드레일 섹션 다음에 배치 -->
<AutoEvaluationSection bind:autoEvaluation />
```

## 3. 관리자 결과 조회 UI

### Evaluations.svelte (탭 추가)

```svelte
<script>
  import AutoResults from './Evaluations/AutoResults.svelte';
  let selectedTab = 'leaderboard';
</script>

<div class="tabs">
  <button on:click={() => selectedTab = 'leaderboard'}>Leaderboard</button>
  <button on:click={() => selectedTab = 'feedbacks'}>Feedbacks</button>
  <button on:click={() => selectedTab = 'auto'}>평가결과</button>  <!-- 새 탭 -->
</div>

<div class="content">
  {#if selectedTab === 'auto'}
    <AutoResults />
  {/if}
</div>
```

### AutoResults.svelte

```svelte
<script lang="ts">
  import { DropdownMenu } from 'bits-ui';
  import { getAutoEvaluations, getAutoEvaluationStats } from '$lib/apis/auto-evaluations';

  // 필터 상태
  let selectedModels: string[] = [];
  let selectedTypes: string[] = [];
  let selectedStatuses: string[] = [];
  let dateRange = '7d';

  // 데이터
  let autoEvaluations = [];
  let stats = null;
  let total = 0;
  let page = 1;

  async function loadData() {
    const filters = {
      page,
      limit: 10,
      date_from: fromDate,
      date_to: toDate
    };

    // 멀티셀렉트 필터 적용
    if (selectedModels.length > 0 && selectedModels.length < availableModels.length) {
      filters.model_id = selectedModels[0];
    }

    const response = await getAutoEvaluations(localStorage.token, filters);
    autoEvaluations = response.items;
    total = response.total;
  }
</script>

<!-- 헤더 -->
<div class="header">
  <h2>평가 결과 ({total})</h2>
  <div class="actions">
    <button on:click={() => handleExport('json')}>JSON</button>
    <button on:click={() => handleExport('csv')}>CSV</button>
  </div>
</div>

<!-- 필터 -->
<div class="filters">
  <!-- 기간 필터 -->
  <select bind:value={dateRange} on:change={handleDateChange}>
    <option value="1d">최근 1일</option>
    <option value="7d">최근 7일</option>
    <option value="30d">최근 30일</option>
    <option value="all">전체</option>
    <option value="custom">직접 지정</option>
  </select>

  <!-- 모델 멀티셀렉트 -->
  <DropdownMenu.Root>
    <DropdownMenu.Trigger>
      <button>{getModelFilterLabel()}</button>
    </DropdownMenu.Trigger>
    <DropdownMenu.Content>
      {#each availableModels as model}
        <DropdownMenu.Item onSelect={() => toggleModel(model.id)}>
          <Checkbox checked={selectedModels.includes(model.id)} />
          {model.name}
        </DropdownMenu.Item>
      {/each}
    </DropdownMenu.Content>
  </DropdownMenu.Root>

  <!-- 유형, 상태 필터도 동일 패턴 -->
</div>

<!-- 통계 요약 -->
{#if stats}
  <div class="stats-summary">
    <div class="stat">
      <span class="value">{stats.total_count}</span>
      <span class="label">전체</span>
    </div>
    <div class="stat completed">
      <span class="value">{stats.completed_count}</span>
      <span class="label">완료</span>
    </div>
    <div class="stat pending">
      <span class="value">{stats.pending_count}</span>
      <span class="label">대기</span>
    </div>
    <div class="stat">
      <span class="value">{formatScore(stats.avg_score)}</span>
      <span class="label">평균 점수</span>
    </div>
  </div>
{/if}

<!-- 결과 테이블 -->
<table>
  <thead>
    <tr>
      <th>모델</th>
      <th>유형</th>
      <th>점수</th>
      <th>상태</th>
      <th>생성일</th>
      <th></th>
    </tr>
  </thead>
  <tbody>
    {#each autoEvaluations as evaluation}
      <tr on:click={() => openDetail(evaluation)}>
        <td>{evaluation.model_id}</td>
        <td>{evaluation.evaluation_type}</td>
        <td class={getScoreColor(evaluation.score)}>{formatScore(evaluation.score)}</td>
        <td><Badge type={getStatusBadgeType(evaluation.status)}>{evaluation.status}</Badge></td>
        <td>{dayjs(evaluation.created_at * 1000).fromNow()}</td>
        <td><button on:click|stopPropagation={() => handleDelete(evaluation.id)}>삭제</button></td>
      </tr>
    {/each}
  </tbody>
</table>

<!-- 페이지네이션 -->
<Pagination bind:page count={total} perPage={10} />
```

### AutoResultDetail.svelte

```svelte
<script lang="ts">
  import Modal from '$lib/components/common/Modal.svelte';
  import { getAutoEvaluationById } from '$lib/apis/auto-evaluations';

  export let evaluation;

  let fullEvaluation = null;

  onMount(async () => {
    fullEvaluation = await getAutoEvaluationById(localStorage.token, evaluation.id);
  });
</script>

<Modal size="lg" show={true} on:close>
  <div class="detail">
    <!-- 기본 정보 -->
    <div class="grid">
      <div>
        <label>상태</label>
        <Badge type={getStatusBadgeType(fullEvaluation.status)}>
          {fullEvaluation.status}
        </Badge>
      </div>
      <div>
        <label>점수</label>
        <span class={getScoreColor(fullEvaluation.score)}>
          {formatScore(fullEvaluation.score)}
        </span>
      </div>
      <div>
        <label>유형</label>
        <span>{getTypeName(fullEvaluation.evaluation_type)}</span>
      </div>
    </div>

    <!-- 모델 정보 -->
    <div class="models">
      <div>
        <label>평가 대상 모델</label>
        <code>{fullEvaluation.model_id}</code>
      </div>
      <div>
        <label>심사 모델</label>
        <code>{fullEvaluation.judge_model_id}</code>
      </div>
    </div>

    <!-- 평가 근거 -->
    {#if fullEvaluation.reasoning}
      <div class="reasoning">
        <label>평가 근거</label>
        <pre>{fullEvaluation.reasoning}</pre>
      </div>
    {/if}

    <!-- 원본 대화 -->
    {#if fullEvaluation.user_query}
      <div class="query">
        <label>사용자 질문</label>
        <pre>{fullEvaluation.user_query}</pre>
      </div>
    {/if}

    {#if fullEvaluation.assistant_response}
      <div class="response">
        <label>어시스턴트 응답</label>
        <pre>{fullEvaluation.assistant_response}</pre>
      </div>
    {/if}

    <!-- 검색 컨텍스트 -->
    {#if fullEvaluation.retrieved_contexts?.length > 0}
      <div class="contexts">
        <label>검색된 컨텍스트 ({fullEvaluation.retrieved_contexts.length}개)</label>
        {#each fullEvaluation.retrieved_contexts as context, idx}
          <div class="context-item">
            <span class="index">#{idx + 1}</span>
            <pre>{context.content || context.text}</pre>
          </div>
        {/each}
      </div>
    {/if}
  </div>
</Modal>
```

## 4. 점수 표시 유틸리티

```typescript
// 점수 포맷팅
function formatScore(score: number | undefined): string {
  if (score === undefined || score === null) return '-';
  return (score * 100).toFixed(1) + '%';
}

// 점수별 색상
function getScoreColor(score: number | undefined): string {
  if (score === undefined || score === null) return 'text-gray-500';
  if (score >= 0.8) return 'text-green-600';
  if (score >= 0.5) return 'text-yellow-600';
  return 'text-red-600';
}

// 상태별 배지 타입
function getStatusBadgeType(status: string): 'success' | 'warning' | 'error' {
  switch (status) {
    case 'completed': return 'success';
    case 'pending': return 'warning';
    case 'failed': return 'error';
    default: return 'muted';
  }
}
```

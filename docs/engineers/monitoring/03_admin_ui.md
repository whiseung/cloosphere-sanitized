# Monitoring 관리자 UI

## 1. 개요

관리자 패널의 Monitoring 탭에서 Usage와 Audit Logs를 조회할 수 있습니다. 이 문서는 관련 UI 컴포넌트와 접근 권한에 대해 설명합니다.

## 2. 접근 권한

### 권한 체계

Monitoring 탭에 접근하려면 다음 조건 중 하나를 만족해야 합니다:

1. `admin` 역할
2. `userPermissions.admin.monitoring` 권한

```svelte
<script lang="ts">
  import { user, userPermissions } from '$lib/stores';

  $: isAdmin = $user?.role === 'admin';
  $: hasMonitoringAccess = isAdmin || $userPermissions?.admin?.monitoring;
</script>

{#if hasMonitoringAccess}
  <a href="/admin/monitoring">Monitoring</a>
{/if}
```

### 권한 설정

그룹 권한 설정에서 `admin.monitoring` 권한을 부여할 수 있습니다:

```json
{
  "permissions": {
    "admin": {
      "monitoring": true
    }
  }
}
```

## 3. 페이지 구조

### 라우트

```
src/routes/(app)/admin/monitoring/
└── +page.svelte
```

### 레이아웃

```svelte
<!-- src/routes/(app)/admin/monitoring/+page.svelte -->
<script lang="ts">
  import Usage from '$lib/components/admin/Monitoring/Usage.svelte';
  import AuditLogs from '$lib/components/admin/Monitoring/AuditLogs.svelte';
  import SystemInfo from '$lib/components/admin/Monitoring/SystemInfo.svelte';

  let activeTab = 'usage';
</script>

<div class="monitoring-page">
  <!-- 탭 네비게이션 -->
  <div class="tabs">
    <button
      class:active={activeTab === 'usage'}
      on:click={() => activeTab = 'usage'}
    >
      Usage
    </button>
    <button
      class:active={activeTab === 'audit'}
      on:click={() => activeTab = 'audit'}
    >
      Audit Logs
    </button>
    <button
      class:active={activeTab === 'system'}
      on:click={() => activeTab = 'system'}
    >
      System Info
    </button>
  </div>

  <!-- 탭 콘텐츠 -->
  <div class="tab-content">
    {#if activeTab === 'usage'}
      <Usage />
    {:else if activeTab === 'audit'}
      <AuditLogs />
    {:else if activeTab === 'system'}
      <SystemInfo />
    {/if}
  </div>
</div>
```

## 4. Usage 컴포넌트

### 파일 위치

```
src/lib/components/admin/Monitoring/Usage.svelte
```

### 주요 기능

1. **기간 필터**: 날짜 범위 선택
2. **사용자 필터**: 특정 사용자 선택
3. **모델/에이전트 필터**: 특정 모델 또는 에이전트 선택
4. **통계 차트**: 일별/주별/월별 사용량 차트
5. **요약 카드**: 총 토큰, 요청 수, 평균 등

### 컴포넌트 구조

```svelte
<script lang="ts">
  import { onMount, getContext } from 'svelte';
  import { getUsageStats, getUsages } from '$lib/apis/usage';

  const i18n = getContext('i18n');

  // 필터 상태
  let dateRange = {
    start: Date.now() - 7 * 24 * 60 * 60 * 1000, // 7일 전
    end: Date.now()
  };
  let selectedUser = '';
  let selectedAgent = '';
  let selectedModel = '';
  let groupBy = 'day';

  // 데이터
  let stats = null;
  let loading = false;

  async function loadStats() {
    loading = true;
    try {
      stats = await getUsageStats(localStorage.token, {
        start_date: Math.floor(dateRange.start / 1000),
        end_date: Math.floor(dateRange.end / 1000),
        user_id: selectedUser || undefined,
        agent_id: selectedAgent || undefined,
        model_id: selectedModel || undefined,
        group_by: groupBy
      });
    } finally {
      loading = false;
    }
  }

  onMount(loadStats);
</script>

<!-- 필터 영역 -->
<div class="filters flex gap-4 mb-6">
  <DateRangePicker
    bind:startDate={dateRange.start}
    bind:endDate={dateRange.end}
    on:change={loadStats}
  />

  <select
    bind:value={selectedUser}
    on:change={loadStats}
    class="input"
  >
    <option value="">{$i18n.t('All Users')}</option>
    {#each users as user}
      <option value={user.id}>{user.name}</option>
    {/each}
  </select>

  <select
    bind:value={selectedAgent}
    on:change={loadStats}
    class="input"
  >
    <option value="">{$i18n.t('All Agents')}</option>
    {#each agents as agent}
      <option value={agent.id}>{agent.name}</option>
    {/each}
  </select>

  <select
    bind:value={groupBy}
    on:change={loadStats}
    class="input"
  >
    <option value="day">{$i18n.t('Daily')}</option>
    <option value="week">{$i18n.t('Weekly')}</option>
    <option value="month">{$i18n.t('Monthly')}</option>
  </select>
</div>

<!-- 요약 카드 -->
{#if stats}
  <div class="grid grid-cols-4 gap-4 mb-6">
    <SummaryCard
      title={$i18n.t('Total Tokens')}
      value={formatNumber(stats.summary.total_tokens)}
      icon="token"
    />
    <SummaryCard
      title={$i18n.t('Total Requests')}
      value={formatNumber(stats.summary.total_requests)}
      icon="request"
    />
    <SummaryCard
      title={$i18n.t('Avg Tokens/Request')}
      value={formatNumber(stats.summary.avg_tokens_per_request)}
      icon="average"
    />
    <SummaryCard
      title={$i18n.t('Active Users')}
      value={formatNumber(stats.summary.active_users)}
      icon="users"
    />
  </div>

  <!-- 사용량 차트 -->
  <div class="chart-container mb-6">
    <UsageChart data={stats.daily} />
  </div>

  <!-- 상위 사용자 테이블 -->
  <div class="top-users mb-6">
    <h3 class="text-lg font-semibold mb-4">{$i18n.t('Top Users')}</h3>
    <table class="w-full">
      <thead>
        <tr class="text-left text-gray-500 dark:text-gray-400">
          <th class="py-2">{$i18n.t('User')}</th>
          <th class="py-2">{$i18n.t('Tokens')}</th>
          <th class="py-2">{$i18n.t('Requests')}</th>
        </tr>
      </thead>
      <tbody>
        {#each stats.top_users as user}
          <tr class="border-t dark:border-gray-700">
            <td class="py-2">{user.name}</td>
            <td class="py-2">{formatNumber(user.total_tokens)}</td>
            <td class="py-2">{formatNumber(user.request_count)}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>

  <!-- 모델별 사용량 -->
  <div class="model-usage">
    <h3 class="text-lg font-semibold mb-4">{$i18n.t('Usage by Model')}</h3>
    <ModelUsageChart data={stats.by_model} />
  </div>
{/if}
```

## 5. AuditLogs 컴포넌트

### 파일 위치

```
src/lib/components/admin/Monitoring/AuditLogs.svelte
```

### 주요 기능

1. **Action 필터**: 특정 작업 유형 필터링
2. **Resource 필터**: 특정 리소스 유형 필터링
3. **사용자 필터**: 특정 사용자 활동 필터링
4. **기간 필터**: 날짜 범위 선택
5. **페이지네이션**: 대량 로그 페이징
6. **CSV 내보내기**: 필터링된 로그 다운로드
7. **상세 보기**: 각 로그의 상세 정보 모달

### 컴포넌트 구조

```svelte
<script lang="ts">
  import { onMount, getContext } from 'svelte';
  import { getAuditLogs, exportAuditLogs } from '$lib/apis/audit_logs';
  import { saveAs } from 'file-saver';

  const i18n = getContext('i18n');

  // 필터 상태
  let filters = {
    action: '',
    resource_type: '',
    user_id: '',
    start_date: null,
    end_date: null
  };

  // 페이징
  let page = 1;
  let limit = 50;
  let total = 0;

  // 데이터
  let logs = [];
  let loading = false;
  let selectedLog = null;
  let showDetailModal = false;

  async function loadLogs() {
    loading = true;
    try {
      const result = await getAuditLogs(
        localStorage.token,
        page,
        limit,
        filters
      );
      logs = result.items;
      total = result.total;
    } finally {
      loading = false;
    }
  }

  async function handleExport() {
    const blob = await exportAuditLogs(localStorage.token, filters);
    saveAs(blob, `audit-logs-${Date.now()}.csv`);
  }

  function showDetails(log) {
    selectedLog = log;
    showDetailModal = true;
  }

  onMount(loadLogs);
</script>

<!-- 필터 영역 -->
<div class="filters flex flex-wrap gap-4 mb-6">
  <select bind:value={filters.action} on:change={loadLogs} class="input">
    <option value="">{$i18n.t('All Actions')}</option>
    <option value="create">{$i18n.t('Create')}</option>
    <option value="update">{$i18n.t('Update')}</option>
    <option value="delete">{$i18n.t('Delete')}</option>
    <option value="login">{$i18n.t('Login')}</option>
    <option value="logout">{$i18n.t('Logout')}</option>
    <option value="login_failed">{$i18n.t('Login Failed')}</option>
  </select>

  <select bind:value={filters.resource_type} on:change={loadLogs} class="input">
    <option value="">{$i18n.t('All Resources')}</option>
    <option value="user">{$i18n.t('User')}</option>
    <option value="chat">{$i18n.t('Chat')}</option>
    <option value="knowledge">{$i18n.t('Knowledge')}</option>
    <option value="model">{$i18n.t('Model')}</option>
    <option value="settings">{$i18n.t('Settings')}</option>
  </select>

  <DateRangePicker
    bind:startDate={filters.start_date}
    bind:endDate={filters.end_date}
    on:change={loadLogs}
  />

  <button
    class="btn btn-secondary"
    on:click={handleExport}
  >
    {$i18n.t('Export CSV')}
  </button>
</div>

<!-- 로그 테이블 -->
<div class="overflow-x-auto">
  <table class="w-full">
    <thead>
      <tr class="text-left text-gray-500 dark:text-gray-400 border-b dark:border-gray-700">
        <th class="py-3">{$i18n.t('Time')}</th>
        <th class="py-3">{$i18n.t('User')}</th>
        <th class="py-3">{$i18n.t('Action')}</th>
        <th class="py-3">{$i18n.t('Resource')}</th>
        <th class="py-3">{$i18n.t('IP Address')}</th>
        <th class="py-3"></th>
      </tr>
    </thead>
    <tbody>
      {#each logs as log}
        <tr class="border-b dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-800">
          <td class="py-3">{formatDateTime(log.created_at)}</td>
          <td class="py-3">{log.user_id}</td>
          <td class="py-3">
            <span class="badge badge-{getActionColor(log.action)}">
              {log.action}
            </span>
          </td>
          <td class="py-3">
            <span class="text-gray-500">{log.resource_type}</span>
            {#if log.resource_id}
              <span class="text-xs text-gray-400">/ {log.resource_id}</span>
            {/if}
          </td>
          <td class="py-3 text-gray-500">{log.ip_address || '-'}</td>
          <td class="py-3">
            <button
              class="text-blue-500 hover:underline"
              on:click={() => showDetails(log)}
            >
              {$i18n.t('Details')}
            </button>
          </td>
        </tr>
      {/each}
    </tbody>
  </table>
</div>

<!-- 페이지네이션 -->
<Pagination
  bind:page
  {total}
  {limit}
  on:change={loadLogs}
/>

<!-- 상세 모달 -->
{#if showDetailModal && selectedLog}
  <Modal bind:show={showDetailModal}>
    <h2 class="text-xl font-semibold mb-4">{$i18n.t('Log Details')}</h2>

    <div class="space-y-4">
      <div>
        <label class="text-gray-500">{$i18n.t('Time')}</label>
        <p>{formatDateTime(selectedLog.created_at)}</p>
      </div>

      <div>
        <label class="text-gray-500">{$i18n.t('User')}</label>
        <p>{selectedLog.user_id}</p>
      </div>

      <div>
        <label class="text-gray-500">{$i18n.t('Action')}</label>
        <p>{selectedLog.action}</p>
      </div>

      <div>
        <label class="text-gray-500">{$i18n.t('Resource')}</label>
        <p>{selectedLog.resource_type} / {selectedLog.resource_id || '-'}</p>
      </div>

      <div>
        <label class="text-gray-500">{$i18n.t('IP Address')}</label>
        <p>{selectedLog.ip_address || '-'}</p>
      </div>

      <div>
        <label class="text-gray-500">{$i18n.t('User Agent')}</label>
        <p class="text-sm break-all">{selectedLog.user_agent || '-'}</p>
      </div>

      {#if selectedLog.details}
        <div>
          <label class="text-gray-500">{$i18n.t('Details')}</label>
          <pre class="bg-gray-100 dark:bg-gray-800 p-3 rounded text-sm overflow-x-auto">
            {JSON.stringify(selectedLog.details, null, 2)}
          </pre>
        </div>
      {/if}
    </div>
  </Modal>
{/if}
```

## 6. SystemInfo 컴포넌트

### 파일 위치

```
src/lib/components/admin/Monitoring/SystemInfo.svelte
```

### 주요 기능

1. **서버 정보**: 버전, 환경, 가동 시간
2. **데이터베이스 상태**: 연결 상태, 테이블 통계
3. **벡터 DB 상태**: 연결 상태, 인덱스 정보

```svelte
<script lang="ts">
  import { onMount } from 'svelte';
  import { getSystemInfo } from '$lib/apis';

  let systemInfo = null;

  onMount(async () => {
    systemInfo = await getSystemInfo(localStorage.token);
  });
</script>

{#if systemInfo}
  <div class="grid grid-cols-2 gap-6">
    <!-- 서버 정보 -->
    <div class="card p-4">
      <h3 class="text-lg font-semibold mb-4">Server</h3>
      <dl class="space-y-2">
        <div class="flex justify-between">
          <dt class="text-gray-500">Version</dt>
          <dd>{systemInfo.version}</dd>
        </div>
        <div class="flex justify-between">
          <dt class="text-gray-500">Environment</dt>
          <dd>{systemInfo.environment}</dd>
        </div>
        <div class="flex justify-between">
          <dt class="text-gray-500">Uptime</dt>
          <dd>{formatUptime(systemInfo.uptime)}</dd>
        </div>
      </dl>
    </div>

    <!-- 데이터베이스 정보 -->
    <div class="card p-4">
      <h3 class="text-lg font-semibold mb-4">Database</h3>
      <dl class="space-y-2">
        <div class="flex justify-between">
          <dt class="text-gray-500">Status</dt>
          <dd class="text-green-500">Connected</dd>
        </div>
        <div class="flex justify-between">
          <dt class="text-gray-500">Users</dt>
          <dd>{systemInfo.stats.users}</dd>
        </div>
        <div class="flex justify-between">
          <dt class="text-gray-500">Chats</dt>
          <dd>{systemInfo.stats.chats}</dd>
        </div>
      </dl>
    </div>
  </div>
{/if}
```

## 7. 스타일링

### 공통 스타일

```css
/* 필터 영역 */
.filters {
  @apply flex flex-wrap gap-4 p-4 bg-gray-50 dark:bg-gray-800 rounded-lg;
}

/* 카드 */
.card {
  @apply bg-white dark:bg-gray-850 rounded-xl border border-gray-100 dark:border-gray-800;
}

/* 뱃지 */
.badge {
  @apply px-2 py-0.5 rounded text-xs font-medium;
}

.badge-create { @apply bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300; }
.badge-update { @apply bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300; }
.badge-delete { @apply bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-300; }
.badge-login { @apply bg-purple-100 text-purple-700 dark:bg-purple-900 dark:text-purple-300; }

/* 테이블 */
table {
  @apply w-full;
}

th {
  @apply text-left text-gray-500 dark:text-gray-400 font-medium;
}

td {
  @apply py-3;
}

tr {
  @apply border-b dark:border-gray-700;
}

tr:hover {
  @apply bg-gray-50 dark:bg-gray-800;
}
```

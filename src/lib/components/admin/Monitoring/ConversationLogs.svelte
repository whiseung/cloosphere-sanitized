<script lang="ts">
	import { getContext, onMount } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { DropdownMenu } from 'bits-ui';
	import { flyAndScale } from '$lib/utils/transitions';

	import MagnifyingGlass from '$lib/components/icons/MagnifyingGlass.svelte';
	import ArrowPath from '$lib/components/icons/ArrowPath.svelte';
	import ChevronLeft from '$lib/components/icons/ChevronLeft.svelte';
	import ChevronRight from '$lib/components/icons/ChevronRight.svelte';
	import ChevronDown from '$lib/components/icons/ChevronDown.svelte';
	import XMark from '$lib/components/icons/XMark.svelte';
	import Checkbox from '$lib/components/common/Checkbox.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import Modal from '$lib/components/common/Modal.svelte';
	import Button from '$lib/components/common/Button.svelte';
	import Input from '$lib/components/common/Input.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';

	import {
		getConversationLogs,
		getConversationLogStats,
		getConversationLogFilterModels,
		getConversationLogFilterUsers,
		type ConversationLog,
		type ConversationLogStats
	} from '$lib/apis/conversation-logs';

	const i18n = getContext('i18n');

	// State
	let loading = true;
	let logs: ConversationLog[] = [];
	let total = 0;
	let totalPages = 0;
	let stats: ConversationLogStats = {
		total_requests: 0,
		total_tokens: 0,
		unique_users: 0,
		unique_models: 0
	};
	let filterModels: { id: string; name: string }[] = [];
	let filterUsers: { id: string; name: string }[] = [];

	// Filters
	let page = 1;
	let limit = 50;
	let selectedSourceTypes: string[] = [];
	let selectedModelIds: string[] = [];
	let searchUser = '';
	let expandedId: string | null = null;

	// Dropdown state
	let showSourceDropdown = false;
	let showModelDropdown = false;

	// 고정 Source Type 목록
	const availableSourceTypes = ['chat', 'agent', 'code_gateway', 'api'];

	// Date range (기본값: 최근 7일)
	let dateRange = '7d';
	let fromDate: number | null = null;
	let toDate: number | null = null;

	// 직접 지정용 날짜
	let customFromDate = '';
	let customToDate = '';
	let customDateLabel = '';
	let showCustomDateModal = false;

	const toDateTimeLocal = (date: Date) => {
		const pad = (n: number) => n.toString().padStart(2, '0');
		return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
	};

	const setDateRange = (range: string) => {
		if (range === 'custom') {
			const now = new Date();
			const weekAgo = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
			customFromDate = toDateTimeLocal(weekAgo);
			customToDate = toDateTimeLocal(now);
			customDateLabel = `${formatDateTimeLabel(customFromDate)} ~ ${formatDateTimeLabel(customToDate)}`;
			showCustomDateModal = true;
			return;
		}

		dateRange = range;
		const now = Math.floor(Date.now() / 1000);
		toDate = now;

		switch (range) {
			case '1h':
				fromDate = now - 3600;
				break;
			case '6h':
				fromDate = now - 3600 * 6;
				break;
			case '1d':
				fromDate = now - 86400;
				break;
			case '7d':
				fromDate = now - 86400 * 7;
				break;
			case '30d':
				fromDate = now - 86400 * 30;
				break;
			case 'all':
				fromDate = null;
				toDate = null;
				break;
			default:
				fromDate = now - 86400 * 7;
		}
	};

	const applyCustomDateRange = () => {
		if (customFromDate && customToDate) {
			fromDate = Math.floor(new Date(customFromDate).getTime() / 1000);
			toDate = Math.floor(new Date(customToDate).getTime() / 1000);
			customDateLabel = `${formatDateTimeLabel(customFromDate)} ~ ${formatDateTimeLabel(customToDate)}`;
			dateRange = 'custom';
			showCustomDateModal = false;
			handleSearch();
		}
	};

	const formatDateTimeLabel = (dateStr: string) => {
		if (!dateStr) return '';
		const date = new Date(dateStr);
		const month = (date.getMonth() + 1).toString().padStart(2, '0');
		const day = date.getDate().toString().padStart(2, '0');
		const hours = date.getHours().toString().padStart(2, '0');
		const minutes = date.getMinutes().toString().padStart(2, '0');
		return `${month}/${day} ${hours}:${minutes}`;
	};

	const getCustomDateLabel = () => {
		if (dateRange === 'custom' && customDateLabel) {
			return customDateLabel;
		}
		return '';
	};

	// 초기 날짜 범위 설정
	setDateRange('7d');

	// 멀티셀렉트 토글 함수
	const toggleSourceType = (type: string) => {
		if (selectedSourceTypes.includes(type)) {
			selectedSourceTypes = selectedSourceTypes.filter((t) => t !== type);
		} else {
			selectedSourceTypes = [...selectedSourceTypes, type];
		}
	};

	const toggleModelId = (id: string) => {
		if (selectedModelIds.includes(id)) {
			selectedModelIds = selectedModelIds.filter((m) => m !== id);
		} else {
			selectedModelIds = [...selectedModelIds, id];
		}
	};

	const toggleAllSourceTypes = () => {
		if (selectedSourceTypes.length === availableSourceTypes.length) {
			selectedSourceTypes = [];
		} else {
			selectedSourceTypes = [...availableSourceTypes];
		}
	};

	const toggleAllModels = () => {
		if (selectedModelIds.length === filterModels.length) {
			selectedModelIds = [];
		} else {
			selectedModelIds = filterModels.map((m) => m.id);
		}
	};

	// 필터 라벨 (reactive)
	$: sourceFilterLabel = (() => {
		if (
			selectedSourceTypes.length === availableSourceTypes.length &&
			availableSourceTypes.length > 0
		) {
			return $i18n.t('All Sources');
		}
		if (selectedSourceTypes.length === 0) {
			return $i18n.t('All Sources');
		}
		if (selectedSourceTypes.length === 1) {
			return getSourceFilterLabel(selectedSourceTypes[0]);
		}
		return `${selectedSourceTypes.length} ${$i18n.t('selected')}`;
	})();

	$: modelFilterLabel = (() => {
		if (selectedModelIds.length === filterModels.length && filterModels.length > 0) {
			return $i18n.t('All Models');
		}
		if (selectedModelIds.length === 0) {
			return $i18n.t('All Models');
		}
		if (selectedModelIds.length === 1) {
			const m = filterModels.find((m) => m.id === selectedModelIds[0]);
			return m?.name || selectedModelIds[0];
		}
		return `${selectedModelIds.length} ${$i18n.t('selected')}`;
	})();

	const getSourceFilterLabel = (type: string): string => {
		const labels: Record<string, string> = {
			chat: $i18n.t('Chat'),
			agent: $i18n.t('Agent'),
			code_gateway: $i18n.t('Code Gateway'),
			api: $i18n.t('API')
		};
		return labels[type] || type;
	};

	// 현재 선택이 "부분 선택"이면 콤마 구분 문자열, 아니면 undefined
	const getActiveSourceTypeFilter = () =>
		selectedSourceTypes.length > 0 && selectedSourceTypes.length < availableSourceTypes.length
			? selectedSourceTypes.join(',')
			: undefined;

	const getActiveModelFilter = () =>
		selectedModelIds.length > 0 && selectedModelIds.length < filterModels.length
			? selectedModelIds.join(',')
			: undefined;

	// Cascading: source type 변경 → model 옵션 갱신
	const refreshModelOptions = async () => {
		try {
			const params: { source_type?: string } = {};
			const stFilter = getActiveSourceTypeFilter();
			if (stFilter) params.source_type = stFilter;
			const newModels = await getConversationLogFilterModels(localStorage.token, params);
			filterModels = newModels;
			// 기존 선택 중 사라진 옵션 제거
			const newIds = new Set(newModels.map((m) => m.id));
			selectedModelIds = selectedModelIds.filter((id) => newIds.has(id));
			if (selectedModelIds.length === 0) selectedModelIds = newModels.map((m) => m.id);
		} catch {
			filterModels = [];
		}
	};

	const loadLogs = async () => {
		loading = true;
		try {
			const params: Record<string, unknown> = { page, limit };
			const stFilter = getActiveSourceTypeFilter();
			const modelFilter = getActiveModelFilter();
			if (stFilter) params.source_type = stFilter;
			if (modelFilter) params.model_id = modelFilter;
			if (searchUser) params.user_search = searchUser;
			if (fromDate) params.from_date = fromDate;
			if (toDate) params.to_date = toDate;

			const result = await getConversationLogs(localStorage.token, params);
			logs = result.items;
			total = result.total;
			totalPages = result.total_pages;
		} catch (error: any) {
			console.error('Conversation logs error:', error);
			const message = error?.detail || error?.message || 'Unknown error';
			toast.error(`${$i18n.t('Failed to load conversation logs')}: ${message}`);
		}
		loading = false;
	};

	const loadStats = async () => {
		try {
			const params: Record<string, unknown> = {};
			const stFilter = getActiveSourceTypeFilter();
			if (stFilter) params.source_type = stFilter;
			if (fromDate) params.from_date = fromDate;
			if (toDate) params.to_date = toDate;
			stats = await getConversationLogStats(localStorage.token, params);
		} catch {
			// ignore
		}
	};

	const loadFilters = async () => {
		try {
			filterModels = await getConversationLogFilterModels(localStorage.token);
		} catch {
			filterModels = [];
		}
		try {
			filterUsers = await getConversationLogFilterUsers(localStorage.token);
		} catch {
			filterUsers = [];
		}
		// 초기 전체 선택
		selectedSourceTypes = [...availableSourceTypes];
		selectedModelIds = filterModels.map((m) => m.id);
	};

	const handleSearch = () => {
		page = 1;
		expandedId = null;
		// 상대 날짜 범위(1h, 7d 등)면 현재 시간 기준으로 재계산
		if (dateRange && dateRange !== 'custom' && dateRange !== 'all') {
			setDateRange(dateRange);
		}
		loadLogs();
		loadStats();
	};

	const handleSearchKeydown = (event: CustomEvent<KeyboardEvent>) => {
		if (event.detail?.key === 'Enter') handleSearch();
	};

	const handlePageChange = (newPage: number) => {
		page = newPage;
		expandedId = null;
		loadLogs();
	};

	const formatTimestamp = (timestamp: number) => {
		return new Date(timestamp * 1000).toLocaleString();
	};

	const formatTokens = (n: number): string => {
		if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
		if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K';
		return String(n);
	};

	const toggleExpand = (id: string) => {
		expandedId = expandedId === id ? null : id;
	};

	const truncateArgs = (args: string | undefined, maxLen = 200): string => {
		if (!args) return '';
		return args.length > maxLen ? args.slice(0, maxLen) + '...' : args;
	};

	onMount(async () => {
		await loadFilters();
		await Promise.all([loadLogs(), loadStats()]);
	});

	// source_type → source_label 변환 (테이블 행에서 사용)
	const getSourceLabel = (sourceType: string): string => {
		if (sourceType === 'chat') return $i18n.t('Chat');
		if (sourceType === 'code_gateway') return $i18n.t('Code');
		if (sourceType === 'generation') return $i18n.t('Agent');
		return sourceType;
	};

	const getSourceStyle = (sourceType: string): string => {
		if (sourceType === 'chat')
			return 'bg-blue-500/20 text-blue-700 dark:text-blue-400';
		if (sourceType === 'code_gateway')
			return 'bg-purple-500/20 text-purple-700 dark:text-purple-400';
		if (sourceType === 'generation')
			return 'bg-green-500/20 text-green-700 dark:text-green-400';
		return 'bg-gray-500/20 text-gray-700 dark:text-gray-400';
	};
</script>

<!-- Header -->
<div class="mt-0.5 mb-2 flex flex-col gap-2">
	<div class="flex items-center justify-between">
		<div class="flex items-center text-lg font-bold px-0.5">
			{$i18n.t('Conversation Logs')}
			<div class="flex self-center w-[1px] h-6 mx-2.5 bg-gray-50 dark:bg-gray-850" />
			<span class="text-lg font-medium text-gray-500 dark:text-gray-300">{total}</span>
		</div>
	</div>

	<div class="flex gap-1.5 flex-wrap items-center">
		<!-- Date Range Filter (pill buttons) -->
		<div class="flex items-center rounded-lg bg-gray-50 dark:bg-gray-950 p-0.5 gap-0.5">
			{#each [
				{ value: '1h', label: '1h' },
				{ value: '6h', label: '6h' },
				{ value: '1d', label: '1d' },
				{ value: '7d', label: '7d' },
				{ value: '30d', label: '30d' },
				{ value: 'all', label: $i18n.t('All') }
			] as opt}
				<button
					class="px-3 py-1.5 text-sm font-medium rounded-md transition-all {dateRange === opt.value
						? 'bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 shadow-sm'
						: 'text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200'}"
					on:click={() => {
						dateRange = opt.value;
						setDateRange(opt.value);
						handleSearch();
					}}
				>
					{opt.label}
				</button>
			{/each}
			<button
				class="px-3 py-1.5 text-sm font-medium rounded-md transition-all {dateRange === 'custom'
					? 'bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 shadow-sm'
					: 'text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200'}"
				on:click={() => setDateRange('custom')}
			>
				{dateRange === 'custom' && customDateLabel ? customDateLabel : $i18n.t('Custom')}
			</button>
		</div>

		<!-- Source Type Filter (Multi-select) -->
		<DropdownMenu.Root
			open={showSourceDropdown}
			onOpenChange={(open) => {
				showSourceDropdown = open;
				if (!open) {
					handleSearch();
					refreshModelOptions();
				}
			}}
		>
			<DropdownMenu.Trigger>
				<button
					class="flex items-center gap-2 px-3 py-1.5 min-w-[140px] text-sm bg-gray-50 dark:bg-gray-950 rounded-lg outline-none cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-900 transition"
				>
					<span class="flex-1 text-left truncate">{sourceFilterLabel}</span>
					<ChevronDown className="size-4 flex-shrink-0" />
				</button>
			</DropdownMenu.Trigger>

			<DropdownMenu.Content
				class="w-48 max-h-72 overflow-y-auto rounded-lg p-1 border border-gray-100 dark:border-gray-850 bg-white dark:bg-gray-900 shadow-lg z-50"
				sideOffset={4}
				transition={flyAndScale}
			>
				<!-- Select All -->
				<button
					class="flex w-full items-center gap-2 px-3 py-2 text-sm rounded-md cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-850 transition"
					on:click|stopPropagation={() => toggleAllSourceTypes()}
				>
					<Checkbox state={selectedSourceTypes.length === availableSourceTypes.length ? 'checked' : 'unchecked'} />
					<span class="font-medium">{$i18n.t('Select All')}</span>
				</button>

				<div class="h-px bg-gray-100 dark:bg-gray-800 my-1" />

				{#each availableSourceTypes as type}
					<button
						class="flex w-full items-center gap-2 px-3 py-2 text-sm rounded-md cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-850 transition"
						on:click|stopPropagation={() => toggleSourceType(type)}
					>
						<Checkbox state={selectedSourceTypes.includes(type) ? 'checked' : 'unchecked'} />
						<span>{getSourceFilterLabel(type)}</span>
					</button>
				{/each}
			</DropdownMenu.Content>
		</DropdownMenu.Root>

		<!-- Model Filter (Multi-select) -->
		{#if filterModels.length > 0}
			<DropdownMenu.Root
				open={showModelDropdown}
				onOpenChange={(open) => {
					showModelDropdown = open;
					if (!open) {
						handleSearch();
					}
				}}
			>
				<DropdownMenu.Trigger>
					<button
						class="flex items-center gap-2 px-3 py-1.5 min-w-[140px] max-w-[280px] text-sm bg-gray-50 dark:bg-gray-950 rounded-lg outline-none cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-900 transition"
					>
						<span class="flex-1 text-left truncate">{modelFilterLabel}</span>
						<ChevronDown className="size-4 flex-shrink-0" />
					</button>
				</DropdownMenu.Trigger>

				<DropdownMenu.Content
					class="w-64 max-h-72 overflow-y-auto rounded-lg p-1 border border-gray-100 dark:border-gray-850 bg-white dark:bg-gray-900 shadow-lg z-50"
					sideOffset={4}
					transition={flyAndScale}
				>
					<!-- Select All -->
					<button
						class="flex w-full items-center gap-2 px-3 py-2 text-sm rounded-md cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-850 transition"
						on:click|stopPropagation={() => toggleAllModels()}
					>
						<Checkbox state={selectedModelIds.length === filterModels.length ? 'checked' : 'unchecked'} />
						<span class="font-medium">{$i18n.t('Select All')}</span>
					</button>

					<div class="h-px bg-gray-100 dark:bg-gray-800 my-1" />

					{#each filterModels as m}
						<button
							class="flex w-full items-center gap-2 px-3 py-2 text-sm rounded-md cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-850 transition"
							on:click|stopPropagation={() => toggleModelId(m.id)}
						>
							<Checkbox state={selectedModelIds.includes(m.id) ? 'checked' : 'unchecked'} />
							<span class="truncate">{m.name}</span>
						</button>
					{/each}
				</DropdownMenu.Content>
			</DropdownMenu.Root>
		{/if}

		<!-- Search User -->
		<div class="w-44">
			<Input
				bind:value={searchUser}
				placeholder={$i18n.t('User')}
				size="sm"
				on:keydown={handleSearchKeydown}
			>
				<svelte:fragment slot="prefix">
					<MagnifyingGlass className="size-4" />
				</svelte:fragment>
			</Input>
		</div>

		<!-- Refresh -->
		<Tooltip content={$i18n.t('Refresh')}>
			<Button kind="text" size="sm" type="button" on:click={handleSearch}>
				<ArrowPath className="size-5" />
			</Button>
		</Tooltip>
	</div>
</div>

<hr class="mb-3 border-gray-50 dark:border-gray-850" />

<!-- Stats Cards -->
<div class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-3">
	<div class="rounded-xl bg-gray-50 dark:bg-gray-850 p-3">
		<div class="text-xs text-gray-500 dark:text-gray-500">{$i18n.t('Total Requests')}</div>
		<div class="text-xl font-semibold mt-0.5">{stats.total_requests.toLocaleString()}</div>
	</div>
	<div class="rounded-xl bg-gray-50 dark:bg-gray-850 p-3">
		<div class="text-xs text-gray-500 dark:text-gray-500">{$i18n.t('Total Tokens')}</div>
		<div class="text-xl font-semibold mt-0.5">{formatTokens(stats.total_tokens)}</div>
	</div>
	<div class="rounded-xl bg-gray-50 dark:bg-gray-850 p-3">
		<div class="text-xs text-gray-500 dark:text-gray-500">{$i18n.t('Unique Users')}</div>
		<div class="text-xl font-semibold mt-0.5">{stats.unique_users}</div>
	</div>
	<div class="rounded-xl bg-gray-50 dark:bg-gray-850 p-3">
		<div class="text-xs text-gray-500 dark:text-gray-500">{$i18n.t('Unique Models')}</div>
		<div class="text-xl font-semibold mt-0.5">{stats.unique_models}</div>
	</div>
</div>

<!-- Content -->
{#if loading}
	<div class="flex justify-center py-8">
		<Spinner className="size-6" />
	</div>
{:else if logs.length === 0}
	<div class="flex flex-col items-center justify-center py-12 text-center">
		<svg
			xmlns="http://www.w3.org/2000/svg"
			viewBox="0 0 24 24"
			fill="currentColor"
			class="size-12 text-gray-400 dark:text-gray-600 mb-4"
		>
			<path
				d="M4.913 2.658c2.075-.27 4.19-.408 6.337-.408 2.147 0 4.262.139 6.337.408 1.922.25 3.291 1.861 3.405 3.727a4.403 4.403 0 00-1.032-.211 50.89 50.89 0 00-8.42 0c-2.358.196-4.04 2.19-4.04 4.434v4.286a4.47 4.47 0 002.433 3.984L7.28 21.53A.75.75 0 016 21v-4.03a48.527 48.527 0 01-1.087-.128C2.905 16.58 1.5 14.833 1.5 12.862V6.638c0-1.97 1.405-3.718 3.413-3.979z"
			/>
			<path
				d="M15.75 7.5c-1.376 0-2.739.057-4.086.169C10.124 7.797 9 9.103 9 10.609v4.285c0 1.507 1.128 2.814 2.67 2.94 1.243.102 2.5.157 3.768.165l2.782 2.781a.75.75 0 001.28-.53v-2.39l.33-.026c1.542-.125 2.67-1.433 2.67-2.94v-4.286c0-1.505-1.125-2.811-2.664-2.94A49.392 49.392 0 0015.75 7.5z"
			/>
		</svg>
		<p class="text-gray-500 dark:text-gray-400">
			{$i18n.t('No conversation logs found')}
		</p>
	</div>
{:else}
	<!-- Table Header -->
	<div class="hidden md:flex text-xs font-medium text-gray-500 px-1 mb-1 uppercase">
		<div class="flex-none w-8" />
		<div class="flex-none w-44">{$i18n.t('Time')}</div>
		<div class="flex-1 min-w-0">{$i18n.t('User')}</div>
		<div class="flex-1 min-w-0">{$i18n.t('Model')}</div>
		<div class="flex-1 min-w-0">{$i18n.t('Agent')}</div>
		<div class="flex-none w-24 text-center">{$i18n.t('Source')}</div>
		<div class="flex-none w-24 text-center">{$i18n.t('Platform')}</div>
		<div class="flex-none w-24 text-right">{$i18n.t('Input')}</div>
		<div class="flex-none w-24 text-right">{$i18n.t('Output')}</div>
		<div class="flex-none w-24 text-right">{$i18n.t('Total')}</div>
	</div>
	<hr class="mb-2 border-gray-50 dark:border-gray-850 hidden md:block" />

	<!-- Table Rows -->
	{#each logs as log}
		<!-- svelte-ignore a11y-click-events-have-key-events -->
		<div
			class="flex flex-col md:flex-row md:items-center py-2 px-1 hover:bg-gray-50 dark:hover:bg-gray-950 rounded-lg gap-1 md:gap-0 cursor-pointer"
			on:click={() => toggleExpand(log.id)}
		>
			<div class="flex-none w-8 flex items-center justify-center text-gray-400">
				<svg
					class="size-3.5 transition-transform {expandedId === log.id ? 'rotate-90' : ''}"
					fill="none"
					viewBox="0 0 24 24"
					stroke="currentColor"
					stroke-width="2"
				>
					<path stroke-linecap="round" stroke-linejoin="round" d="M9 5l7 7-7 7" />
				</svg>
			</div>
			<div class="flex-none w-44 text-sm text-gray-600 dark:text-gray-400">
				{formatTimestamp(log.created_at)}
			</div>
			<div class="flex-1 min-w-0">
				<div class="font-medium text-sm text-gray-900 dark:text-gray-100 truncate">{log.user_name || '-'}</div>
				<div class="text-xs text-gray-500 dark:text-gray-400 truncate">{log.user_email || ''}</div>
			</div>
			<div class="flex-1 min-w-0">
				<span
					class="inline-flex px-1.5 py-0.5 rounded bg-blue-50 dark:bg-blue-900/20 text-blue-700 dark:text-blue-300 text-xs font-mono truncate max-w-full"
				>
					{log.model_id}
				</span>
			</div>
			<div class="flex-1 min-w-0">
				{#if log.agent_name}
					<span
						class="inline-flex px-1.5 py-0.5 rounded bg-green-50 dark:bg-green-900/20 text-green-700 dark:text-green-300 text-xs font-medium truncate max-w-full"
					>
						{log.agent_name}
					</span>
				{:else}
					<span class="text-gray-400 dark:text-gray-600">-</span>
				{/if}
			</div>
			<div class="flex-none w-24 flex justify-center">
				<span
					class="px-2 py-0.5 text-xs font-medium rounded {getSourceStyle(log.source_type)}"
				>
					{getSourceLabel(log.source_type)}
				</span>
			</div>
			<div class="flex-none w-24 flex justify-center">
				{#if log.client_type === 'widget'}
					<span
						class="px-2 py-0.5 text-xs font-medium rounded bg-purple-50 dark:bg-purple-900/20 text-purple-700 dark:text-purple-300"
						title={log.embed_widget_name
							? $i18n.t('Embed widget: {{name}}', { name: log.embed_widget_name })
							: $i18n.t('Embed widget')}
					>
						Widget
					</span>
				{:else if log.client_type === 'api_key'}
					<span class="px-2 py-0.5 text-xs font-medium rounded bg-yellow-50 dark:bg-yellow-900/20 text-yellow-700 dark:text-yellow-300">
						API
					</span>
				{:else if log.client_type === 'cursor'}
					<span class="px-2 py-0.5 text-xs font-medium rounded bg-purple-50 dark:bg-purple-900/20 text-purple-700 dark:text-purple-300">
						Cursor
					</span>
				{:else if log.client_type === 'claude-code'}
					<span class="px-2 py-0.5 text-xs font-medium rounded bg-orange-50 dark:bg-orange-900/20 text-orange-700 dark:text-orange-300">
						Claude Code
					</span>
				{:else if log.client_type === 'codex-cli'}
					<span class="px-2 py-0.5 text-xs font-medium rounded bg-green-50 dark:bg-green-900/20 text-green-700 dark:text-green-300">
						Codex CLI
					</span>
				{:else if log.client_type === 'gemini-cli'}
					<span class="px-2 py-0.5 text-xs font-medium rounded bg-blue-50 dark:bg-blue-900/20 text-blue-700 dark:text-blue-300">
						Gemini CLI
					</span>
				{:else if log.client_type && log.client_type !== 'web'}
					<span class="px-2 py-0.5 text-xs font-medium rounded bg-gray-50 dark:bg-gray-900/20 text-gray-700 dark:text-gray-300">
						{log.client_type}
					</span>
				{:else}
					<span class="px-2 py-0.5 text-xs font-medium rounded bg-gray-50 dark:bg-gray-900/20 text-gray-600 dark:text-gray-400">
						Web
					</span>
				{/if}
			</div>
			<div class="flex-none w-24 text-right text-sm tabular-nums text-gray-600 dark:text-gray-400">
				{log.input_tokens.toLocaleString()}
			</div>
			<div class="flex-none w-24 text-right text-sm tabular-nums text-gray-600 dark:text-gray-400">
				{log.output_tokens.toLocaleString()}
			</div>
			<div class="flex-none w-24 text-right text-sm tabular-nums font-medium text-gray-800 dark:text-gray-200">
				{log.total_tokens.toLocaleString()}
			</div>
		</div>

		<!-- Expanded detail -->
		{#if expandedId === log.id}
			<div class="mx-1 mb-2 p-4 rounded-lg bg-gray-50 dark:bg-gray-850 space-y-3 text-xs">
					<!-- Request section -->
				{#if log.input_preview || log.message_count}
					<div>
						<div class="font-medium text-gray-700 dark:text-gray-300 mb-1 flex items-center gap-2">
							<svg class="size-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
								<path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5" />
							</svg>
							{$i18n.t('Request')}
							{#if log.message_count}
								<span class="text-gray-400 dark:text-gray-500 font-normal"
									>({log.message_count} {$i18n.t('messages')})</span
								>
							{/if}
						</div>
						{#if log.input_preview}
							<div class="pl-5.5 text-gray-600 dark:text-gray-400 whitespace-pre-wrap break-all leading-relaxed max-h-32 overflow-y-auto">
								{log.input_preview}
							</div>
						{/if}
					</div>
				{/if}

				<!-- Response section -->
				{#if log.output_preview}
					<div>
						<div class="font-medium text-gray-700 dark:text-gray-300 mb-1 flex items-center gap-2">
							<svg class="size-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
								<path stroke-linecap="round" stroke-linejoin="round" d="M8.625 12a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0H8.25m4.125 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0H12m4.125 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0h-.375M21 12c0 4.556-4.03 8.25-9 8.25a9.764 9.764 0 01-2.555-.337A5.972 5.972 0 015.41 20.97a5.969 5.969 0 01-.474-.065 4.48 4.48 0 00.978-2.025c.09-.457-.133-.901-.467-1.226C3.93 16.178 3 14.189 3 12c0-4.556 4.03-8.25 9-8.25s9 3.694 9 8.25z" />
							</svg>
							{$i18n.t('Response')}
							{#if log.finish_reason}
								<span class="text-gray-400 dark:text-gray-500 font-normal">({log.finish_reason})</span>
							{/if}
						</div>
						<div class="pl-5.5 text-gray-600 dark:text-gray-400 whitespace-pre-wrap break-all leading-relaxed max-h-48 overflow-y-auto">
							{log.output_preview}
						</div>
					</div>
				{/if}

				<!-- Token Usage Breakdown -->
				{#if log.usage_breakdown && log.usage_breakdown.length > 0}
					<div>
						<div class="font-medium text-gray-700 dark:text-gray-300 mb-1.5 flex items-center gap-2">
							<svg class="size-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
								<path stroke-linecap="round" stroke-linejoin="round" d="M3.75 3v11.25A2.25 2.25 0 006 16.5h2.25M3.75 3h-1.5m1.5 0h16.5m0 0h1.5m-1.5 0v11.25A2.25 2.25 0 0118 16.5h-2.25m-7.5 0h7.5m-7.5 0l-1 3m8.5-3l1 3m0 0l.5 1.5m-.5-1.5h-9.5m0 0l-.5 1.5" />
							</svg>
							{$i18n.t('Token Usage')}
						</div>
						<div class="pl-5.5">
							<div class="flex text-[10px] font-medium text-gray-400 dark:text-gray-500 uppercase mb-1 gap-2">
								<div class="flex-1 min-w-0">{$i18n.t('Model')}</div>
								<div class="w-20 text-right">{$i18n.t('Input')}</div>
								<div class="w-20 text-right">{$i18n.t('Output')}</div>
								<div class="w-20 text-right">{$i18n.t('Total')}</div>
							</div>
							{#each log.usage_breakdown as b}
								<div class="flex items-center gap-2 py-0.5 text-gray-600 dark:text-gray-400">
									<div class="flex-1 min-w-0 font-mono truncate">{b.model_id || '-'}</div>
									<div class="w-20 text-right tabular-nums">{b.input_tokens.toLocaleString()}</div>
									<div class="w-20 text-right tabular-nums">{b.output_tokens.toLocaleString()}</div>
									<div class="w-20 text-right tabular-nums font-medium text-gray-700 dark:text-gray-300">{b.total_tokens.toLocaleString()}</div>
								</div>
							{/each}
						</div>
					</div>
				{/if}

				<!-- Tool Calls -->
				{#if log.tool_calls && log.tool_calls.length > 0}
					<div>
						<div class="font-medium text-gray-700 dark:text-gray-300 mb-1 flex items-center gap-2">
							<svg class="size-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
								<path stroke-linecap="round" stroke-linejoin="round" d="M11.42 15.17l-5.1-5.1m0 0L11.42 4.97m-5.1 5.1H21M3 21V3" />
							</svg>
							{$i18n.t('Function Calls')}
							<span class="text-gray-400 dark:text-gray-500 font-normal"
								>({log.tool_calls.length})</span
							>
						</div>
						<div class="pl-5.5 space-y-1.5">
							{#each log.tool_calls as tc}
								<div
									class="flex items-start gap-2 rounded-md bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 px-2.5 py-1.5"
								>
									<span class="font-mono font-medium text-amber-700 dark:text-amber-400 shrink-0"
										>{tc.name}</span
									>
									{#if tc.arguments}
										<span class="text-gray-500 dark:text-gray-500 font-mono break-all"
											>{truncateArgs(tc.arguments)}</span
										>
									{/if}
								</div>
							{/each}
						</div>
					</div>
				{/if}

				<!-- Token Details (cached, reasoning tokens) -->
				{#if log.token_details && Object.keys(log.token_details).length > 0}
					<div>
						<div class="font-medium text-gray-700 dark:text-gray-300 mb-1 flex items-center gap-2">
							<svg class="size-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
								<path stroke-linecap="round" stroke-linejoin="round" d="M9.568 3H5.25A2.25 2.25 0 003 5.25v4.318c0 .597.237 1.17.659 1.591l9.581 9.581c.699.699 1.78.872 2.607.33a18.095 18.095 0 005.223-5.223c.542-.827.369-1.908-.33-2.607L11.16 3.66A2.25 2.25 0 009.568 3z" />
								<path stroke-linecap="round" stroke-linejoin="round" d="M6 6h.008v.008H6V6z" />
							</svg>
							{$i18n.t('Token Details')}
						</div>
						<div class="pl-5.5 flex flex-wrap gap-3">
							{#each Object.entries(log.token_details) as [key, val]}
								{#if typeof val === 'object' && val !== null}
									{#each Object.entries(val) as [sk, sv]}
										<span
											class="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700"
										>
											<span class="text-gray-500 dark:text-gray-500">{key}.{sk}:</span>
											<span class="font-medium text-gray-700 dark:text-gray-300">{sv}</span>
										</span>
									{/each}
								{/if}
							{/each}
						</div>
					</div>
				{/if}

				<!-- Chat ID + Trace -->
				{#if log.chat_id}
					<div>
						<div class="flex items-center justify-between">
							<div class="font-medium text-gray-700 dark:text-gray-300 mb-1 flex items-center gap-2">
								<svg class="size-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
									<path stroke-linecap="round" stroke-linejoin="round" d="M13.19 8.688a4.5 4.5 0 011.242 7.244l-4.5 4.5a4.5 4.5 0 01-6.364-6.364l1.757-1.757m13.35-.622l1.757-1.757a4.5 4.5 0 00-6.364-6.364l-4.5 4.5a4.5 4.5 0 001.242 7.244" />
								</svg>
								{$i18n.t('Chat ID')}
							</div>
							<Button
								kind="filled"
								size="sm"
								on:click={() => {
									const params = new URLSearchParams();
									if (log.message_id) params.set('message_id', log.message_id);
									else params.set('chat_id', log.chat_id);
									window.open(`/admin/evaluations?tab=tracing&${params.toString()}`, '_blank');
								}}
							>
								{$i18n.t('Trace')}
							</Button>
						</div>
						<div class="pl-5.5 text-gray-500 dark:text-gray-500 font-mono break-all">
							{log.chat_id}
						</div>
					</div>
				{/if}

				<!-- No detail data -->
				{#if !log.input_preview && !log.output_preview && (!log.usage_breakdown || log.usage_breakdown.length === 0) && (!log.tool_calls || log.tool_calls.length === 0)}
					<div class="text-gray-400 dark:text-gray-500 text-center py-2">
						{$i18n.t('No detail data available')}
					</div>
				{/if}
			</div>
		{/if}
	{/each}

	<!-- Pagination -->
	{#if totalPages > 1}
		<div
			class="flex items-center justify-center gap-2 mt-4 pt-4 border-t border-gray-50 dark:border-gray-850"
		>
			<Button
				kind="text"
				size="sm"
				type="button"
				disabled={page <= 1}
				on:click={() => handlePageChange(page - 1)}
			>
				<ChevronLeft className="size-5" />
			</Button>
			<span class="text-sm text-gray-600 dark:text-gray-400">
				{page} / {totalPages}
			</span>
			<Button
				kind="text"
				size="sm"
				type="button"
				disabled={page >= totalPages}
				on:click={() => handlePageChange(page + 1)}
			>
				<ChevronRight className="size-5" />
			</Button>
		</div>
	{/if}
{/if}

<!-- Custom Date Range Modal -->
<Modal bind:show={showCustomDateModal} size="sm">
	<div>
		<div class="flex justify-between dark:text-gray-100 px-5 pt-4 mb-2">
			<div class="text-lg font-medium self-center">
				{$i18n.t('Custom Date Range')}
			</div>
			<Button
				kind="text"
				size="sm"
				type="button"
				on:click={() => {
					showCustomDateModal = false;
					if (dateRange !== 'custom') {
						dateRange = '7d';
					}
				}}
			>
				<XMark className="size-5" />
			</Button>
		</div>

		<div class="px-5 pb-4">
			<div class="flex flex-col gap-3">
				<div class="flex flex-col w-full">
					<div class="mb-0.5 text-xs text-gray-500">{$i18n.t('From')}</div>
					<div class="flex-1">
						<input
							type="datetime-local"
							bind:value={customFromDate}
							class="w-full text-sm bg-transparent placeholder:text-gray-300 dark:placeholder:text-gray-700 outline-none"
						/>
					</div>
				</div>

				<div class="flex flex-col w-full">
					<div class="mb-0.5 text-xs text-gray-500">{$i18n.t('To')}</div>
					<div class="flex-1">
						<input
							type="datetime-local"
							bind:value={customToDate}
							class="w-full text-sm bg-transparent placeholder:text-gray-300 dark:placeholder:text-gray-700 outline-none"
						/>
					</div>
				</div>
			</div>

			<div class="flex justify-end gap-2 mt-4 pt-3 border-t border-gray-50 dark:border-gray-850">
				<Button
					kind="text"
					size="sm"
					type="button"
					on:click={() => {
						showCustomDateModal = false;
						if (dateRange !== 'custom') {
							dateRange = '7d';
						}
					}}
				>
					{$i18n.t('Cancel')}
				</Button>
				<Button
					kind="filled"
					size="sm"
					type="button"
					disabled={!customFromDate || !customToDate}
					on:click={applyCustomDateRange}
				>
					{$i18n.t('Apply')}
				</Button>
			</div>
		</div>
	</div>
</Modal>

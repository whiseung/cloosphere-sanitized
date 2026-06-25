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
	import Button from '$lib/components/common/Button.svelte';
	import Checkbox from '$lib/components/common/Checkbox.svelte';
	import Input from '$lib/components/common/Input.svelte';
	import LabelBase from '$lib/components/common/LabelBase.svelte';
	import Modal from '$lib/components/common/Modal.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';

	import {
		getGuardrailLogs,
		getAvailableActions,
		type GuardrailLog,
		type GuardrailLogListResponse
	} from '$lib/apis/guardrail-logs';

	const i18n = getContext('i18n');

	// State
	let loading = true;
	let guardrailLogs: GuardrailLog[] = [];
	let total = 0;
	let totalPages = 0;
	let availableActions: string[] = [];

	// Filters
	let page = 1;
	let limit = 50;
	let selectedActions: string[] = [];
	let selectedDetectionPatterns: string[] = ['rule', 'llm'];
	let selectedSources: string[] = ['chat', 'code_gateway'];
	let searchUser = '';
	let searchChatId = '';

	// Dropdown state
	let showActionDropdown = false;
	let showDetectionDropdown = false;
	let showSourceDropdown = false;

	// 고정 옵션
	const availableDetectionPatterns = ['rule', 'llm'];
	const availableSources = ['chat', 'code_gateway'];

	// Date range (기본값: 최근 1시간)
	let dateRange = '1h';
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
				fromDate = now - 3600;
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
	setDateRange('1h');

	// Modal
	let showDetailModal = false;
	let selectedLog: GuardrailLog | null = null;

	const loadGuardrailLogs = async () => {
		loading = true;
		try {
			const params: Record<string, unknown> = { page, limit };
			if (selectedActions.length > 0 && selectedActions.length < availableActions.length) {
				params.action = selectedActions.join(',');
			}
			const ds = getActiveDetectionSource();
			if (ds) params.detection_source = ds;
			const src = getActiveSourceFilter();
			if (src) params.source = src;
			if (searchUser) params.user_search = searchUser;
			if (searchChatId) params.chat_id = searchChatId;
			if (fromDate) params.from_date = fromDate;
			if (toDate) params.to_date = toDate;

			const response: GuardrailLogListResponse = await getGuardrailLogs(
				localStorage.token,
				params
			);
			guardrailLogs = response.items;
			total = response.total;
			totalPages = response.total_pages;
		} catch (error: any) {
			console.error('Guardrail logs error:', error);
			const message = error?.detail || error?.message || 'Unknown error';
			toast.error(`${$i18n.t('Failed to load guardrail logs')}: ${message}`);
		}
		loading = false;
	};

	// 멀티셀렉트 토글 함수
	const toggleAction = (act: string) => {
		if (selectedActions.includes(act)) {
			selectedActions = selectedActions.filter((a) => a !== act);
		} else {
			selectedActions = [...selectedActions, act];
		}
	};

	const toggleAllActions = () => {
		if (selectedActions.length === availableActions.length) {
			selectedActions = [];
		} else {
			selectedActions = [...availableActions];
		}
	};

	const getActionFilterLabel = () => {
		if (
			selectedActions.length === 0 ||
			selectedActions.length === availableActions.length
		) {
			return $i18n.t('All Actions');
		}
		if (selectedActions.length === 1) {
			return getActionLabel(selectedActions[0]);
		}
		return `${selectedActions.length} ${$i18n.t('selected')}`;
	};

	// Detection Pattern 토글
	const toggleDetectionPattern = (p: string) => {
		if (selectedDetectionPatterns.includes(p)) {
			selectedDetectionPatterns = selectedDetectionPatterns.filter((x) => x !== p);
		} else {
			selectedDetectionPatterns = [...selectedDetectionPatterns, p];
		}
	};
	const toggleAllDetectionPatterns = () => {
		if (selectedDetectionPatterns.length === availableDetectionPatterns.length) {
			selectedDetectionPatterns = [];
		} else {
			selectedDetectionPatterns = [...availableDetectionPatterns];
		}
	};

	// Source 토글
	const toggleSource = (s: string) => {
		if (selectedSources.includes(s)) {
			selectedSources = selectedSources.filter((x) => x !== s);
		} else {
			selectedSources = [...selectedSources, s];
		}
	};
	const toggleAllSources = () => {
		if (selectedSources.length === availableSources.length) {
			selectedSources = [];
		} else {
			selectedSources = [...availableSources];
		}
	};

	// 라벨
	const getDetectionPatternLabel = (p: string) => {
		return p === 'rule' ? $i18n.t('Rule') : $i18n.t('LLM');
	};
	const getSourceFilterLabel = (s: string) => {
		return s === 'chat' ? $i18n.t('Chat') : $i18n.t('Gateway');
	};

	$: detectionFilterLabel = (() => {
		if (selectedDetectionPatterns.length === 0 || selectedDetectionPatterns.length === availableDetectionPatterns.length) {
			return $i18n.t('All Patterns');
		}
		if (selectedDetectionPatterns.length === 1) return getDetectionPatternLabel(selectedDetectionPatterns[0]);
		return `${selectedDetectionPatterns.length} ${$i18n.t('selected')}`;
	})();

	$: sourceFilterLabel = (() => {
		if (selectedSources.length === 0 || selectedSources.length === availableSources.length) {
			return $i18n.t('All Sources');
		}
		if (selectedSources.length === 1) return getSourceFilterLabel(selectedSources[0]);
		return `${selectedSources.length} ${$i18n.t('selected')}`;
	})();

	// Cascading 필터용 헬퍼: 현재 활성 필터 값 반환
	const getActiveActionFilter = () =>
		selectedActions.length > 0 && selectedActions.length < availableActions.length
			? selectedActions.join(',')
			: undefined;

	const getActiveDetectionSource = () => {
		if (selectedDetectionPatterns.length === 0 || selectedDetectionPatterns.length === availableDetectionPatterns.length) return undefined;
		const map: Record<string, string[]> = {
			rule: ['pii', 'custom_pattern', 'blocked_word'],
			llm: ['llm_judge']
		};
		const sources = selectedDetectionPatterns.flatMap((p) => map[p] || []);
		return sources.join(',');
	};

	const getActiveSourceFilter = () =>
		selectedSources.length > 0 && selectedSources.length < availableSources.length
			? selectedSources.join(',')
			: undefined;

	const getCascadingParams = () => ({
		detection_source: getActiveDetectionSource(),
		source: getActiveSourceFilter(),
		user_search: searchUser || undefined,
	});

	const refreshActionOptions = async () => {
		try {
			const newActions = await getAvailableActions(localStorage.token, getCascadingParams());
			availableActions = newActions;
			selectedActions = selectedActions.filter((a) => newActions.includes(a));
			if (selectedActions.length === 0 && newActions.length > 0) selectedActions = [...newActions];
		} catch (error) {
			console.error('Action options error:', error);
		}
	};

	const loadFilters = async () => {
		try {
			availableActions = await getAvailableActions(localStorage.token);
			selectedActions = [...availableActions];
		} catch (error) {
			console.error('Filters error:', error);
		}
	};

	const handleSearch = () => {
		page = 1;
		if (dateRange && dateRange !== 'custom' && dateRange !== 'all') {
			setDateRange(dateRange);
		}
		loadGuardrailLogs();
	};

	const handleUserSearchKeydown = (event: CustomEvent<KeyboardEvent>) => {
		if (event.detail?.key === 'Enter') {
			handleSearch();
			refreshActionOptions();
		}
	};

	const handleChatIdSearchKeydown = (event: CustomEvent<KeyboardEvent>) => {
		if (event.detail?.key === 'Enter') handleSearch();
	};

	const handlePageChange = (newPage: number) => {
		page = newPage;
		loadGuardrailLogs();
	};

	const showLogDetail = (log: GuardrailLog) => {
		selectedLog = log;
		showDetailModal = true;
	};

	const formatTimestamp = (timestamp: number) => {
		return new Date(timestamp * 1000).toLocaleString();
	};

	const getActionStyle = (actionType: string) => {
		const styles: Record<string, string> = {
			block: 'bg-red-500/20 text-red-700 dark:text-red-400',
			redact: 'bg-yellow-500/20 text-yellow-700 dark:text-yellow-400',
			mask: 'bg-blue-500/20 text-blue-700 dark:text-blue-400',
			hash: 'bg-purple-500/20 text-purple-700 dark:text-purple-400'
		};
		return styles[actionType] || 'bg-gray-500/20 text-gray-700 dark:text-gray-400';
	};

	const getActionLabel = (actionType: string) => {
		const labels: Record<string, string> = {
			block: $i18n.t('Block'),
			redact: $i18n.t('Redact'),
			mask: $i18n.t('Mask'),
			hash: $i18n.t('Hash')
		};
		return labels[actionType] || actionType;
	};

	const getDetectionSourceStyle = (source: string) => {
		const styles: Record<string, string> = {
			pii: 'bg-orange-500/20 text-orange-700 dark:text-orange-400',
			custom_pattern: 'bg-purple-500/20 text-purple-700 dark:text-purple-400',
			blocked_word: 'bg-red-500/20 text-red-700 dark:text-red-400',
			llm_judge: 'bg-indigo-500/20 text-indigo-700 dark:text-indigo-400'
		};
		return styles[source] || 'bg-gray-500/20 text-gray-700 dark:text-gray-400';
	};

	const getDetectionSourceLabel = (source: string) => {
		const labels: Record<string, string> = {
			pii: $i18n.t('PII'),
			custom_pattern: $i18n.t('Custom Pattern'),
			blocked_word: $i18n.t('Blocked Word'),
			llm_judge: $i18n.t('LLM Judge')
		};
		return labels[source] || source;
	};

	const truncateText = (text: string | null, maxLength: number = 80) => {
		if (!text) return '-';
		return text.length > maxLength ? text.substring(0, maxLength) + '...' : text;
	};

	onMount(async () => {
		await Promise.all([loadGuardrailLogs(), loadFilters()]);
	});
</script>

<!-- Header -->
<div class="mt-0.5 mb-2 flex flex-col gap-2">
	<div class="flex items-center justify-between">
		<div class="flex items-center text-lg font-bold px-0.5">
			{$i18n.t('Guardrail Logs')}
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

		<!-- Action Filter (Multi-select) -->
		<DropdownMenu.Root
			open={showActionDropdown}
			onOpenChange={(open) => {
				showActionDropdown = open;
				if (!open) handleSearch();
			}}
		>
			<DropdownMenu.Trigger>
				<button
					class="flex items-center gap-2 px-3 py-1.5 min-w-[130px] text-sm bg-gray-50 dark:bg-gray-950 rounded-lg outline-none cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-900 transition"
				>
					<span class="flex-1 text-left truncate">{getActionFilterLabel()}</span>
					<ChevronDown className="size-4 flex-shrink-0" />
				</button>
			</DropdownMenu.Trigger>

			<DropdownMenu.Content
				class="w-48 max-h-72 overflow-y-auto rounded-lg p-1 border border-gray-100 dark:border-gray-850 bg-white dark:bg-gray-900 shadow-lg z-50"
				sideOffset={4}
				transition={flyAndScale}
			>
				<button
					class="flex w-full items-center gap-2 px-3 py-2 text-sm rounded-md cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-850 transition"
					on:click|stopPropagation={() => toggleAllActions()}
				>
					<Checkbox state={selectedActions.length === availableActions.length ? 'checked' : 'unchecked'} />
					<span class="font-medium">{$i18n.t('Select All')}</span>
				</button>

				<div class="h-px bg-gray-100 dark:bg-gray-800 my-1" />

				{#each availableActions as act}
					<button
						class="flex w-full items-center gap-2 px-3 py-2 text-sm rounded-md cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-850 transition"
						on:click|stopPropagation={() => toggleAction(act)}
					>
						<Checkbox state={selectedActions.includes(act) ? 'checked' : 'unchecked'} />
						<span>{getActionLabel(act)}</span>
					</button>
				{/each}
			</DropdownMenu.Content>
		</DropdownMenu.Root>

		<!-- Detection Pattern Filter (Multi-select) -->
		<DropdownMenu.Root
			open={showDetectionDropdown}
			onOpenChange={(open) => {
				showDetectionDropdown = open;
				if (!open) { handleSearch(); refreshActionOptions(); }
			}}
		>
			<DropdownMenu.Trigger>
				<button class="flex items-center gap-2 px-3 py-1.5 min-w-[130px] text-sm bg-gray-50 dark:bg-gray-950 rounded-lg outline-none cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-900 transition">
					<span class="flex-1 text-left truncate">{detectionFilterLabel}</span>
					<ChevronDown className="size-4 flex-shrink-0" />
				</button>
			</DropdownMenu.Trigger>
			<DropdownMenu.Content class="w-48 max-h-72 overflow-y-auto rounded-lg p-1 border border-gray-100 dark:border-gray-850 bg-white dark:bg-gray-900 shadow-lg z-50" sideOffset={4} transition={flyAndScale}>
				<button class="flex w-full items-center gap-2 px-3 py-2 text-sm rounded-md cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-850 transition" on:click|stopPropagation={() => toggleAllDetectionPatterns()}>
					<Checkbox state={selectedDetectionPatterns.length === availableDetectionPatterns.length ? 'checked' : 'unchecked'} />
					<span class="font-medium">{$i18n.t('Select All')}</span>
				</button>
				<div class="h-px bg-gray-100 dark:bg-gray-800 my-1" />
				{#each availableDetectionPatterns as p}
					<button class="flex w-full items-center gap-2 px-3 py-2 text-sm rounded-md cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-850 transition" on:click|stopPropagation={() => toggleDetectionPattern(p)}>
						<Checkbox state={selectedDetectionPatterns.includes(p) ? 'checked' : 'unchecked'} />
						<span>{getDetectionPatternLabel(p)}</span>
					</button>
				{/each}
			</DropdownMenu.Content>
		</DropdownMenu.Root>

		<!-- Source Filter (Multi-select) -->
		<DropdownMenu.Root
			open={showSourceDropdown}
			onOpenChange={(open) => {
				showSourceDropdown = open;
				if (!open) { handleSearch(); refreshActionOptions(); }
			}}
		>
			<DropdownMenu.Trigger>
				<button class="flex items-center gap-2 px-3 py-1.5 min-w-[130px] text-sm bg-gray-50 dark:bg-gray-950 rounded-lg outline-none cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-900 transition">
					<span class="flex-1 text-left truncate">{sourceFilterLabel}</span>
					<ChevronDown className="size-4 flex-shrink-0" />
				</button>
			</DropdownMenu.Trigger>
			<DropdownMenu.Content class="w-48 max-h-72 overflow-y-auto rounded-lg p-1 border border-gray-100 dark:border-gray-850 bg-white dark:bg-gray-900 shadow-lg z-50" sideOffset={4} transition={flyAndScale}>
				<button class="flex w-full items-center gap-2 px-3 py-2 text-sm rounded-md cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-850 transition" on:click|stopPropagation={() => toggleAllSources()}>
					<Checkbox state={selectedSources.length === availableSources.length ? 'checked' : 'unchecked'} />
					<span class="font-medium">{$i18n.t('Select All')}</span>
				</button>
				<div class="h-px bg-gray-100 dark:bg-gray-800 my-1" />
				{#each availableSources as s}
					<button class="flex w-full items-center gap-2 px-3 py-2 text-sm rounded-md cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-850 transition" on:click|stopPropagation={() => toggleSource(s)}>
						<Checkbox state={selectedSources.includes(s) ? 'checked' : 'unchecked'} />
						<span>{getSourceFilterLabel(s)}</span>
					</button>
				{/each}
			</DropdownMenu.Content>
		</DropdownMenu.Root>

		<!-- Search User -->
		<div class="w-36">
			<Input
				bind:value={searchUser}
				placeholder={$i18n.t('User')}
				size="sm"
				on:keydown={handleUserSearchKeydown}
			>
				<svelte:fragment slot="prefix">
					<MagnifyingGlass className="size-4" />
				</svelte:fragment>
			</Input>
		</div>

		<!-- Search Chat ID -->
		<div class="w-36">
			<Input
				bind:value={searchChatId}
				placeholder={$i18n.t('Chat ID')}
				size="sm"
				on:keydown={handleChatIdSearchKeydown}
			>
				<svelte:fragment slot="prefix">
					<MagnifyingGlass className="size-4" />
				</svelte:fragment>
			</Input>
		</div>

		<!-- Refresh -->
		<Tooltip content={$i18n.t('Refresh')}>
			<Button kind="text" size="sm" type="button" on:click={loadGuardrailLogs}>
				<svelte:fragment slot="prefix">
					<ArrowPath className="size-5" />
				</svelte:fragment>
			</Button>
		</Tooltip>
	</div>
</div>

<hr class="mb-3 border-gray-50 dark:border-gray-850" />

<!-- Content -->
{#if loading}
	<div class="flex justify-center py-8">
		<Spinner className="size-6" />
	</div>
{:else if guardrailLogs.length === 0}
	<div class="flex flex-col items-center justify-center py-12 text-center">
		<svg
			xmlns="http://www.w3.org/2000/svg"
			viewBox="0 0 24 24"
			fill="currentColor"
			class="size-12 text-gray-400 dark:text-gray-600 mb-4"
		>
			<path
				fill-rule="evenodd"
				d="M12.516 2.17a.75.75 0 0 0-1.032 0 11.209 11.209 0 0 1-7.877 3.08.75.75 0 0 0-.722.515A12.74 12.74 0 0 0 2.25 9.75c0 5.942 4.064 10.933 9.563 12.348a.749.749 0 0 0 .374 0c5.499-1.415 9.563-6.406 9.563-12.348 0-1.39-.223-2.73-.635-3.985a.75.75 0 0 0-.722-.516l-.143.001c-2.996 0-5.717-1.17-7.734-3.08Zm3.094 8.016a.75.75 0 1 0-1.22-.872l-3.236 4.53L9.53 12.22a.75.75 0 0 0-1.06 1.06l2.25 2.25a.75.75 0 0 0 1.14-.094l3.75-5.25Z"
				clip-rule="evenodd"
			/>
		</svg>
		<p class="text-gray-500 dark:text-gray-400">
			{$i18n.t('No guardrail logs found.')}
		</p>
	</div>
{:else}
	<!-- Table Header -->
	<div class="hidden md:flex text-xs font-medium text-gray-500 px-1 mb-1 uppercase">
		<div class="flex-none w-44">{$i18n.t('Time')}</div>
		<div class="flex-1 min-w-0">{$i18n.t('User')}</div>
		<div class="flex-none w-20 text-center">{$i18n.t('Action')}</div>
		<div class="flex-none w-28 text-center">{$i18n.t('Detection Source')}</div>
		<div class="flex-1 min-w-0">{$i18n.t('Detail')}</div>
		<div class="flex-1 min-w-0">{$i18n.t('Original Content')}</div>
		<div class="flex-none w-16 text-center" />
	</div>
	<hr class="mb-2 border-gray-50 dark:border-gray-850 hidden md:block" />

	<!-- Table Rows -->
	{#each guardrailLogs as log}
		<div
			class="flex flex-col md:flex-row md:items-center py-2 px-1 hover:bg-gray-50 dark:hover:bg-gray-950 rounded-lg gap-1 md:gap-0"
		>
			<div class="flex-none w-44 text-sm text-gray-600 dark:text-gray-400">
				{formatTimestamp(log.created_at)}
			</div>
			<div class="flex-1 min-w-0">
				<div class="font-medium text-sm text-gray-900 dark:text-gray-100 truncate">{log.user_name || '-'}</div>
				<div class="text-xs text-gray-500 dark:text-gray-400 truncate">{log.user_email || ''}</div>
			</div>
			<div class="flex-none w-20 flex justify-center">
				<span
					class="px-2 py-0.5 text-xs font-medium rounded {getActionStyle(log.action)}"
				>
					{getActionLabel(log.action)}
				</span>
			</div>
			<div class="flex-none w-28 flex justify-center">
				<span
					class="px-2 py-0.5 text-xs font-medium rounded {getDetectionSourceStyle(
						log.detection_source
					)}"
				>
					{getDetectionSourceLabel(log.detection_source)}
				</span>
			</div>
			<div class="flex-1 min-w-0">
				<div class="text-sm text-gray-600 dark:text-gray-400 truncate">
					{log.detection_detail || '-'}
				</div>
			</div>
			<div class="flex-1 min-w-0">
				<div class="text-sm text-gray-500 dark:text-gray-400 truncate">
					{truncateText(log.original_content, 60)}
				</div>
			</div>
			<div class="flex-none w-16 flex justify-center">
				<Button kind="outlined" size="sm" type="button" on:click={() => showLogDetail(log)}>
					{$i18n.t('Detail')}
				</Button>
			</div>
		</div>
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
				<svelte:fragment slot="prefix">
					<ChevronLeft className="size-5" />
				</svelte:fragment>
			</Button>
			<span class="text-sm text-gray-600 dark:text-gray-400 tabular-nums">
				{page} / {totalPages}
			</span>
			<Button
				kind="text"
				size="sm"
				type="button"
				disabled={page >= totalPages}
				on:click={() => handlePageChange(page + 1)}
			>
				<svelte:fragment slot="prefix">
					<ChevronRight className="size-5" />
				</svelte:fragment>
			</Button>
		</div>
	{/if}
{/if}

<!-- Detail Modal -->
<Modal bind:show={showDetailModal} size="lg">
	<div class="px-5 py-4">
		<div class="flex items-center justify-between mb-4">
			<h2 class="text-lg font-semibold">{$i18n.t('Guardrail Log Detail')}</h2>
		</div>

		{#if selectedLog}
			<div class="space-y-4 max-h-[60vh] overflow-y-auto">
				<div class="grid grid-cols-2 gap-4">
					<div>
						<div class="text-xs text-gray-500 dark:text-gray-400 mb-1">
							{$i18n.t('Time')}
						</div>
						<div class="text-sm text-gray-900 dark:text-gray-100">{formatTimestamp(selectedLog.created_at)}</div>
					</div>
					<div>
						<div class="text-xs text-gray-500 dark:text-gray-400 mb-1">
							{$i18n.t('Action')}
						</div>
						<span
							class="px-2 py-0.5 text-xs font-medium rounded {getActionStyle(
								selectedLog.action
							)}"
						>
							{getActionLabel(selectedLog.action)}
						</span>
					</div>
					<div>
						<div class="text-xs text-gray-500 dark:text-gray-400 mb-1">
							{$i18n.t('User')}
						</div>
						<div class="text-sm text-gray-900 dark:text-gray-100">{selectedLog.user_name || '-'}</div>
						<div class="text-xs text-gray-500 dark:text-gray-400">{selectedLog.user_email || ''}</div>
					</div>
					<div>
						<div class="text-xs text-gray-500 dark:text-gray-400 mb-1">
							{$i18n.t('Detection Source')}
						</div>
						<span
							class="px-2 py-0.5 text-xs font-medium rounded {getDetectionSourceStyle(
								selectedLog.detection_source
							)}"
						>
							{getDetectionSourceLabel(selectedLog.detection_source)}
						</span>
					</div>
					<div>
						<div class="text-xs text-gray-500 dark:text-gray-400 mb-1">
							{$i18n.t('Guardrail')}
						</div>
						<div class="text-sm text-gray-900 dark:text-gray-100">{selectedLog.guardrail_name || '-'}</div>
					</div>
					<div>
						<div class="text-xs text-gray-500 dark:text-gray-400 mb-1">
							{$i18n.t('Detection Detail')}
						</div>
						<div class="text-sm text-gray-900 dark:text-gray-100">{selectedLog.detection_detail || '-'}</div>
					</div>
					<div>
						<div class="text-xs text-gray-500 dark:text-gray-400 mb-1">
							{$i18n.t('Chat ID')}
						</div>
						<div class="text-xs text-gray-500 dark:text-gray-400 break-all">
							{selectedLog.chat_id || '-'}
						</div>
					</div>
					<div>
						<div class="text-xs text-gray-500 dark:text-gray-400 mb-1">
							{$i18n.t('Message ID')}
						</div>
						<div class="text-xs text-gray-500 dark:text-gray-400 break-all">
							{selectedLog.message_id || '-'}
						</div>
					</div>
				</div>

				{#if selectedLog.original_content}
					<div>
						<div class="text-xs text-gray-500 dark:text-gray-400 mb-2">
							{$i18n.t('Original Content')}
						</div>
						<pre
							class="bg-gray-50 dark:bg-gray-950 text-gray-900 dark:text-gray-200 p-3 rounded-lg text-xs overflow-x-auto max-h-40 whitespace-pre-wrap">{selectedLog.original_content}</pre>
					</div>
				{/if}

				{#if selectedLog.processed_content}
					<div>
						<div class="text-xs text-gray-500 dark:text-gray-400 mb-2">
							{$i18n.t('Processed Content')}
						</div>
						<pre
							class="bg-gray-50 dark:bg-gray-950 text-gray-900 dark:text-gray-200 p-3 rounded-lg text-xs overflow-x-auto max-h-40 whitespace-pre-wrap">{selectedLog.processed_content}</pre>
					</div>
				{/if}

				{#if selectedLog.meta}
					<div>
						<div class="text-xs text-gray-500 dark:text-gray-400 mb-2">
							{$i18n.t('Metadata')}
						</div>
						<pre
							class="bg-gray-50 dark:bg-gray-950 text-gray-900 dark:text-gray-200 p-3 rounded-lg text-xs overflow-x-auto max-h-40">{JSON.stringify(selectedLog.meta, null, 2)}</pre>
					</div>
				{/if}
			</div>
		{/if}

		<div class="flex justify-end gap-2 mt-4 pt-4 border-t border-gray-100 dark:border-gray-850">
			{#if selectedLog?.message_id}
				<Button
					kind="filled"
					size="md"
					on:click={() => {
						window.open(
							`/admin/evaluations?tab=tracing&message_id=${selectedLog?.message_id}`,
							'_blank'
						);
					}}
				>
					{$i18n.t('Trace')}
				</Button>
			{/if}
			<Button kind="outlined" size="md" on:click={() => (showDetailModal = false)}>
				{$i18n.t('Close')}
			</Button>
		</div>
	</div>
</Modal>

<!-- Custom Date Range Modal -->
<Modal bind:show={showCustomDateModal} size="sm">
	<div>
		<div class="flex justify-between dark:text-gray-100 px-5 pt-4 mb-2">
			<div class="text-lg font-medium self-center">
				{$i18n.t('Custom Date Range')}
			</div>
			<button
				class="self-center"
				type="button"
				on:click={() => {
					showCustomDateModal = false;
					if (dateRange !== 'custom') {
						dateRange = '1h';
					}
				}}
			>
				<svg
					xmlns="http://www.w3.org/2000/svg"
					viewBox="0 0 20 20"
					fill="currentColor"
					class="w-5 h-5"
				>
					<path
						d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z"
					/>
				</svg>
			</button>
		</div>

		<div class="px-5 pb-4">
			<div class="flex flex-col gap-3">
				<div class="flex flex-col w-full">
					<LabelBase label={$i18n.t('From')} size="md" />
					<input
						type="datetime-local"
						bind:value={customFromDate}
						class="w-full text-sm bg-transparent placeholder:text-gray-300 dark:placeholder:text-gray-700 outline-none"
					/>
				</div>

				<div class="flex flex-col w-full">
					<LabelBase label={$i18n.t('To')} size="md" />
					<input
						type="datetime-local"
						bind:value={customToDate}
						class="w-full text-sm bg-transparent placeholder:text-gray-300 dark:placeholder:text-gray-700 outline-none"
					/>
				</div>
			</div>

			<div class="flex justify-end gap-2 mt-4 pt-3 border-t border-gray-50 dark:border-gray-850">
				<Button
					kind="outlined"
					size="md"
					on:click={() => {
						showCustomDateModal = false;
						if (dateRange !== 'custom') {
							dateRange = '1h';
						}
					}}
				>
					{$i18n.t('Cancel')}
				</Button>
				<Button
					kind="filled"
					size="md"
					disabled={!customFromDate || !customToDate}
					on:click={applyCustomDateRange}
				>
					{$i18n.t('Apply')}
				</Button>
			</div>
		</div>
	</div>
</Modal>

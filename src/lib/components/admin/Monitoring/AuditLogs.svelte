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
		getAuditLogs,
		getAuditLogStats,
		getAvailableActions,
		getAvailableResourceTypes,
		type AuditLog,
		type AuditLogListResponse,
		type AuditLogStats
	} from '$lib/apis/audit-logs';

	const i18n = getContext('i18n');

	// State
	let loading = true;
	let auditLogs: AuditLog[] = [];
	let total = 0;
	let totalPages = 0;
	let stats: AuditLogStats | null = null;
	let availableActions: string[] = [];
	let availableResourceTypes: string[] = [];

	// Filters
	let page = 1;
	let limit = 50;
	let selectedResourceTypes: string[] = [];
	let selectedActions: string[] = [];
	let searchUserId = '';
	// Dropdown state
	let showResourceDropdown = false;
	let showActionDropdown = false;

	// Date range (기본값: 최근 1시간)
	let dateRange = '1h';
	let fromDate: number | null = null;
	let toDate: number | null = null;

	// 직접 지정용 날짜
	let customFromDate = '';
	let customToDate = '';
	let customDateLabel = ''; // 적용된 날짜 라벨
	let showCustomDateModal = false;

	// datetime-local 포맷 (YYYY-MM-DDTHH:mm)
	const toDateTimeLocal = (date: Date) => {
		const pad = (n: number) => n.toString().padStart(2, '0');
		return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
	};

	const setDateRange = (range: string) => {
		if (range === 'custom') {
			// 기본값: 최근 1주일
			const now = new Date();
			const weekAgo = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
			customFromDate = toDateTimeLocal(weekAgo);
			customToDate = toDateTimeLocal(now);
			// 기본값으로 라벨 미리 설정
			customDateLabel = `${formatDateTimeLabel(customFromDate)} ~ ${formatDateTimeLabel(customToDate)}`;
			showCustomDateModal = true;
			return;
		}

		dateRange = range;
		const now = Math.floor(Date.now() / 1000);
		toDate = now;

		switch (range) {
			case '1h':
				fromDate = now - 3600; // 1시간
				break;
			case '6h':
				fromDate = now - 3600 * 6; // 6시간
				break;
			case '1d':
				fromDate = now - 86400; // 1일
				break;
			case '7d':
				fromDate = now - 86400 * 7; // 7일
				break;
			case '30d':
				fromDate = now - 86400 * 30; // 30일
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
			// 라벨 저장
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
	let selectedLog: AuditLog | null = null;

	const handleSearchKeydown = (event: CustomEvent<KeyboardEvent>) => {
		if (event.detail?.key === 'Enter') handleSearch();
	};

	const loadAuditLogs = async () => {
		loading = true;
		try {
			const params: Record<string, unknown> = { page, limit };
			const rtFilter = getActiveResourceTypeFilter();
			const actFilter = getActiveActionFilter();
			if (rtFilter) params.resource_type = rtFilter;
			if (actFilter) params.action = actFilter;
			if (searchUserId) params.user_id = searchUserId;
			if (fromDate) params.from_date = fromDate;
			if (toDate) params.to_date = toDate;
			const response: AuditLogListResponse = await getAuditLogs(localStorage.token, params);
			auditLogs = response.items;
			total = response.total;
			totalPages = response.total_pages;
		} catch (error: any) {
			console.error('Audit logs error:', error);
			const message = error?.detail || error?.message || 'Unknown error';
			toast.error(`${$i18n.t('Failed to load audit logs')}: ${message}`);
		}
		loading = false;
	};

	// 멀티셀렉트 토글 함수 (선택만 변경, 조회는 갱신 버튼으로)
	const toggleResourceType = (type: string) => {
		if (selectedResourceTypes.includes(type)) {
			selectedResourceTypes = selectedResourceTypes.filter((t) => t !== type);
		} else {
			selectedResourceTypes = [...selectedResourceTypes, type];
		}
	};

	const toggleAction = (act: string) => {
		if (selectedActions.includes(act)) {
			selectedActions = selectedActions.filter((a) => a !== act);
		} else {
			selectedActions = [...selectedActions, act];
		}
	};

	const toggleAllResourceTypes = () => {
		if (selectedResourceTypes.length === availableResourceTypes.length) {
			selectedResourceTypes = [];
		} else {
			selectedResourceTypes = [...availableResourceTypes];
		}
	};

	const toggleAllActions = () => {
		if (selectedActions.length === availableActions.length) {
			selectedActions = [];
		} else {
			selectedActions = [...availableActions];
		}
	};

	// 필터 라벨 생성 (reactive)
	$: resourceFilterLabel = (() => {
		if (selectedResourceTypes.length === availableResourceTypes.length && availableResourceTypes.length > 0) {
			return $i18n.t('All Resources');
		}
		if (selectedResourceTypes.length === 0) {
			return `0 ${$i18n.t('selected')}`;
		}
		if (selectedResourceTypes.length === 1) {
			return getResourceTypeLabel(selectedResourceTypes[0]);
		}
		return `${selectedResourceTypes.length} ${$i18n.t('selected')}`;
	})();

	$: actionFilterLabel = (() => {
		if (selectedActions.length === availableActions.length && availableActions.length > 0) {
			return $i18n.t('All Actions');
		}
		if (selectedActions.length === 0) {
			return `0 ${$i18n.t('selected')}`;
		}
		if (selectedActions.length === 1) {
			return getActionLabel(selectedActions[0]);
		}
		return `${selectedActions.length} ${$i18n.t('selected')}`;
	})();

	const loadStats = async () => {
		try {
			stats = await getAuditLogStats(
				localStorage.token,
				fromDate ?? undefined,
				toDate ?? undefined,
				getActiveResourceTypeFilter(),
				getActiveActionFilter(),
				searchUserId || undefined
			);
		} catch (error) {
			console.error('Stats error:', error);
		}
	};

	// 현재 선택이 "부분 선택"이면 콤마 구분 문자열, 아니면 undefined
	const getActiveResourceTypeFilter = () =>
		selectedResourceTypes.length > 0 && selectedResourceTypes.length < availableResourceTypes.length
			? selectedResourceTypes.join(',')
			: undefined;

	const getActiveActionFilter = () =>
		selectedActions.length > 0 && selectedActions.length < availableActions.length
			? selectedActions.join(',')
			: undefined;

	// Cascading: resource type 변경 → action 옵션 갱신 (반대도 동일)
	const refreshActionOptions = async () => {
		try {
			const newActions = await getAvailableActions(localStorage.token, getActiveResourceTypeFilter());
			availableActions = newActions;
			// 기존 선택 중 사라진 옵션 제거
			selectedActions = selectedActions.filter((a) => newActions.includes(a));
			if (selectedActions.length === 0) selectedActions = [...newActions];
		} catch (error) {
			console.error('Action options error:', error);
		}
	};

	const refreshResourceTypeOptions = async () => {
		try {
			const newTypes = await getAvailableResourceTypes(localStorage.token, getActiveActionFilter());
			availableResourceTypes = newTypes;
			selectedResourceTypes = selectedResourceTypes.filter((t) => newTypes.includes(t));
			if (selectedResourceTypes.length === 0) selectedResourceTypes = [...newTypes];
		} catch (error) {
			console.error('Resource type options error:', error);
		}
	};

	const loadFilters = async () => {
		try {
			availableActions = await getAvailableActions(localStorage.token);
			availableResourceTypes = await getAvailableResourceTypes(localStorage.token);
			// 기본값: 전체 선택
			selectedActions = [...availableActions];
			selectedResourceTypes = [...availableResourceTypes];
		} catch (error) {
			console.error('Filters error:', error);
		}
	};

	const handleSearch = () => {
		page = 1;
		if (dateRange && dateRange !== 'custom' && dateRange !== 'all') {
			setDateRange(dateRange);
		}
		loadAuditLogs();
		loadStats();
	};

	const handlePageChange = (newPage: number) => {
		page = newPage;
		loadAuditLogs();
	};

	const showLogDetail = (log: AuditLog) => {
		selectedLog = log;
		showDetailModal = true;
	};

	const formatTimestamp = (timestamp: number) => {
		return new Date(timestamp * 1000).toLocaleString();
	};

	const getActionStyle = (actionType: string) => {
		const styles: Record<string, string> = {
			CREATE: 'bg-green-500/20 text-green-700 dark:text-green-400',
			READ: 'bg-cyan-500/20 text-cyan-700 dark:text-cyan-400',
			UPDATE: 'bg-blue-500/20 text-blue-700 dark:text-blue-400',
			DELETE: 'bg-red-500/20 text-red-700 dark:text-red-400',
			ACCESS_CONTROL_CHANGE: 'bg-purple-500/20 text-purple-700 dark:text-purple-400',
			PERMISSION_CHANGE: 'bg-indigo-500/20 text-indigo-700 dark:text-indigo-400',
			MEMBER_ADD: 'bg-teal-500/20 text-teal-700 dark:text-teal-400',
			MEMBER_REMOVE: 'bg-orange-500/20 text-orange-700 dark:text-orange-400',
			ROLE_CHANGE: 'bg-yellow-500/20 text-yellow-700 dark:text-yellow-400',
			LOGIN: 'bg-emerald-500/20 text-emerald-700 dark:text-emerald-400',
			LOGOUT: 'bg-gray-500/20 text-gray-700 dark:text-gray-400',
			LOGIN_FAILED: 'bg-red-600/20 text-red-700 dark:text-red-400',
			API_KEY_CREATED: 'bg-green-500/20 text-green-700 dark:text-green-400',
			API_KEY_DELETED: 'bg-red-500/20 text-red-700 dark:text-red-400'
		};
		return styles[actionType] || 'bg-gray-500/20 text-gray-700 dark:text-gray-400';
	};

	const getActionLabel = (actionType: string) => {
		const labels: Record<string, string> = {
			CREATE: $i18n.t('Create'),
			READ: $i18n.t('Read'),
			UPDATE: $i18n.t('Update'),
			DELETE: $i18n.t('Delete'),
			ACCESS_CONTROL_CHANGE: $i18n.t('Access Control'),
			PERMISSION_CHANGE: $i18n.t('Permission'),
			MEMBER_ADD: $i18n.t('Member+'),
			MEMBER_REMOVE: $i18n.t('Member-'),
			ROLE_CHANGE: $i18n.t('Role'),
			LOGIN: $i18n.t('Login'),
			LOGOUT: $i18n.t('Logout'),
			LOGIN_FAILED: $i18n.t('Failed'),
			API_KEY_CREATED: $i18n.t('API Key+'),
			API_KEY_DELETED: $i18n.t('API Key-')
		};
		return labels[actionType] || actionType;
	};

	const getResourceTypeLabel = (type: string) => {
		const labels: Record<string, string> = {
			model: $i18n.t('Model'),
			knowledge: $i18n.t('Knowledge'),
			dbsphere: $i18n.t('Database'),
			glossary: $i18n.t('Glossary'),
			prompt: $i18n.t('Prompt'),
			tool: $i18n.t('Tool'),
			agent: $i18n.t('Agent'),
			chat: $i18n.t('Chat'),
			user: $i18n.t('User'),
			organization: $i18n.t('Organization'),
			organizational_unit: $i18n.t('Org Unit'),
			group: $i18n.t('Group'),
			auth: $i18n.t('Auth'),
			memory: $i18n.t('Memory'),
			admin_settings: $i18n.t('Admin Settings')
		};
		return labels[type] || type;
	};

	const refreshData = async () => {
		// 프리셋(1h/6h/1d/7d/30d) 선택 시 현재 시각 기준으로 재계산
		if (dateRange !== 'custom' && dateRange !== 'all') {
			setDateRange(dateRange);
		}
		await Promise.all([loadAuditLogs(), loadStats()]);
	};

	onMount(async () => {
		await Promise.all([loadAuditLogs(), loadStats(), loadFilters()]);
	});
</script>

<!-- Header -->
<div class="mt-0.5 mb-2 flex flex-col gap-2">
	<div class="flex items-center justify-between">
		<div class="flex items-center text-lg font-bold px-0.5">
			{$i18n.t('Audit Logs')}
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

		<!-- Resource Type Filter (Multi-select) -->
		<DropdownMenu.Root
			open={showResourceDropdown}
			onOpenChange={(open) => {
				showResourceDropdown = open;
				if (!open) {
					handleSearch();
					refreshActionOptions();
				}
			}}
		>
			<DropdownMenu.Trigger>
				<button
					class="flex items-center gap-2 px-3 py-1.5 min-w-[150px] text-sm bg-gray-50 dark:bg-gray-950 rounded-lg outline-none cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-900 transition"
				>
					<span class="flex-1 text-left truncate">{resourceFilterLabel}</span>
					<ChevronDown className="size-4 flex-shrink-0" />
				</button>
			</DropdownMenu.Trigger>

			<DropdownMenu.Content
				class="w-56 max-h-72 overflow-y-auto rounded-lg p-1 border border-gray-100 dark:border-gray-850 bg-white dark:bg-gray-900 shadow-lg z-50"
				sideOffset={4}
				transition={flyAndScale}
			>
				<!-- Select All -->
				<button
					class="flex w-full items-center gap-2 px-3 py-2 text-sm rounded-md cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-850 transition"
					on:click|stopPropagation={() => toggleAllResourceTypes()}
					>
					<Checkbox state={selectedResourceTypes.length === availableResourceTypes.length ? 'checked' : 'unchecked'} />
					<span class="font-medium">{$i18n.t('Select All')}</span>
				</button>

				<div class="h-px bg-gray-100 dark:bg-gray-800 my-1"></div>

				<!-- Individual Items -->
				{#each availableResourceTypes as type}
					<button
						class="flex w-full items-center gap-2 px-3 py-2 text-sm rounded-md cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-850 transition"
						on:click|stopPropagation={() => toggleResourceType(type)}
						>
						<Checkbox state={selectedResourceTypes.includes(type) ? 'checked' : 'unchecked'} />
						<span>{getResourceTypeLabel(type)}</span>
					</button>
				{/each}
			</DropdownMenu.Content>
		</DropdownMenu.Root>

		<!-- Action Filter (Multi-select) -->
		<DropdownMenu.Root
			open={showActionDropdown}
			onOpenChange={(open) => {
				showActionDropdown = open;
				if (!open) {
					handleSearch();
					refreshResourceTypeOptions();
				}
			}}
		>
			<DropdownMenu.Trigger>
				<button
					class="flex items-center gap-2 px-3 py-1.5 min-w-[140px] text-sm bg-gray-50 dark:bg-gray-950 rounded-lg outline-none cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-900 transition"
				>
					<span class="flex-1 text-left truncate">{actionFilterLabel}</span>
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
					on:click|stopPropagation={() => toggleAllActions()}
					>
					<Checkbox state={selectedActions.length === availableActions.length ? 'checked' : 'unchecked'} />
					<span class="font-medium">{$i18n.t('Select All')}</span>
				</button>

				<div class="h-px bg-gray-100 dark:bg-gray-800 my-1"></div>

				<!-- Individual Items -->
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

		<!-- Search -->
		<div class="w-40">
			<Input
				bind:value={searchUserId}
				placeholder={$i18n.t('User Name')}
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
			<Button kind="text" size="sm" type="button" on:click={refreshData}>
				<ArrowPath className="size-5" />
			</Button>
		</Tooltip>
	</div>
</div>

<hr class="mb-3 border-gray-50 dark:border-gray-850" />

<!-- Stats -->
{#if stats}
	<div class="flex gap-4 mb-4 flex-wrap">
		<div class="flex items-center gap-2 px-3 py-2 bg-gray-50 dark:bg-gray-950 rounded-lg">
			<span class="text-2xl font-bold text-gray-700 dark:text-gray-200">{stats.total}</span>
			<span class="text-xs text-gray-500 dark:text-gray-400">{$i18n.t('Total Audit Logs')}</span>
		</div>
	</div>
{/if}

<!-- Content -->
{#if loading}
	<div class="flex justify-center py-8">
		<Spinner className="size-6" />
	</div>
{:else if auditLogs.length === 0}
	<div class="flex flex-col items-center justify-center py-12 text-center">
		<svg
			xmlns="http://www.w3.org/2000/svg"
			viewBox="0 0 24 24"
			fill="currentColor"
			class="size-12 text-gray-400 dark:text-gray-600 mb-4"
		>
			<path
				fill-rule="evenodd"
				d="M5.625 1.5H9a3.75 3.75 0 0 1 3.75 3.75v1.875c0 1.036.84 1.875 1.875 1.875H16.5a3.75 3.75 0 0 1 3.75 3.75v7.875c0 1.035-.84 1.875-1.875 1.875H5.625a1.875 1.875 0 0 1-1.875-1.875V3.375c0-1.036.84-1.875 1.875-1.875ZM9.75 17.25a.75.75 0 0 0-1.5 0V18a.75.75 0 0 0 1.5 0v-.75Zm2.25-3a.75.75 0 0 1 .75.75v3a.75.75 0 0 1-1.5 0v-3a.75.75 0 0 1 .75-.75Zm3.75-1.5a.75.75 0 0 0-1.5 0V18a.75.75 0 0 0 1.5 0v-5.25Z"
				clip-rule="evenodd"
			/>
			<path
				d="M14.25 5.25a5.23 5.23 0 0 0-1.279-3.434 9.768 9.768 0 0 1 6.963 6.963A5.23 5.23 0 0 0 16.5 7.5h-1.875a.375.375 0 0 1-.375-.375V5.25Z"
			/>
		</svg>
		<p class="text-gray-500 dark:text-gray-400">
			{$i18n.t('No audit logs found.')}
		</p>
	</div>
{:else}
	<!-- Table Header -->
	<div class="hidden md:flex text-xs font-medium text-gray-500 px-1 mb-1 uppercase">
		<div class="flex-none w-44">{$i18n.t('Time')}</div>
		<div class="flex-1">{$i18n.t('User')}</div>
		<div class="flex-none w-24 text-center">{$i18n.t('Action')}</div>
		<div class="flex-1">{$i18n.t('Resource')}</div>
		<div class="flex-none w-28">{$i18n.t('IP')}</div>
		<div class="flex-none w-16 text-center"></div>
	</div>
	<hr class="mb-2 border-gray-50 dark:border-gray-850 hidden md:block" />

	<!-- Table Rows -->
	{#each auditLogs as log}
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
			<div class="flex-none w-24 flex justify-center">
				<span class="px-2 py-0.5 text-xs font-medium rounded {getActionStyle(log.action)}">
					{getActionLabel(log.action)}
				</span>
			</div>
			<div class="flex-1 min-w-0">
				<div class="font-medium text-sm text-gray-900 dark:text-gray-100">{getResourceTypeLabel(log.resource_type)}</div>
				<div class="text-xs text-gray-500 dark:text-gray-400 truncate">{log.resource_name || log.resource_id || '-'}</div>
			</div>
			<div class="flex-none w-28 text-xs text-gray-500 dark:text-gray-400">
				{log.ip_address || '-'}
			</div>
			<div class="flex-none w-16 flex justify-center">
				<Button
					kind="outlined"
					size="sm"
					type="button"
					on:click={() => showLogDetail(log)}
				>
					{$i18n.t('Detail')}
				</Button>
			</div>
		</div>
	{/each}

	<!-- Pagination -->
	{#if totalPages > 1}
		<div class="flex items-center justify-center gap-2 mt-4 pt-4 border-t border-gray-50 dark:border-gray-850">
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

<!-- Detail Modal -->
<Modal bind:show={showDetailModal} size="lg">
	<div class="px-5 py-4">
		<div class="flex items-center justify-between mb-4">
			<h2 class="text-lg font-semibold text-gray-900 dark:text-gray-100">{$i18n.t('Audit Log Detail')}</h2>
		</div>

		{#if selectedLog}
			<div class="space-y-4 max-h-[60vh] overflow-y-auto">
				<div class="grid grid-cols-2 gap-4">
					<div>
						<div class="text-xs text-gray-500 dark:text-gray-400 mb-1">{$i18n.t('Time')}</div>
						<div class="text-sm text-gray-900 dark:text-gray-100">{formatTimestamp(selectedLog.created_at)}</div>
					</div>
					<div>
						<div class="text-xs text-gray-500 dark:text-gray-400 mb-1">{$i18n.t('Action')}</div>
						<span class="px-2 py-0.5 text-xs font-medium rounded {getActionStyle(selectedLog.action)}">
							{getActionLabel(selectedLog.action)}
						</span>
					</div>
					<div>
						<div class="text-xs text-gray-500 dark:text-gray-400 mb-1">{$i18n.t('User')}</div>
						<div class="text-sm text-gray-900 dark:text-gray-100">{selectedLog.user_name || '-'}</div>
						<div class="text-xs text-gray-500 dark:text-gray-400">{selectedLog.user_email || ''}</div>
					</div>
					<div>
						<div class="text-xs text-gray-500 dark:text-gray-400 mb-1">{$i18n.t('Resource')}</div>
						<div class="text-sm text-gray-900 dark:text-gray-100">{getResourceTypeLabel(selectedLog.resource_type)}</div>
						<div class="text-xs text-gray-500 dark:text-gray-400">{selectedLog.resource_name || selectedLog.resource_id}</div>
					</div>
					<div>
						<div class="text-xs text-gray-500 dark:text-gray-400 mb-1">{$i18n.t('IP Address')}</div>
						<div class="text-sm text-gray-900 dark:text-gray-100">{selectedLog.ip_address || '-'}</div>
					</div>
					<div>
						<div class="text-xs text-gray-500 dark:text-gray-400 mb-1">{$i18n.t('Request Path')}</div>
						<div class="text-sm text-gray-900 dark:text-gray-100 truncate">{selectedLog.request_path || '-'}</div>
					</div>
				</div>

				{#if selectedLog.changed_fields && selectedLog.changed_fields.length > 0}
					<div>
						<div class="text-xs text-gray-500 dark:text-gray-400 mb-2">{$i18n.t('Changed Fields')}</div>
						<div class="flex flex-wrap gap-1">
							{#each selectedLog.changed_fields as field}
								<span class="px-2 py-0.5 bg-yellow-100 dark:bg-yellow-900/30 text-yellow-800 dark:text-yellow-300 text-xs rounded">
									{field}
								</span>
							{/each}
						</div>
					</div>
				{/if}

				{#if selectedLog.access_control_changes}
					<div>
						<div class="text-xs text-gray-500 dark:text-gray-400 mb-2">{$i18n.t('Access Control Changes')}</div>
						<pre class="bg-gray-50 dark:bg-gray-950 text-gray-900 dark:text-gray-200 p-3 rounded-lg text-xs overflow-x-auto">{JSON.stringify(selectedLog.access_control_changes, null, 2)}</pre>
					</div>
				{/if}

				{#if selectedLog.before_state}
					<div>
						<div class="text-xs text-gray-500 dark:text-gray-400 mb-2">{$i18n.t('Before State')}</div>
						<pre class="bg-gray-50 dark:bg-gray-950 text-gray-900 dark:text-gray-200 p-3 rounded-lg text-xs overflow-x-auto max-h-40">{JSON.stringify(selectedLog.before_state, null, 2)}</pre>
					</div>
				{/if}

				{#if selectedLog.after_state}
					<div>
						<div class="text-xs text-gray-500 dark:text-gray-400 mb-2">{$i18n.t('After State')}</div>
						<pre class="bg-gray-50 dark:bg-gray-950 text-gray-900 dark:text-gray-200 p-3 rounded-lg text-xs overflow-x-auto max-h-40">{JSON.stringify(selectedLog.after_state, null, 2)}</pre>
					</div>
				{/if}

				{#if selectedLog.user_agent}
					<div>
						<div class="text-xs text-gray-500 dark:text-gray-400 mb-2">{$i18n.t('User Agent')}</div>
						<div class="text-xs text-gray-600 dark:text-gray-400 break-all bg-gray-50 dark:bg-gray-950 p-2 rounded-lg">
							{selectedLog.user_agent}
						</div>
					</div>
				{/if}
			</div>
		{/if}

		<div class="flex justify-end mt-4 pt-4 border-t border-gray-100 dark:border-gray-850">
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
			<Button
				kind="text"
				size="sm"
				type="button"
				on:click={() => {
					showCustomDateModal = false;
					if (dateRange !== 'custom') {
						dateRange = '1h';
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

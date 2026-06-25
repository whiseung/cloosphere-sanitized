<script lang="ts">
	import { getContext, onMount, onDestroy } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { PLOTLY_FONT_FAMILY } from '$lib/constants';
	import { DropdownMenu } from 'bits-ui';
	import { flyAndScale } from '$lib/utils/transitions';

	import ArrowPath from '$lib/components/icons/ArrowPath.svelte';
	import ChevronDown from '$lib/components/icons/ChevronDown.svelte';
	import XMark from '$lib/components/icons/XMark.svelte';
	import Checkbox from '$lib/components/common/Checkbox.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import Modal from '$lib/components/common/Modal.svelte';
	import Button from '$lib/components/common/Button.svelte';
	import LabelBase from '$lib/components/common/LabelBase.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import { formatBackendError } from '$lib/utils/error';

	import {
		getUsageStats,
		getUsageTrends,
		getUsageByModel,
		getUsageByUser,
		getUsageByGroup,
		getUsageByOrganization,
		getUsageByType,
		getUsageByAgent,
		getAvailableModels,
		getAvailableUsers,
		getAvailableGroups,
		getAvailableOrganizations,
		getAvailableAgents,
		getOnlineUsers,
		type UsageStats,
		type UsageTrendItem,
		type UsageByModelItem,
		type UsageByUserItem,
		type UsageByGroupItem,
		type UsageByOrganizationItem,
		type UsageByTypeItem,
		type UsageByAgentItem,
		type FilterOption,
		type OnlineUsers
	} from '$lib/apis/usage';

	const i18n = getContext('i18n');

	let loading = true;
	let Plotly: any = null;

	// Date range
	let dateRange = '7d';
	let fromDate: number | undefined = undefined;
	let toDate: number | undefined = undefined;

	// Custom date range
	let customFromDate = '';
	let customToDate = '';
	let customDateLabel = '';
	let showCustomDateModal = false;

	// Filters (Multi-select arrays)
	let selectedAgents: string[] = [];
	let selectedModels: string[] = [];
	let selectedUsers: string[] = [];
	let selectedGroups: string[] = [];
	let selectedOrganizations: string[] = [];

	// Dropdown states
	let showAgentDropdown = false;
	let showModelDropdown = false;
	let showUserDropdown = false;
	let showGroupDropdown = false;
	let showOrgDropdown = false;

	// Filter options
	let modelOptions: FilterOption[] = [];
	let userOptions: FilterOption[] = [];
	let groupOptions: FilterOption[] = [];
	let organizationOptions: FilterOption[] = [];
	let agentOptions: FilterOption[] = [];

	// Data
	let stats: UsageStats | null = null;
	let onlineUsers: OnlineUsers | null = null;
	let trends: UsageTrendItem[] = [];
	let byModel: UsageByModelItem[] = [];
	let byUser: UsageByUserItem[] = [];
	let byGroup: UsageByGroupItem[] = [];
	let byOrganization: UsageByOrganizationItem[] = [];
	let byType: UsageByTypeItem[] = [];
	let byAgent: UsageByAgentItem[] = [];

	// Chart containers
	let trendsChartEl: HTMLDivElement;
	let modelChartEl: HTMLDivElement;
	let typeChartEl: HTMLDivElement;
	let userChartEl: HTMLDivElement;
	let groupChartEl: HTMLDivElement;
	let orgChartEl: HTMLDivElement;
	let agentChartEl: HTMLDivElement;

	// datetime-local 포맷 (YYYY-MM-DDTHH:mm)
	const toDateTimeLocal = (date: Date) => {
		const pad = (n: number) => n.toString().padStart(2, '0');
		return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
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

	const setDateRange = (range: string) => {
		if (range === 'custom') {
			// 기본값: 최근 1주일
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
				fromDate = undefined;
				toDate = undefined;
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
			loadUsageData();
		}
	};

	const getCustomDateLabel = () => {
		if (dateRange === 'custom' && customDateLabel) {
			return customDateLabel;
		}
		return '';
	};

	// 초기 날짜 범위 설정
	setDateRange('7d');

	const loadFilterOptions = async () => {
		// Load each filter option independently to prevent one failure from blocking others
		const loadSafe = async <T>(fn: () => Promise<T>, defaultValue: T): Promise<T> => {
			try {
				return await fn() ?? defaultValue;
			} catch (err) {
				console.error('Failed to load filter option:', err);
				return defaultValue;
			}
		};

		const [models, users, groups, orgs, agents] = await Promise.all([
			loadSafe(() => getAvailableModels(localStorage.token), []),
			loadSafe(() => getAvailableUsers(localStorage.token), []),
			loadSafe(() => getAvailableGroups(localStorage.token), []),
			loadSafe(() => getAvailableOrganizations(localStorage.token), []),
			loadSafe(() => getAvailableAgents(localStorage.token), [])
		]);

		modelOptions = models;
		userOptions = users;
		groupOptions = groups;
		organizationOptions = orgs;
		agentOptions = agents;

		// 기본값: 전체 선택
		selectedAgents = agentOptions.map((a) => a.id);
		selectedModels = modelOptions.map((m) => m.id);
		selectedUsers = userOptions.map((u) => u.id);
		selectedGroups = groupOptions.map((g) => g.id);
		selectedOrganizations = organizationOptions.map((o) => o.id);
	};

	const loadUsageData = async () => {
		// 상대 날짜 범위면 현재 시간 기준으로 재계산
		if (dateRange && dateRange !== 'custom' && dateRange !== 'all') {
			setDateRange(dateRange);
		}
		loading = true;

		// Filter logic:
		// - All selected (or length === options.length): no filter (show all)
		// - 0 selected: send "__none__" marker to return empty results
		// - Partial selection: send comma-separated IDs
		const params: Record<string, string | number | undefined> = {
			from_date: fromDate,
			to_date: toDate
		};

		const applyFilter = (selected: string[], options: FilterOption[], key: string) => {
			if (options.length === 0) {
				// No options available — don't filter (show all)
				return;
			}
			if (selected.length === 0) {
				params[key] = '__none__';
			} else if (selected.length < options.length) {
				params[key] = selected.join(',');
			}
			// If all selected, don't set the param (show all)
		};

		applyFilter(selectedAgents, agentOptions, 'agent_id');
		applyFilter(selectedModels, modelOptions, 'model_id');
		applyFilter(selectedUsers, userOptions, 'user_id');
		applyFilter(selectedGroups, groupOptions, 'group_id');
		applyFilter(selectedOrganizations, organizationOptions, 'organization_id');

		try {
			const [statsRes, onlineRes, trendsRes, modelRes, userRes, groupRes, orgRes, typeRes, agentRes] =
				await Promise.all([
					getUsageStats(localStorage.token, params),
					getOnlineUsers(localStorage.token),
					getUsageTrends(localStorage.token, {
						...params,
						granularity: dateRange === '1d' ? 'hour' : 'day'
					}),
					getUsageByModel(localStorage.token, params),
					getUsageByUser(localStorage.token, { ...params, limit: 5 }),
					getUsageByGroup(localStorage.token, { ...params, limit: 5 }),
					getUsageByOrganization(localStorage.token, { ...params, limit: 10 }),
					getUsageByType(localStorage.token, params),
					getUsageByAgent(localStorage.token, { ...params, limit: 10 })
				]);

			stats = statsRes;
			onlineUsers = onlineRes;
			trends = trendsRes;
			byModel = modelRes;
			byUser = userRes;
			byGroup = groupRes;
			byOrganization = orgRes;
			byType = typeRes;
			byAgent = agentRes;

			loading = false;

			// Render charts after DOM update
			setTimeout(() => {
				renderCharts();
			}, 0);
		} catch (err: any) {
			toast.error(formatBackendError(err, $i18n) || $i18n.t('Failed to load usage data'));
			loading = false;
		}
	};

	// Toggle functions for multi-select filters
	const toggleAgent = (id: string) => {
		if (selectedAgents.includes(id)) {
			selectedAgents = selectedAgents.filter((a) => a !== id);
		} else {
			selectedAgents = [...selectedAgents, id];
		}
		loadUsageData();
	};

	const toggleAllAgents = () => {
		if (selectedAgents.length === agentOptions.length) {
			selectedAgents = [];
		} else {
			selectedAgents = agentOptions.map((a) => a.id);
		}
		loadUsageData();
	};

	const toggleModel = (id: string) => {
		if (selectedModels.includes(id)) {
			selectedModels = selectedModels.filter((m) => m !== id);
		} else {
			selectedModels = [...selectedModels, id];
		}
		loadUsageData();
	};

	const toggleAllModels = () => {
		if (selectedModels.length === modelOptions.length) {
			selectedModels = [];
		} else {
			selectedModels = modelOptions.map((m) => m.id);
		}
		loadUsageData();
	};

	const toggleUser = (id: string) => {
		if (selectedUsers.includes(id)) {
			selectedUsers = selectedUsers.filter((u) => u !== id);
		} else {
			selectedUsers = [...selectedUsers, id];
		}
		loadUsageData();
	};

	const toggleAllUsers = () => {
		if (selectedUsers.length === userOptions.length) {
			selectedUsers = [];
		} else {
			selectedUsers = userOptions.map((u) => u.id);
		}
		loadUsageData();
	};

	const toggleGroup = (id: string) => {
		if (selectedGroups.includes(id)) {
			selectedGroups = selectedGroups.filter((g) => g !== id);
		} else {
			selectedGroups = [...selectedGroups, id];
		}
		loadUsageData();
	};

	const toggleAllGroups = () => {
		if (selectedGroups.length === groupOptions.length) {
			selectedGroups = [];
		} else {
			selectedGroups = groupOptions.map((g) => g.id);
		}
		loadUsageData();
	};

	const toggleOrganization = (id: string) => {
		if (selectedOrganizations.includes(id)) {
			selectedOrganizations = selectedOrganizations.filter((o) => o !== id);
		} else {
			selectedOrganizations = [...selectedOrganizations, id];
		}
		loadUsageData();
	};

	const toggleAllOrganizations = () => {
		if (selectedOrganizations.length === organizationOptions.length) {
			selectedOrganizations = [];
		} else {
			selectedOrganizations = organizationOptions.map((o) => o.id);
		}
		loadUsageData();
	};

	// Reactive filter labels
	const getFilterLabel = (selected: string[], options: FilterOption[], allLabel: string) => {
		if (selected.length === options.length) {
			return allLabel;
		}
		if (selected.length === 0) {
			return `0 ${$i18n.t('selected')}`;
		}
		if (selected.length === 1) {
			return options.find((o) => o.id === selected[0])?.name || selected[0];
		}
		return `${selected.length} ${$i18n.t('selected')}`;
	};

	$: agentFilterLabel = getFilterLabel(selectedAgents, agentOptions, $i18n.t('All Agents'));
	$: modelFilterLabel = getFilterLabel(selectedModels, modelOptions, $i18n.t('All Models'));
	$: userFilterLabel = getFilterLabel(selectedUsers, userOptions, $i18n.t('All Users'));
	$: groupFilterLabel = getFilterLabel(selectedGroups, groupOptions, $i18n.t('All Groups'));
	$: orgFilterLabel = getFilterLabel(selectedOrganizations, organizationOptions, $i18n.t('All Teams'));

	const formatNumber = (num: number) => {
		if (num >= 1000000) {
			return (num / 1000000).toFixed(1) + 'M';
		}
		if (num >= 1000) {
			return (num / 1000).toFixed(1) + 'K';
		}
		return num.toLocaleString();
	};

	const truncateLabel = (label: string, maxLength: number = 20) => {
		if (!label) return '';
		if (label.length <= maxLength) return label;
		return label.substring(0, maxLength - 3) + '...';
	};

	const getChartLayout = (title: string, extraOptions = {}) => ({
		title: {
			text: title,
			font: {
				size: 14,
				color: '#6b7280',
				family: PLOTLY_FONT_FAMILY
			}
		},
		paper_bgcolor: 'rgba(0,0,0,0)',
		plot_bgcolor: 'rgba(0,0,0,0)',
		font: {
			color: '#6b7280',
			family: PLOTLY_FONT_FAMILY
		},
		margin: { t: 40, r: 20, b: 40, l: 50 },
		...extraOptions
	});

	const getChartConfig = () => ({
		responsive: true,
		displayModeBar: false
	});

	// Color palette for bar charts (per-bar coloring)
	const BAR_COLORS = [
		'#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6',
		'#ec4899', '#06b6d4', '#84cc16', '#f97316', '#6366f1',
		'#14b8a6', '#e11d48', '#0ea5e9', '#a855f7', '#eab308',
		'#22c55e', '#f43f5e', '#8b5cf6', '#64748b', '#0d9488'
	];

	const getBarColors = (count: number) =>
		Array.from({ length: count }, (_, i) => BAR_COLORS[i % BAR_COLORS.length]);

	const renderCharts = () => {
		if (!Plotly) return;

		// Trends chart (Area)
		if (trendsChartEl && trends.length > 0) {
			const trendData = [
				{
					x: trends.map((t) => t.date),
					y: trends.map((t) => t.tokens),
					type: 'scatter',
					mode: 'lines',
					fill: 'tozeroy',
					name: $i18n.t('Tokens'),
					line: { color: '#3b82f6', width: 2 },
					fillcolor: 'rgba(59, 130, 246, 0.1)'
				}
			];
			Plotly.newPlot(
				trendsChartEl,
				trendData,
				getChartLayout($i18n.t('Token Usage Trend'), {
					xaxis: { showgrid: false },
					yaxis: { showgrid: true, gridcolor: 'rgba(107, 114, 128, 0.1)' }
				}),
				getChartConfig()
			);
		}

		// Model chart (Donut)
		if (modelChartEl && byModel.length > 0) {
			const modelData = [
				{
					values: byModel.map((m) => m.total_tokens),
					labels: byModel.map((m) => m.model_id),
					type: 'pie',
					hole: 0.4,
					textinfo: 'percent',
					textposition: 'inside',
					marker: {
						colors: [
							'#3b82f6',
							'#10b981',
							'#f59e0b',
							'#ef4444',
							'#8b5cf6',
							'#ec4899',
							'#06b6d4',
							'#84cc16'
						]
					}
				}
			];
			Plotly.newPlot(
				modelChartEl,
				modelData,
				getChartLayout($i18n.t('Usage by Model'), {
					showlegend: true,
					legend: { orientation: 'h', y: -0.1 }
				}),
				getChartConfig()
			);
		}

		// Type chart (Bar)
		if (typeChartEl && byType.length > 0) {
			const typeData = [
				{
					x: byType.map((t) => t.message_type),
					y: byType.map((t) => t.total_tokens),
					type: 'bar',
					marker: {
						color: getBarColors(byType.length)
					}
				}
			];
			Plotly.newPlot(
				typeChartEl,
				typeData,
				getChartLayout($i18n.t('Usage by Type'), {
					xaxis: { showgrid: false },
					yaxis: { showgrid: true, gridcolor: 'rgba(107, 114, 128, 0.1)' }
				}),
				getChartConfig()
			);
		}

		// User chart (Horizontal Bar)
		if (userChartEl && byUser.length > 0) {
			const userData = [
				{
					y: byUser.map((u) => truncateLabel(u.user_name || u.user_email, 25)),
					x: byUser.map((u) => u.total_tokens),
					text: byUser.map((u) => u.user_name || u.user_email),
					hovertemplate: '%{text}<br>Tokens: %{x:,.0f}<extra></extra>',
					type: 'bar',
					orientation: 'h',
					marker: {
						color: getBarColors(byUser.length)
					}
				}
			];
			Plotly.newPlot(
				userChartEl,
				userData,
				getChartLayout($i18n.t('Top Users'), {
					xaxis: { showgrid: true, gridcolor: 'rgba(107, 114, 128, 0.1)' },
					yaxis: { showgrid: false, automargin: true },
					margin: { t: 40, r: 20, b: 40, l: 120 }
				}),
				getChartConfig()
			);
		}

		// Group chart (Horizontal Bar)
		if (groupChartEl && byGroup.length > 0) {
			const groupData = [
				{
					y: byGroup.map((g) => truncateLabel(g.group_name, 25)),
					x: byGroup.map((g) => g.total_tokens),
					text: byGroup.map((g) => g.group_name),
					hovertemplate: '%{text}<br>Tokens: %{x:,.0f}<extra></extra>',
					type: 'bar',
					orientation: 'h',
					marker: {
						color: getBarColors(byGroup.length)
					}
				}
			];
			Plotly.newPlot(
				groupChartEl,
				groupData,
				getChartLayout($i18n.t('Top Groups'), {
					xaxis: { showgrid: true, gridcolor: 'rgba(107, 114, 128, 0.1)' },
					yaxis: { showgrid: false, automargin: true },
					margin: { t: 40, r: 20, b: 40, l: 120 }
				}),
				getChartConfig()
			);
		}

		// Organization/Team chart (Horizontal Bar)
		if (orgChartEl && byOrganization.length > 0) {
			const orgData = [
				{
					y: byOrganization.map((o) => truncateLabel(o.organization_name, 30)),
					x: byOrganization.map((o) => o.total_tokens),
					text: byOrganization.map((o) => o.organization_name),
					hovertemplate: '%{text}<br>Tokens: %{x:,.0f}<extra></extra>',
					type: 'bar',
					orientation: 'h',
					marker: {
						color: getBarColors(byOrganization.length)
					}
				}
			];
			Plotly.newPlot(
				orgChartEl,
				orgData,
				getChartLayout($i18n.t('Top Teams'), {
					xaxis: { showgrid: true, gridcolor: 'rgba(107, 114, 128, 0.1)' },
					yaxis: { showgrid: false, automargin: true },
					margin: { t: 40, r: 20, b: 40, l: 150 }
				}),
				getChartConfig()
			);
		}

		// Agent chart (Horizontal Bar)
		if (agentChartEl && byAgent.length > 0) {
			const agentData = [
				{
					y: byAgent.map((a) => truncateLabel(a.agent_name, 25)),
					x: byAgent.map((a) => a.total_tokens),
					text: byAgent.map((a) => a.agent_name),
					hovertemplate: '%{text}<br>Tokens: %{x:,.0f}<extra></extra>',
					type: 'bar',
					orientation: 'h',
					marker: {
						color: getBarColors(byAgent.length)
					}
				}
			];
			Plotly.newPlot(
				agentChartEl,
				agentData,
				getChartLayout($i18n.t('Top Agents'), {
					xaxis: { showgrid: true, gridcolor: 'rgba(107, 114, 128, 0.1)' },
					yaxis: { showgrid: false, automargin: true },
					margin: { t: 40, r: 20, b: 40, l: 150 }
				}),
				getChartConfig()
			);
		}
	};

	const hasActiveFilters = () => {
		return (
			(selectedAgents.length > 0 && selectedAgents.length < agentOptions.length) ||
			(selectedModels.length > 0 && selectedModels.length < modelOptions.length) ||
			(selectedUsers.length > 0 && selectedUsers.length < userOptions.length) ||
			(selectedGroups.length > 0 && selectedGroups.length < groupOptions.length) ||
			(selectedOrganizations.length > 0 && selectedOrganizations.length < organizationOptions.length)
		);
	};

	const clearFilters = () => {
		selectedAgents = agentOptions.map((a) => a.id);
		selectedModels = modelOptions.map((m) => m.id);
		selectedUsers = userOptions.map((u) => u.id);
		selectedGroups = groupOptions.map((g) => g.id);
		selectedOrganizations = organizationOptions.map((o) => o.id);
		loadUsageData();
	};

	onMount(async () => {
		// Dynamic import Plotly
		const plotlyModule = await import('plotly.js-dist-min');
		Plotly = plotlyModule.default;
		await loadFilterOptions();
		loadUsageData();
	});

	onDestroy(() => {
		// Cleanup charts
		if (Plotly) {
			if (trendsChartEl) Plotly.purge(trendsChartEl);
			if (modelChartEl) Plotly.purge(modelChartEl);
			if (typeChartEl) Plotly.purge(typeChartEl);
			if (userChartEl) Plotly.purge(userChartEl);
			if (groupChartEl) Plotly.purge(groupChartEl);
			if (orgChartEl) Plotly.purge(orgChartEl);
			if (agentChartEl) Plotly.purge(agentChartEl);
		}
	});
</script>

<!-- Header -->
<div class="mt-0.5 mb-2 flex flex-col gap-2">
	<div class="flex items-center text-lg font-bold px-0.5">
		{$i18n.t('Usage')}
	</div>

	<div class="flex gap-1.5 flex-wrap items-center">
		<!-- Date Range Filter (pill buttons) -->
		<div class="flex items-center rounded-lg bg-gray-50 dark:bg-gray-950 p-0.5 gap-0.5">
			{#each [
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
						loadUsageData();
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

		<!-- Agent Filter (Multi-select) -->
		<DropdownMenu.Root bind:open={showAgentDropdown}>
			<DropdownMenu.Trigger>
				<button
					class="flex items-center gap-2 px-3 py-1.5 min-w-[140px] max-w-[220px] text-sm bg-gray-50 dark:bg-gray-950 rounded-lg outline-none cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-900 transition"
					title={agentFilterLabel}
				>
					<span class="flex-1 text-left truncate">{agentFilterLabel}</span>
					<ChevronDown className="size-4 flex-shrink-0" />
				</button>
			</DropdownMenu.Trigger>
			<DropdownMenu.Content
				class="w-64 max-h-72 overflow-y-auto rounded-lg p-1 border border-gray-100 dark:border-gray-850 bg-white dark:bg-gray-900 shadow-lg z-50"
				sideOffset={4}
				transition={flyAndScale}
			>
				<button
					class="flex w-full items-center gap-2 px-3 py-2 text-sm rounded-md cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-850 transition"
					on:click|stopPropagation={() => toggleAllAgents()}
					>
					<Checkbox state={selectedAgents.length === agentOptions.length && agentOptions.length > 0 ? 'checked' : 'unchecked'} />
					<span class="font-medium">{$i18n.t('Select All')}</span>
				</button>
				<div class="h-px bg-gray-100 dark:bg-gray-800 my-1"></div>
				{#each agentOptions as agent}
					<button
						class="flex w-full items-center gap-2 px-3 py-2 text-sm rounded-md cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-850 transition"
						on:click|stopPropagation={() => toggleAgent(agent.id)}
						>
						<Checkbox state={selectedAgents.includes(agent.id) ? 'checked' : 'unchecked'} />
						<span class="truncate">{agent.name}</span>
					</button>
				{:else}
					<div class="px-3 py-2 text-sm text-gray-400">{$i18n.t('No agents available')}</div>
				{/each}
			</DropdownMenu.Content>
		</DropdownMenu.Root>

		<!-- Model Filter (Multi-select) -->
		<DropdownMenu.Root bind:open={showModelDropdown}>
			<DropdownMenu.Trigger>
				<button
					class="flex items-center gap-2 px-3 py-1.5 min-w-[140px] max-w-[220px] text-sm bg-gray-50 dark:bg-gray-950 rounded-lg outline-none cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-900 transition"
					title={modelFilterLabel}
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
				<button
					class="flex w-full items-center gap-2 px-3 py-2 text-sm rounded-md cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-850 transition"
					on:click|stopPropagation={() => toggleAllModels()}
					>
					<Checkbox state={selectedModels.length === modelOptions.length && modelOptions.length > 0 ? 'checked' : 'unchecked'} />
					<span class="font-medium">{$i18n.t('Select All')}</span>
				</button>
				<div class="h-px bg-gray-100 dark:bg-gray-800 my-1"></div>
				{#each modelOptions as model}
					<button
						class="flex w-full items-center gap-2 px-3 py-2 text-sm rounded-md cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-850 transition"
						on:click|stopPropagation={() => toggleModel(model.id)}
						>
						<Checkbox state={selectedModels.includes(model.id) ? 'checked' : 'unchecked'} />
						<span class="truncate">{model.name}</span>
					</button>
				{:else}
					<div class="px-3 py-2 text-sm text-gray-400">{$i18n.t('No models available')}</div>
				{/each}
			</DropdownMenu.Content>
		</DropdownMenu.Root>

		<!-- User Filter (Multi-select) -->
		<DropdownMenu.Root bind:open={showUserDropdown}>
			<DropdownMenu.Trigger>
				<button
					class="flex items-center gap-2 px-3 py-1.5 min-w-[140px] max-w-[220px] text-sm bg-gray-50 dark:bg-gray-950 rounded-lg outline-none cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-900 transition"
					title={userFilterLabel}
				>
					<span class="flex-1 text-left truncate">{userFilterLabel}</span>
					<ChevronDown className="size-4 flex-shrink-0" />
				</button>
			</DropdownMenu.Trigger>
			<DropdownMenu.Content
				class="w-64 max-h-72 overflow-y-auto rounded-lg p-1 border border-gray-100 dark:border-gray-850 bg-white dark:bg-gray-900 shadow-lg z-50"
				sideOffset={4}
				transition={flyAndScale}
			>
				<button
					class="flex w-full items-center gap-2 px-3 py-2 text-sm rounded-md cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-850 transition"
					on:click|stopPropagation={() => toggleAllUsers()}
					>
					<Checkbox state={selectedUsers.length === userOptions.length && userOptions.length > 0 ? 'checked' : 'unchecked'} />
					<span class="font-medium">{$i18n.t('Select All')}</span>
				</button>
				<div class="h-px bg-gray-100 dark:bg-gray-800 my-1"></div>
				{#each userOptions as user}
					<button
						class="flex w-full items-center gap-2 px-3 py-2 text-sm rounded-md cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-850 transition"
						on:click|stopPropagation={() => toggleUser(user.id)}
						>
						<Checkbox state={selectedUsers.includes(user.id) ? 'checked' : 'unchecked'} />
						<span class="truncate">{user.name}</span>
					</button>
				{:else}
					<div class="px-3 py-2 text-sm text-gray-400">{$i18n.t('No users available')}</div>
				{/each}
			</DropdownMenu.Content>
		</DropdownMenu.Root>

		<!-- Group Filter (Multi-select) -->
		<DropdownMenu.Root bind:open={showGroupDropdown}>
			<DropdownMenu.Trigger>
				<button
					class="flex items-center gap-2 px-3 py-1.5 min-w-[140px] max-w-[220px] text-sm bg-gray-50 dark:bg-gray-950 rounded-lg outline-none cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-900 transition"
					title={groupFilterLabel}
				>
					<span class="flex-1 text-left truncate">{groupFilterLabel}</span>
					<ChevronDown className="size-4 flex-shrink-0" />
				</button>
			</DropdownMenu.Trigger>
			<DropdownMenu.Content
				class="w-64 max-h-72 overflow-y-auto rounded-lg p-1 border border-gray-100 dark:border-gray-850 bg-white dark:bg-gray-900 shadow-lg z-50"
				sideOffset={4}
				transition={flyAndScale}
			>
				<button
					class="flex w-full items-center gap-2 px-3 py-2 text-sm rounded-md cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-850 transition"
					on:click|stopPropagation={() => toggleAllGroups()}
					>
					<Checkbox state={selectedGroups.length === groupOptions.length && groupOptions.length > 0 ? 'checked' : 'unchecked'} />
					<span class="font-medium">{$i18n.t('Select All')}</span>
				</button>
				<div class="h-px bg-gray-100 dark:bg-gray-800 my-1"></div>
				{#each groupOptions as group}
					<button
						class="flex w-full items-center gap-2 px-3 py-2 text-sm rounded-md cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-850 transition"
						on:click|stopPropagation={() => toggleGroup(group.id)}
						>
						<Checkbox state={selectedGroups.includes(group.id) ? 'checked' : 'unchecked'} />
						<span class="truncate">{group.name}</span>
					</button>
				{:else}
					<div class="px-3 py-2 text-sm text-gray-400">{$i18n.t('No groups available')}</div>
				{/each}
			</DropdownMenu.Content>
		</DropdownMenu.Root>

		<!-- Team Filter (Multi-select) -->
		<DropdownMenu.Root bind:open={showOrgDropdown}>
			<DropdownMenu.Trigger>
				<button
					class="flex items-center gap-2 px-3 py-1.5 min-w-[140px] max-w-[220px] text-sm bg-gray-50 dark:bg-gray-950 rounded-lg outline-none cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-900 transition"
					title={orgFilterLabel}
				>
					<span class="flex-1 text-left truncate">{orgFilterLabel}</span>
					<ChevronDown className="size-4 flex-shrink-0" />
				</button>
			</DropdownMenu.Trigger>
			<DropdownMenu.Content
				class="w-80 max-h-72 overflow-y-auto rounded-lg p-1 border border-gray-100 dark:border-gray-850 bg-white dark:bg-gray-900 shadow-lg z-50"
				sideOffset={4}
				transition={flyAndScale}
			>
				<button
					class="flex w-full items-center gap-2 px-3 py-2 text-sm rounded-md cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-850 transition"
					on:click|stopPropagation={() => toggleAllOrganizations()}
					>
					<Checkbox state={selectedOrganizations.length === organizationOptions.length && organizationOptions.length > 0 ? 'checked' : 'unchecked'} />
					<span class="font-medium">{$i18n.t('Select All')}</span>
				</button>
				<div class="h-px bg-gray-100 dark:bg-gray-800 my-1"></div>
				{#each organizationOptions as org}
					<button
						class="flex w-full items-center gap-2 px-3 py-2 text-sm rounded-md cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-850 transition"
						on:click|stopPropagation={() => toggleOrganization(org.id)}
						>
						<Checkbox state={selectedOrganizations.includes(org.id) ? 'checked' : 'unchecked'} />
						<span class="truncate">{org.name}</span>
					</button>
				{:else}
					<div class="px-3 py-2 text-sm text-gray-400">{$i18n.t('No teams available')}</div>
				{/each}
			</DropdownMenu.Content>
		</DropdownMenu.Root>

		<!-- Clear Filters -->
		{#if hasActiveFilters()}
			<Tooltip content={$i18n.t('Clear Filters')}>
				<Button kind="text" size="sm" type="button" on:click={clearFilters}>
					<svelte:fragment slot="prefix">
						<XMark className="size-4" />
					</svelte:fragment>
				</Button>
			</Tooltip>
		{/if}

		<!-- Refresh -->
		<Tooltip content={$i18n.t('Refresh')}>
			<Button kind="text" size="sm" type="button" on:click={loadUsageData}>
				<svelte:fragment slot="prefix">
					<ArrowPath className="size-4" />
				</svelte:fragment>
			</Button>
		</Tooltip>
	</div>
</div>

<hr class="mb-3 border-gray-50 dark:border-gray-850" />

{#if loading}
	<div class="flex justify-center py-8">
		<Spinner className="size-6" />
	</div>
{:else}
	<!-- Summary Cards -->
	<div class="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-4 mb-6">
		<!-- 실시간 접속자 (강조) -->
		<div class="p-4 bg-emerald-50 dark:bg-emerald-950/30 rounded-xl border border-emerald-200 dark:border-emerald-800">
			<div class="flex items-center gap-1.5 text-xs text-emerald-600 dark:text-emerald-400 mb-1">
				<span class="relative flex h-2 w-2">
					<span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
					<span class="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
				</span>
				{$i18n.t('Online Now')}
			</div>
			<div class="text-2xl font-bold text-emerald-700 dark:text-emerald-300">{formatNumber(onlineUsers?.count || 0)}</div>
		</div>

		<div class="p-4 bg-gray-50 dark:bg-gray-950 rounded-xl">
			<div class="text-xs text-gray-500 dark:text-gray-400 mb-1">{$i18n.t('Total Tokens')}</div>
			<div class="text-2xl font-bold">{formatNumber(stats?.total_tokens || 0)}</div>
		</div>

		<div class="p-4 bg-gray-50 dark:bg-gray-950 rounded-xl">
			<div class="text-xs text-gray-500 dark:text-gray-400 mb-1">{$i18n.t('Total Requests')}</div>
			<div class="text-2xl font-bold">{formatNumber(stats?.total_requests || 0)}</div>
		</div>

		<div class="p-4 bg-gray-50 dark:bg-gray-950 rounded-xl">
			<div class="text-xs text-gray-500 dark:text-gray-400 mb-1">{$i18n.t('Users in Period')}</div>
			<div class="text-2xl font-bold">{formatNumber(stats?.unique_users || 0)}</div>
		</div>

		<div class="p-4 bg-gray-50 dark:bg-gray-950 rounded-xl">
			<div class="text-xs text-gray-500 dark:text-gray-400 mb-1">{$i18n.t('Active Chats')}</div>
			<div class="text-2xl font-bold">{formatNumber(stats?.unique_chats || 0)}</div>
		</div>

		<div class="p-4 bg-gray-50 dark:bg-gray-950 rounded-xl">
			<div class="text-xs text-gray-500 dark:text-gray-400 mb-1">{$i18n.t('Models Used')}</div>
			<div class="text-2xl font-bold">{formatNumber(stats?.unique_models || 0)}</div>
		</div>

		<div class="p-4 bg-gray-50 dark:bg-gray-950 rounded-xl">
			<div class="text-xs text-gray-500 dark:text-gray-400 mb-1">
				{$i18n.t('Avg Tokens/Request')}
			</div>
			<div class="text-2xl font-bold">{formatNumber(stats?.avg_tokens_per_request || 0)}</div>
		</div>
	</div>

	<!-- Charts Grid -->
	<div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
		<!-- Token Usage Trend -->
		<div class="p-4 bg-gray-50 dark:bg-gray-950 rounded-xl lg:col-span-2">
			{#if trends.length > 0}
				<div bind:this={trendsChartEl} class="h-64"></div>
			{:else}
				<div class="h-64 flex items-center justify-center text-gray-400">
					{$i18n.t('No trend data available')}
				</div>
			{/if}
		</div>

		<!-- Usage by Model -->
		<div class="p-4 bg-gray-50 dark:bg-gray-950 rounded-xl">
			{#if byModel.length > 0}
				<div bind:this={modelChartEl} class="h-80"></div>
			{:else}
				<div class="h-80 flex items-center justify-center text-gray-400">
					{$i18n.t('No model usage data available')}
				</div>
			{/if}
		</div>

		<!-- Usage by Agent -->
		<div class="p-4 bg-gray-50 dark:bg-gray-950 rounded-xl">
			{#if byAgent.length > 0}
				<div bind:this={agentChartEl} class="h-80"></div>
			{:else}
				<div class="h-80 flex items-center justify-center text-gray-400">
					{$i18n.t('No agent usage data available')}
				</div>
			{/if}
		</div>

		<!-- Usage by Type -->
		<div class="p-4 bg-gray-50 dark:bg-gray-950 rounded-xl">
			{#if byType.length > 0}
				<div bind:this={typeChartEl} class="h-80"></div>
			{:else}
				<div class="h-80 flex items-center justify-center text-gray-400">
					{$i18n.t('No type usage data available')}
				</div>
			{/if}
		</div>

		<!-- Top Users -->
		<div class="p-4 bg-gray-50 dark:bg-gray-950 rounded-xl">
			{#if byUser.length > 0}
				<div bind:this={userChartEl} class="h-80"></div>
			{:else}
				<div class="h-80 flex items-center justify-center text-gray-400">
					{$i18n.t('No user usage data available')}
				</div>
			{/if}
		</div>

		<!-- Usage by Group -->
		<div class="p-4 bg-gray-50 dark:bg-gray-950 rounded-xl">
			{#if byGroup.length > 0}
				<div bind:this={groupChartEl} class="h-80"></div>
			{:else}
				<div class="h-80 flex items-center justify-center text-gray-400">
					{$i18n.t('No group usage data available')}
				</div>
			{/if}
		</div>

		<!-- Usage by Organization/Team -->
		<div class="p-4 bg-gray-50 dark:bg-gray-950 rounded-xl lg:col-span-2">
			{#if byOrganization.length > 0}
				<div bind:this={orgChartEl} class="h-96"></div>
			{:else}
				<div class="h-96 flex items-center justify-center text-gray-400">
					{$i18n.t('No team usage data available')}
				</div>
			{/if}
		</div>
	</div>
{/if}

<!-- Custom Date Range Modal -->
<Modal bind:show={showCustomDateModal} size="sm">
	<div>
		<div class="flex justify-between dark:text-gray-100 px-5 pt-4 mb-2">
			<div class="text-lg font-medium self-center">
				{$i18n.t('Custom Date Range')}
			</div>
			<button
				type="button"
				class="self-center"
				on:click={() => {
					showCustomDateModal = false;
					if (dateRange !== 'custom') {
						dateRange = '7d';
					}
				}}
			>
				<XMark className="size-5" />
			</button>
		</div>

		<div class="px-5 pb-4">
			<div class="flex flex-col gap-3">
				<div class="flex flex-col w-full gap-1">
					<LabelBase label={$i18n.t('From')} size="md" />
					<input
						type="datetime-local"
						bind:value={customFromDate}
						class="w-full text-sm bg-transparent placeholder:text-gray-300 dark:placeholder:text-gray-700 outline-none"
					/>
				</div>

				<div class="flex flex-col w-full gap-1">
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
							dateRange = '7d';
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

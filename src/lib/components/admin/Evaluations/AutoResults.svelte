<script lang="ts">
	import { toast } from 'svelte-sonner';
	import fileSaver from 'file-saver';
	import { PLOTLY_FONT_FAMILY } from '$lib/constants';
	const { saveAs } = fileSaver;

	import dayjs from 'dayjs';
	import relativeTime from 'dayjs/plugin/relativeTime';
	dayjs.extend(relativeTime);

	import { onMount, onDestroy, getContext, tick } from 'svelte';
	import { DropdownMenu } from 'bits-ui';
	import { flyAndScale } from '$lib/utils/transitions';

	const i18n = getContext('i18n');

	import { models } from '$lib/stores';
	import {
		getAutoEvaluations,
		getAutoEvaluationStats,
		deleteAutoEvaluation,
		exportAutoEvaluations,
		type AutoEvaluation,
		type AutoEvaluationStats,
		type AutoEvaluationFilter
	} from '$lib/apis/auto-evaluations';

	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import ArrowDownTray from '$lib/components/icons/ArrowDownTray.svelte';
	import ArrowPath from '$lib/components/icons/ArrowPath.svelte';
	import ChevronDown from '$lib/components/icons/ChevronDown.svelte';
	import Check from '$lib/components/icons/Check.svelte';
	import Badge from '$lib/components/common/Badge.svelte';
	import Pagination from '$lib/components/common/Pagination.svelte';
	import Modal from '$lib/components/common/Modal.svelte';
	import AutoResultDetail from './AutoResultDetail.svelte';

	let loaded = false;
	let autoEvaluations: AutoEvaluation[] = [];
	let stats: AutoEvaluationStats | null = null;
	let total = 0;
	let page = 1;
	let limit = 10;

	// Chart
	let Plotly: any = null;
	let scoreChartEl: HTMLDivElement;
	let chartData: AutoEvaluation[] = [];
	type TimeGranularity = 'hour' | 'day' | 'week' | 'month';
	let chartGranularity: TimeGranularity = 'day';
	let chartGranularityAuto = true;

	const granularityOptions: { id: TimeGranularity; label: string }[] = [
		{ id: 'hour', label: 'Hour' },
		{ id: 'day', label: 'Day' },
		{ id: 'week', label: 'Week' },
		{ id: 'month', label: 'Month' }
	];

	// Available options
	let availableModels: { id: string; name: string }[] = [];

	const evaluationTypes = [
		{ id: 'retrieval', name: 'Retrieval Quality' },
		{ id: 'faithfulness', name: 'Faithfulness' },
		{ id: 'quality', name: 'Response Quality' }
	];

	const statusOptions = [
		{ id: 'pending', name: 'Pending' },
		{ id: 'completed', name: 'Completed' },
		{ id: 'failed', name: 'Failed' }
	];

	// Multi-select filters
	let selectedModels: string[] = [];
	let selectedTypes: string[] = [];
	let selectedStatuses: string[] = [];

	// Dropdown state
	let showModelDropdown = false;
	let showTypeDropdown = false;
	let showStatusDropdown = false;

	// Date range
	let dateRange = '7d';
	let fromDate: number | null = null;
	let toDate: number | null = null;

	// Custom date
	let customFromDate = '';
	let customToDate = '';
	let customDateLabel = '';
	let showCustomDateModal = false;

	// Detail modal
	let showDetail = false;
	let selectedEvaluation: AutoEvaluation | null = null;

	// datetime-local format
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
			loadData();
			loadChartData();
		}
	};

	const getCustomDateLabel = () => {
		if (dateRange === 'custom' && customDateLabel) {
			return customDateLabel;
		}
		return '';
	};

	// Initialize date range
	setDateRange('7d');

	// Toggle functions
	const toggleModel = (id: string) => {
		if (selectedModels.includes(id)) {
			selectedModels = selectedModels.filter((m) => m !== id);
		} else {
			selectedModels = [...selectedModels, id];
		}
		tick().then(() => renderChart());
	};

	const toggleType = (id: string) => {
		if (selectedTypes.includes(id)) {
			selectedTypes = selectedTypes.filter((t) => t !== id);
		} else {
			selectedTypes = [...selectedTypes, id];
		}
		tick().then(() => renderChart());
	};

	const toggleStatus = (id: string) => {
		if (selectedStatuses.includes(id)) {
			selectedStatuses = selectedStatuses.filter((s) => s !== id);
		} else {
			selectedStatuses = [...selectedStatuses, id];
		}
	};

	const toggleAllModels = () => {
		if (selectedModels.length === availableModels.length) {
			selectedModels = [];
		} else {
			selectedModels = availableModels.map((m) => m.id);
		}
		tick().then(() => renderChart());
	};

	const toggleAllTypes = () => {
		if (selectedTypes.length === evaluationTypes.length) {
			selectedTypes = [];
		} else {
			selectedTypes = evaluationTypes.map((t) => t.id);
		}
		tick().then(() => renderChart());
	};

	const toggleAllStatuses = () => {
		if (selectedStatuses.length === statusOptions.length) {
			selectedStatuses = [];
		} else {
			selectedStatuses = statusOptions.map((s) => s.id);
		}
	};

	// Label functions
	const getModelFilterLabel = () => {
		if (selectedModels.length === 0 || selectedModels.length === availableModels.length) {
			return $i18n.t('All Models');
		}
		if (selectedModels.length === 1) {
			const model = availableModels.find((m) => m.id === selectedModels[0]);
			return model?.name || selectedModels[0];
		}
		return `${selectedModels.length} ${$i18n.t('selected')}`;
	};

	const getTypeFilterLabel = () => {
		if (selectedTypes.length === 0 || selectedTypes.length === evaluationTypes.length) {
			return $i18n.t('All Types');
		}
		if (selectedTypes.length === 1) {
			const type = evaluationTypes.find((t) => t.id === selectedTypes[0]);
			return type ? $i18n.t(type.name) : selectedTypes[0];
		}
		return `${selectedTypes.length} ${$i18n.t('selected')}`;
	};

	const getStatusFilterLabel = () => {
		if (selectedStatuses.length === 0 || selectedStatuses.length === statusOptions.length) {
			return $i18n.t('All Status');
		}
		if (selectedStatuses.length === 1) {
			const status = statusOptions.find((s) => s.id === selectedStatuses[0]);
			return status ? $i18n.t(status.name) : selectedStatuses[0];
		}
		return `${selectedStatuses.length} ${$i18n.t('selected')}`;
	};

	async function loadData() {
		const filters: AutoEvaluationFilter = {
			page,
			limit
		};

		// Apply multi-select filters (only if not all selected)
		if (selectedModels.length > 0 && selectedModels.length < availableModels.length) {
			filters.model_id = selectedModels[0]; // API supports single for now
		}
		if (selectedTypes.length > 0 && selectedTypes.length < evaluationTypes.length) {
			filters.evaluation_type = selectedTypes[0];
		}
		if (selectedStatuses.length > 0 && selectedStatuses.length < statusOptions.length) {
			filters.status = selectedStatuses[0];
		}
		if (fromDate) filters.date_from = fromDate;
		if (toDate) filters.date_to = toDate;

		try {
			const response = await getAutoEvaluations(localStorage.token, filters);
			autoEvaluations = response.items;
			total = response.total;
		} catch (err) {
			toast.error(err);
		}
	}

	async function loadStats() {
		try {
			stats = await getAutoEvaluationStats(localStorage.token);
		} catch (err) {
			console.error('Failed to load stats:', err);
		}
	}

	function detectGranularity(): TimeGranularity {
		if (!fromDate || !toDate) return 'month';
		const diffDays = (toDate - fromDate) / 86400;
		if (diffDays <= 1) return 'hour';
		if (diffDays <= 30) return 'day';
		if (diffDays <= 90) return 'week';
		return 'month';
	}

	function getBucketKey(timestamp: number, granularity: TimeGranularity): string {
		const d = new Date(timestamp * 1000);
		const pad = (n: number) => n.toString().padStart(2, '0');
		switch (granularity) {
			case 'hour':
				return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:00`;
			case 'day':
				return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
			case 'week': {
				const monday = new Date(d);
				const day = monday.getDay();
				monday.setDate(monday.getDate() - day + (day === 0 ? -6 : 1));
				return `${monday.getFullYear()}-${pad(monday.getMonth() + 1)}-${pad(monday.getDate())}`;
			}
			case 'month':
				return `${d.getFullYear()}-${pad(d.getMonth() + 1)}`;
		}
	}

	async function loadChartData() {
		const filters: AutoEvaluationFilter = {
			status: 'completed',
			limit: 100,
			sort_by: 'created_at',
			order: 'asc'
		};
		if (fromDate) filters.date_from = fromDate;
		if (toDate) filters.date_to = toDate;
		if (selectedModels.length > 0 && selectedModels.length < availableModels.length) {
			filters.model_id = selectedModels[0];
		}
		if (selectedTypes.length > 0 && selectedTypes.length < evaluationTypes.length) {
			filters.evaluation_type = selectedTypes[0];
		}

		let allItems: AutoEvaluation[] = [];
		let currentPage = 1;
		try {
			while (true) {
				filters.page = currentPage;
				const response = await getAutoEvaluations(localStorage.token, filters);
				allItems = [...allItems, ...response.items];
				if (allItems.length >= response.total || response.items.length === 0) break;
				currentPage++;
				if (currentPage > 10) break;
			}
			chartData = allItems;
			if (chartGranularityAuto) {
				chartGranularity = detectGranularity();
			}
			await tick();
			renderChart();
		} catch (err) {
			console.error('Failed to load chart data:', err);
		}
	}

	function renderChart() {
		if (!Plotly || !scoreChartEl || chartData.length === 0) return;

		const allTypesSelected =
			selectedTypes.length === 0 || selectedTypes.length === evaluationTypes.length;

		let filtered = chartData;
		if (!allTypesSelected) {
			filtered = chartData.filter((e) => selectedTypes.includes(e.evaluation_type));
		}

		const allModelsSelected =
			selectedModels.length === 0 || selectedModels.length === availableModels.length;
		if (!allModelsSelected) {
			filtered = filtered.filter((e) => selectedModels.includes(e.model_id));
		}

		const granularity = chartGranularity;

		// Build trace key → bucket → scores
		// trace key: model (allTypes) or model+type (specific types)
		const bucketMap: Record<string, Record<string, number[]>> = {};

		for (const e of filtered) {
			if (e.score == null) continue;
			const modelName =
				availableModels.find((m) => m.id === e.model_id)?.name || e.model_id;
			let traceKey: string;
			if (allTypesSelected) {
				traceKey = modelName;
			} else {
				const typeName =
					evaluationTypes.find((t) => t.id === e.evaluation_type)?.name ||
					e.evaluation_type;
				traceKey = `${modelName} - ${typeName}`;
			}
			const bucket = getBucketKey(e.created_at, granularity);
			if (!bucketMap[traceKey]) bucketMap[traceKey] = {};
			if (!bucketMap[traceKey][bucket]) bucketMap[traceKey][bucket] = [];
			bucketMap[traceKey][bucket].push(e.score);
		}

		// Convert bucketMap → sorted traces
		const traces: Record<string, { x: string[]; y: number[] }> = {};
		for (const [traceKey, buckets] of Object.entries(bucketMap)) {
			const sortedKeys = Object.keys(buckets).sort();
			traces[traceKey] = {
				x: sortedKeys,
				y: sortedKeys.map((k) => {
					const scores = buckets[k];
					return scores.reduce((a, b) => a + b, 0) / scores.length;
				})
			};
		}

		const colors = [
			'#3b82f6',
			'#10b981',
			'#f59e0b',
			'#ef4444',
			'#8b5cf6',
			'#ec4899',
			'#06b6d4',
			'#84cc16'
		];
		const plotData = Object.entries(traces).map(([name, data], i) => ({
			x: data.x,
			y: data.y,
			type: 'scatter',
			mode: 'lines+markers',
			name,
			line: { color: colors[i % colors.length], width: 2 },
			marker: { size: 5 }
		}));

		const xaxisConfig: Record<string, any> = { showgrid: false };
		if (granularity === 'hour') {
			xaxisConfig.tickformat = '%m/%d %H:%M';
		} else if (granularity === 'day') {
			xaxisConfig.tickformat = '%m/%d';
		} else if (granularity === 'week') {
			xaxisConfig.tickformat = '%m/%d';
			xaxisConfig.dtick = 7 * 86400000;
		} else {
			xaxisConfig.tickformat = '%Y-%m';
		}

		Plotly.newPlot(
			scoreChartEl,
			plotData,
			{
				paper_bgcolor: 'rgba(0,0,0,0)',
				plot_bgcolor: 'rgba(0,0,0,0)',
				font: {
					color: '#6b7280',
					family: PLOTLY_FONT_FAMILY
				},
				margin: { t: 20, r: 20, b: 40, l: 50 },
				xaxis: xaxisConfig,
				yaxis: {
					showgrid: true,
					gridcolor: 'rgba(107, 114, 128, 0.1)',
					range: [0, 1.05],
					tickformat: '.0%'
				},
				legend: { orientation: 'h', y: -0.15 },
				showlegend: true
			},
			{ responsive: true, displayModeBar: false }
		);
	}

	async function handleDelete(id: string) {
		if (!confirm($i18n.t('Are you sure you want to delete this evaluation?'))) return;

		try {
			await deleteAutoEvaluation(localStorage.token, id);
			toast.success($i18n.t('Evaluation deleted'));
			await Promise.all([loadData(), loadStats(), loadChartData()]);
		} catch (err) {
			toast.error(err);
		}
	}

	async function handleExport(format: 'json' | 'csv') {
		try {
			const data = await exportAutoEvaluations(localStorage.token, format);
			if (format === 'csv') {
				const blob = new Blob([data], { type: 'text/csv' });
				saveAs(blob, `auto-evaluations-export-${Date.now()}.csv`);
			} else {
				const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
				saveAs(blob, `auto-evaluations-export-${Date.now()}.json`);
			}
			toast.success($i18n.t('Export completed'));
		} catch (err) {
			toast.error(err);
		}
	}

	function openDetail(evaluation: AutoEvaluation) {
		selectedEvaluation = evaluation;
		showDetail = true;
	}

	function getStatusBadgeType(status: string): 'success' | 'warning' | 'error' | 'info' | 'muted' {
		switch (status) {
			case 'completed':
				return 'success';
			case 'pending':
				return 'warning';
			case 'failed':
				return 'error';
			default:
				return 'muted';
		}
	}

	function formatScore(score: number | undefined): string {
		if (score === undefined || score === null) return '-';
		return (score * 100).toFixed(1) + '%';
	}

	function getScoreColor(score: number | undefined): string {
		if (score === undefined || score === null) return 'text-gray-500';
		if (score >= 0.8) return 'text-green-600 dark:text-green-400';
		if (score >= 0.5) return 'text-yellow-600 dark:text-yellow-400';
		return 'text-red-600 dark:text-red-400';
	}

	$: if (page) {
		loadData();
	}

	onMount(async () => {
		// Build available models list
		availableModels = $models
			.filter((m) => !(m?.arena ?? false))
			.map((m) => ({ id: m.id, name: m.name || m.id }));

		// Initialize all selected
		selectedModels = availableModels.map((m) => m.id);
		selectedTypes = evaluationTypes.map((t) => t.id);
		selectedStatuses = statusOptions.map((s) => s.id);

		const plotlyModule = await import('plotly.js-dist-min');
		Plotly = plotlyModule.default;

		await Promise.all([loadData(), loadStats(), loadChartData()]);
		loaded = true;
		await tick();
		renderChart();
	});

	onDestroy(() => {
		if (Plotly && scoreChartEl) Plotly.purge(scoreChartEl);
	});
</script>

{#if showDetail && selectedEvaluation}
	<AutoResultDetail
		evaluation={selectedEvaluation}
		on:close={() => {
			showDetail = false;
			selectedEvaluation = null;
		}}
	/>
{/if}

{#if loaded}
	<!-- Header -->
	<div class="mt-0.5 mb-2 flex flex-col gap-2">
		<div class="flex items-center justify-between">
			<div class="flex items-center text-lg font-bold px-0.5">
				{$i18n.t('Evaluation Results')}
				<div class="flex self-center w-[1px] h-6 mx-2.5 bg-gray-50 dark:bg-gray-850" />
				<span class="text-lg font-medium text-gray-500 dark:text-gray-300">{total}</span>
			</div>
			<div class="flex gap-1">
				<Tooltip content={$i18n.t('Export as JSON')}>
					<button
						class="p-2 rounded-xl hover:bg-gray-100 dark:hover:bg-gray-850 transition"
						on:click={() => handleExport('json')}
					>
						<ArrowDownTray className="size-4" />
					</button>
				</Tooltip>
				<Tooltip content={$i18n.t('Export as CSV')}>
					<button
						class="p-2 rounded-xl hover:bg-gray-100 dark:hover:bg-gray-850 transition text-xs font-medium"
						on:click={() => handleExport('csv')}
					>
						CSV
					</button>
				</Tooltip>
			</div>
		</div>

		<div class="flex gap-1.5 flex-wrap items-center">
			<!-- Custom Date Range Display -->
			{#if dateRange === 'custom' && customDateLabel && !showCustomDateModal}
				<div class="flex items-center gap-1 px-2.5 py-1 text-sm bg-gray-100 dark:bg-gray-850 text-gray-600 dark:text-gray-400 rounded-lg">
					<span>{getCustomDateLabel()}</span>
					<button
						class="ml-1 hover:text-gray-900 dark:hover:text-gray-100"
						on:click={() => {
							dateRange = '7d';
							setDateRange('7d');
							loadData();
							loadChartData();
						}}
					>
						<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor" class="size-3.5">
							<path d="M5.28 4.22a.75.75 0 0 0-1.06 1.06L6.94 8l-2.72 2.72a.75.75 0 1 0 1.06 1.06L8 9.06l2.72 2.72a.75.75 0 1 0 1.06-1.06L9.06 8l2.72-2.72a.75.75 0 0 0-1.06-1.06L8 6.94 5.28 4.22Z" />
						</svg>
					</button>
				</div>
			{/if}

			<!-- Date Range Filter -->
			<select
				bind:value={dateRange}
				on:change={() => {
					setDateRange(dateRange);
					if (dateRange !== 'custom') {
						loadData();
						loadChartData();
					}
				}}
				class="px-3 pr-7 py-1.5 min-w-[120px] text-sm bg-gray-50 dark:bg-gray-950 rounded-lg outline-none cursor-pointer"
			>
				<option value="1d">{$i18n.t('Last 1 Day')}</option>
				<option value="7d">{$i18n.t('Last 7 Days')}</option>
				<option value="30d">{$i18n.t('Last 30 Days')}</option>
				<option value="all">{$i18n.t('All Time')}</option>
				<option value="custom">{$i18n.t('Custom Range')}</option>
			</select>

			<!-- Model Filter (Multi-select) -->
			<DropdownMenu.Root bind:open={showModelDropdown}>
				<DropdownMenu.Trigger>
					<button
						class="flex items-center gap-2 px-3 py-1.5 min-w-[140px] text-sm bg-gray-50 dark:bg-gray-950 rounded-lg outline-none cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-900 transition"
					>
						<span class="flex-1 text-left truncate">{getModelFilterLabel()}</span>
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
						<div class="size-4 flex items-center justify-center rounded border {selectedModels.length === availableModels.length ? 'bg-black dark:bg-white border-black dark:border-white' : 'border-gray-300 dark:border-gray-600'}">
							{#if selectedModels.length === availableModels.length}
								<Check className="size-3 text-white dark:text-black" />
							{/if}
						</div>
						<span class="font-medium">{$i18n.t('Select All')}</span>
					</button>

					<div class="h-px bg-gray-100 dark:bg-gray-800 my-1"></div>

					{#each availableModels as model}
						<button
							class="flex w-full items-center gap-2 px-3 py-2 text-sm rounded-md cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-850 transition"
							on:click|stopPropagation={() => toggleModel(model.id)}
						>
							<div class="size-4 flex items-center justify-center rounded border {selectedModels.includes(model.id) ? 'bg-black dark:bg-white border-black dark:border-white' : 'border-gray-300 dark:border-gray-600'}">
								{#if selectedModels.includes(model.id)}
									<Check className="size-3 text-white dark:text-black" />
								{/if}
							</div>
							<span class="truncate">{model.name}</span>
						</button>
					{/each}
				</DropdownMenu.Content>
			</DropdownMenu.Root>

			<!-- Type Filter (Multi-select) -->
			<DropdownMenu.Root bind:open={showTypeDropdown}>
				<DropdownMenu.Trigger>
					<button
						class="flex items-center gap-2 px-3 py-1.5 min-w-[130px] text-sm bg-gray-50 dark:bg-gray-950 rounded-lg outline-none cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-900 transition"
					>
						<span class="flex-1 text-left truncate">{getTypeFilterLabel()}</span>
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
						on:click|stopPropagation={() => toggleAllTypes()}
					>
						<div class="size-4 flex items-center justify-center rounded border {selectedTypes.length === evaluationTypes.length ? 'bg-black dark:bg-white border-black dark:border-white' : 'border-gray-300 dark:border-gray-600'}">
							{#if selectedTypes.length === evaluationTypes.length}
								<Check className="size-3 text-white dark:text-black" />
							{/if}
						</div>
						<span class="font-medium">{$i18n.t('Select All')}</span>
					</button>

					<div class="h-px bg-gray-100 dark:bg-gray-800 my-1"></div>

					{#each evaluationTypes as type}
						<button
							class="flex w-full items-center gap-2 px-3 py-2 text-sm rounded-md cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-850 transition"
							on:click|stopPropagation={() => toggleType(type.id)}
						>
							<div class="size-4 flex items-center justify-center rounded border {selectedTypes.includes(type.id) ? 'bg-black dark:bg-white border-black dark:border-white' : 'border-gray-300 dark:border-gray-600'}">
								{#if selectedTypes.includes(type.id)}
									<Check className="size-3 text-white dark:text-black" />
								{/if}
							</div>
							<span>{$i18n.t(type.name)}</span>
						</button>
					{/each}
				</DropdownMenu.Content>
			</DropdownMenu.Root>

			<!-- Status Filter (Multi-select) -->
			<DropdownMenu.Root bind:open={showStatusDropdown}>
				<DropdownMenu.Trigger>
					<button
						class="flex items-center gap-2 px-3 py-1.5 min-w-[120px] text-sm bg-gray-50 dark:bg-gray-950 rounded-lg outline-none cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-900 transition"
					>
						<span class="flex-1 text-left truncate">{getStatusFilterLabel()}</span>
						<ChevronDown className="size-4 flex-shrink-0" />
					</button>
				</DropdownMenu.Trigger>

				<DropdownMenu.Content
					class="w-40 max-h-72 overflow-y-auto rounded-lg p-1 border border-gray-100 dark:border-gray-850 bg-white dark:bg-gray-900 shadow-lg z-50"
					sideOffset={4}
					transition={flyAndScale}
				>
					<button
						class="flex w-full items-center gap-2 px-3 py-2 text-sm rounded-md cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-850 transition"
						on:click|stopPropagation={() => toggleAllStatuses()}
					>
						<div class="size-4 flex items-center justify-center rounded border {selectedStatuses.length === statusOptions.length ? 'bg-black dark:bg-white border-black dark:border-white' : 'border-gray-300 dark:border-gray-600'}">
							{#if selectedStatuses.length === statusOptions.length}
								<Check className="size-3 text-white dark:text-black" />
							{/if}
						</div>
						<span class="font-medium">{$i18n.t('Select All')}</span>
					</button>

					<div class="h-px bg-gray-100 dark:bg-gray-800 my-1"></div>

					{#each statusOptions as statusOpt}
						<button
							class="flex w-full items-center gap-2 px-3 py-2 text-sm rounded-md cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-850 transition"
							on:click|stopPropagation={() => toggleStatus(statusOpt.id)}
						>
							<div class="size-4 flex items-center justify-center rounded border {selectedStatuses.includes(statusOpt.id) ? 'bg-black dark:bg-white border-black dark:border-white' : 'border-gray-300 dark:border-gray-600'}">
								{#if selectedStatuses.includes(statusOpt.id)}
									<Check className="size-3 text-white dark:text-black" />
								{/if}
							</div>
							<span>{$i18n.t(statusOpt.name)}</span>
						</button>
					{/each}
				</DropdownMenu.Content>
			</DropdownMenu.Root>

			<!-- Refresh -->
			<button
				class="p-2 rounded-xl hover:bg-gray-100 dark:hover:bg-gray-900 transition"
				on:click={() => { loadData(); loadChartData(); }}
			>
				<ArrowPath className="size-5" />
			</button>
		</div>
	</div>

	<hr class="mb-3 border-gray-50 dark:border-gray-850" />

	<!-- Stats Summary -->
	{#if stats}
		<div class="flex gap-4 mb-4 flex-wrap">
			<div class="flex items-center gap-2 px-3 py-2 bg-gray-50 dark:bg-gray-950 rounded-lg">
				<span class="text-2xl font-bold text-gray-700 dark:text-gray-200">{stats.total_count}</span>
				<span class="text-xs text-gray-500 dark:text-gray-400">{$i18n.t('Total')}</span>
			</div>
			<div class="flex items-center gap-2 px-3 py-2 bg-green-50 dark:bg-green-900/20 rounded-lg">
				<span class="text-2xl font-bold text-green-600 dark:text-green-400">{stats.completed_count}</span>
				<span class="text-xs text-gray-500 dark:text-gray-400">{$i18n.t('Completed')}</span>
			</div>
			<div class="flex items-center gap-2 px-3 py-2 bg-yellow-50 dark:bg-yellow-900/20 rounded-lg">
				<span class="text-2xl font-bold text-yellow-600 dark:text-yellow-400">{stats.pending_count}</span>
				<span class="text-xs text-gray-500 dark:text-gray-400">{$i18n.t('Pending')}</span>
			</div>
			<div class="flex items-center gap-2 px-3 py-2 bg-blue-50 dark:bg-blue-900/20 rounded-lg">
				<span class="text-2xl font-bold text-blue-600 dark:text-blue-400">
					{stats.avg_score !== null && stats.avg_score !== undefined
						? formatScore(stats.avg_score)
						: '-'}
				</span>
				<span class="text-xs text-gray-500 dark:text-gray-400">{$i18n.t('Avg Score')}</span>
			</div>
		</div>
	{/if}

	<!-- Score Trend Chart -->
	<div class="mb-4 p-4 bg-white dark:bg-gray-900 rounded-lg border border-gray-100 dark:border-gray-850" class:hidden={chartData.length === 0}>
		<div class="flex items-center justify-between mb-2">
			<div class="text-sm font-medium text-gray-500 dark:text-gray-400">
				{$i18n.t('Score Trend')}
			</div>
			<div class="flex items-center gap-1">
				{#each granularityOptions as opt}
					<button
						class="px-2 py-0.5 text-xs rounded transition-colors
							{chartGranularity === opt.id
								? 'bg-blue-500 text-white'
								: 'text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800'}"
						on:click={() => {
							chartGranularity = opt.id;
							chartGranularityAuto = false;
							renderChart();
						}}
					>
						{$i18n.t(opt.label)}
					</button>
				{/each}
				<button
					class="px-2 py-0.5 text-xs rounded transition-colors
						{chartGranularityAuto
							? 'bg-blue-500 text-white'
							: 'text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800'}"
					on:click={() => {
						chartGranularityAuto = true;
						chartGranularity = detectGranularity();
						renderChart();
					}}
				>
					Auto
				</button>
			</div>
		</div>
		<div bind:this={scoreChartEl} class="h-64"></div>
	</div>

	<!-- Results Table -->
	<div class="scrollbar-hidden relative whitespace-nowrap overflow-x-auto max-w-full rounded-sm">
		{#if autoEvaluations.length === 0}
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
					{$i18n.t('No auto evaluations found')}
				</p>
			</div>
		{:else}
			<table
				class="w-full text-sm text-left text-gray-500 dark:text-gray-400 table-auto max-w-full rounded-sm"
			>
				<thead
					class="text-xs text-gray-700 uppercase bg-gray-50 dark:bg-gray-850 dark:text-gray-400"
				>
					<tr>
						<th scope="col" class="px-3 py-2">{$i18n.t('Model')}</th>
						<th scope="col" class="px-3 py-2">{$i18n.t('Type')}</th>
						<th scope="col" class="px-3 py-2 text-center">{$i18n.t('Score')}</th>
						<th scope="col" class="px-3 py-2">{$i18n.t('Status')}</th>
						<th scope="col" class="px-3 py-2 text-right">{$i18n.t('Created')}</th>
						<th scope="col" class="px-3 py-2 w-10"></th>
					</tr>
				</thead>
				<tbody>
					{#each autoEvaluations as evaluation (evaluation.id)}
						<tr
							class="bg-white dark:bg-gray-900 border-b border-gray-100 dark:border-gray-850 hover:bg-gray-50 dark:hover:bg-gray-850 cursor-pointer"
							on:click={() => openDetail(evaluation)}
						>
							<td class="px-3 py-2 font-medium text-gray-900 dark:text-white">
								<div class="max-w-[200px] truncate">
									{evaluation.model_id}
								</div>
							</td>
							<td class="px-3 py-2">
								<span
									class="px-2 py-0.5 text-xs rounded-full bg-gray-100 dark:bg-gray-800 capitalize"
								>
									{evaluation.evaluation_type}
								</span>
							</td>
							<td class="px-3 py-2 text-center font-semibold {getScoreColor(evaluation.score)}">
								{formatScore(evaluation.score)}
							</td>
							<td class="px-3 py-2">
								<Badge
									type={getStatusBadgeType(evaluation.status)}
									content={$i18n.t(evaluation.status.charAt(0).toUpperCase() + evaluation.status.slice(1))}
								/>
							</td>
							<td class="px-3 py-2 text-right text-xs">
								<Tooltip content={dayjs(evaluation.created_at * 1000).format('YYYY-MM-DD HH:mm:ss')}>
									{dayjs(evaluation.created_at * 1000).fromNow()}
								</Tooltip>
							</td>
							<td class="px-3 py-2 text-right">
								<button
									class="p-1 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-lg"
									on:click|stopPropagation={() => handleDelete(evaluation.id)}
								>
									<svg
										xmlns="http://www.w3.org/2000/svg"
										viewBox="0 0 20 20"
										fill="currentColor"
										class="size-4 text-gray-500 hover:text-red-500"
									>
										<path
											fill-rule="evenodd"
											d="M8.75 1A2.75 2.75 0 006 3.75v.443c-.795.077-1.584.176-2.365.298a.75.75 0 10.23 1.482l.149-.022.841 10.518A2.75 2.75 0 007.596 19h4.807a2.75 2.75 0 002.742-2.53l.841-10.519.149.023a.75.75 0 00.23-1.482A41.03 41.03 0 0014 4.193V3.75A2.75 2.75 0 0011.25 1h-2.5zM10 4c.84 0 1.673.025 2.5.075V3.75c0-.69-.56-1.25-1.25-1.25h-2.5c-.69 0-1.25.56-1.25 1.25v.325C8.327 4.025 9.16 4 10 4zM8.58 7.72a.75.75 0 00-1.5.06l.3 7.5a.75.75 0 101.5-.06l-.3-7.5zm4.34.06a.75.75 0 10-1.5-.06l-.3 7.5a.75.75 0 101.5.06l.3-7.5z"
											clip-rule="evenodd"
										/>
									</svg>
								</button>
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		{/if}
	</div>

	{#if total > limit}
		<div class="mt-4">
			<Pagination bind:page count={total} perPage={limit} />
		</div>
	{/if}
{:else}
	<div class="flex justify-center items-center py-8">
		<svg
			class="animate-spin size-6 text-gray-500"
			xmlns="http://www.w3.org/2000/svg"
			fill="none"
			viewBox="0 0 24 24"
		>
			<circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"
			></circle>
			<path
				class="opacity-75"
				fill="currentColor"
				d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
			></path>
		</svg>
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
				class="self-center"
				on:click={() => {
					showCustomDateModal = false;
					if (dateRange !== 'custom') {
						dateRange = '7d';
					}
				}}
			>
				<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-5 h-5">
					<path d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z" />
				</svg>
			</button>
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
				<button
					class="px-4 py-1.5 text-sm rounded-lg bg-gray-100 dark:bg-gray-850 hover:bg-gray-200 dark:hover:bg-gray-800 transition"
					on:click={() => {
						showCustomDateModal = false;
						if (dateRange !== 'custom') {
							dateRange = '7d';
						}
					}}
				>
					{$i18n.t('Cancel')}
				</button>
				<button
					class="px-4 py-1.5 text-sm rounded-lg bg-black text-white hover:bg-gray-800 dark:bg-white dark:text-black dark:hover:bg-gray-100 transition disabled:opacity-50"
					disabled={!customFromDate || !customToDate}
					on:click={applyCustomDateRange}
				>
					{$i18n.t('Apply')}
				</button>
			</div>
		</div>
	</div>
</Modal>

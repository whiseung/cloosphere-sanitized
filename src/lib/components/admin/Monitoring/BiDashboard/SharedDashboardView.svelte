<script lang="ts">
	import { getContext, onMount } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { goto } from '$app/navigation';
	import PanelCard from './PanelCard.svelte';
	import FilterBar from './FilterBar.svelte';
	import TimeRangePicker from './TimeRangePicker.svelte';
	import Badge from '$lib/components/common/Badge.svelte';
	import { executeSharedDashboardSql } from '$lib/apis/bi-dashboards';
	import type { BiDashboardDetail } from '$lib/apis/bi-dashboards';

	const i18n = getContext('i18n');

	export let dashboard: BiDashboardDetail;
	export let shareId: string;

	let filters: any[] = [];
	let filterVersion = 0;
	let timeRange = 'yesterday';
	let timeCustomFrom = '';
	let timeCustomTo = '';
	let gridEl: HTMLDivElement;

	// 공유 대시보드용 SQL executor
	function sharedSqlExecutor(token: string, data: any) {
		return executeSharedDashboardSql(token, shareId, data);
	}

	function handleTimeRangeChange(e: CustomEvent) {
		const { from_value, to_value } = e.detail;
		const idx = filters.findIndex((f: any) => f.id === '__time_range__');
		const timeFilter = { id: '__time_range__', type: 'date_range', field: '', from_value, to_value };
		if (idx >= 0) {
			filters[idx] = timeFilter;
		} else {
			filters = [...filters, timeFilter];
		}
		filters = filters;
		filterVersion++;
	}

	function handleFilterChange(e: CustomEvent) {
		const nonTime = e.detail.filters || [];
		const timeFilter = filters.find((f: any) => f.id === '__time_range__');
		filters = timeFilter ? [timeFilter, ...nonTime] : nonTime;
		filterVersion++;
	}
</script>

<div class="flex flex-col h-screen bg-white dark:bg-gray-950">
	<!-- Header -->
	<div class="flex items-center justify-between px-6 py-4 border-b border-gray-200 dark:border-gray-800">
		<div class="flex items-center gap-3 min-w-0">
			<button
				class="p-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 transition text-gray-500 dark:text-gray-400"
				on:click={() => goto('/')}
			>
				<svg xmlns="http://www.w3.org/2000/svg" class="size-5" viewBox="0 0 20 20" fill="currentColor">
					<path fill-rule="evenodd" d="M17 10a.75.75 0 01-.75.75H5.612l4.158 3.96a.75.75 0 11-1.04 1.08l-5.5-5.25a.75.75 0 010-1.08l5.5-5.25a.75.75 0 111.04 1.08L5.612 9.25H16.25A.75.75 0 0117 10z" clip-rule="evenodd" />
				</svg>
			</button>
			<h1 class="text-lg font-semibold dark:text-gray-100 truncate">{dashboard.name}</h1>
			<Badge status="info" size="sm">{$i18n.t('Shared')}</Badge>
		</div>
	</div>

	<!-- Content -->
	<div class="flex-1 overflow-y-auto px-6 py-4">
		<!-- Filters -->
		<div class="flex flex-wrap items-center gap-3 mb-4">
			<TimeRangePicker
				bind:selectedRange={timeRange}
				bind:customFrom={timeCustomFrom}
				bind:customTo={timeCustomTo}
				on:change={handleTimeRangeChange}
			/>
			<FilterBar
				filters={filters.filter((f) => f.id !== '__time_range__')}
				editMode={false}
				on:change={handleFilterChange}
			/>
		</div>

		<!-- Panel Grid -->
		{#if dashboard.panels.length === 0}
			<div class="flex flex-col items-center justify-center h-64 text-gray-400 dark:text-gray-500 gap-3">
				<p class="text-sm">{$i18n.t('No panels in this dashboard')}</p>
			</div>
		{:else}
			<div
				bind:this={gridEl}
				class="grid gap-4"
				style="grid-template-columns: repeat(12, 1fr); grid-auto-rows: 80px;"
			>
				{#each dashboard.panels as panel (panel.id)}
					{@const layout = panel.data?.layout || { x: 0, y: 0, w: 6, h: 4 }}
					<div
						id="panel-{panel.id}"
						style="grid-column: {layout.x + 1} / span {layout.w}; grid-row: {layout.y + 1} / span {layout.h};"
					>
						<PanelCard
							{panel}
							dashboardId={dashboard.id}
							editMode={false}
							{filters}
							{filterVersion}
							gridContainer={gridEl}
							sqlExecutor={sharedSqlExecutor}
						/>
					</div>
				{/each}
			</div>
		{/if}
	</div>
</div>

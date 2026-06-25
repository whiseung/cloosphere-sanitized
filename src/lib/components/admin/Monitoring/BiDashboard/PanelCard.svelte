<script lang="ts">
	import { toast } from 'svelte-sonner';
	import { createEventDispatcher, getContext, onMount } from 'svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import PanelChart from './PanelChart.svelte';
	import { executePanel, executeSql } from '$lib/apis/bi-dashboards';
	import type { BiPanel } from '$lib/apis/bi-dashboards';
	import { formatBackendError } from '$lib/utils/error';

	const i18n = getContext('i18n');
	const dispatch = createEventDispatcher();

	export let panel: BiPanel;
	export let dashboardId: string;
	export let editMode = false;
	export let filters: any[] = [];
	export let filterVersion = 0;
	export let gridContainer: HTMLDivElement | null = null;
	export let sqlExecutor: ((token: string, data: any) => Promise<any>) | null = null;

	let loading = false;
	let resultData: any = null;
	let resizing = false;

	const GAP = 16; // gap-4 = 16px
	const ROW_H = 80; // grid-auto-rows: 80px

	function getColWidth() {
		if (!gridContainer) return 80;
		return (gridContainer.clientWidth - GAP * 11) / 12;
	}

	function onMoveStart(e: MouseEvent) {
		if (!editMode || !gridContainer) return;
		e.preventDefault();
		const startX = e.clientX;
		const startY = e.clientY;
		const layout = panel.data?.layout || { x: 0, y: 0, w: 6, h: 4 };
		const startGridX = layout.x;
		const startGridY = layout.y;
		const colW = getColWidth();
		let newX = startGridX;
		let newY = startGridY;

		function onMouseMove(ev: MouseEvent) {
			const dx = ev.clientX - startX;
			const dy = ev.clientY - startY;
			newX = Math.max(0, Math.min(12 - layout.w, Math.round(startGridX + dx / (colW + GAP))));
			newY = Math.max(0, Math.round(startGridY + dy / (ROW_H + GAP)));
			const el = document.getElementById(`panel-${panel.id}`);
			if (el) {
				el.style.gridColumn = `${newX + 1} / span ${layout.w}`;
				el.style.gridRow = `${newY + 1} / span ${layout.h}`;
			}
		}

		function onMouseUp() {
			window.removeEventListener('mousemove', onMouseMove);
			window.removeEventListener('mouseup', onMouseUp);
			if (newX !== startGridX || newY !== startGridY) {
				dispatch('move', { panelId: panel.id, x: newX, y: newY });
			}
		}

		window.addEventListener('mousemove', onMouseMove);
		window.addEventListener('mouseup', onMouseUp);
	}

	function onResizeStart(e: MouseEvent) {
		if (!editMode) return;
		e.preventDefault();
		resizing = true;
		const startX = e.clientX;
		const startY = e.clientY;
		const layout = panel.data?.layout || { x: 0, y: 0, w: 6, h: 4 };
		const startW = layout.w;
		const startH = layout.h;
		const colW = getColWidth();

		function onMouseMove(ev: MouseEvent) {
			const dx = ev.clientX - startX;
			const dy = ev.clientY - startY;
			const newW = Math.max(1, Math.min(12, Math.round(startW + dx / (colW + GAP))));
			const newH = Math.max(1, Math.min(12, Math.round(startH + dy / (ROW_H + GAP))));
			// 실시간 미리보기: 현재 패널 DOM 크기 변경
			const el = document.getElementById(`panel-${panel.id}`);
			if (el) {
				el.style.gridColumn = `${layout.x + 1} / span ${newW}`;
				el.style.gridRow = `${layout.y + 1} / span ${newH}`;
			}
			// 임시 저장
			(onMouseMove as any)._newW = newW;
			(onMouseMove as any)._newH = newH;
		}

		function onMouseUp() {
			resizing = false;
			window.removeEventListener('mousemove', onMouseMove);
			window.removeEventListener('mouseup', onMouseUp);
			const newW = (onMouseMove as any)._newW || startW;
			const newH = (onMouseMove as any)._newH || startH;
			if (newW !== startW || newH !== startH) {
				dispatch('resize', { panelId: panel.id, w: newW, h: newH });
			}
		}

		window.addEventListener('mousemove', onMouseMove);
		window.addEventListener('mouseup', onMouseUp);
	}
	let lastFilterVersion = 0;

	const CHART_TYPE_ICONS: Record<string, { label: string; icon: string }> = {
		table: { label: 'Table', icon: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor"><path fill-rule="evenodd" d="M2 3.5A1.5 1.5 0 0 1 3.5 2h9A1.5 1.5 0 0 1 14 3.5v9a1.5 1.5 0 0 1-1.5 1.5h-9A1.5 1.5 0 0 1 2 12.5v-9ZM3.5 3a.5.5 0 0 0-.5.5V6h4V3H3.5ZM3 7v2.5h4V7H3Zm0 3.5v2h.5a.5.5 0 0 0 .5-.5v-1.5H3ZM8 13h4.5a.5.5 0 0 0 .5-.5V10.5H8V13ZM13 9.5V7H8v2.5h5ZM8 6h5V3.5a.5.5 0 0 0-.5-.5H8v3Z" clip-rule="evenodd"/></svg>' },
		bar: { label: 'Bar', icon: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor"><path d="M2 13.5V2h1v11h11v1H2.5a.5.5 0 0 1-.5-.5Z"/><path d="M4 6h2v6H4V6Zm3-3h2v9H7V3Zm3 5h2v4h-2V8Z"/></svg>' },
		line: { label: 'Line', icon: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor"><path d="M2 13.5V2h1v11h11v1H2.5a.5.5 0 0 1-.5-.5Z"/><path fill-rule="evenodd" d="M13.5 3.5 9.25 8l-2.5-2L4 9v1.2l3-3.2 2.5 2L14 4.7V3.5h-.5Z" clip-rule="evenodd"/></svg>' },
		pie: { label: 'Pie', icon: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor"><path d="M7.5 1.018v6.482h6.482A6.5 6.5 0 1 1 7.5 1.018Z"/><path d="M8.5 1.018A6.502 6.502 0 0 1 14.982 7.5H8.5V1.018Z"/></svg>' },
		area: { label: 'Area', icon: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor"><path d="M2 13.5V2h1v11h11v1H2.5a.5.5 0 0 1-.5-.5Z"/><path d="M4 12l3-4 2.5 2L14 5v7H4Z" opacity=".4"/><path fill-rule="evenodd" d="M13.5 3.5 9.25 8l-2.5-2L4 9v1.2l3-3.2 2.5 2L14 4.7V3.5h-.5Z" clip-rule="evenodd"/></svg>' },
		scatter: { label: 'Scatter', icon: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor"><path d="M2 13.5V2h1v11h11v1H2.5a.5.5 0 0 1-.5-.5Z"/><circle cx="5" cy="10" r="1.2"/><circle cx="7" cy="7" r="1.2"/><circle cx="9.5" cy="9" r="1.2"/><circle cx="10" cy="5" r="1.2"/><circle cx="12.5" cy="4" r="1.2"/></svg>' },
		histogram: { label: 'Histogram', icon: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor"><path d="M2 13.5V2h1v11h11v1H2.5a.5.5 0 0 1-.5-.5Z"/><path d="M4 8h1.5v4H4V8Zm2.5-1H8v5H6.5V7ZM9 5h1.5v7H9V5Zm2.5 3H13v4h-1.5V8Z"/></svg>' },
		heatmap: { label: 'Heatmap', icon: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor"><rect x="2" y="2" width="3.5" height="3.5" rx=".5" opacity=".3"/><rect x="6.25" y="2" width="3.5" height="3.5" rx=".5" opacity=".6"/><rect x="10.5" y="2" width="3.5" height="3.5" rx=".5" opacity=".9"/><rect x="2" y="6.25" width="3.5" height="3.5" rx=".5" opacity=".7"/><rect x="6.25" y="6.25" width="3.5" height="3.5" rx=".5" opacity=".4"/><rect x="10.5" y="6.25" width="3.5" height="3.5" rx=".5" opacity=".8"/><rect x="2" y="10.5" width="3.5" height="3.5" rx=".5" opacity=".5"/><rect x="6.25" y="10.5" width="3.5" height="3.5" rx=".5" opacity=".9"/><rect x="10.5" y="10.5" width="3.5" height="3.5" rx=".5" opacity=".2"/></svg>' },
		grouped_bar: { label: 'Grouped Bar', icon: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor"><path d="M2 13.5V2h1v11h11v1H2.5a.5.5 0 0 1-.5-.5Z"/><path d="M4 7h1.2v5H4V7Zm1.8-2H7v7H5.8V5ZM8.5 8h1.2v4H8.5V8Zm1.8-2H11.5v6h-1.2V6Z"/></svg>' },
		card: { label: 'Card', icon: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor"><path fill-rule="evenodd" d="M2 3.5A1.5 1.5 0 0 1 3.5 2h9A1.5 1.5 0 0 1 14 3.5v9a1.5 1.5 0 0 1-1.5 1.5h-9A1.5 1.5 0 0 1 2 12.5v-9ZM5 8.5a.5.5 0 0 1 .5-.5h5a.5.5 0 0 1 0 1h-5a.5.5 0 0 1-.5-.5Zm1.5-3a1.5 1.5 0 1 0 3 0 1.5 1.5 0 0 0-3 0Z" clip-rule="evenodd"/></svg>' },
	};

	$: panelData = panel.data || {};
	let chartType = '';
	$: if (panelData.chart_type) chartType = panelData.chart_type;
	$: panelShowTitle = panelData.show_title !== false;
	$: titlePosition = panelData.title_position || 'inside';
	$: isCardManual = chartType === 'card' && panelData.card_source === 'manual';

	// 활성 필터 라벨
	$: activeFilterLabels = (() => {
		const labels: string[] = [];
		const timeFilter = filters.find((f: any) => f.id === '__time_range__');
		if (timeFilter && panelData.use_time_filter && panelData.sql_template && (timeFilter.from_value || timeFilter.to_value)) {
			const col = panelData.date_column || 'date';
			labels.push(`$${col}: ${timeFilter.from_value || '*'} ~ ${timeFilter.to_value || '*'}`);
		}
		for (const f of filters.filter((f: any) => f.id !== '__time_range__' && (f.value || f.from_value || f.to_value))) {
			if (f.type === 'date_range') {
				labels.push(`$${f.field}: ${f.from_value || ''} ~ ${f.to_value || ''}`);
			} else {
				labels.push(`$${f.field}: ${f.value}`);
			}
		}
		return labels;
	})();

	function setChartType(type: string) {
		chartType = type;
		// 백엔드에 저장
		dispatch('chartTypeChange', { panelId: panel.id, chartType: type });
	}

	// SQL 없는 패널 (수동 카드): cached_result 바로 표시
	$: if (!panelData.sql && panelData.cached_result) {
		resultData = panelData.cached_result;
		loading = false;
	}

	// cached_result가 없는 패널: 마운트 시 SQL 실행
	onMount(() => {
		if (panelData.sql && !panelData.cached_result) {
			refresh();
		}
	});

	// 필터 변경 감지 → SQL 재실행
	$: if (panelData.sql && filterVersion !== lastFilterVersion) {
		lastFilterVersion = filterVersion;
		if (filterVersion > 0) {
			refreshWithFilters();
		} else {
			refresh();
		}
	}

	async function refresh() {
		if (!panelData.sql) return;
		loading = true;
		try {
			resultData = await executePanel(localStorage.token, dashboardId, panel.id);
		} catch (e: any) {
			toast.error(formatBackendError(e, $i18n) || $i18n.t('Failed to execute panel'));
		} finally {
			loading = false;
		}
	}

	async function refreshWithFilters() {
		if (!panelData.sql) return;

		const timeFilter = filters.find((f: any) => f.id === '__time_range__');
		const appliedFilters: any[] = [];
		let useTemplate = false;
		let fromValue = '';
		let toValue = '';

		// 기간 필터: $st/$ed 치환은 백엔드에서 DB 타입별로 처리
		if (timeFilter && panelData.use_time_filter && (timeFilter.from_value || timeFilter.to_value)) {
			if (panelData.sql_template && (panelData.sql_template.includes('$st') || panelData.sql_template.includes('$ed'))) {
				useTemplate = true;
				fromValue = timeFilter.from_value || '';
				toValue = timeFilter.to_value || '';
			}
		}

		// 일반 필터
		for (const f of filters) {
			if (f.id === '__time_range__') continue;
			if (f.value || f.from_value || f.to_value) {
				appliedFilters.push(f);
			}
		}

		if (!useTemplate && appliedFilters.length === 0) {
			await refresh();
			return;
		}

		loading = true;
		try {
			const executor = sqlExecutor || executeSql;
			resultData = await executor(localStorage.token, {
				dbsphere_id: panel.dbsphere_id,
				sql: panelData.sql,
				...(useTemplate ? { sql_template: panelData.sql_template, from_value: fromValue, to_value: toValue } : {}),
				filters: appliedFilters.length > 0 ? appliedFilters : undefined
			});
		} catch (e: any) {
			toast.error(formatBackendError(e, $i18n) || $i18n.t('Failed to refresh with filters'));
		} finally {
			loading = false;
		}
	}
</script>

<div
	class="relative flex flex-col rounded-xl overflow-hidden h-full {chartType === 'card' && panelData.card_bg_color ? '' : 'bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700'}"
	style={chartType === 'card' && panelData.card_bg_color ? `background-color: ${panelData.card_bg_color};` : ''}
>
	<!-- Header: 편집 모드 또는 제목 표시(헤더) 시에만 표시 -->
	{#if editMode || (panelShowTitle && titlePosition === 'top')}
	<!-- svelte-ignore a11y-no-static-element-interactions -->
	<div
		class="flex items-center justify-between px-3 py-2 {chartType === 'card' && panelData.card_bg_color ? '' : 'border-b border-gray-100 dark:border-gray-800'} {editMode ? 'cursor-grab active:cursor-grabbing' : ''}"
		on:mousedown={editMode ? onMoveStart : undefined}
	>
		<div class="flex items-center gap-2 min-w-0">
			{#if editMode}
				<svg xmlns="http://www.w3.org/2000/svg" class="size-3.5 shrink-0 text-gray-400" viewBox="0 0 20 20" fill="currentColor">
					<path fill-rule="evenodd" d="M2 4.75A.75.75 0 012.75 4h14.5a.75.75 0 010 1.5H2.75A.75.75 0 012 4.75zm0 5A.75.75 0 012.75 9h14.5a.75.75 0 010 1.5H2.75A.75.75 0 012 9.75zm0 5a.75.75 0 01.75-.75h14.5a.75.75 0 010 1.5H2.75a.75.75 0 01-.75-.75z" clip-rule="evenodd" />
				</svg>
			{/if}
			{#if panelShowTitle && titlePosition === 'top'}
				<span class="text-sm font-medium truncate {chartType === 'card' && panelData.card_bg_color ? 'text-white' : 'dark:text-gray-200'}">{panel.name}</span>
			{:else if editMode}
				<span class="text-sm font-medium truncate text-gray-300 dark:text-gray-600">{panel.name}</span>
			{/if}
			{#each activeFilterLabels as label}
				<span class="text-[10px] px-1.5 py-0.5 rounded bg-blue-50 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400 whitespace-nowrap">
					{label}
				</span>
			{/each}
		</div>
		{#if editMode}
			<div class="flex items-center gap-0.5" on:mousedown|stopPropagation>
				{#each Object.entries(CHART_TYPE_ICONS) as [typeKey, meta]}
					<button
						class="p-1 rounded transition-colors {chartType === typeKey
							? 'bg-gray-800 text-white dark:bg-white dark:text-gray-900'
							: 'text-gray-400 hover:text-gray-700 hover:bg-gray-100 dark:text-gray-500 dark:hover:text-gray-200 dark:hover:bg-gray-800'}"
						on:click={() => setChartType(typeKey)}
						title={meta.label}
					>
						<span class="block size-3.5">{@html meta.icon}</span>
					</button>
				{/each}
			</div>
		{/if}
		<div class="flex items-center gap-1 shrink-0">
			<!-- Refresh -->
			<button
				class="p-1 rounded hover:bg-gray-100 dark:hover:bg-gray-800 transition text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
				on:click={refreshWithFilters}
				title={$i18n.t('Refresh')}
			>
				<svg xmlns="http://www.w3.org/2000/svg" class="size-3.5" viewBox="0 0 20 20" fill="currentColor">
					<path fill-rule="evenodd" d="M15.312 11.424a5.5 5.5 0 01-9.201 2.466l-.312-.311h2.433a.75.75 0 000-1.5H4.598a.75.75 0 00-.75.75v3.634a.75.75 0 001.5 0v-2.033l.312.311a7 7 0 0011.712-3.138.75.75 0 00-1.449-.389zm-11.624-2.848a.75.75 0 01.389-1.449 5.5 5.5 0 019.201-2.466l.312.311H11.157a.75.75 0 000 1.5h3.634a.75.75 0 00.75-.75V2.088a.75.75 0 00-1.5 0v2.033l-.312-.311A7 7 0 002.017 6.938a.75.75 0 001.449.389z" clip-rule="evenodd" />
				</svg>
			</button>
			{#if editMode}
				<!-- Edit -->
				<button
					class="p-1 rounded hover:bg-gray-100 dark:hover:bg-gray-800 transition text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
					on:click={() => dispatch('edit', panel)}
					title={$i18n.t('Edit')}
				>
					<svg xmlns="http://www.w3.org/2000/svg" class="size-3.5" viewBox="0 0 20 20" fill="currentColor">
						<path d="m5.433 13.917 1.262-3.155A4 4 0 0 1 7.58 9.42l6.92-6.918a2.121 2.121 0 0 1 3 3l-6.92 6.918c-.383.383-.84.685-1.343.886l-3.154 1.262a.5.5 0 0 1-.65-.65Z" />
						<path d="M3.5 5.75c0-.69.56-1.25 1.25-1.25H10A.75.75 0 0 0 10 3H4.75A2.75 2.75 0 0 0 2 5.75v9.5A2.75 2.75 0 0 0 4.75 18h9.5A2.75 2.75 0 0 0 17 15.25V10a.75.75 0 0 0-1.5 0v5.25c0 .69-.56 1.25-1.25 1.25h-9.5c-.69 0-1.25-.56-1.25-1.25v-9.5Z" />
					</svg>
				</button>
				<!-- Delete -->
				<button
					class="p-1 rounded hover:bg-red-50 dark:hover:bg-red-900/20 transition text-gray-400 hover:text-red-500"
					on:click={() => dispatch('delete', panel)}
					title={$i18n.t('Delete')}
				>
					<svg xmlns="http://www.w3.org/2000/svg" class="size-3.5" viewBox="0 0 20 20" fill="currentColor">
						<path fill-rule="evenodd" d="M8.75 1A2.75 2.75 0 006 3.75v.443c-.795.077-1.584.176-2.365.298a.75.75 0 10.23 1.482l.149-.022.841 10.518A2.75 2.75 0 007.596 19h4.807a2.75 2.75 0 002.742-2.53l.841-10.519.149.023a.75.75 0 00.23-1.482A41.03 41.03 0 0014 4.193V3.75A2.75 2.75 0 0011.25 1h-2.5z" clip-rule="evenodd" />
					</svg>
				</button>
			{/if}
		</div>
	</div>
	{/if}

	<!-- Chart -->
	<div class="flex-1 p-2 min-h-0">
		{#if loading}
			<div class="flex items-center justify-center h-full">
				<Spinner className="size-6" />
			</div>
		{:else}
			<PanelChart
				data={resultData}
				{chartType}
				title={panelShowTitle && (titlePosition === 'inside-top' || titlePosition === 'inside-bottom' || titlePosition === 'left' || titlePosition === 'right') ? panel.name : ''}
				{titlePosition}
				cardBgColor={panelData.card_bg_color || ''}
			/>
		{/if}
	</div>

	<!-- Footer Title -->
	{#if panelShowTitle && titlePosition === 'bottom'}
		<div class="px-3 py-1 text-xs text-center text-gray-500 dark:text-gray-400 border-t border-gray-100 dark:border-gray-800">
			{panel.name}
		</div>
	{/if}

	<!-- Resize Handle -->
	{#if editMode}
		<!-- svelte-ignore a11y-no-static-element-interactions -->
		<div
			class="absolute bottom-0 right-0 w-4 h-4 cursor-nwse-resize z-10 flex items-end justify-end"
			on:mousedown={onResizeStart}
		>
			<svg class="size-3 text-gray-400" viewBox="0 0 6 6" fill="currentColor">
				<circle cx="5" cy="1" r="0.8" />
				<circle cx="5" cy="5" r="0.8" />
				<circle cx="1" cy="5" r="0.8" />
				<circle cx="3" cy="5" r="0.8" />
				<circle cx="5" cy="3" r="0.8" />
				<circle cx="3" cy="3" r="0.8" />
			</svg>
		</div>
	{/if}
</div>

<script lang="ts">
	import { onMount, onDestroy, tick } from 'svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import { PLOTLY_FONT_FAMILY } from '$lib/constants';

	export let data: { columns: string[]; data: Record<string, any>[]; row_count: number } | null =
		null;
	export let chartType: string = 'bar';
	export let title: string = '';
	export let titlePosition: string = 'inside-bottom';
	export let cardBgColor: string = '';

	let Plotly: any = null;
	let chartEl: HTMLDivElement;
	let wrapperEl: HTMLDivElement;
	let loading = true;

	// Plotly 기본 + 추가 색상 (다채로운 팔레트)
	const COLORS = [
		'#636EFA', '#EF553B', '#00CC96', '#AB63FA', '#FFA15A',
		'#19D3F3', '#FF6692', '#B6E880', '#FF97FF', '#FECB52',
		'#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd',
		'#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf'
	];

	let resizeObserver: ResizeObserver;

	onMount(async () => {
		const plotlyModule = await import('plotly.js-dist-min');
		Plotly = plotlyModule.default;
		loading = false;
		await tick(); // DOM이 업데이트되어 chartEl이 바인딩될 때까지 대기
		renderChart();

		// 컨테이너 크기 변경 시 차트 리사이즈 (또는 초기 렌더링)
		resizeObserver = new ResizeObserver(() => {
			if (Plotly && chartEl && chartEl.offsetWidth > 0 && chartEl.offsetHeight > 0) {
				if (chartEl.data) {
					Plotly.Plots.resize(chartEl);
				} else {
					renderChart();
				}
			}
		});
		if (wrapperEl) resizeObserver.observe(wrapperEl);
	});

	onDestroy(() => {
		if (resizeObserver) resizeObserver.disconnect();
		if (Plotly && chartEl) {
			Plotly.purge(chartEl);
		}
	});

	// 카드 타입: 단일 값 표시
	$: cardValue = (() => {
		if (chartType !== 'card' || !data || data.data.length === 0) return null;
		const row = data.data[0];
		const col = data.columns[data.columns.length - 1]; // 마지막 컬럼 값
		const val = row[col];
		return { value: val, label: data.columns.length > 1 ? data.columns[0] + ': ' + row[data.columns[0]] : col };
	})();

	$: if (Plotly && data && chartEl && chartType && chartType !== 'card') {
		// DOM 레이아웃 완료 후 렌더링 (axis scaling 에러 방지)
		requestAnimationFrame(() => renderChart());
	}

	function renderChart() {
		if (!Plotly || !data || !chartEl || data.data.length === 0) return;
		// Plotly는 최소 plot area가 필요 (margin 제외 후 음수면 axis scaling 에러)
		if (chartEl.offsetWidth < 120 || chartEl.offsetHeight < 120) return;

		const columns = data.columns;
		const rows = data.data;

		// 컬럼 타입 추론
		const numericCols = columns.filter((col) => {
			// 첫 5행 샘플링하여 숫자 여부 판별
			const samples = rows.slice(0, 5).map((r) => r[col]).filter((v) => v !== null && v !== '');
			if (samples.length === 0) return false;
			const numCount = samples.filter((v) => typeof v === 'number').length;
			return numCount >= samples.length * 0.8;
		});

		const dateCols = columns.filter((col) => {
			if (numericCols.includes(col)) return false;
			const sample = String(rows[0]?.[col] || '');
			return /^\d{4}-\d{2}/.test(sample);
		});

		const categoricalCols = columns.filter(
			(col) => !numericCols.includes(col) && !dateCols.includes(col)
		);

		// 차트 타입에 따라 x축 선택
		let xCol: string;
		if (chartType === 'line' || chartType === 'area') {
			// 시계열: 날짜 컬럼 우선
			xCol = dateCols[0] || categoricalCols[0] || columns[0];
		} else if (chartType === 'bar' || chartType === 'pie' || chartType === 'grouped_bar') {
			// 카테고리: 비날짜 categorical 우선
			xCol = categoricalCols[0] || dateCols[0] || columns[0];
		} else {
			xCol = categoricalCols[0] || dateCols[0] || columns[0];
		}
		const yCols = numericCols.length > 0 ? numericCols : columns.filter((c) => c !== xCol);

		let traces: any[] = [];

		// x축 라벨 truncate (긴 UUID 등)
		const xValues = rows.map((r) => {
			const v = String(r[xCol] ?? '');
			return v.length > 20 ? v.slice(0, 17) + '...' : v;
		});

		// x축 라벨이 길면 하단 여백 늘리고 기울이기
		const maxLabelLen = Math.max(...xValues.map((v) => String(v).length), 0);
		const needsAngle = maxLabelLen > 8 && chartType !== 'pie' && chartType !== 'table' && chartType !== 'heatmap';

		const layout: any = {
			title: title || undefined,
			paper_bgcolor: 'transparent',
			plot_bgcolor: 'transparent',
			font: {
				color: '#888',
				size: 12,
				family: PLOTLY_FONT_FAMILY
			},
			margin: { t: title ? 40 : 20, r: 20, b: needsAngle ? 80 : 40, l: 50 },
			autosize: true,
			showlegend: yCols.length > 1 || chartType === 'pie',
			legend: { orientation: 'h', y: -0.2 },
			xaxis: needsAngle ? { tickangle: -30 } : {},
			barmode: yCols.length > 1 || chartType === 'grouped_bar' ? 'group' : undefined
		};

		if (chartType === 'pie') {
			const yCol = yCols[0] || columns[1];
			traces = [
				{
					type: 'pie',
					labels: xValues,
					values: rows.map((r) => Number(r[yCol]) || 0),
					marker: { colors: COLORS },
					textinfo: 'label+percent',
					hole: 0.3
				}
			];
		} else if (chartType === 'histogram') {
			// Histogram: 숫자 컬럼별 분포
			yCols.forEach((yc, i) => {
				traces.push({
					type: 'histogram',
					x: rows.map((r) => Number(r[yc]) || 0),
					name: yc,
					marker: { color: COLORS[i % COLORS.length] },
					opacity: 0.7
				});
			});
			if (yCols.length > 1) layout.barmode = 'overlay';
		} else if (chartType === 'heatmap') {
			// Heatmap: x축(카테고리/날짜) × y축(두번째 카테고리) → z축(숫자 값)
			const allCats = [...categoricalCols, ...dateCols];
			const yCol = allCats.find((c) => c !== xCol) || (yCols.length >= 2 ? yCols[1] : yCols[0]);
			const zCol = yCols[0] || columns[columns.length - 1];

			if (allCats.length >= 2) {
				// 2개 카테고리 + 1개 숫자: pivot 형태
				const xLabels = [...new Set(rows.map((r) => String(r[xCol] ?? '')))];
				const yLabels = [...new Set(rows.map((r) => String(r[yCol] ?? '')))];
				const zValues = yLabels.map((yl) =>
					xLabels.map((xl) => {
						const row = rows.find((r) => String(r[xCol]) === xl && String(r[yCol]) === yl);
						return row ? Number(row[zCol] || 0) : 0;
					})
				);
				traces.push({
					type: 'heatmap',
					x: xLabels,
					y: yLabels,
					z: zValues,
					colorscale: 'YlOrRd'
				});
			} else {
				// 숫자 컬럼만 있을 때: 컬럼 간 상관행렬 스타일
				const zValues = numericCols.map((yc) =>
					rows.map((r) => Number(r[yc]) || 0)
				);
				traces.push({
					type: 'heatmap',
					x: xValues,
					y: numericCols,
					z: zValues,
					colorscale: 'YlOrRd'
				});
			}
			layout.margin = { t: title ? 40 : 20, r: 20, b: 60, l: 80 };
		} else if (chartType === 'table') {
			traces = [
				{
					type: 'table',
					header: {
						values: columns.map((c) => `<b>${c}</b>`),
						fill: { color: '#1f77b4' },
						font: {
							color: 'white',
							size: 12,
							family: PLOTLY_FONT_FAMILY
						},
						align: 'left'
					},
					cells: {
						values: columns.map((col) => rows.map((r) => r[col])),
						fill: { color: ['#f9fafb', 'white'] },
						align: 'left',
						font: {
							size: 11,
							family: PLOTLY_FONT_FAMILY
						}
					}
				}
			];
			layout.margin = { t: 10, r: 10, b: 10, l: 10 };
		} else {
			const plotType = chartType === 'line' || chartType === 'area' ? 'scatter' : chartType === 'grouped_bar' ? 'bar' : chartType;

			// 그룹 컬럼 감지: x축도 아니고 숫자도 아닌 컬럼 (e.g., model_id, user_id)
			const groupCol = [...categoricalCols, ...dateCols].find((c) => c !== xCol);
			const yCol = yCols[0] || columns[columns.length - 1];

			if (groupCol && yCols.length === 1) {
				// 그룹별 시리즈 생성 (e.g., 사용자별/모델별 트렌드)
				const groups = [...new Set(rows.map((r) => String(r[groupCol] ?? 'unknown')))];
				groups.forEach((groupVal, i) => {
					const groupRows = rows.filter((r) => String(r[groupCol] ?? 'unknown') === groupVal);
					const trace: any = {
						x: groupRows.map((r) => r[xCol]),
						y: groupRows.map((r) => Number(r[yCol]) || 0),
						name: groupVal,
						marker: { color: COLORS[i % COLORS.length] }
					};
					if (plotType === 'scatter' && chartType === 'line') {
						trace.type = 'scatter';
						trace.mode = 'lines+markers';
					} else if (plotType === 'scatter' && chartType === 'area') {
						trace.type = 'scatter';
						trace.mode = 'lines';
						trace.fill = 'tozeroy';
					} else if (chartType === 'scatter') {
						trace.type = 'scatter';
						trace.mode = 'markers';
					} else {
						trace.type = plotType;
					}
					traces.push(trace);
				});
				layout.showlegend = groups.length > 1;
			} else {
				// 단일 시리즈 (그룹 없음 또는 숫자 컬럼 여러 개)
				yCols.forEach((yc, i) => {
					const trace: any = {
						x: xValues,
						y: rows.map((r) => Number(r[yc]) || 0),
						name: yc,
						marker: { color: COLORS[i % COLORS.length] }
					};
					if (plotType === 'scatter' && chartType === 'line') {
						trace.type = 'scatter';
						trace.mode = 'lines+markers';
					} else if (plotType === 'scatter' && chartType === 'area') {
						trace.type = 'scatter';
						trace.mode = 'lines';
						trace.fill = 'tozeroy';
					} else if (chartType === 'scatter') {
						trace.type = 'scatter';
						trace.mode = 'markers';
					} else {
						trace.type = plotType;
					}
					traces.push(trace);
				});
			}
		}

		try {
			Plotly.newPlot(chartEl, traces, layout, {
				responsive: true,
				displayModeBar: false
			});
		} catch (e) {
			// axis scaling 등 Plotly 렌더링 에러 시 한 프레임 후 재시도
			console.warn('Plotly render failed, retrying:', e);
			requestAnimationFrame(() => {
				try {
					if (chartEl && chartEl.offsetWidth > 0 && chartEl.offsetHeight > 0) {
						Plotly.newPlot(chartEl, traces, layout, { responsive: true, displayModeBar: false });
					}
				} catch { /* silent */ }
			});
		}
	}
</script>

<div bind:this={wrapperEl} class="w-full h-full relative">
	{#if loading}
		<div class="flex items-center justify-center h-full">
			<Spinner className="size-6" />
		</div>
	{:else if !data || data.data.length === 0}
		<div
			class="flex items-center justify-center h-full text-sm text-gray-400 dark:text-gray-500"
		>
			No data
		</div>
	{:else if chartType === 'card' && cardValue}
		{@const isHorizontal = titlePosition === 'left' || titlePosition === 'right'}
		{@const titleBefore = titlePosition === 'left' || titlePosition === 'inside-top'}
		{@const valText = typeof cardValue.value === 'number' ? cardValue.value.toLocaleString() : cardValue.value}
		{@const titleClass = cardBgColor ? 'text-white/70' : 'text-gray-500 dark:text-gray-400'}
		{@const valClass = cardBgColor ? 'text-white' : 'dark:text-gray-100'}
		<div class="flex {isHorizontal ? 'flex-row' : 'flex-col'} items-center justify-center gap-1.5 h-full px-4">
			{#if title && titleBefore}
				<div class="text-xs {titleClass} whitespace-nowrap">{title}</div>
			{/if}
			<div class="text-2xl font-bold {valClass} whitespace-nowrap">{valText}</div>
			{#if title && !titleBefore}
				<div class="text-xs {titleClass} whitespace-nowrap">{title}</div>
			{/if}
		</div>
	{:else}
		<div bind:this={chartEl} class="w-full h-full"></div>
	{/if}
</div>

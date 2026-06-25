<script lang="ts">
	import { toast } from 'svelte-sonner';
	import { createEventDispatcher, getContext, onMount } from 'svelte';
	import Modal from '$lib/components/common/Modal.svelte';
	import Button from '$lib/components/common/Button.svelte';
	import Input from '$lib/components/common/Input.svelte';
	import Textarea from '$lib/components/common/Textarea.svelte';
	import Selector from '$lib/components/common/Selector.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import PanelChart from './PanelChart.svelte';
	import { getDbSpheres } from '$lib/apis/dbsphere';
	import { getModels } from '$lib/apis';
	import { generateSql, executeSql } from '$lib/apis/bi-dashboards';
	import { formatBackendError } from '$lib/utils/error';

	const i18n = getContext('i18n');
	const dispatch = createEventDispatcher();

	export let show = false;
	export let editPanel: any = null;
	export let filters: any[] = [];

	let panelType: 'chart' | 'card' = 'chart';
	let name = '';
	let dbsphereId = '';
	let modelId = '';
	let nlQuery = '';
	let sql = '';
	let sqlTemplate = '';
	let chartType = 'bar';
	let explanation = '';
	let panelW = 6;
	let panelH = 4;
	let useTimeFilter = false;
	let dateColumn = '';
	let cardBgColor = '';

	// 제목 옵션
	let showTitle = true;
	let titlePosition: 'top' | 'bottom' | 'inside' = 'inside';

	// 카드용
	let cardSource: 'db' | 'manual' = 'db';
	let cardManualValue = '';

	let dbspheres: any[] = [];
	let models: any[] = [];
	let generating = false;
	let executing = false;
	let previewData: any = null;

	onMount(async () => {
		await loadOptions();
	});

	async function loadOptions() {
		try {
			dbspheres = await getDbSpheres(localStorage.token);
			const allModels = await getModels(localStorage.token);
			models = allModels.filter(
				(m: any) =>
					m.id &&
					m.name &&
					!m.info?.base_model_id &&
					m.owned_by !== 'agent_flow' &&
					m.owned_by !== 'arena'
			);
		} catch (e: any) {
			toast.error(formatBackendError(e, $i18n) || $i18n.t('Failed to load data'));
		}
	}

	// show가 true로 바뀔 때만 폼 초기화
	let prevShow = false;
	$: if (show && !prevShow) {
		prevShow = true;
		if (dbspheres.length === 0) loadOptions();
		if (editPanel) {
			name = editPanel.name || '';
			dbsphereId = editPanel.dbsphere_id || '';
			const panelData = editPanel.data || {};
			panelType = panelData.panel_type || (panelData.chart_type === 'card' ? 'card' : 'chart');
			nlQuery = panelData.nl_query || '';
			sql = panelData.sql || '';
			sqlTemplate = panelData.sql_template || '';
			chartType = panelData.chart_type || 'bar';
			modelId = panelData.model_id || '';
			panelW = panelData.layout?.w || 6;
			panelH = panelData.layout?.h || 4;
			useTimeFilter = panelData.use_time_filter !== false;
			dateColumn = panelData.date_column || '';
			cardBgColor = panelData.card_bg_color || '';
			showTitle = panelData.show_title !== false;
			titlePosition = panelData.title_position || (panelType === 'card' ? 'inside-bottom' : 'top');
			cardSource = panelData.card_source || 'db';
			cardManualValue = panelData.card_manual_value || '';
			previewData = panelData.cached_result || null;
		} else {
			panelType = 'chart';
			name = '';
			dbsphereId = '';
			nlQuery = '';
			sql = '';
			sqlTemplate = '';
			chartType = 'bar';
			modelId = '';
			explanation = '';
			panelW = 6;
			panelH = 4;
			useTimeFilter = true;
			dateColumn = '';
			cardBgColor = '';
			showTitle = true;
			titlePosition = 'top';
			cardSource = 'db';
			cardManualValue = '';
			previewData = null;
		}
	} else if (!show) {
		prevShow = false;
	}

	// panelType 전환 시 제목 위치 기본값 변경 + 카드면 테이블 로드
	$: if (panelType && !editPanel) {
		titlePosition = panelType === 'card' ? 'inside-bottom' : 'top';
	}
	async function handleGenerateSql() {
		if (!dbsphereId) {
			toast.error($i18n.t('Please select a database'));
			return;
		}
		if (!modelId) {
			toast.error($i18n.t('Please select a model'));
			return;
		}
		if (!nlQuery.trim()) {
			toast.error($i18n.t('Please enter a query'));
			return;
		}

		generating = true;
		try {
			const activeFilters = filters.filter(
				(f: any) => f.value || f.from_value || f.to_value
			);

			// 기간 필터 사용 시: 현재 기간 범위를 필터에 포함하여 날짜 WHERE 절 생성 유도
			if (useTimeFilter) {
				const timeFilter = filters.find((f: any) => f.id === '__time_range__');
				if (timeFilter && (timeFilter.from_value || timeFilter.to_value)) {
					activeFilters.push({
						type: 'date_range',
						field: 'date',
						label: 'Period',
						from_value: timeFilter.from_value,
						to_value: timeFilter.to_value
					});
				} else {
					// 기간이 선택 안 됐으면 기본 7일
					const now = new Date();
					const weekAgo = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
					activeFilters.push({
						type: 'date_range',
						field: 'date',
						label: 'Period',
						from_value: weekAgo.toISOString().split('T')[0],
						to_value: now.toISOString().split('T')[0]
					});
				}
			}

			const result = await generateSql(localStorage.token, {
				dbsphere_id: dbsphereId,
				nl_query: nlQuery,
				model_id: modelId,
				filters: activeFilters.length > 0 ? activeFilters : undefined
			});
			sql = result.sql || '';
			explanation = result.explanation || '';
			if (result.result) {
				previewData = result.result;
			}
			// SQL 템플릿 + 날짜 컬럼 자동 감지
			if (result.sql_template) {
				sqlTemplate = result.sql_template;
			}
			if (result.date_column) {
				dateColumn = result.date_column;
				useTimeFilter = true;
			}
			toast.success($i18n.t('SQL generated successfully'));
		} catch (e: any) {
			toast.error(formatBackendError(e, $i18n) || $i18n.t('SQL generation failed'));
		} finally {
			generating = false;
		}
	}

	async function handleExecuteSql() {
		if (!sql.trim()) {
			toast.error($i18n.t('No SQL to execute'));
			return;
		}
		executing = true;
		try {
			previewData = await executeSql(localStorage.token, {
				dbsphere_id: dbsphereId,
				sql: sql
			});
			toast.success($i18n.t('SQL executed successfully'));
		} catch (e: any) {
			toast.error(formatBackendError(e, $i18n) || $i18n.t('SQL execution failed'));
		} finally {
			executing = false;
		}
	}

	function handleSave() {
		if (!name.trim()) {
			toast.error($i18n.t('Panel name is required'));
			return;
		}
		if (panelType === 'card' && cardSource === 'manual') {
			if (!cardManualValue.trim()) {
				toast.error($i18n.t('Please enter a value'));
				return;
			}
		} else {
			if (!dbsphereId) {
				toast.error($i18n.t('Please select a database'));
				return;
			}
			if (!sql.trim()) {
				toast.error($i18n.t('Please generate SQL first'));
				return;
			}
		}

		const finalChartType = panelType === 'card' ? 'card' : chartType;
		const finalW = panelType === 'card' ? (editPanel?.data?.layout?.w || 3) : panelW;
		const finalH = panelType === 'card' ? (editPanel?.data?.layout?.h || 1) : panelH;

		// 카드 수동 입력인 경우 previewData 생성
		let finalPreview = previewData;
		let finalSql = sql;
		if (panelType === 'card' && cardSource === 'manual') {
			finalPreview = { columns: ['value'], data: [{ value: cardManualValue }], row_count: 1 };
			finalSql = '';
		}

		dispatch('save', {
			name,
			dbsphere_id: dbsphereId || '',
			data: {
				panel_type: panelType,
				nl_query: nlQuery,
				sql: finalSql,
				sql_template: sqlTemplate || finalSql,
				chart_type: finalChartType,
				model_id: modelId,
				layout: { x: editPanel?.data?.layout?.x || 0, y: editPanel?.data?.layout?.y || 0, w: finalW, h: finalH },
				show_title: showTitle,
				title_position: titlePosition,
				use_time_filter: useTimeFilter,
				date_column: useTimeFilter ? dateColumn : '',
				card_bg_color: cardBgColor,
				card_source: panelType === 'card' ? cardSource : '',
				card_manual_value: panelType === 'card' && cardSource === 'manual' ? cardManualValue : '',
				cached_result: finalPreview,
				cached_at: finalPreview ? Math.floor(Date.now() / 1000) : null
			}
		});
		show = false;
	}
</script>

<Modal bind:show size="lg">
	<div class="px-5 py-4 max-h-[85vh] overflow-y-auto">
		<div class="text-lg font-semibold mb-1 dark:text-gray-100">
			{editPanel ? $i18n.t('Edit Panel') : $i18n.t('Add Panel')}
		</div>
		{#if editPanel && nlQuery}
			<div class="text-xs text-gray-400 dark:text-gray-500 mb-3 italic">
				"{nlQuery}"
			</div>
		{/if}

		<div class="flex flex-col gap-3">
			<!-- 패널 유형 -->
			<div class="flex items-center gap-2">
				<button
					class="px-3 py-1.5 text-sm font-medium rounded-md transition-all {panelType === 'chart'
						? 'bg-gray-800 text-white dark:bg-white dark:text-gray-900'
						: 'bg-gray-100 dark:bg-gray-800 text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200'}"
					on:click={() => (panelType = 'chart')}
				>
					{$i18n.t('Chart')}
				</button>
				<button
					class="px-3 py-1.5 text-sm font-medium rounded-md transition-all {panelType === 'card'
						? 'bg-gray-800 text-white dark:bg-white dark:text-gray-900'
						: 'bg-gray-100 dark:bg-gray-800 text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200'}"
					on:click={() => (panelType = 'card')}
				>
					{$i18n.t('Card')}
				</button>
			</div>

			<Input bind:value={name} label={$i18n.t('Panel Name')} size="md" required />

			{#if !(panelType === 'card' && cardSource === 'manual')}
			<div class="flex gap-3">
				<div class="flex-1">
					<Selector
						value={dbsphereId}
						items={dbspheres.map((d) => ({ value: d.id, label: d.name }))}
						placeholder={$i18n.t('Select database')}
						searchEnabled
						size="md"
						contentClassName="z-[99999]"
						on:change={(e) => {
							dbsphereId = e.detail.value;
						}}
					/>
				</div>
				{#if !(panelType === 'card' && cardSource === 'manual')}
					<div class="flex-1">
						<Selector
							value={modelId}
							items={models.map((m) => ({ value: m.id, label: m.name }))}
							placeholder={$i18n.t('Select model')}
							searchEnabled
							size="md"
							contentClassName="z-[99999]"
							on:change={(e) => {
								modelId = e.detail.value;
							}}
						/>
					</div>
				{/if}
			</div>
			{/if}

			{#if panelType === 'card'}
				<!-- 카드: 소스 선택 -->
				<div class="flex items-center gap-2">
					<button
						class="px-3 py-1 text-xs font-medium rounded-md transition-all {cardSource === 'manual'
							? 'bg-gray-800 text-white dark:bg-white dark:text-gray-900'
							: 'bg-gray-100 dark:bg-gray-800 text-gray-500 dark:text-gray-400'}"
						on:click={() => (cardSource = 'manual')}
					>{$i18n.t('Manual Input')}</button>
					<button
						class="px-3 py-1 text-xs font-medium rounded-md transition-all {cardSource === 'db'
							? 'bg-gray-800 text-white dark:bg-white dark:text-gray-900'
							: 'bg-gray-100 dark:bg-gray-800 text-gray-500 dark:text-gray-400'}"
						on:click={() => (cardSource = 'db')}
					>{$i18n.t('DB Query')}</button>
				</div>

				{#if cardSource === 'manual'}
					<Input bind:value={cardManualValue} label={$i18n.t('Value')} placeholder={$i18n.t('e.g. 1,234 or Active')} size="md" />
				{:else}
					<!-- 카드: 차트와 동일한 NL 질문 → SQL 생성 -->
					<div class="flex gap-2 items-end">
						<div class="flex-1">
							<Textarea
								bind:value={nlQuery}
								label={$i18n.t('Query')}
								placeholder={$i18n.t('e.g. Total number of orders, Average order amount')}
								size="md"
								rows={2}
							/>
						</div>
						<Button kind="filled" size="md" loading={generating} on:click={handleGenerateSql}>
							{$i18n.t('Generate SQL')}
						</Button>
					</div>

					{#if sql}
						<div>
							<div class="text-xs font-medium text-gray-500 dark:text-gray-400 mb-1">
								{$i18n.t('Generated SQL')}
							</div>
							<div class="relative">
								<textarea
									bind:value={sql}
									rows={3}
									class="w-full font-mono text-sm bg-gray-50 dark:bg-gray-800 dark:text-gray-200 border border-gray-200 dark:border-gray-700 rounded-lg p-3 outline-none resize-none"
								></textarea>
								<div class="absolute top-2 right-2">
									<Button kind="outlined" size="sm" loading={executing} on:click={handleExecuteSql}>
										{$i18n.t('Execute')}
									</Button>
								</div>
							</div>
						</div>
					{/if}
				{/if}

				<!-- 미리보기 -->
				{#if (cardSource === 'manual' && cardManualValue) || (previewData && previewData.data?.length > 0)}
					{@const val = cardSource === 'manual' ? cardManualValue : (previewData?.data?.[0]?.value ?? previewData?.data?.[0]?.[previewData?.columns?.[0]] ?? '-')}
					<div class="flex items-center justify-center rounded-lg p-4" style={cardBgColor ? `background-color: ${cardBgColor};` : 'background-color: var(--cloo-bg-surface);'}>
						<span class="text-3xl font-bold {cardBgColor ? 'text-white' : 'dark:text-gray-100'}">
							{typeof val === 'number' ? val.toLocaleString() : val}
						</span>
					</div>
				{/if}

				<!-- 카드 배경색 -->
				<div class="flex items-center gap-2 px-1">
					<span class="text-sm text-gray-700 dark:text-gray-300">{$i18n.t('Card Color')}</span>
					<input type="color" bind:value={cardBgColor} class="w-7 h-7 rounded border border-gray-200 dark:border-gray-700 cursor-pointer" />
					{#if cardBgColor}
						<button class="text-xs text-gray-400 hover:text-gray-600 dark:hover:text-gray-300" on:click={() => (cardBgColor = '')}>&#x2715;</button>
					{/if}
				</div>
			{:else}
				<!-- 차트: NL 쿼리 -->
				<div class="flex gap-2 items-end">
					<div class="flex-1">
						<Textarea
							bind:value={nlQuery}
							label={$i18n.t('Natural Language Query')}
							placeholder={$i18n.t('e.g. Show monthly sales by product category')}
							size="md"
							rows={2}
						/>
					</div>
					<Button kind="filled" size="md" loading={generating} on:click={handleGenerateSql}>
						{$i18n.t('Generate SQL')}
					</Button>
				</div>
			{/if}

			{#if explanation}
				<div
					class="text-sm text-gray-600 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 rounded-lg p-3"
				>
					{explanation}
				</div>
			{/if}

			{#if sql && panelType === 'chart'}
				<div>
					<div class="text-xs font-medium text-gray-500 dark:text-gray-400 mb-1">
						{$i18n.t('Generated SQL')}
					</div>
					<div class="relative">
						<textarea
							bind:value={sql}
							rows={4}
							class="w-full font-mono text-sm bg-gray-50 dark:bg-gray-800 dark:text-gray-200 border border-gray-200 dark:border-gray-700 rounded-lg p-3 outline-none resize-none"
						></textarea>
						<div class="absolute top-2 right-2">
							<Button kind="outlined" size="sm" loading={executing} on:click={handleExecuteSql}>
								{$i18n.t('Execute')}
							</Button>
						</div>
					</div>
				</div>
			{/if}

			<!-- 기간 필터 (카드/차트 공통) -->
			{#if panelType !== 'card' || cardSource !== 'manual'}
				<div class="flex items-center gap-4 px-1 flex-wrap">
					<label class="flex items-center gap-2 cursor-pointer">
						<input
							type="checkbox"
							bind:checked={useTimeFilter}
							class="rounded border-gray-300 dark:border-gray-600"
						/>
						<span class="text-sm text-gray-700 dark:text-gray-300">
							{$i18n.t('Use time filter')}
						</span>
					</label>
					{#if useTimeFilter}
						<div class="w-40">
							<Input
								bind:value={dateColumn}
								placeholder={$i18n.t('e.g. created_date')}
								size="sm"
							/>
						</div>
					{/if}
				</div>
			{/if}

			{#if previewData && panelType === 'chart'}
				<div
					class="border border-gray-200 dark:border-gray-700 rounded-lg overflow-hidden"
					style="height: 300px;"
				>
					<PanelChart data={previewData} {chartType} />
				</div>
			{/if}
		</div>

		<!-- 제목 옵션 -->
		<div class="flex items-center gap-4 px-1 mt-2 flex-wrap">
			<label class="flex items-center gap-2 cursor-pointer">
				<input type="checkbox" bind:checked={showTitle} class="rounded border-gray-300 dark:border-gray-600" />
				<span class="text-sm text-gray-700 dark:text-gray-300">{$i18n.t('Show Title')}</span>
			</label>
			{#if showTitle}
				<div class="w-36">
					<Selector
						value={titlePosition}
						items={[
							{ value: 'top', label: $i18n.t('Header') },
							{ value: 'bottom', label: $i18n.t('Footer') },
							{ value: 'inside-top', label: $i18n.t('Inside Top') },
							{ value: 'inside-bottom', label: $i18n.t('Inside Bottom') },
							{ value: 'left', label: $i18n.t('Inside Left') },
							{ value: 'right', label: $i18n.t('Inside Right') }
						]}
						size="sm"
						contentClassName="z-[99999]"
						on:change={(e) => { titlePosition = e.detail.value; }}
					/>
				</div>
			{/if}
		</div>

		<div class="flex justify-end gap-2 mt-4">
			<Button kind="outlined" size="md" on:click={() => (show = false)}>
				{$i18n.t('Cancel')}
			</Button>
			<Button kind="filled" size="md" on:click={handleSave}>
				{$i18n.t('Save')}
			</Button>
		</div>
	</div>
</Modal>

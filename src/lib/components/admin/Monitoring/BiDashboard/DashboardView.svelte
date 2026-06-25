<script lang="ts">
	import { toast } from 'svelte-sonner';
	import { createEventDispatcher, getContext, onMount } from 'svelte';
	import { trackAIGeneration, clearAITask } from '$lib/stores/ai-generation';
	import { showSidebar } from '$lib/stores';
	import Button from '$lib/components/common/Button.svelte';
	import Input from '$lib/components/common/Input.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import PanelCard from './PanelCard.svelte';
	import PanelEditor from './PanelEditor.svelte';
	import FilterBar from './FilterBar.svelte';
	import TimeRangePicker from './TimeRangePicker.svelte';
	import Selector from '$lib/components/common/Selector.svelte';
	import {
		getDashboardById,
		updateDashboard,
		createPanel,
		updatePanel,
		deletePanel,
		autoBuildDashboardChat,
		exportDashboardHtml
	} from '$lib/apis/bi-dashboards';
	import type { BiDashboardDetail, BiPanel } from '$lib/apis/bi-dashboards';
	import ShareDashboardModal from './ShareDashboardModal.svelte';
	import { getModels } from '$lib/apis';
	import { getDbSpheres } from '$lib/apis/dbsphere';
	import { formatBackendError } from '$lib/utils/error';

	const i18n = getContext('i18n');
	const dispatch = createEventDispatcher();

	export let dashboardId: string;

	let dashboard: BiDashboardDetail | null = null;
	let loading = true;
	let editMode = false;
	let editName = '';
	let saving = false;

	let showPanelEditor = false;
	let editingPanel: BiPanel | null = null;
	let filters: any[] = [];
	let filterVersion = 0;
	let timeRange = 'yesterday';
	let timeCustomFrom = '';
	let timeCustomTo = '';
	let gridEl: HTMLDivElement;

	// 리사이즈 상태
	let resizingPanelId: string | null = null;
	let resizeGhost = { w: 0, h: 0 };

	// Share & Export
	let showShareModal = false;
	let exporting = false;

	// AI Chat Panel
	let showAIChat = false;
	let aiChatInput = '';
	let aiChatModel = '';
	let aiChatLoading = false;
	let aiChatHeight = 320;

	type ChatMsg = {
		role: 'user' | 'ai';
		content: string;
		loading?: boolean;
		buttons?: Array<{ label: string; value: string }>;
	};
	let aiChatMessages: ChatMsg[] = [];
	let conversationHistory: Array<{ role: string; content: string }> = [];
	let pendingTaskId = '';

	let aiModelOptions: Array<{ value: string; label: string }> = [];
	let aiDbOptions: Array<{ value: string; label: string }> = [];
	let aiSelectedDb = '';

	function loadChatHistory(meta: any) {
		if (meta?.ai_chat_history) {
			conversationHistory = meta.ai_chat_history;
			aiChatMessages = conversationHistory.map((m: any) => ({
				role: m.role === 'assistant' ? 'ai' as const : 'user' as const,
				content: m.content,
			}));
		}
	}

	function handleButtonClick(value: string) {
		aiChatMessages = aiChatMessages.map(m =>
			m.buttons ? { ...m, buttons: undefined } : m
		);
		sendAIChat(value);
	}

	async function sendAIChat(overrideMsg?: string | Event) {
		const msg = typeof overrideMsg === 'string' ? overrideMsg.trim() : '';
		const userMsg = msg || aiChatInput.trim();
		if (!userMsg || aiChatLoading) return;
		aiChatInput = '';

		conversationHistory = [...conversationHistory, { role: 'user', content: userMsg }];
		aiChatMessages = [...aiChatMessages, { role: 'user', content: userMsg }];
		aiChatMessages = [...aiChatMessages, { role: 'ai', content: '', loading: true }];
		aiChatLoading = true;

		// API 호출을 글로벌 트래커에 등록 — 페이지 이동 후에도 toast 표시
		const promise = autoBuildDashboardChat(
			localStorage.token,
			conversationHistory,
			aiChatModel,
			dashboardId || '',
			aiSelectedDb ? [aiSelectedDb] : undefined
		);

		pendingTaskId = trackAIGeneration('dashboard', dashboardId || 'new', promise, {
			success: $i18n.t('Dashboard updated by AI'),
			error: $i18n.t('Dashboard AI generation failed'),
		});

		try {
			const result = await promise;

			const aiMsg = result.assistant_message || '';
			conversationHistory = [...conversationHistory, { role: 'assistant', content: aiMsg }];

			aiChatMessages = aiChatMessages.slice(0, -1);

			if (result.pending_input && result.pending_input.options?.length > 0) {
				aiChatMessages = [...aiChatMessages, {
					role: 'ai',
					content: aiMsg,
					buttons: result.pending_input.options.map((o: string) => ({ label: o, value: o })),
				}];
			} else {
				aiChatMessages = [...aiChatMessages, { role: 'ai', content: aiMsg }];
			}

			// Reload dashboard after any AI action (add/delete/reposition)
			if (result.dashboard_id && !dashboardId) {
				dashboardId = result.dashboard_id;
			}
			await loadDashboard();

			// toast는 trackAIGeneration에서 처리됨
			clearAITask(pendingTaskId);
		} catch (e: any) {
			aiChatMessages = aiChatMessages.slice(0, -1);
			aiChatMessages = [...aiChatMessages, {
				role: 'ai',
				content: `❌ ${formatBackendError(e, $i18n) || e?.toString() || 'Error'}`,
			}];
			clearAITask(pendingTaskId);
		} finally {
			aiChatLoading = false;
			pendingTaskId = '';
		}
	}

	onMount(async () => {
		await loadDashboard();
		// Load model and DbSphere options for AI chat
		try {
			const allModels = await getModels(localStorage.token);
			aiModelOptions = allModels
				.filter((m: any) => m.id && m.name && !m.info?.base_model_id && m.owned_by !== 'agent_flow' && m.owned_by !== 'arena')
				.map((m: any) => ({ value: m.id, label: m.name }));
		} catch { /* silent */ }
		try {
			const dbs = await getDbSpheres(localStorage.token);
			aiDbOptions = dbs.map((db: any) => ({ value: db.id, label: db.name }));
		} catch { /* silent */ }
	});

	async function loadDashboard() {
		loading = true;
		try {
			dashboard = await getDashboardById(localStorage.token, dashboardId);
			editName = dashboard.name;
			filters = dashboard.data?.filters || [];
			// Restore AI chat history if available
			if (conversationHistory.length === 0) {
				loadChatHistory(dashboard.meta);
			}
		} catch (e: any) {
			toast.error(formatBackendError(e, $i18n) || $i18n.t('Failed to load dashboard'));
		} finally {
			loading = false;
		}
	}

	async function handleTimeRangeChange(e: CustomEvent) {
		const { from_value, to_value } = e.detail;

		// 기간 필터를 filters에 주입 (field는 PanelCard에서 패널별로 적용)
		const timeFilter = {
			id: '__time_range__',
			label: 'Time',
			type: 'date_range',
			field: '',  // 패널별 date_column으로 대체됨
			from_value,
			to_value
		};

		const otherFilters = filters.filter((f: any) => f.id !== '__time_range__');
		if (from_value || to_value) {
			filters = [...otherFilters, timeFilter];
		} else {
			filters = otherFilters;
		}
		filterVersion++;
	}

	async function handleFilterChange(e: CustomEvent) {
		filters = e.detail;
		filterVersion++;
		if (!dashboard) return;
		try {
			await updateDashboard(localStorage.token, dashboard.id, {
				name: dashboard.name,
				description: dashboard.description,
				data: { ...dashboard.data, filters }
			});
		} catch {
			// silent save
		}
	}

	async function handleSaveName() {
		if (!dashboard || !editName.trim()) return;
		saving = true;
		try {
			await updateDashboard(localStorage.token, dashboard.id, {
				name: editName,
				description: dashboard.description
			});
			dashboard.name = editName;
			toast.success($i18n.t('Dashboard updated'));
		} catch (e: any) {
			toast.error(formatBackendError(e, $i18n) || $i18n.t('Failed to update dashboard'));
		} finally {
			saving = false;
		}
	}

	async function handleExportHtml() {
		if (!dashboard) return;
		exporting = true;
		try {
			const timeFilter = filters.find((f: any) => f.id === '__time_range__');
			const blob = await exportDashboardHtml(localStorage.token, dashboard.id, {
				from_value: timeFilter?.from_value || undefined,
				to_value: timeFilter?.to_value || undefined,
				filters: filters.filter((f: any) => f.id !== '__time_range__' && (f.value || f.from_value || f.to_value))
			});
			const url = URL.createObjectURL(blob);
			const a = document.createElement('a');
			a.href = url;
			a.download = `${dashboard.name}.html`;
			a.click();
			URL.revokeObjectURL(url);
			toast.success($i18n.t('Dashboard exported'));
		} catch (e: any) {
			toast.error(formatBackendError(e, $i18n) || $i18n.t('Export failed'));
		} finally {
			exporting = false;
		}
	}

	function handleAddPanel() {
		editingPanel = null;
		showPanelEditor = true;
	}

	function handleEditPanel(e: CustomEvent) {
		editingPanel = e.detail;
		showPanelEditor = true;
	}

	function findNextAvailablePosition(w: number, h: number): { x: number; y: number } {
		if (!dashboard) return { x: 0, y: 0 };
		const panels = dashboard.panels || [];
		// 기존 패널들이 차지하는 영역 계산
		let maxY = 0;
		for (const p of panels) {
			const l = p.data?.layout || { x: 0, y: 0, w: 6, h: 4 };
			const bottom = l.y + l.h;
			if (bottom > maxY) maxY = bottom;
		}
		// 같은 행에 빈 공간 찾기
		for (let y = 0; y <= maxY; y++) {
			for (let x = 0; x <= 12 - w; x++) {
				let fits = true;
				for (const p of panels) {
					const l = p.data?.layout || { x: 0, y: 0, w: 6, h: 4 };
					// 겹치는지 확인
					if (x < l.x + l.w && x + w > l.x && y < l.y + l.h && y + h > l.y) {
						fits = false;
						break;
					}
				}
				if (fits) return { x, y };
			}
		}
		// 빈 공간 없으면 맨 아래에 배치
		return { x: 0, y: maxY };
	}

	async function handleSavePanel(e: CustomEvent) {
		if (!dashboard) return;
		const panelData = e.detail;

		// 새 패널이면 빈 공간에 배치
		if (!editingPanel && panelData.data?.layout) {
			const layout = panelData.data.layout;
			const pos = findNextAvailablePosition(layout.w, layout.h);
			panelData.data.layout = { ...layout, x: pos.x, y: pos.y };
		}

		try {
			if (editingPanel) {
				await updatePanel(localStorage.token, dashboard.id, editingPanel.id, panelData);
			} else {
				await createPanel(localStorage.token, dashboard.id, panelData);
			}
			await loadDashboard();
			toast.success($i18n.t('Panel saved'));
		} catch (e: any) {
			toast.error(formatBackendError(e, $i18n) || $i18n.t('Failed to save panel'));
		}
	}

	async function handlePanelMove(e: CustomEvent) {
		const { panelId, x, y } = e.detail;
		if (!dashboard) return;
		const panel = dashboard.panels.find((p) => p.id === panelId);
		if (!panel) return;

		const currentLayout = panel.data?.layout || { x: 0, y: 0, w: 6, h: 4 };
		const newData = { ...panel.data, layout: { ...currentLayout, x, y } };

		try {
			await updatePanel(localStorage.token, dashboard.id, panelId, {
				name: panel.name,
				dbsphere_id: panel.dbsphere_id,
				data: newData
			});
			panel.data = newData;
			dashboard = dashboard;
		} catch (e: any) {
			toast.error(formatBackendError(e, $i18n) || $i18n.t('Failed to move panel'));
		}
	}

	async function handleChartTypeChange(e: CustomEvent) {
		const { panelId, chartType } = e.detail;
		if (!dashboard) return;
		const panel = dashboard.panels.find((p) => p.id === panelId);
		if (!panel) return;

		const newData = { ...panel.data, chart_type: chartType };
		try {
			await updatePanel(localStorage.token, dashboard.id, panelId, {
				name: panel.name,
				dbsphere_id: panel.dbsphere_id,
				data: newData
			});
			panel.data = newData;
			dashboard = dashboard;
		} catch (e: any) {
			toast.error(formatBackendError(e, $i18n) || $i18n.t('Failed to update chart type'));
		}
	}

	async function handlePanelResize(e: CustomEvent) {
		const { panelId, w, h } = e.detail;
		if (!dashboard) return;
		const panel = dashboard.panels.find((p) => p.id === panelId);
		if (!panel) return;

		const currentLayout = panel.data?.layout || { x: 0, y: 0, w: 6, h: 4 };
		const newData = { ...panel.data, layout: { ...currentLayout, w, h } };

		try {
			await updatePanel(localStorage.token, dashboard.id, panelId, {
				name: panel.name,
				dbsphere_id: panel.dbsphere_id,
				data: newData
			});
			// 로컬 상태 즉시 반영
			panel.data = newData;
			dashboard = dashboard; // trigger reactivity
		} catch (e: any) {
			toast.error(formatBackendError(e, $i18n) || $i18n.t('Failed to resize panel'));
		}
	}

	async function insertRowAt(y: number) {
		if (!dashboard) return;
		for (const panel of dashboard.panels) {
			const layout = panel.data?.layout || { x: 0, y: 0, w: 6, h: 4 };
			if (layout.y >= y) {
				const newData = { ...panel.data, layout: { ...layout, y: layout.y + 1 } };
				await updatePanel(localStorage.token, dashboard.id, panel.id, {
					name: panel.name,
					dbsphere_id: panel.dbsphere_id,
					data: newData
				});
			}
		}
		await loadDashboard();
	}

	async function removeRowAt(y: number) {
		if (!dashboard) return;
		// y행에 패널이 있으면 삭제 불가
		const hasPanel = dashboard.panels.some((p) => {
			const l = p.data?.layout || { x: 0, y: 0, w: 6, h: 4 };
			return l.y === y;
		});
		if (hasPanel) {
			toast.error($i18n.t('Cannot remove row with panels'));
			return;
		}
		for (const panel of dashboard.panels) {
			const layout = panel.data?.layout || { x: 0, y: 0, w: 6, h: 4 };
			if (layout.y > y) {
				const newData = { ...panel.data, layout: { ...layout, y: layout.y - 1 } };
				await updatePanel(localStorage.token, dashboard.id, panel.id, {
					name: panel.name,
					dbsphere_id: panel.dbsphere_id,
					data: newData
				});
			}
		}
		await loadDashboard();
	}

	async function handleDeletePanel(e: CustomEvent) {
		if (!dashboard) return;
		const panel = e.detail;
		if (!confirm($i18n.t('Are you sure you want to delete this panel?'))) return;

		try {
			await deletePanel(localStorage.token, dashboard.id, panel.id);
			await loadDashboard();
			toast.success($i18n.t('Panel deleted'));
		} catch (e: any) {
			toast.error(formatBackendError(e, $i18n) || $i18n.t('Failed to delete panel'));
		}
	}
</script>

<div class="flex flex-col h-full">
{#if loading}
	<div class="flex items-center justify-center h-64">
		<Spinner className="size-8" />
	</div>
{:else if dashboard}
	<div class="flex flex-col flex-1 min-h-0 gap-3 relative">
		<!-- Header -->
		<div class="flex items-center justify-between gap-3">
			<div class="flex items-center gap-2 min-w-0">
				<button
					class="p-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 transition text-gray-500 dark:text-gray-400"
					on:click={() => dispatch('back')}
				>
					<svg xmlns="http://www.w3.org/2000/svg" class="size-5" viewBox="0 0 20 20" fill="currentColor">
						<path fill-rule="evenodd" d="M17 10a.75.75 0 01-.75.75H5.612l4.158 3.96a.75.75 0 11-1.04 1.08l-5.5-5.25a.75.75 0 010-1.08l5.5-5.25a.75.75 0 111.04 1.08L5.612 9.25H16.25A.75.75 0 0117 10z" clip-rule="evenodd" />
					</svg>
				</button>

				{#if editMode}
					<div class="flex items-center gap-2">
						<Input bind:value={editName} size="sm" />
						<Button kind="filled" size="sm" loading={saving} on:click={handleSaveName}>
							{$i18n.t('Save')}
						</Button>
					</div>
				{:else}
					<h2 class="text-lg font-semibold dark:text-gray-100 truncate">{dashboard.name}</h2>
				{/if}
			</div>

			<div class="flex items-center gap-2 shrink-0">
				{#if editMode}
					<Button kind="outlined" size="sm" on:click={() => insertRowAt(0)}>
						↓ {$i18n.t('Insert Row')}
					</Button>
					<Button kind="outlined" size="sm" on:click={() => removeRowAt(0)}>
						↑ {$i18n.t('Remove Row')}
					</Button>
				{/if}
				<Button kind="outlined" size="sm" on:click={handleExportHtml} loading={exporting}>
					<svelte:fragment slot="prefix">
						<svg xmlns="http://www.w3.org/2000/svg" class="size-3.5" viewBox="0 0 20 20" fill="currentColor">
							<path d="M10.75 2.75a.75.75 0 00-1.5 0v8.614L6.295 8.235a.75.75 0 10-1.09 1.03l4.25 4.5a.75.75 0 001.09 0l4.25-4.5a.75.75 0 00-1.09-1.03l-2.955 3.129V2.75z" />
							<path d="M3.5 12.75a.75.75 0 00-1.5 0v2.5A2.75 2.75 0 004.75 18h10.5A2.75 2.75 0 0018 15.25v-2.5a.75.75 0 00-1.5 0v2.5c0 .69-.56 1.25-1.25 1.25H4.75c-.69 0-1.25-.56-1.25-1.25v-2.5z" />
						</svg>
					</svelte:fragment>
					{$i18n.t('Export')}
				</Button>
				<Button kind="outlined" size="sm" on:click={() => (showShareModal = true)}>
					<svelte:fragment slot="prefix">
						<svg xmlns="http://www.w3.org/2000/svg" class="size-3.5" viewBox="0 0 20 20" fill="currentColor">
							<path d="M12.232 4.232a2.5 2.5 0 013.536 3.536l-1.225 1.224a.75.75 0 001.061 1.06l1.224-1.224a4 4 0 00-5.656-5.656l-3 3a4 4 0 00.225 5.865.75.75 0 00.977-1.138 2.5 2.5 0 01-.142-3.667l3-3z" />
							<path d="M11.603 7.963a.75.75 0 00-.977 1.138 2.5 2.5 0 01.142 3.667l-3 3a2.5 2.5 0 01-3.536-3.536l1.225-1.224a.75.75 0 00-1.061-1.06l-1.224 1.224a4 4 0 105.656 5.656l3-3a4 4 0 00-.225-5.865z" />
						</svg>
					</svelte:fragment>
					{$i18n.t('Share')}
				</Button>
				<Button kind="outlined" size="sm" on:click={() => (editMode = !editMode)}>
					{editMode ? $i18n.t('Done') : $i18n.t('Edit')}
				</Button>
				<Button kind="filled" size="sm" on:click={handleAddPanel}>
					<svelte:fragment slot="prefix">
						<svg xmlns="http://www.w3.org/2000/svg" class="size-3.5" viewBox="0 0 20 20" fill="currentColor">
							<path d="M10.75 4.75a.75.75 0 00-1.5 0v4.5h-4.5a.75.75 0 000 1.5h4.5v4.5a.75.75 0 001.5 0v-4.5h4.5a.75.75 0 000-1.5h-4.5v-4.5z" />
						</svg>
					</svelte:fragment>
					{$i18n.t('Add Panel')}
				</Button>
			</div>
		</div>

		<!-- Time Range + Filters -->
		<div class="flex flex-wrap items-center gap-3">
			<TimeRangePicker
				bind:selectedRange={timeRange}
				bind:customFrom={timeCustomFrom}
				bind:customTo={timeCustomTo}
				on:change={handleTimeRangeChange}
			/>
			<FilterBar
				filters={filters.filter((f) => f.id !== '__time_range__')}
				{editMode}
				on:change={handleFilterChange}
			/>
		</div>

		<!-- Panel Grid -->
		{#if dashboard.panels.length === 0}
			<div
				class="flex flex-col items-center justify-center h-64 text-gray-400 dark:text-gray-500 gap-3"
			>
				<svg xmlns="http://www.w3.org/2000/svg" class="size-12" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1">
					<path stroke-linecap="round" stroke-linejoin="round" d="M3.75 3v11.25A2.25 2.25 0 006 16.5h2.25M3.75 3h-1.5m1.5 0h16.5m0 0h1.5m-1.5 0v11.25A2.25 2.25 0 0118 16.5h-2.25m-7.5 0h7.5m-7.5 0l-1 3m8.5-3l1 3m0 0l.5 1.5m-.5-1.5h-9.5m0 0l-.5 1.5" />
				</svg>
				<p class="text-sm">{$i18n.t('No panels yet. Click "Add Panel" to get started.')}</p>
			</div>
		{:else}
			<div class="relative">
				{#if editMode}
					<div
						class="absolute inset-0 grid gap-4 pointer-events-none"
						style="grid-template-columns: repeat(12, 1fr); grid-auto-rows: 80px;"
					>
						{#each Array(96) as _}
							<div class="rounded border border-dashed border-gray-200 dark:border-gray-700/50 bg-gray-50/30 dark:bg-gray-800/20"></div>
						{/each}
					</div>
				{/if}
				<div
					bind:this={gridEl}
					class="grid gap-4 relative"
					style="grid-template-columns: repeat(12, 1fr); grid-auto-rows: 80px;"
				>
				{#each dashboard.panels as panel (panel.id)}
					{@const layout = panel.data?.layout || { x: 0, y: 0, w: 6, h: 4 }}
					{@const isChart = panel.data?.chart_type && panel.data.chart_type !== 'card'}
					{@const safeH = isChart && layout.h < 3 ? 3 : layout.h}
					<div
						id="panel-{panel.id}"
						style="grid-column: {layout.x + 1} / span {layout.w}; grid-row: {layout.y + 1} / span {safeH};"
					>
						<PanelCard
							{panel}
							dashboardId={dashboard.id}
							{editMode}
							{filters}
							{filterVersion}
							gridContainer={gridEl}
							on:edit={handleEditPanel}
							on:delete={handleDeletePanel}
							on:resize={handlePanelResize}
							on:move={handlePanelMove}
							on:chartTypeChange={handleChartTypeChange}
						/>
					</div>
				{/each}
			</div>
			</div>
		{/if}
		<!-- AI Chat Toggle Button (viewport-fixed) -->
		{#if !showAIChat}
			<button
				type="button"
				class="fixed bottom-4 right-4 z-40 flex items-center gap-2 px-4 py-2.5 rounded-full bg-violet-600 hover:bg-violet-700 text-white shadow-lg transition-all hover:shadow-xl hover:scale-105"
				on:click={() => { showAIChat = true; }}
			>
				<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z" />
				</svg>
				<span class="text-sm font-medium">{$i18n.t('AI Assistant')}</span>
			</button>
		{/if}
	</div>

	<!-- AI Chat Panel (fixed right side) -->
	{#if showAIChat}
		<div
			class="fixed bottom-0 right-0 border-t border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 flex flex-col shadow-2xl z-50"
			style="height: {aiChatHeight}px; min-height: 280px; max-height: calc(100vh - 60px); left: {$showSidebar ? '260px' : '68px'};"
		>
			<!-- Resize handle -->
			<div
				class="h-1.5 cursor-ns-resize bg-gray-100 dark:bg-gray-800 hover:bg-violet-200 dark:hover:bg-violet-900/40 transition-colors flex items-center justify-center"
				on:mousedown={(e) => {
					const startY = e.clientY;
					const startH = aiChatHeight;
					const onMove = (ev) => {
						aiChatHeight = Math.max(280, Math.min(window.innerHeight - 60, startH - (ev.clientY - startY)));
					};
					const onUp = () => {
						window.removeEventListener('mousemove', onMove);
						window.removeEventListener('mouseup', onUp);
					};
					window.addEventListener('mousemove', onMove);
					window.addEventListener('mouseup', onUp);
				}}
				role="separator"
				aria-orientation="horizontal"
			>
				<div class="w-8 h-0.5 rounded-full bg-gray-300 dark:bg-gray-600"></div>
			</div>

			<!-- Header -->
			<div class="flex items-center justify-between px-4 py-2 border-b border-gray-100 dark:border-gray-800">
				<div class="flex items-center gap-2">
					<div class="w-6 h-6 rounded-full bg-violet-100 dark:bg-violet-900/30 flex items-center justify-center">
						<svg class="w-3.5 h-3.5 text-violet-600 dark:text-violet-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z" />
						</svg>
					</div>
					<span class="text-sm font-medium text-gray-700 dark:text-gray-300">{$i18n.t('AI Dashboard Assistant')}</span>
					{#if aiDbOptions.length > 0}
						<div class="ml-2 min-w-[220px]">
							<Selector
								value={aiSelectedDb}
								items={[{ value: '', label: $i18n.t('Auto') }, ...aiDbOptions]}
								size="sm"
								portal="body"
								contentClassName="z-[99999]"
								placeholder={$i18n.t('Database')}
								on:change={(e) => { aiSelectedDb = e.detail.value; }}
							/>
						</div>
					{/if}
					{#if aiModelOptions.length > 0}
						<div class="ml-1 min-w-[220px]">
							<Selector
								value={aiChatModel}
								items={aiModelOptions}
								size="sm"
								portal="body"
								contentClassName="z-[99999]"
								on:change={(e) => { aiChatModel = e.detail.value; }}
							/>
						</div>
					{/if}
				</div>
				<button
					type="button"
					class="p-1 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-400"
					on:click={() => { showAIChat = false; }}
				>
					<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
					</svg>
				</button>
			</div>

			<!-- Messages -->
			<div class="flex-1 overflow-y-auto px-4 py-3 space-y-3">
				{#if aiChatMessages.length === 0}
					<div class="text-center py-6">
						<div class="w-12 h-12 rounded-full bg-violet-50 dark:bg-violet-900/20 flex items-center justify-center mx-auto mb-3">
							<svg class="w-6 h-6 text-violet-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
								<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z" />
							</svg>
						</div>
						<p class="text-sm text-gray-500 dark:text-gray-400 mb-3">{$i18n.t('Ask AI to build or modify your dashboard')}</p>
						<div class="flex flex-wrap gap-1.5 justify-center">
							{#each [
								$i18n.t('Create a sales overview dashboard'),
								$i18n.t('Add KPI cards for key metrics'),
								$i18n.t('Show a monthly trend chart'),
							] as suggestion}
								<button
									type="button"
									class="px-2.5 py-1 text-xs rounded-full border border-violet-200 dark:border-violet-700 text-violet-600 dark:text-violet-400 hover:bg-violet-50 dark:hover:bg-violet-900/20"
									on:click={() => { aiChatInput = suggestion; }}
								>
									{suggestion}
								</button>
							{/each}
						</div>
					</div>
				{/if}

				{#each aiChatMessages as msg}
					<div class="flex {msg.role === 'user' ? 'justify-end' : 'justify-start'}">
						<div class="max-w-[85%]">
							<div class="px-3 py-2 rounded-xl text-sm whitespace-pre-wrap {msg.role === 'user'
								? 'bg-violet-600 text-white rounded-br-sm'
								: 'bg-gray-100 dark:bg-gray-800 text-gray-800 dark:text-gray-200 rounded-bl-sm'}">
								{#if msg.loading}
									<div class="flex items-center gap-2">
										<Spinner className="size-4" />
										<span class="text-gray-500">{$i18n.t('Generating dashboard...')}</span>
									</div>
								{:else}
									{msg.content}
								{/if}
							</div>
							{#if msg.buttons && msg.buttons.length > 0}
								<div class="flex flex-wrap gap-1.5 mt-2">
									{#each msg.buttons as btn}
										<button
											type="button"
											class="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg
												border border-violet-200 dark:border-violet-700
												text-violet-700 dark:text-violet-300
												bg-white dark:bg-gray-800
												hover:bg-violet-50 dark:hover:bg-violet-900/20
												hover:border-violet-400 dark:hover:border-violet-500
												transition-all shadow-sm hover:shadow"
											on:click|stopPropagation|preventDefault={() => handleButtonClick(btn.value)}
										>
											{btn.label}
										</button>
									{/each}
								</div>
							{/if}
						</div>
					</div>
				{/each}
			</div>

			<!-- Input -->
			<div class="px-4 py-3 border-t border-gray-100 dark:border-gray-800">
				<div class="flex items-center gap-2">
					<input
						type="text"
						bind:value={aiChatInput}
						on:keydown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendAIChat(); } }}
						class="flex-1 px-3 py-2 text-sm rounded-xl border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 text-gray-900 dark:text-white focus:ring-2 focus:ring-violet-500 focus:border-transparent"
						placeholder={$i18n.t('Describe the dashboard you want...')}
						disabled={aiChatLoading}
					/>
					<button
						type="button"
						disabled={!aiChatInput.trim() || aiChatLoading}
						class="p-2 rounded-xl bg-violet-600 text-white hover:bg-violet-700 disabled:opacity-50 transition-colors"
						on:click={() => sendAIChat()}
					>
						<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
						</svg>
					</button>
				</div>
			</div>
		</div>
	{/if}
{/if}
</div>

<PanelEditor bind:show={showPanelEditor} editPanel={editingPanel} {filters} on:save={handleSavePanel} />

{#if dashboard}
	<ShareDashboardModal bind:show={showShareModal} bind:dashboard={dashboard} />
{/if}

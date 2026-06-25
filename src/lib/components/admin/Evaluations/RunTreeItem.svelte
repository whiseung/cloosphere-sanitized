<script lang="ts">
	import { createEventDispatcher } from 'svelte';
	import type { TraceRun } from '$lib/apis/traces';

	export let run: TraceRun;
	export let depth: number = 0;
	export let selectedRunId: string | null = null;

	const dispatch = createEventDispatcher<{ select: TraceRun }>();

	const RUN_TYPE_CONFIG: Record<string, { color: string; label: string; shortLabel: string }> = {
		chain: { color: 'bg-purple-500', label: 'CHAIN', shortLabel: 'CH' },
		llm: { color: 'bg-blue-500', label: 'LLM', shortLabel: 'LM' },
		tool: { color: 'bg-green-500', label: 'TOOL', shortLabel: 'TL' },
		retrieval: { color: 'bg-orange-500', label: 'RAG', shortLabel: 'RG' },
		web_search: { color: 'bg-cyan-500', label: 'WEB', shortLabel: 'WB' },
		guardrail: { color: 'bg-red-500', label: 'GUARD', shortLabel: 'GD' },
		embedding: { color: 'bg-yellow-500', label: 'EMBED', shortLabel: 'EM' },
		filter: { color: 'bg-pink-500', label: 'FILTER', shortLabel: 'FL' },
		pipeline: { color: 'bg-indigo-500', label: 'PIPE', shortLabel: 'PP' },
		task: { color: 'bg-slate-400', label: 'TASK', shortLabel: 'TK' }
	};

	const getRunTypeConfig = (runType: string) => {
		return RUN_TYPE_CONFIG[runType] || { color: 'bg-gray-500', label: runType.toUpperCase().slice(0, 5), shortLabel: runType.slice(0, 2).toUpperCase() };
	};

	const STATUS_ICONS: Record<string, { icon: string; color: string }> = {
		success: { icon: '●', color: 'text-green-500' },
		error: { icon: '●', color: 'text-red-500' },
		running: { icon: '◐', color: 'text-yellow-500' },
		pending: { icon: '○', color: 'text-gray-400' }
	};

	const formatDuration = (ms: number | null) => {
		if (ms === null) return '-';
		if (ms < 1000) return `${ms}ms`;
		if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
		return `${Math.floor(ms / 60000)}m`;
	};

	// 자식이 있는 TOOL인지 확인 (ACTION으로 표시할지)
	$: isAction = run.run_type === 'tool' && run.children && run.children.length > 0;

	// ACTION 접기/펴기 상태
	let actionExpanded = true;

	// ACTION인 경우 전체 시간 계산
	const calculateTotalLatency = (node: TraceRun): number => {
		let total = node.latency_ms || 0;
		if (node.children) {
			for (const child of node.children) {
				total += calculateTotalLatency(child);
			}
		}
		return total;
	};

	$: actionTotalLatency = isAction ? calculateTotalLatency(run) : null;

	// ACTION 내 전체 상태 계산
	const calculateOverallStatus = (node: TraceRun): string => {
		if (node.status === 'error') return 'error';
		if (node.children) {
			for (const child of node.children) {
				if (calculateOverallStatus(child) === 'error') return 'error';
			}
		}
		if (node.status === 'running') return 'running';
		return node.status;
	};

	$: actionStatus = isAction ? calculateOverallStatus(run) : run.status;

	const handleSelect = () => {
		dispatch('select', run);
	};

	const handleChildSelect = (event: CustomEvent<TraceRun>) => {
		dispatch('select', event.detail);
	};

	$: statusInfo = STATUS_ICONS[run.status] || STATUS_ICONS.pending;
	$: actionStatusInfo = STATUS_ICONS[actionStatus] || STATUS_ICONS.pending;
</script>

<div class="tree-item" style="margin-left: {depth * 14}px">
	{#if isAction}
		<!-- ACTION 그룹 헤더 -->
		<button
			class="w-full flex items-center gap-2 px-2 py-1.5 rounded text-left text-sm bg-violet-50 dark:bg-violet-900/20 hover:bg-violet-100 dark:hover:bg-violet-900/30 transition mb-1"
			on:click={() => actionExpanded = !actionExpanded}
		>
			<svg
				class="w-3 h-3 text-violet-500 shrink-0 transition-transform {actionExpanded ? 'rotate-90' : ''}"
				fill="none"
				stroke="currentColor"
				viewBox="0 0 24 24"
			>
				<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M9 5l7 7-7 7" />
			</svg>

			<span class="px-1.5 py-0.5 text-[10px] font-bold text-white rounded bg-violet-500">ACT</span>
			<span class="flex-1 text-violet-600 dark:text-violet-400 truncate">{run.name}</span>
			<span class="text-xs {actionStatusInfo.color}">{actionStatusInfo.icon}</span>
			<span class="text-xs text-gray-400 font-mono w-14 text-right">{formatDuration(actionTotalLatency)}</span>
		</button>

		<!-- ACTION 내부 -->
		{#if actionExpanded}
		<div class="ml-4 pl-2 border-l-2 border-violet-300 dark:border-violet-700">
			<!-- 원래 TOOL -->
			<button
				class="w-full flex items-center gap-2 px-2 py-1.5 rounded hover:bg-gray-100 dark:hover:bg-gray-800 text-left text-sm mb-1
					{selectedRunId === run.id ? 'bg-blue-50 dark:bg-blue-900/30 ring-1 ring-blue-200 dark:ring-blue-800' : ''}"
				on:click={handleSelect}
			>
				<span class="px-1.5 py-0.5 text-[10px] font-bold text-white rounded {getRunTypeConfig(run.run_type).color}">{getRunTypeConfig(run.run_type).shortLabel}</span>
				<span class="flex-1 truncate text-gray-700 dark:text-gray-300">{run.name}</span>
				<span class="text-xs {statusInfo.color}">{statusInfo.icon}</span>
				<span class="text-xs text-gray-400 font-mono w-14 text-right">{formatDuration(run.latency_ms)}</span>
			</button>

			<!-- 자식들 -->
			{#each run.children as child}
				{@const childStatus = STATUS_ICONS[child.status] || STATUS_ICONS.pending}
				<button
					class="w-full flex items-center gap-2 px-2 py-1.5 rounded hover:bg-gray-100 dark:hover:bg-gray-800 text-left text-sm mb-1
						{selectedRunId === child.id ? 'bg-blue-50 dark:bg-blue-900/30 ring-1 ring-blue-200 dark:ring-blue-800' : ''}"
					on:click={() => dispatch('select', child)}
				>
					<span class="px-1.5 py-0.5 text-[10px] font-bold text-white rounded {getRunTypeConfig(child.run_type).color}">{getRunTypeConfig(child.run_type).shortLabel}</span>
					<span class="flex-1 truncate text-gray-700 dark:text-gray-300">{child.name}</span>
					<span class="text-xs {childStatus.color}">{childStatus.icon}</span>
					<span class="text-xs text-gray-400 font-mono w-14 text-right">{formatDuration(child.latency_ms)}</span>
				</button>
			{/each}
		</div>
		{/if}
	{:else}
		<!-- 일반 항목 -->
		<button
			class="w-full flex items-center gap-2 px-2 py-1.5 rounded hover:bg-gray-100 dark:hover:bg-gray-800 text-left text-sm mb-1
				{selectedRunId === run.id ? 'bg-blue-50 dark:bg-blue-900/30 ring-1 ring-blue-200 dark:ring-blue-800' : ''}"
			on:click={handleSelect}
		>
			{#if run.children && run.children.length > 0}
				<svg class="w-3 h-3 text-gray-400 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M9 5l7 7-7 7" />
				</svg>
			{:else}
				<span class="w-3 shrink-0"></span>
			{/if}

			<span class="px-1.5 py-0.5 text-[10px] font-bold text-white rounded {getRunTypeConfig(run.run_type).color}">{getRunTypeConfig(run.run_type).shortLabel}</span>
			<span class="flex-1 truncate text-gray-700 dark:text-gray-300">{run.name}</span>
			<span class="text-xs {statusInfo.color}">{statusInfo.icon}</span>
			<span class="text-xs text-gray-400 font-mono w-14 text-right">{formatDuration(run.latency_ms)}</span>
		</button>

		{#if run.children && run.children.length > 0}
			<div class="ml-4 pl-2 border-l border-gray-200 dark:border-gray-700">
				{#each run.children as child}
					<svelte:self
						run={child}
						depth={depth + 1}
						{selectedRunId}
						on:select={handleChildSelect}
					/>
				{/each}
			</div>
		{/if}
	{/if}
</div>

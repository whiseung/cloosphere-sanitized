<script lang="ts">
	import { onMount, getContext } from 'svelte';
	import { page } from '$app/stores';
	import { toast } from 'svelte-sonner';

	import {
		getKnowledgeGraphById,
		type KnowledgeGraph
	} from '$lib/apis/knowledge-graph';
	import GraphView from '$lib/components/workspace/KnowledgeGraph/GraphView.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';

	const i18n = getContext<{ t: (key: string, params?: Record<string, unknown>) => string }>(
		'i18n'
	);

	let id = '';
	let kg: KnowledgeGraph | null = null;
	let loaded = false;

	const closeWindow = () => {
		// 새 창으로 열렸을 때만 닫힘 — 탭 안에서 직접 주소로 온 경우에는 상세 페이지로 이동
		if (window.opener) {
			window.close();
		} else {
			window.location.href = `/workspace/knowledge-graph/${id}`;
		}
	};

	onMount(async () => {
		id = $page.params.id;
		try {
			kg = await getKnowledgeGraphById(localStorage.token, id);
		} catch (e) {
			toast.error(`${e}`);
		}
		loaded = true;
	});
</script>

<svelte:head>
	<title>{kg?.name ?? 'Knowledge Graph'} — Fullscreen</title>
</svelte:head>

<div class="fixed inset-0 flex flex-col bg-white dark:bg-gray-900">
	<!-- Slim header -->
	<div
		class="flex items-center justify-between px-4 py-2 border-b border-[var(--cloo-border-subtle)] bg-white dark:bg-gray-900 shrink-0"
	>
		<div class="flex items-center gap-2 min-w-0">
			<span class="text-[10px] font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400">
				{$i18n.t('Knowledge Graph')}
			</span>
			<span class="text-gray-300 dark:text-gray-600">/</span>
			<h1 class="text-sm font-semibold text-gray-900 dark:text-white truncate">
				{kg?.name ?? ''}
			</h1>
		</div>
		<button
			type="button"
			class="flex items-center gap-1 px-2 py-1 rounded text-xs text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-800 transition"
			on:click={closeWindow}
			title={$i18n.t('Close')}
		>
			<svg class="size-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
				<path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
			</svg>
			<span>{$i18n.t('Close')}</span>
		</button>
	</div>

	<!-- Graph area fills the rest -->
	<div class="flex-1 min-h-0 overflow-hidden p-3">
		{#if !loaded}
			<div class="w-full h-full flex items-center justify-center">
				<Spinner />
			</div>
		{:else if kg}
			<GraphView kgId={id} height="calc(100vh - 80px)" showEdgeList={true} maxNodes={2000} />
		{:else}
			<div class="w-full h-full flex items-center justify-center text-gray-500">
				{$i18n.t('Knowledge Graph not found')}
			</div>
		{/if}
	</div>
</div>

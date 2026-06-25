<script lang="ts">
	import { getContext } from 'svelte';
	import type { TraceAnalysisResponse } from '$lib/apis/trace-analysis';
	import Modal from '$lib/components/common/Modal.svelte';
	import Markdown from '$lib/components/chat/Messages/Markdown.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import { toast } from 'svelte-sonner';

	const i18n = getContext('i18n');

	export let show = false;
	export let analysis: TraceAnalysisResponse | null = null;

	const copyReport = () => {
		if (analysis?.report) {
			navigator.clipboard.writeText(analysis.report);
			toast.success($i18n.t('Copied to clipboard'));
		}
	};

	const downloadReport = () => {
		if (analysis?.report) {
			const blob = new Blob([analysis.report], { type: 'text/markdown' });
			const url = URL.createObjectURL(blob);
			const a = document.createElement('a');
			a.href = url;
			a.download = `trace_analysis_${analysis.trace_id.slice(0, 8)}.md`;
			a.click();
			URL.revokeObjectURL(url);
		}
	};

	const getStatusBadge = (status: string) => {
		switch (status) {
			case 'completed':
				return 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400';
			case 'failed':
				return 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400';
			case 'running':
				return 'bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-400';
			default:
				return 'bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-400';
		}
	};
</script>

<Modal size="lg" bind:show className="bg-white dark:bg-gray-900 rounded-2xl max-w-4xl">
	<div class="px-6 py-5">
		<!-- Header -->
		<div class="flex justify-between items-center mb-4 text-gray-900 dark:text-gray-100">
			<div class="flex items-center gap-3">
				<div class="text-xl font-semibold">{$i18n.t('Trace Analysis Report')}</div>
				{#if analysis}
					<span class="px-2 py-0.5 text-xs font-medium rounded-full {getStatusBadge(analysis.status)}">
						{analysis.status}
					</span>
				{/if}
			</div>
			<div class="flex items-center gap-1">
				{#if analysis?.status === 'completed'}
					<!-- Copy -->
					<button
						class="p-1.5 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-lg"
						title={$i18n.t('Copy')}
						on:click={copyReport}
					>
						<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="size-4">
							<path d="M7 3.5A1.5 1.5 0 0 1 8.5 2h3.879a1.5 1.5 0 0 1 1.06.44l3.122 3.12A1.5 1.5 0 0 1 17 6.622V12.5a1.5 1.5 0 0 1-1.5 1.5h-1v-3.379a3 3 0 0 0-.879-2.121L10.5 5.379A3 3 0 0 0 8.379 4.5H7v-1Z" />
							<path d="M4.5 6A1.5 1.5 0 0 0 3 7.5v9A1.5 1.5 0 0 0 4.5 18h7a1.5 1.5 0 0 0 1.5-1.5v-5.879a1.5 1.5 0 0 0-.44-1.06L9.44 6.439A1.5 1.5 0 0 0 8.378 6H4.5Z" />
						</svg>
					</button>
					<!-- Download -->
					<button
						class="p-1.5 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-lg"
						title={$i18n.t('Download')}
						on:click={downloadReport}
					>
						<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="size-4">
							<path d="M10.75 2.75a.75.75 0 0 0-1.5 0v8.614L6.295 8.235a.75.75 0 1 0-1.09 1.03l4.25 4.5a.75.75 0 0 0 1.09 0l4.25-4.5a.75.75 0 0 0-1.09-1.03l-2.955 3.129V2.75Z" />
							<path d="M3.5 12.75a.75.75 0 0 0-1.5 0v2.5A2.75 2.75 0 0 0 4.75 18h10.5A2.75 2.75 0 0 0 18 15.25v-2.5a.75.75 0 0 0-1.5 0v2.5c0 .69-.56 1.25-1.25 1.25H4.75c-.69 0-1.25-.56-1.25-1.25v-2.5Z" />
						</svg>
					</button>
				{/if}
				<!-- Close -->
				<button
					class="p-1.5 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-lg"
					on:click={() => (show = false)}
				>
					<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="size-5">
						<path d="M6.28 5.22a.75.75 0 0 0-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 1 0 1.06 1.06L10 11.06l3.72 3.72a.75.75 0 1 0 1.06-1.06L11.06 10l3.72-3.72a.75.75 0 0 0-1.06-1.06L10 8.94 6.28 5.22Z" />
					</svg>
				</button>
			</div>
		</div>

		{#if analysis}
			<!-- Context Summary -->
			{#if analysis.context_summary}
				<div class="flex flex-wrap items-center gap-3 mb-4 text-xs text-gray-500 dark:text-gray-400">
					{#if analysis.context_summary.analysis_model}
						<span class="bg-gray-100 dark:bg-gray-800 px-2 py-1 rounded">
							{$i18n.t('Analysis Model')}: <strong>{analysis.context_summary.analysis_model}</strong>
						</span>
					{/if}
					<span class="bg-gray-100 dark:bg-gray-800 px-2 py-1 rounded">
						{$i18n.t('Runs')}: <strong>{analysis.context_summary.run_count}</strong>
					</span>
					<span class="bg-gray-100 dark:bg-gray-800 px-2 py-1 rounded">
						{$i18n.t('Errors')}: <strong class="{analysis.context_summary.error_count > 0 ? 'text-red-500' : ''}">{analysis.context_summary.error_count}</strong>
					</span>
					{#if analysis.context_summary.has_knowledge}
						<span class="bg-blue-50 dark:bg-blue-900/20 text-blue-600 dark:text-blue-400 px-2 py-1 rounded">KB</span>
					{/if}
					{#if analysis.context_summary.has_dbsphere}
						<span class="bg-purple-50 dark:bg-purple-900/20 text-purple-600 dark:text-purple-400 px-2 py-1 rounded">DB</span>
					{/if}
					{#if analysis.context_summary.has_guardrails}
						<span class="bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400 px-2 py-1 rounded">Guard</span>
					{/if}
					{#if analysis.context_summary.has_glossary}
						<span class="bg-green-50 dark:bg-green-900/20 text-green-600 dark:text-green-400 px-2 py-1 rounded">Glossary</span>
					{/if}
				</div>
			{/if}

			<!-- Content -->
			<div class="overflow-y-auto" style="max-height: calc(100vh - 220px);">
				{#if analysis.status === 'completed' && analysis.report}
					<div class="prose dark:prose-invert prose-sm max-w-none">
						<Markdown content={analysis.report} />
					</div>
				{:else if analysis.status === 'failed'}
					<div class="text-center py-12">
						<div class="text-red-500 text-lg mb-2">{$i18n.t('Analysis Failed')}</div>
						{#if analysis.error_message}
							<div class="text-sm text-gray-500 dark:text-gray-400 bg-red-50 dark:bg-red-900/20 p-3 rounded-lg">
								{analysis.error_message}
							</div>
						{/if}
					</div>
				{:else}
					<!-- running / pending -->
					<div class="text-center py-16">
						<Spinner className="size-8 mx-auto mb-4" />
						<div class="text-gray-500 dark:text-gray-400">{$i18n.t('Analyzing trace...')}</div>
					</div>
				{/if}
			</div>
		{/if}
	</div>
</Modal>

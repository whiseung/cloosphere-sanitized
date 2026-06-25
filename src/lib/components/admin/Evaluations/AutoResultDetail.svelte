<script lang="ts">
	import { createEventDispatcher, getContext, onMount } from 'svelte';
	import dayjs from 'dayjs';
	import type { AutoEvaluation } from '$lib/apis/auto-evaluations';
	import { getAutoEvaluationById } from '$lib/apis/auto-evaluations';
	import Modal from '$lib/components/common/Modal.svelte';
	import Badge from '$lib/components/common/Badge.svelte';

	const i18n = getContext('i18n');
	const dispatch = createEventDispatcher();

	export let evaluation: AutoEvaluation;

	let fullEvaluation: AutoEvaluation | null = null;
	let loading = true;

	let showModal = true;

	function close() {
		dispatch('close');
	}

	$: if (!showModal) {
		close();
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

	function getEvaluationTypeName(type: string): string {
		switch (type) {
			case 'retrieval':
				return $i18n.t('Retrieval Quality');
			case 'faithfulness':
				return $i18n.t('Faithfulness');
			case 'quality':
				return $i18n.t('Response Quality');
			default:
				return type;
		}
	}

	onMount(async () => {
		try {
			fullEvaluation = await getAutoEvaluationById(localStorage.token, evaluation.id);
		} catch (err) {
			console.error('Failed to load evaluation details:', err);
			fullEvaluation = evaluation;
		}
		loading = false;
	});
</script>

<Modal size="lg" bind:show={showModal} on:close={close}>
	<div class="px-6 py-5">
		<!-- Header -->
		<div class="flex justify-between items-start mb-4">
			<div>
				<h2 class="text-lg font-semibold">{$i18n.t('Evaluation Details')}</h2>
				<p class="text-sm text-gray-500">ID: {evaluation.id}</p>
			</div>
			<button
				class="p-1 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-lg"
				on:click={close}
			>
				<svg
					xmlns="http://www.w3.org/2000/svg"
					viewBox="0 0 20 20"
					fill="currentColor"
					class="size-5"
				>
					<path
						d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z"
					/>
				</svg>
			</button>
		</div>

		{#if loading}
			<div class="flex justify-center items-center py-12">
				<svg
					class="animate-spin size-8 text-gray-500"
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
		{:else if fullEvaluation}
			<div class="space-y-6">
				<!-- Basic Info -->
				<div class="grid grid-cols-2 md:grid-cols-4 gap-4">
					<div>
						<div class="text-xs text-gray-500 dark:text-gray-400 mb-1">{$i18n.t('Status')}</div>
						<Badge
							type={getStatusBadgeType(fullEvaluation.status)}
							content={$i18n.t(fullEvaluation.status.charAt(0).toUpperCase() + fullEvaluation.status.slice(1))}
						/>
					</div>
					<div>
						<div class="text-xs text-gray-500 dark:text-gray-400 mb-1">{$i18n.t('Score')}</div>
						<div class="text-lg font-bold {getScoreColor(fullEvaluation.score)}">
							{formatScore(fullEvaluation.score)}
						</div>
					</div>
					<div>
						<div class="text-xs text-gray-500 dark:text-gray-400 mb-1">{$i18n.t('Type')}</div>
						<div class="font-medium">{$i18n.t(getEvaluationTypeName(fullEvaluation.evaluation_type))}</div>
					</div>
					<div>
						<div class="text-xs text-gray-500 dark:text-gray-400 mb-1">{$i18n.t('Created')}</div>
						<div class="text-sm">{dayjs(fullEvaluation.created_at * 1000).format('YYYY-MM-DD HH:mm:ss')}</div>
					</div>
				</div>

				<!-- Models -->
				<div class="grid grid-cols-1 md:grid-cols-2 gap-4">
					<div>
						<div class="text-xs text-gray-500 dark:text-gray-400 mb-1">{$i18n.t('Evaluated Model')}</div>
						<div class="font-medium text-sm bg-gray-50 dark:bg-gray-900 rounded-lg px-3 py-2">
							{fullEvaluation.model_id}
						</div>
					</div>
					<div>
						<div class="text-xs text-gray-500 dark:text-gray-400 mb-1">{$i18n.t('Judge Model')}</div>
						<div class="font-medium text-sm bg-gray-50 dark:bg-gray-900 rounded-lg px-3 py-2">
							{fullEvaluation.judge_model_id}
						</div>
					</div>
				</div>

				<!-- Error Message (if failed) -->
				{#if fullEvaluation.status === 'failed' && fullEvaluation.error_message}
					<div>
						<div class="text-xs text-gray-500 dark:text-gray-400 mb-1">{$i18n.t('Error')}</div>
						<div class="text-sm bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-300 rounded-lg px-3 py-2">
							{fullEvaluation.error_message}
						</div>
					</div>
				{/if}

				<!-- Reasoning -->
				{#if fullEvaluation.reasoning}
					<div>
						<div class="text-xs text-gray-500 dark:text-gray-400 mb-1">{$i18n.t('Evaluation Reasoning')}</div>
						<div class="text-sm bg-blue-50 dark:bg-blue-900/20 rounded-lg px-3 py-2 whitespace-pre-wrap">
							{fullEvaluation.reasoning}
						</div>
					</div>
				{/if}

				<!-- User Query -->
				{#if fullEvaluation.user_query}
					<div>
						<div class="text-xs text-gray-500 dark:text-gray-400 mb-1">{$i18n.t('User Query')}</div>
						<div class="text-sm bg-gray-50 dark:bg-gray-900 rounded-lg px-3 py-2 max-h-32 overflow-y-auto">
							{fullEvaluation.user_query}
						</div>
					</div>
				{/if}

				<!-- Assistant Response -->
				{#if fullEvaluation.assistant_response}
					<div>
						<div class="text-xs text-gray-500 dark:text-gray-400 mb-1">{$i18n.t('Assistant Response')}</div>
						<div class="text-sm bg-gray-50 dark:bg-gray-900 rounded-lg px-3 py-2 max-h-48 overflow-y-auto whitespace-pre-wrap">
							{fullEvaluation.assistant_response}
						</div>
					</div>
				{/if}

				<!-- Retrieved Contexts -->
				{#if fullEvaluation.retrieved_contexts && fullEvaluation.retrieved_contexts.length > 0}
					<div>
						<div class="text-xs text-gray-500 dark:text-gray-400 mb-1">
							{$i18n.t('Retrieved Contexts')} ({fullEvaluation.retrieved_contexts.length})
						</div>
						<div class="space-y-2 max-h-64 overflow-y-auto">
							{#each fullEvaluation.retrieved_contexts as context, idx}
								<div class="text-sm bg-gray-50 dark:bg-gray-900 rounded-lg px-3 py-2">
									<div class="flex items-center gap-2 mb-1">
										<span class="text-xs font-semibold text-gray-500">#{idx + 1}</span>
										{#if context.source}
											<span class="text-xs text-gray-400">{context.source}</span>
										{/if}
									</div>
									<div class="text-xs whitespace-pre-wrap line-clamp-3">
										{context.content || context.text || JSON.stringify(context)}
									</div>
								</div>
							{/each}
						</div>
					</div>
				{/if}

				<!-- Details JSON (if any) -->
				{#if fullEvaluation.details && Object.keys(fullEvaluation.details).length > 0}
					<div>
						<div class="text-xs text-gray-500 dark:text-gray-400 mb-1">{$i18n.t('Additional Details')}</div>
						<pre class="text-xs bg-gray-50 dark:bg-gray-900 text-gray-900 dark:text-gray-200 rounded-lg px-3 py-2 overflow-x-auto">
{JSON.stringify(fullEvaluation.details, null, 2)}
						</pre>
					</div>
				{/if}

				<!-- User Info -->
				{#if fullEvaluation.user}
					<div class="pt-4 border-t border-gray-100 dark:border-gray-850">
						<div class="flex items-center gap-2">
							<div class="text-xs text-gray-500 dark:text-gray-400">{$i18n.t('Evaluated by')}:</div>
							<div class="text-sm font-medium">{fullEvaluation.user.name}</div>
							<div class="text-xs text-gray-400">({fullEvaluation.user.email})</div>
						</div>
					</div>
				{/if}
			</div>
		{/if}
	</div>
</Modal>

<script lang="ts">
	import { createEventDispatcher, getContext } from 'svelte';
	import dayjs from 'dayjs';
	import Badge from '$lib/components/common/Badge.svelte';
	import Button from '$lib/components/common/Button.svelte';
	import Modal from '$lib/components/common/Modal.svelte';

	const i18n = getContext('i18n');
	const dispatch = createEventDispatcher();

	export let feedback: {
		id: string;
		data: {
			rating: number;
			model_id: string;
			sibling_model_ids: string[] | null;
			reason: string;
			comment: string;
			tags?: string[];
		};
		meta?: {
			arena?: boolean;
			chat_id?: string;
			message_id?: string;
			tags?: string[];
		};
		user: {
			name: string;
			profile_image_url: string;
		};
		updated_at: number;
		snapshot?: any;
	};

	// tags can be in data or meta
	$: tags = feedback.data?.tags ?? feedback.meta?.tags ?? [];

	let showModal = true;

	function close() {
		showModal = false;
		dispatch('close');
	}

	function getRatingBadge(rating: number): { type: 'success' | 'warning' | 'error' | 'info' | 'muted'; label: string } {
		switch (rating.toString()) {
			case '1':
				return { type: 'info', label: 'Won' };
			case '0':
				return { type: 'muted', label: 'Draw' };
			case '-1':
				return { type: 'error', label: 'Lost' };
			default:
				return { type: 'muted', label: 'Unknown' };
		}
	}

	$: ratingInfo = getRatingBadge(feedback.data.rating);
</script>

<Modal size="md" bind:show={showModal} on:close={close}>
	<div class="px-6 py-5">
		<!-- Header -->
		<div class="flex justify-between items-start mb-4">
			<div>
				<h2 class="text-lg font-semibold">{$i18n.t('Feedback Details')}</h2>
				<div class="flex flex-col gap-0.5 mt-1">
					<p class="text-xs text-gray-500 dark:text-gray-400">
						<span class="text-gray-400 dark:text-gray-500">ID:</span> {feedback.id}
					</p>
					{#if feedback.meta?.message_id}
						<p class="text-xs text-gray-500 dark:text-gray-400">
							<span class="text-gray-400 dark:text-gray-500">{$i18n.t('Message ID')}:</span> {feedback.meta.message_id}
						</p>
					{/if}
					{#if feedback.meta?.chat_id}
						<p class="text-xs text-gray-500 dark:text-gray-400">
							<span class="text-gray-400 dark:text-gray-500">{$i18n.t('Chat ID')}:</span> {feedback.meta.chat_id}
						</p>
					{/if}
					{#if feedback.meta?.chat_id || feedback.meta?.message_id}
						<div class="mt-1.5">
							<Button
								kind="text"
								size="sm"
								type="button"
								on:click={() => {
									const chatId = feedback.meta?.chat_id ?? '';
									window.open(`/admin/evaluations?tab=tracing&chat_id=${chatId}`, '_blank');
								}}
							>
								<svelte:fragment slot="prefix">
									<svg
										xmlns="http://www.w3.org/2000/svg"
										fill="none"
										viewBox="0 0 24 24"
										stroke-width="1.5"
										stroke="currentColor"
										class="w-3 h-3"
									>
										<path
											stroke-linecap="round"
											stroke-linejoin="round"
											d="M13.19 8.688a4.5 4.5 0 0 1 1.242 7.244l-4.5 4.5a4.5 4.5 0 0 1-6.364-6.364l1.757-1.757m13.35-.622 1.757-1.757a4.5 4.5 0 0 0-6.364-6.364l-4.5 4.5a4.5 4.5 0 0 0 1.242 7.244"
										/>
									</svg>
								</svelte:fragment>
								{$i18n.t('View Trace')}
							</Button>
						</div>
					{/if}
				</div>
			</div>
			<button
				class="p-1 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-lg"
				type="button"
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

		<div class="space-y-4">
			<!-- User & Result -->
			<div class="grid grid-cols-2 gap-4">
				<div>
					<div class="text-xs text-gray-500 dark:text-gray-400 mb-1">{$i18n.t('User')}</div>
					<div class="flex items-center gap-2">
						<img
							src={feedback.user?.profile_image_url ?? '/user.png'}
							alt={feedback.user?.name}
							class="size-6 rounded-full object-cover"
						/>
						<span class="font-medium text-sm">{feedback.user?.name ?? $i18n.t('Unknown')}</span>
					</div>
				</div>
				<div>
					<div class="text-xs text-gray-500 dark:text-gray-400 mb-1">{$i18n.t('Result')}</div>
					<Badge type={ratingInfo.type} content={$i18n.t(ratingInfo.label)} />
				</div>
			</div>

			<!-- Models -->
			<div>
				<div class="text-xs text-gray-500 dark:text-gray-400 mb-1">{$i18n.t('Evaluated Model')}</div>
				<div class="font-medium text-sm bg-gray-50 dark:bg-gray-850 rounded-lg px-3 py-2">
					{feedback.data.model_id}
				</div>
			</div>

			{#if feedback.data.sibling_model_ids && feedback.data.sibling_model_ids.length > 0}
				<div>
					<div class="text-xs text-gray-500 dark:text-gray-400 mb-1">{$i18n.t('Compared Models')}</div>
					<div class="flex flex-wrap gap-2">
						{#each feedback.data.sibling_model_ids as modelId}
							<div class="text-xs bg-gray-100 dark:bg-gray-800 rounded-lg px-2 py-1">
								{modelId}
							</div>
						{/each}
					</div>
				</div>
			{/if}

			<!-- Reason -->
			{#if feedback.data.reason}
				<div>
					<div class="text-xs text-gray-500 dark:text-gray-400 mb-1">{$i18n.t('Reason')}</div>
					<div class="text-sm bg-blue-50 dark:bg-blue-900/20 rounded-lg px-3 py-2">
						{feedback.data.reason}
					</div>
				</div>
			{/if}

			<!-- Comment -->
			{#if feedback.data.comment}
				<div>
					<div class="text-xs text-gray-500 dark:text-gray-400 mb-1">{$i18n.t('Comment')}</div>
					<div class="text-sm bg-gray-50 dark:bg-gray-850 rounded-lg px-3 py-2 whitespace-pre-wrap max-h-48 overflow-y-auto">
						{feedback.data.comment}
					</div>
				</div>
			{/if}

			<!-- Tags -->
			{#if tags && tags.length > 0}
				<div>
					<div class="text-xs text-gray-500 dark:text-gray-400 mb-1">{$i18n.t('Tags')}</div>
					<div class="flex flex-wrap gap-2">
						{#each tags as tag}
							<span class="text-xs bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 rounded-full px-2 py-0.5">
								{tag}
							</span>
						{/each}
					</div>
				</div>
			{/if}

			<!-- Updated At -->
			<div class="pt-3 border-t border-gray-100 dark:border-gray-850">
				<div class="flex items-center justify-between text-xs text-gray-500 dark:text-gray-400">
					<span>{$i18n.t('Updated')}</span>
					<span>{dayjs(feedback.updated_at * 1000).format('YYYY-MM-DD HH:mm:ss')}</span>
				</div>
			</div>
		</div>
	</div>
</Modal>

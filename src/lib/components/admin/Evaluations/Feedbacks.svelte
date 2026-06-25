<script lang="ts">
	import { toast } from 'svelte-sonner';
	import fileSaver from 'file-saver';
	const { saveAs } = fileSaver;

	import dayjs from 'dayjs';
	import relativeTime from 'dayjs/plugin/relativeTime';
	dayjs.extend(relativeTime);

	import { onMount, getContext } from 'svelte';
	const i18n = getContext('i18n');

	import { deleteFeedbackById, exportAllFeedbacks, getAllFeedbacks } from '$lib/apis/evaluations';

	import Badge from '$lib/components/common/Badge.svelte';
	import Button from '$lib/components/common/Button.svelte';
	import Pagination from '$lib/components/common/Pagination.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import ArrowDownTray from '$lib/components/icons/ArrowDownTray.svelte';
	import CloudArrowUp from '$lib/components/icons/CloudArrowUp.svelte';
	import FeedbackMenu from './FeedbackMenu.svelte';
	import EllipsisHorizontal from '$lib/components/icons/EllipsisHorizontal.svelte';
	import FeedbackDetailModal from './FeedbackDetailModal.svelte';

	export let feedbacks = [];

	let page = 1;
	$: paginatedFeedbacks = feedbacks.slice((page - 1) * 10, page * 10);

	let selectedFeedback: Feedback | null = null;

	type Feedback = {
		id: string;
		data: {
			rating: number;
			model_id: string;
			sibling_model_ids: string[] | null;
			reason: string;
			comment: string;
			tags: string[];
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
	};

	type ModelStats = {
		rating: number;
		won: number;
		lost: number;
	};

	//////////////////////
	//
	// CRUD operations
	//
	//////////////////////

	const deleteFeedbackHandler = async (feedbackId: string) => {
		const response = await deleteFeedbackById(localStorage.token, feedbackId).catch((err) => {
			toast.error(err);
			return null;
		});
		if (response) {
			feedbacks = feedbacks.filter((f) => f.id !== feedbackId);
		}
	};

	const shareHandler = async () => {
		toast.success($i18n.t('Redirecting you to Open WebUI Community'));

		// remove snapshot from feedbacks
		const feedbacksToShare = feedbacks.map((f) => {
			const { snapshot, user, ...rest } = f;
			return rest;
		});
		console.log(feedbacksToShare);

		const url = 'https://openwebui.com';
		const tab = await window.open(`${url}/leaderboard`, '_blank');

		// Define the event handler function
		const messageHandler = (event) => {
			if (event.origin !== url) return;
			if (event.data === 'loaded') {
				tab.postMessage(JSON.stringify(feedbacksToShare), '*');

				// Remove the event listener after handling the message
				window.removeEventListener('message', messageHandler);
			}
		};

		window.addEventListener('message', messageHandler, false);
	};

	const exportHandler = async () => {
		const _feedbacks = await exportAllFeedbacks(localStorage.token).catch((err) => {
			toast.error(err);
			return null;
		});

		if (_feedbacks) {
			let blob = new Blob([JSON.stringify(_feedbacks)], {
				type: 'application/json'
			});
			saveAs(blob, `feedback-history-export-${Date.now()}.json`);
		}
	};
</script>

<div class="mt-0.5 mb-2 gap-1 flex flex-row justify-between">
	<div class="flex md:self-center text-lg font-medium px-0.5">
		{$i18n.t('Feedback History')}

		<div class="flex self-center w-[1px] h-6 mx-2.5 bg-gray-50 dark:bg-gray-850" />

		<span class="text-lg font-medium text-gray-500 dark:text-gray-300">{feedbacks.length}</span>
	</div>

	{#if feedbacks.length > 0}
		<div>
			<Tooltip content={$i18n.t('Export')}>
				<Button
					kind="text"
					size="sm"
					type="button"
					on:click={() => {
						exportHandler();
					}}
				>
					<svelte:fragment slot="prefix">
						<ArrowDownTray className="size-3" />
					</svelte:fragment>
				</Button>
			</Tooltip>
		</div>
	{/if}
</div>

<div
	class="scrollbar-hidden relative whitespace-nowrap overflow-x-auto max-w-full rounded-sm pt-0.5"
>
	{#if (feedbacks ?? []).length === 0}
		<div class="text-center text-xs text-gray-500 dark:text-gray-400 py-1">
			{$i18n.t('No feedbacks found')}
		</div>
	{:else}
		<table
			class="w-full text-sm text-left text-gray-500 dark:text-gray-400 table-auto max-w-full rounded-sm"
		>
			<thead
				class="text-xs text-gray-700 uppercase bg-gray-50 dark:bg-gray-850 dark:text-gray-400 -translate-y-0.5"
			>
				<tr class="">
					<th scope="col" class="px-3 text-right cursor-pointer select-none w-0">
						{$i18n.t('User')}
					</th>

					<th scope="col" class="px-3 pr-1.5 cursor-pointer select-none">
						{$i18n.t('Models')}
					</th>

					<th scope="col" class="px-3 py-1.5 text-right cursor-pointer select-none w-fit">
						{$i18n.t('Result')}
					</th>

					<th scope="col" class="px-3 py-1.5 text-right cursor-pointer select-none w-0">
						{$i18n.t('Updated At')}
					</th>

					<th scope="col" class="px-3 py-1.5 text-right cursor-pointer select-none w-0"> </th>
				</tr>
			</thead>
			<tbody class="">
				{#each paginatedFeedbacks as feedback (feedback.id)}
					<tr
						class="bg-white dark:bg-gray-900 dark:border-gray-850 text-xs hover:bg-gray-50 dark:hover:bg-gray-850 cursor-pointer transition"
						on:click={() => {
							selectedFeedback = feedback;
						}}
					>
						<td class=" py-0.5 text-right font-semibold">
							<div class="flex justify-center">
								<Tooltip content={feedback?.user?.name}>
									<div class="shrink-0">
										<img
											src={feedback?.user?.profile_image_url ?? '/user.png'}
											alt={feedback?.user?.name}
											class="size-5 rounded-full object-cover shrink-0"
										/>
									</div>
								</Tooltip>
							</div>
						</td>

						<td class=" py-1 pl-3 flex flex-col">
							<div class="flex flex-col items-start gap-0.5 h-full">
								<div class="flex flex-col h-full">
									{#if feedback.data?.sibling_model_ids}
										<div class="font-semibold text-gray-600 dark:text-gray-400 flex-1">
											{feedback.data?.model_id}
										</div>

										<Tooltip content={feedback.data.sibling_model_ids.join(', ')}>
											<div class=" text-[0.65rem] text-gray-600 dark:text-gray-400 line-clamp-1">
												{#if feedback.data.sibling_model_ids.length > 2}
													<!-- {$i18n.t('and {{COUNT}} more')} -->
													{feedback.data.sibling_model_ids.slice(0, 2).join(', ')}, {$i18n.t(
														'and {{COUNT}} more',
														{ COUNT: feedback.data.sibling_model_ids.length - 2 }
													)}
												{:else}
													{feedback.data.sibling_model_ids.join(', ')}
												{/if}
											</div>
										</Tooltip>
									{:else}
										<div
											class=" text-sm font-medium text-gray-600 dark:text-gray-400 flex-1 py-1.5"
										>
											{feedback.data?.model_id}
										</div>
									{/if}
								</div>
							</div>
						</td>
						<td class="px-3 py-1 text-right font-medium text-gray-900 dark:text-white w-max">
							<div class=" flex justify-end">
								{#if feedback.data.rating.toString() === '1'}
									<Badge type="info" content={$i18n.t('Won')} />
								{:else if feedback.data.rating.toString() === '0'}
									<Badge type="muted" content={$i18n.t('Draw')} />
								{:else if feedback.data.rating.toString() === '-1'}
									<Badge type="error" content={$i18n.t('Lost')} />
								{/if}
							</div>
						</td>

						<td class=" px-3 py-1 text-right font-medium">
							{dayjs(feedback.updated_at * 1000).fromNow()}
						</td>

						<td class=" px-3 py-1 text-right font-semibold">
							<!-- svelte-ignore a11y-click-events-have-key-events -->
							<!-- svelte-ignore a11y-no-static-element-interactions -->
							<div
								class="flex items-center justify-end gap-1"
								on:click|stopPropagation={() => {}}
							>
								{#if feedback.meta?.chat_id || feedback.meta?.message_id}
									<Tooltip content={$i18n.t('View Trace')}>
										<button
											type="button"
											class="self-center w-fit text-sm p-1 text-gray-400 dark:text-gray-500 hover:text-gray-600 dark:hover:text-gray-300 rounded-lg transition"
											on:click={() => {
												const chatId = feedback.meta?.chat_id ?? '';
												window.open(`/admin/evaluations?tab=tracing&chat_id=${chatId}`, '_blank');
											}}
										>
											<svg
												xmlns="http://www.w3.org/2000/svg"
												fill="none"
												viewBox="0 0 24 24"
												stroke-width="1.5"
												stroke="currentColor"
												class="w-3.5 h-3.5"
											>
												<path
													stroke-linecap="round"
													stroke-linejoin="round"
													d="M13.19 8.688a4.5 4.5 0 0 1 1.242 7.244l-4.5 4.5a4.5 4.5 0 0 1-6.364-6.364l1.757-1.757m13.35-.622 1.757-1.757a4.5 4.5 0 0 0-6.364-6.364l-4.5 4.5a4.5 4.5 0 0 0 1.242 7.244"
												/>
											</svg>
										</button>
									</Tooltip>
								{/if}
								<FeedbackMenu
									on:delete={(e) => {
										deleteFeedbackHandler(feedback.id);
									}}
								>
									<button
										class="self-center w-fit text-sm p-1.5 dark:text-gray-300 dark:hover:text-white hover:bg-black/5 dark:hover:bg-white/5 rounded-xl"
									>
										<EllipsisHorizontal />
									</button>
								</FeedbackMenu>
							</div>
						</td>
					</tr>
				{/each}
			</tbody>
		</table>
	{/if}
</div>

{#if feedbacks.length > 0}
	<div class=" flex flex-col justify-end w-full text-right gap-1">
		<div class="line-clamp-1 text-gray-500 text-xs">
			{$i18n.t('Help us create the best community leaderboard by sharing your feedback history!')}
		</div>

		<div class="flex space-x-1 ml-auto">
			<Tooltip
				content={$i18n.t(
					'To protect your privacy, only ratings, model IDs, tags, and metadata are shared from your feedback—your chat logs remain private and are not included.'
				)}
			>
				<Button
					kind="outlined"
					size="sm"
					type="button"
					on:click={async () => {
						shareHandler();
					}}
				>
					{$i18n.t('Share to Open WebUI Community')}
					<svelte:fragment slot="suffix">
						<CloudArrowUp className="size-3" strokeWidth="3" />
					</svelte:fragment>
				</Button>
			</Tooltip>
		</div>
	</div>
{/if}

{#if feedbacks.length > 10}
	<Pagination bind:page count={feedbacks.length} perPage={10} />
{/if}

{#if selectedFeedback}
	<FeedbackDetailModal
		feedback={selectedFeedback}
		on:close={() => {
			selectedFeedback = null;
		}}
	/>
{/if}

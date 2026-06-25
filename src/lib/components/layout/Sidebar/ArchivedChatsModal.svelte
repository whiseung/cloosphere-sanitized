<script lang="ts">
	import fileSaver from 'file-saver';
	const { saveAs } = fileSaver;
	import { toast } from 'svelte-sonner';
	import dayjs from 'dayjs';
	import { getContext } from 'svelte';
	import localizedFormat from 'dayjs/plugin/localizedFormat';

	dayjs.extend(localizedFormat);

	import {
		archiveChatById,
		deleteChatById,
		getAllArchivedChats,
		getArchivedChatList,
		getChatList,
		getPinnedChatList
	} from '$lib/apis/chats';
	import {
		chats as globalChats,
		pinnedChats,
		currentChatPage,
		scrollPaginationEnabled
	} from '$lib/stores';

	import Modal from '$lib/components/common/Modal.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import Button from '$lib/components/common/Button.svelte';
	import Input from '$lib/components/common/Input.svelte';
	import UnarchiveAllConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';
	import XMark from '$lib/components/icons/XMark.svelte';
	import Search from '$lib/components/icons/Search.svelte';
	import GarbageBin from '$lib/components/icons/GarbageBin.svelte';
	import ArchiveBoxArrowUp from '$lib/components/icons/ArchiveBoxArrowUp.svelte';
	const i18n = getContext('i18n');

	export let show = false;

	let chats = [];

	let searchValue = '';
	let showUnarchiveAllConfirmDialog = false;

	const refreshMainChatList = async () => {
		currentChatPage.set(1);
		scrollPaginationEnabled.set(true);
		globalChats.set(await getChatList(localStorage.token, 1, true));
		pinnedChats.set(await getPinnedChatList(localStorage.token));
	};

	const unarchiveChatHandler = async (chatId) => {
		const res = await archiveChatById(localStorage.token, chatId).catch((error) => {
			toast.error($i18n.t(`${error}`));
		});

		chats = await getArchivedChatList(localStorage.token);
		await refreshMainChatList();
	};

	const deleteChatHandler = async (chatId) => {
		const res = await deleteChatById(localStorage.token, chatId).catch((error) => {
			toast.error($i18n.t(`${error}`));
		});

		chats = await getArchivedChatList(localStorage.token);
	};

	const exportChatsHandler = async () => {
		const chats = await getAllArchivedChats(localStorage.token);
		let blob = new Blob([JSON.stringify(chats)], {
			type: 'application/json'
		});
		saveAs(blob, `${$i18n.t('archived-chat-export')}-${Date.now()}.json`);
	};

	const unarchiveAllHandler = async () => {
		for (const chat of chats) {
			await archiveChatById(localStorage.token, chat.id);
		}
		chats = await getArchivedChatList(localStorage.token);
		await refreshMainChatList();
	};

	$: if (show) {
		(async () => {
			chats = await getArchivedChatList(localStorage.token);
		})();
	}
</script>

<UnarchiveAllConfirmDialog
	bind:show={showUnarchiveAllConfirmDialog}
	message={$i18n.t('Are you sure you want to unarchive all archived chats?')}
	confirmLabel={$i18n.t('Unarchive All')}
	on:confirm={() => {
		unarchiveAllHandler();
	}}
/>

<Modal size="lg" bind:show>
	<div>
		<div class=" flex justify-between dark:text-gray-300 px-5 pt-4 pb-1">
			<div class=" text-lg font-medium self-center">{$i18n.t('Archived Chats')}</div>
			<button
				class="self-center"
				on:click={() => {
					show = false;
				}}
				aria-label={$i18n.t('Close')}
			>
				<XMark className="w-5 h-5" />
			</button>
		</div>

		<div class="flex flex-col w-full px-5 pb-4 dark:text-gray-200">
			<div class="mt-2">
				<Input
					bind:value={searchValue}
					type="search"
					size="md"
					placeholder={$i18n.t('Search Chats')}
				>
					<svelte:fragment slot="prefix">
						<Search className="size-3.5" />
					</svelte:fragment>
				</Input>
			</div>
			<hr class="border-gray-100 dark:border-gray-850 my-2" />
			<div class=" flex flex-col w-full sm:flex-row sm:justify-center sm:space-x-6">
				{#if chats.length > 0}
					<div class="w-full">
						<div class="text-left text-sm w-full mb-3 max-h-[22rem] overflow-y-scroll">
							<div class="relative overflow-x-auto">
								<table class="w-full text-sm text-left text-gray-600 dark:text-gray-400 table-auto">
									<thead
										class="text-xs text-gray-700 uppercase bg-transparent dark:text-gray-200 border-b-2 border-gray-50 dark:border-gray-850"
									>
										<tr>
											<th scope="col" class="px-3 py-2"> {$i18n.t('Name')} </th>
											<th scope="col" class="px-3 py-2 hidden md:flex">
												{$i18n.t('Created At')}
											</th>
											<th scope="col" class="px-3 py-2 text-right" />
										</tr>
									</thead>
									<tbody>
										{#each chats.filter((c) => searchValue === '' || c.title
													.toLowerCase()
													.includes(searchValue.toLowerCase())) as chat, idx}
											<tr
												class="bg-transparent {idx !== chats.length - 1 &&
													'border-b'} dark:bg-gray-900 border-gray-50 dark:border-gray-850 text-xs"
											>
												<td class="px-3 py-1 w-2/3">
													<a href="/c/{chat.id}" target="_blank">
														<div class=" underline line-clamp-1">
															{chat.title}
														</div>
													</a>
												</td>

												<td class=" px-3 py-1 hidden md:flex h-[2.5rem]">
													<div class="my-auto">
														{dayjs(chat.created_at * 1000).format('LLL')}
													</div>
												</td>

												<td class="px-3 py-1 text-right">
													<div class="flex justify-end w-full gap-1">
														<Tooltip content={$i18n.t('Unarchive Chat')}>
															<Button
																kind="text"
																size="sm"
																ariaLabel={$i18n.t('Unarchive Chat')}
																on:click={async () => {
																	unarchiveChatHandler(chat.id);
																}}
															>
																<svelte:fragment slot="prefix">
																	<ArchiveBoxArrowUp className="size-3.5" />
																</svelte:fragment>
															</Button>
														</Tooltip>

														<Tooltip content={$i18n.t('Delete Chat')}>
															<Button
																kind="text"
																size="sm"
																status="error"
																ariaLabel={$i18n.t('Delete Chat')}
																on:click={async () => {
																	deleteChatHandler(chat.id);
																}}
															>
																<svelte:fragment slot="prefix">
																	<GarbageBin className="size-3.5" />
																</svelte:fragment>
															</Button>
														</Tooltip>
													</div>
												</td>
											</tr>
										{/each}
									</tbody>
								</table>
							</div>
						</div>

						<div class="flex flex-wrap text-sm font-medium gap-1.5 mt-2 m-1 justify-end w-full">
							<Button
								kind="outlined"
								size="md"
								on:click={() => {
									showUnarchiveAllConfirmDialog = true;
								}}
							>
								{$i18n.t('Unarchive All Archived Chats')}
							</Button>

							<Button
								kind="outlined"
								size="md"
								on:click={() => {
									exportChatsHandler();
								}}
							>
								{$i18n.t('Export All Archived Chats')}
							</Button>
						</div>
					</div>
				{:else}
					<div class="text-left text-sm w-full mb-8">
						{$i18n.t('You have no archived conversations.')}
					</div>
				{/if}
			</div>
		</div>
	</div>
</Modal>

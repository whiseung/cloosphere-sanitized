<script lang="ts">
	import { getBackendConfig } from '$lib/apis';
	import { setDefaultPromptSuggestions } from '$lib/apis/configs';
	import Switch from '$lib/components/common/Switch.svelte';
	import Button from '$lib/components/common/Button.svelte';
	import Badge from '$lib/components/common/Badge.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import ConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';
	import { config, models, settings, user } from '$lib/stores';
	import { createEventDispatcher, onMount, getContext, tick } from 'svelte';
	import { toast } from 'svelte-sonner';
	import dayjs from 'dayjs';
	import localizedFormat from 'dayjs/plugin/localizedFormat';

	import { deleteMemoriesByUserId, deleteMemoryById, getMemories } from '$lib/apis/memories';
	import AddMemoryModal from './Personalization/AddMemoryModal.svelte';
	import EditMemoryModal from './Personalization/EditMemoryModal.svelte';

	const dispatch = createEventDispatcher();

	const i18n = getContext('i18n');
	dayjs.extend(localizedFormat);

	export let saveSettings: Function;

	let enableMemory = false;

	let memories: any[] = [];
	let profile: any = null;
	let showProfile = false;
	let memoriesLoaded = false;

	let showAddMemoryModal = false;
	let showEditMemoryModal = false;
	let selectedMemory: any = null;
	let showClearConfirmDialog = false;

	const refreshMemories = async () => {
		const allMemories = await getMemories(localStorage.token);
		if (!allMemories) {
			profile = null;
			memories = [];
			return;
		}
		profile = allMemories.find((m: any) => m.source === 'profile') || null;
		memories = allMemories.filter((m: any) => m.source !== 'profile');
	};

	const onClearConfirmed = async () => {
		const res = await deleteMemoriesByUserId(localStorage.token).catch((error) => {
			toast.error($i18n.t(`${error}`));
			return null;
		});

		if (res && memories.length > 0) {
			toast.success($i18n.t('Memory cleared successfully'));
			memories = [];
			profile = null;
		}
		showClearConfirmDialog = false;
	};

	const handleDelete = async (memoryId: string) => {
		const res = await deleteMemoryById(localStorage.token, memoryId).catch((error) => {
			toast.error($i18n.t(`${error}`));
			return null;
		});

		if (res) {
			toast.success($i18n.t('Memory deleted successfully'));
			await refreshMemories();
		}
	};

	$: if (enableMemory && !memoriesLoaded) {
		memoriesLoaded = true;
		refreshMemories();
	}

	onMount(async () => {
		enableMemory = $settings?.memory ?? false;
	});
</script>

<form
	class="flex flex-col h-full justify-between space-y-3 text-sm"
	on:submit|preventDefault={() => {
		dispatch('save');
	}}
>
	<div class="py-1 overflow-y-scroll max-h-[28rem] lg:max-h-full space-y-3">
		<Tooltip
			className="w-full flex items-center justify-between gap-3"
			content={$i18n.t(
				'This is an experimental feature, it may not function as expected and is subject to change at any time.'
			)}
		>
			<span class="text-sm font-medium">
				{$i18n.t('Memory')}
				<span class="text-xs text-gray-500">({$i18n.t('Experimental')})</span>
			</span>
			<Switch
				bind:state={enableMemory}
				on:change={async () => {
					saveSettings({ memory: enableMemory });
				}}
			/>
		</Tooltip>

		<div class="text-xs text-gray-600 dark:text-gray-400 space-y-2">
			<div>
				{$i18n.t('You can personalize your interactions with LLMs by adding memories below, making them more helpful and tailored to you.')}
			</div>
			<div>
				{$i18n.t('When enabled, the system automatically extracts key information from your conversations and saves it as memory for future interactions.')}
			</div>
		</div>

		{#if enableMemory}
			{#if profile}
				<div>
					<button
						type="button"
						class="flex items-center gap-2 w-full text-left text-sm font-medium text-gray-700 dark:text-gray-300 hover:bg-black/5 dark:hover:bg-white/5 rounded-lg px-3 py-2 transition"
						on:click={() => {
							showProfile = !showProfile;
						}}
					>
						<svg
							xmlns="http://www.w3.org/2000/svg"
							viewBox="0 0 20 20"
							fill="currentColor"
							class="w-4 h-4 transition-transform {showProfile ? 'rotate-90' : ''}"
						>
							<path
								fill-rule="evenodd"
								d="M7.21 14.77a.75.75 0 01.02-1.06L11.168 10 7.23 6.29a.75.75 0 111.04-1.08l4.5 4.25a.75.75 0 010 1.08l-4.5 4.25a.75.75 0 01-1.06-.02z"
								clip-rule="evenodd"
							/>
						</svg>
						<span>{$i18n.t('Profile Summary')}</span>
						<Badge status="success" size="sm">{$i18n.t('Auto-generated')}</Badge>
					</button>
					{#if showProfile}
						<div
							class="mt-1 mx-3 px-3 py-2 text-sm text-gray-600 dark:text-gray-400 bg-gray-50 dark:bg-gray-850 rounded-lg whitespace-pre-wrap"
						>
							{profile.content}
						</div>
					{/if}
				</div>
			{/if}

			<div
				class="flex flex-col w-full max-h-[20rem] outline outline-1 rounded-xl outline-gray-100 dark:outline-gray-800 overflow-hidden"
			>
				{#if memories.length > 0}
					<div class="text-left text-sm w-full overflow-y-auto">
						<table class="w-full text-sm text-left text-gray-600 dark:text-gray-400 table-auto">
							<thead
								class="text-xs text-gray-700 uppercase bg-transparent dark:text-gray-200 border-b-2 border-gray-50 dark:border-gray-850 sticky top-0 bg-white dark:bg-gray-900"
							>
								<tr>
									<th scope="col" class="px-3 py-2"> {$i18n.t('Name')} </th>
									<th scope="col" class="px-3 py-2 hidden md:table-cell whitespace-nowrap">
										{$i18n.t('Last Modified')}
									</th>
									<th scope="col" class="px-3 py-2 text-right" />
								</tr>
							</thead>
							<tbody>
								{#each memories as memory}
									<tr class="border-b border-gray-50 dark:border-gray-850 items-center">
										<td class="px-3 py-1">
											<div class="flex items-center gap-1.5">
												{#if memory.source === 'auto'}
													<Badge status="info" size="sm">{$i18n.t('Auto')}</Badge>
												{/if}
												<span class="line-clamp-1">{memory.content}</span>
											</div>
										</td>
										<td class="px-3 py-1 hidden md:table-cell h-[2.5rem]">
											<div class="my-auto whitespace-nowrap">
												{dayjs(memory.updated_at * 1000).format('LLL')}
											</div>
										</td>
										<td class="px-3 py-1">
											<div class="flex justify-end w-full gap-1">
												<Tooltip content={$i18n.t('Edit')}>
													<Button
														kind="text"
														size="sm"
														on:click={() => {
															selectedMemory = memory;
															showEditMemoryModal = true;
														}}
													>
														<svg
															xmlns="http://www.w3.org/2000/svg"
															fill="none"
															viewBox="0 0 24 24"
															stroke-width="1.5"
															stroke="currentColor"
															class="w-4 h-4"
														>
															<path
																stroke-linecap="round"
																stroke-linejoin="round"
																d="m16.862 4.487 1.687-1.688a1.875 1.875 0 1 1 2.652 2.652L6.832 19.82a4.5 4.5 0 0 1-1.897 1.13l-2.685.8.8-2.685a4.5 4.5 0 0 1 1.13-1.897L16.863 4.487Zm0 0L19.5 7.125"
															/>
														</svg>
													</Button>
												</Tooltip>

												<Tooltip content={$i18n.t('Delete')}>
													<Button
														kind="text"
														size="sm"
														status="error"
														on:click={() => handleDelete(memory.id)}
													>
														<svg
															xmlns="http://www.w3.org/2000/svg"
															fill="none"
															viewBox="0 0 24 24"
															stroke-width="1.5"
															stroke="currentColor"
															class="w-4 h-4"
														>
															<path
																stroke-linecap="round"
																stroke-linejoin="round"
																d="m14.74 9-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 0 1-2.244 2.077H8.084a2.25 2.25 0 0 1-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 0 0-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 0 1 3.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 0 0-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 0 0-7.5 0"
															/>
														</svg>
													</Button>
												</Tooltip>
											</div>
										</td>
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
				{:else}
					<div class="text-center flex h-32 text-sm w-full">
						<div class="my-auto px-4 w-full text-gray-500">
							{$i18n.t('Memories accessible by LLMs will be shown here.')}
						</div>
					</div>
				{/if}
			</div>

			<div class="flex gap-1.5">
				<Button
					kind="outlined"
					size="md"
					on:click={() => {
						showAddMemoryModal = true;
					}}
				>
					{$i18n.t('Add Memory')}
				</Button>
				<Button
					kind="outlined"
					size="md"
					status="error"
					on:click={() => {
						if (memories.length > 0) {
							showClearConfirmDialog = true;
						} else {
							toast.error($i18n.t('No memories to clear'));
						}
					}}
				>
					{$i18n.t('Clear memory')}
				</Button>
			</div>
		{/if}
	</div>

	<div class="flex justify-end text-sm font-medium">
		<Button kind="filled" size="md" type="submit">
			{$i18n.t('Save')}
		</Button>
	</div>
</form>

<ConfirmDialog
	title={$i18n.t('Clear Memory')}
	message={$i18n.t('Are you sure you want to clear all memories? This action cannot be undone.')}
	show={showClearConfirmDialog}
	on:confirm={onClearConfirmed}
	on:cancel={() => {
		showClearConfirmDialog = false;
	}}
/>

<AddMemoryModal
	bind:show={showAddMemoryModal}
	on:save={async () => {
		await refreshMemories();
	}}
/>

<EditMemoryModal
	bind:show={showEditMemoryModal}
	memory={selectedMemory}
	on:save={async () => {
		await refreshMemories();
	}}
/>

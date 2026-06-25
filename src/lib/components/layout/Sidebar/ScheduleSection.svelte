<script lang="ts">
	import { onMount, getContext } from 'svelte';
	import { goto } from '$app/navigation';
	import { DropdownMenu } from 'bits-ui';
	import { flyAndScale } from '$lib/utils/transitions';
	import { mobile, showSidebar, user } from '$lib/stores';
	import { getSchedules, type Schedule } from '$lib/apis/schedules';
	import Folder from '../../common/Folder.svelte';

	const i18n = getContext('i18n');

	const MAX_VISIBLE = 3;

	let schedules: Schedule[] = [];
	let showMore = false;

	$: canCreate =
		$user?.role === 'admin' || $user?.permissions?.workspace?.schedules === 'write';
	let open =
		typeof localStorage !== 'undefined'
			? localStorage.getItem('sidebarScheduleSectionOpen') !== 'false'
			: true;

	$: {
		localStorage.setItem('sidebarScheduleSectionOpen', String(open));
	}

	$: hiddenSchedules = schedules.slice(MAX_VISIBLE);

	const loadSchedules = async () => {
		try {
			const all = await getSchedules(localStorage.token);
			schedules = all ?? [];
		} catch (e) {
			console.error('Failed to load schedules', e);
			schedules = [];
		}
	};

	onMount(() => {
		loadSchedules();
	});
</script>

<Folder
	className="px-2 mt-0.5"
	bind:open
	name={$i18n.t('Scheduled Tasks')}
	dragAndDrop={false}
	onAdd={canCreate
		? () => {
				goto('/schedules/create');
				if ($mobile) {
					showSidebar.set(false);
				}
		  }
		: undefined}
	onAddLabel={canCreate ? $i18n.t('Create Schedule') : undefined}
>
	{#if schedules.length === 0}
		<div class="px-2 py-2 text-xs text-gray-500 dark:text-gray-500">
			{$i18n.t('No scheduled tasks')}
		</div>
	{:else}
		<div class="flex flex-col">
			{#each schedules.slice(0, MAX_VISIBLE) as schedule (schedule.id)}
				<a
					class="flex items-center gap-2 px-2 py-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-900 transition cursor-pointer"
					href={schedule.chat_id ? `/c/${schedule.chat_id}` : `/schedules/${schedule.id}`}
					on:click={() => {
						if ($mobile) {
							showSidebar.set(false);
						}
					}}
					draggable="false"
				>
					<svg
						xmlns="http://www.w3.org/2000/svg"
						fill="none"
						viewBox="0 0 24 24"
						stroke-width="2"
						stroke="currentColor"
						class="size-4 shrink-0 text-gray-500 dark:text-gray-400"
					>
						<path
							stroke-linecap="round"
							stroke-linejoin="round"
							d="M12 6v6h4.5m4.5 0a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z"
						/>
					</svg>
					<span class="text-sm truncate flex-1 text-gray-700 dark:text-gray-300">
						{schedule.name}
					</span>
					<span
						class="size-2 rounded-full shrink-0 {schedule.is_active
							? 'bg-green-500'
							: 'bg-gray-400 dark:bg-gray-600'}"
					/>
				</a>
			{/each}

			{#if hiddenSchedules.length > 0}
				<DropdownMenu.Root bind:open={showMore} typeahead={false}>
					<DropdownMenu.Trigger>
						<button
							class="flex items-center gap-1.5 px-2 py-1.5 w-full rounded-lg
								hover:bg-gray-100 dark:hover:bg-gray-900 transition cursor-pointer"
						>
							<svg
								xmlns="http://www.w3.org/2000/svg"
								fill="none"
								viewBox="0 0 24 24"
								stroke-width="2"
								stroke="currentColor"
								class="size-4 shrink-0 text-gray-400 dark:text-gray-500"
							>
								<path
									stroke-linecap="round"
									stroke-linejoin="round"
									d="M8.25 6.75h12M8.25 12h12m-12 5.25h12M3.75 6.75h.007v.008H3.75V6.75Zm.375 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0ZM3.75 12h.007v.008H3.75V12Zm.375 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm-.375 5.25h.007v.008H3.75v-.008Zm.375 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Z"
								/>
							</svg>
							<span class="text-sm text-gray-500 dark:text-gray-400">{$i18n.t('Show More')}</span>
							<svg
								xmlns="http://www.w3.org/2000/svg"
								viewBox="0 0 16 16"
								fill="currentColor"
								class="size-3 text-gray-400 dark:text-gray-500 ml-auto"
							>
								<path fill-rule="evenodd" d="M6.22 4.22a.75.75 0 0 1 1.06 0l3.25 3.25a.75.75 0 0 1 0 1.06l-3.25 3.25a.75.75 0 0 1-1.06-1.06L8.94 8 6.22 5.28a.75.75 0 0 1 0-1.06Z" clip-rule="evenodd" />
							</svg>
						</button>
					</DropdownMenu.Trigger>

					<DropdownMenu.Content
						class="w-full max-w-[220px] max-h-[300px] overflow-y-auto rounded-xl px-1 py-1.5 z-50 bg-white dark:bg-gray-850 dark:text-white shadow-lg border border-gray-100 dark:border-gray-800"
						sideOffset={4}
						side="right"
						align="start"
						transition={flyAndScale}
					>
						{#each hiddenSchedules as schedule (schedule.id)}
							<DropdownMenu.Item
								class="flex items-center gap-2 px-3 py-1.5 text-sm cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-800 rounded-md"
								on:click={() => {
									const href = schedule.chat_id ? `/c/${schedule.chat_id}` : `/schedules/${schedule.id}`;
									goto(href);
									if ($mobile) {
										showSidebar.set(false);
									}
								}}
							>
								<span class="truncate flex-1">{schedule.name}</span>
								<span
									class="size-2 rounded-full shrink-0 {schedule.is_active
										? 'bg-green-500'
										: 'bg-gray-400 dark:bg-gray-600'}"
								/>
							</DropdownMenu.Item>
						{/each}
					</DropdownMenu.Content>
				</DropdownMenu.Root>
			{/if}
		</div>
	{/if}
</Folder>

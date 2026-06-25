<script lang="ts">
	import Fuse from 'fuse.js';

	import { DropdownMenu } from 'bits-ui';
	import { getContext, createEventDispatcher } from 'svelte';
	import { flyAndScale } from '$lib/utils/transitions';
	import { getGlossaries } from '$lib/apis/glossary';
	import Dropdown from '$lib/components/common/Dropdown.svelte';

	const i18n = getContext('i18n');
	const dispatch = createEventDispatcher();

	export let onClose: Function = () => {};
	// 픽커에서 숨길 ID 셋 — KG에서 자동 inherit되는 용어집들
	export let excludeIds: string[] = [];

	let items: any[] = [];
	let filteredItems: any[] = [];
	let loading = false;
	let permissionDenied = false;
	let loaded = false;

	let fuse: Fuse<any> | null = null;
	$: excludeSet = new Set(excludeIds ?? []);
	$: if (fuse) {
		filteredItems = items.filter((it) => !excludeSet.has(it.id));
	}

	async function loadItems() {
		if (loaded) return;
		loading = true;
		permissionDenied = false;
		try {
			const glossaries = await getGlossaries(localStorage.token);
			items = glossaries ?? [];
			fuse = new Fuse(items, { keys: ['name', 'description'] });
			filteredItems = items;
			loaded = true;
		} catch (e: any) {
			const msg = typeof e === 'string' ? e : (e?.detail ?? e?.message ?? '');
			if (
				(typeof msg === 'string' &&
					(msg.includes('permission') ||
						msg.includes('Unauthorized') ||
						msg.includes('Forbidden'))) ||
				e?.status === 401 ||
				e?.status === 403
			) {
				permissionDenied = true;
			} else {
				items = [];
				filteredItems = [];
			}
		} finally {
			loading = false;
		}
	}
</script>

<Dropdown
	on:change={(e) => {
		if (e.detail === true) {
			loadItems();
		} else {
			onClose();
		}
	}}
>
	<slot />

	<div slot="content">
		<DropdownMenu.Content
			class="w-full max-w-80 rounded-lg px-1 py-1.5 border border-gray-300/30 dark:border-gray-700/50 z-[10000] bg-white dark:bg-gray-850 dark:text-white shadow-lg"
			sideOffset={8}
			side="bottom"
			align="start"
			transition={flyAndScale}
		>
			<div class="max-h-48 overflow-y-scroll">
				{#if loading}
					<div class="text-center text-sm text-gray-500 dark:text-gray-400 py-2">
						{$i18n.t('Loading...')}
					</div>
				{:else if permissionDenied}
					<div class="px-3 py-2 text-sm text-red-500 dark:text-red-400">
						{$i18n.t('Access denied. You do not have permission to view glossaries.')}
					</div>
				{:else if filteredItems.length === 0}
					<div class="text-center text-sm text-gray-500 dark:text-gray-400 py-2">
						{$i18n.t('No glossary found')}
					</div>
				{:else}
					{#each filteredItems as item}
						<DropdownMenu.Item
							class="flex gap-2.5 items-center px-3 py-2 text-sm cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-800 rounded-md"
							on:click={() => {
								dispatch('select', item);
							}}
						>
							<div class="flex items-center">
								<div class="flex flex-col">
									<div class="w-fit mb-0.5">
										<div
											class="bg-purple-500/20 text-purple-700 dark:text-purple-200 rounded-sm uppercase text-xs font-bold px-1"
										>
											{$i18n.t('Dictionary')}
										</div>
									</div>
									<div class="line-clamp-1 font-medium pr-0.5">
										{item.name}
									</div>
									{#if item.description}
										<div class="line-clamp-1 text-xs text-gray-500">
											{item.description}
										</div>
									{/if}
								</div>
							</div>
						</DropdownMenu.Item>
					{/each}
				{/if}
			</div>
		</DropdownMenu.Content>
	</div>
</Dropdown>

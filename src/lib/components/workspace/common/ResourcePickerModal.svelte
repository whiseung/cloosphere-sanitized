<script lang="ts">
	import Fuse from 'fuse.js';
	import { createEventDispatcher, getContext } from 'svelte';
	import type { Readable } from 'svelte/store';

	import Modal from '$lib/components/common/Modal.svelte';
	import Search from '$lib/components/icons/Search.svelte';
	import XMark from '$lib/components/icons/XMark.svelte';
	import Check from '$lib/components/icons/Check.svelte';

	type Item = { id: string; name?: string; description?: string; [k: string]: any };
	type FilterOption = { value: string; label: string; predicate: (item: Item) => boolean };
	type I18nStore = Readable<{ t: (key: string, options?: Record<string, unknown>) => string }>;

	const i18n = getContext<I18nStore>('i18n');
	const dispatch = createEventDispatcher();

	export let show = false;
	export let title = '';
	export let description = '';
	export let selected: Item[] = [];
	export let fetchItems: (() => Promise<Item[]>) | null = null;
	export let searchKeys: string[] = ['name', 'description'];
	export let excludeIds: string[] = [];
	export let filters: FilterOption[] = [];
	export let emptyMessage = '';

	let items: Item[] = [];
	let loading = false;
	let permissionDenied = false;
	let loaded = false;

	let query = '';
	let activeFilter = 'all';
	let showUnselectedOnly = false;

	let pending: Item[] = [];
	let fuse: Fuse<Item> | null = null;

	$: if (show && !loaded) {
		void loadItems();
	}

	$: if (show) {
		pending = [...selected];
	}

	$: excludeSet = new Set(excludeIds ?? []);

	$: pendingIds = new Set(pending.map((p) => p.id));

	$: filteredItems = (() => {
		const base = query && fuse ? fuse.search(query).map((e) => e.item) : items;
		const af = filters.find((f) => f.value === activeFilter);
		let out = base.filter((it) => !excludeSet.has(it.id));
		if (af && af.value !== 'all') out = out.filter((it) => af.predicate(it));
		if (showUnselectedOnly) out = out.filter((it) => !pendingIds.has(it.id));
		return out;
	})();

	const loadItems = async () => {
		if (!fetchItems) return;
		loading = true;
		permissionDenied = false;
		try {
			const data = (await fetchItems()) ?? [];
			items = data;
			fuse = new Fuse(items, { keys: searchKeys, threshold: 0.3 });
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
			}
			items = [];
		} finally {
			loading = false;
		}
	};

	const toggleItem = (item: Item) => {
		if (pendingIds.has(item.id)) {
			pending = pending.filter((p) => p.id !== item.id);
		} else {
			pending = [...pending, item];
		}
	};

	const clearAll = () => {
		pending = [];
	};

	const apply = () => {
		dispatch('apply', pending);
		show = false;
	};

	const cancel = () => {
		show = false;
		dispatch('close');
	};

	const reset = () => {
		query = '';
		activeFilter = 'all';
		showUnselectedOnly = false;
	};

	$: if (!show) reset();
</script>

<Modal bind:show size="lg" on:close={cancel}>
	<div class="flex flex-col h-[min(80vh,42rem)]">
		<!-- Header -->
		<div class="flex items-center justify-between px-5 pt-5 pb-3">
			<div>
				<h2 class="text-lg font-semibold text-gray-900 dark:text-gray-100">{title}</h2>
				{#if description}
					<p class="text-xs text-gray-500 dark:text-gray-400 mt-0.5">{description}</p>
				{/if}
			</div>
			<button
				type="button"
				class="text-gray-400 hover:text-gray-700 dark:hover:text-gray-200"
				on:click={cancel}
				aria-label={$i18n.t('Close')}
			>
				<XMark className="size-5" />
			</button>
		</div>

		<!-- Search + Filters -->
		<div class="px-5 pb-3 flex flex-col gap-2">
			<div
				class="flex items-center gap-2 px-3 py-2 rounded-lg bg-gray-50 dark:bg-gray-850 border border-gray-200 dark:border-gray-800"
			>
				<Search className="size-4 text-gray-400" />
				<input
					type="text"
					bind:value={query}
					placeholder={$i18n.t('Search')}
					class="flex-1 bg-transparent outline-none text-sm text-gray-700 dark:text-gray-200 placeholder:text-gray-400"
				/>
				{#if query}
					<button type="button" class="text-gray-400 hover:text-gray-700" on:click={() => (query = '')}>
						<XMark className="size-4" />
					</button>
				{/if}
			</div>

			{#if filters.length > 0}
				<div class="flex flex-wrap gap-1.5">
					<button
						type="button"
						class="px-2.5 py-1 text-xs rounded-full border transition-colors {activeFilter === 'all'
							? 'bg-gray-900 text-white border-gray-900 dark:bg-white dark:text-gray-900 dark:border-white'
							: 'bg-white text-gray-700 border-gray-200 hover:bg-gray-50 dark:bg-gray-900 dark:text-gray-300 dark:border-gray-700 dark:hover:bg-gray-800'}"
						on:click={() => (activeFilter = 'all')}
					>
						{$i18n.t('All')}
					</button>
					{#each filters as f}
						<button
							type="button"
							class="px-2.5 py-1 text-xs rounded-full border transition-colors {activeFilter === f.value
								? 'bg-gray-900 text-white border-gray-900 dark:bg-white dark:text-gray-900 dark:border-white'
								: 'bg-white text-gray-700 border-gray-200 hover:bg-gray-50 dark:bg-gray-900 dark:text-gray-300 dark:border-gray-700 dark:hover:bg-gray-800'}"
							on:click={() => (activeFilter = f.value)}
						>
							{f.label}
						</button>
					{/each}
				</div>
			{/if}

			<label class="flex items-center gap-2 text-xs text-gray-600 dark:text-gray-400 select-none">
				<input type="checkbox" bind:checked={showUnselectedOnly} class="accent-gray-700" />
				{$i18n.t('Show unselected only')}
			</label>
		</div>

		<!-- List -->
		<div class="flex-1 min-h-0 overflow-y-auto px-2 pb-2">
			{#if loading}
				<div class="text-center text-sm text-gray-500 dark:text-gray-400 py-12">
					{$i18n.t('Loading...')}
				</div>
			{:else if permissionDenied}
				<div class="text-center text-sm text-red-500 dark:text-red-400 py-12">
					{$i18n.t('Access denied. You do not have permission to view this resource.')}
				</div>
			{:else if filteredItems.length === 0}
				<div class="text-center text-sm text-gray-500 dark:text-gray-400 py-12">
					{emptyMessage || $i18n.t('No items found')}
				</div>
			{:else}
				<ul class="flex flex-col gap-0.5">
					{#each filteredItems as item (item.id)}
						{@const isSelected = pendingIds.has(item.id)}
						<li>
							<button
								type="button"
								class="w-full flex items-start gap-3 px-3 py-2.5 rounded-lg text-left transition-colors {isSelected
									? 'bg-blue-50 dark:bg-blue-500/10'
									: 'hover:bg-gray-50 dark:hover:bg-gray-850'}"
								on:click={() => toggleItem(item)}
							>
								<div
									class="mt-0.5 size-4 shrink-0 rounded border flex items-center justify-center transition-colors {isSelected
										? 'bg-blue-600 border-blue-600 text-white'
										: 'border-gray-300 dark:border-gray-600'}"
								>
									{#if isSelected}
										<Check className="size-3" strokeWidth="3" />
									{/if}
								</div>
								<div class="flex-1 min-w-0">
									<div class="flex items-center gap-2 flex-wrap">
										<span class="text-sm font-medium text-gray-900 dark:text-gray-100 truncate">
											{item.name ?? item.id}
										</span>
										<slot name="badges" {item} />
									</div>
									{#if item.description}
										<p class="text-xs text-gray-500 dark:text-gray-400 mt-0.5 line-clamp-2">
											{item.description}
										</p>
									{/if}
									<slot name="meta" {item} />
								</div>
							</button>
						</li>
					{/each}
				</ul>
			{/if}
		</div>

		<!-- Footer -->
		<div
			class="flex items-center justify-between px-5 py-3 border-t border-gray-200 dark:border-gray-800"
		>
			<div class="text-xs text-gray-500 dark:text-gray-400">
				{$i18n.t('{{count}} selected', { count: pending.length })}
				{#if pending.length > 0}
					·
					<button
						type="button"
						class="text-gray-700 dark:text-gray-300 hover:underline"
						on:click={clearAll}
					>
						{$i18n.t('Clear all')}
					</button>
				{/if}
			</div>
			<div class="flex items-center gap-2">
				<button
					type="button"
					class="px-3 py-1.5 text-sm rounded-lg border border-gray-200 dark:border-gray-700 text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-850"
					on:click={cancel}
				>
					{$i18n.t('Cancel')}
				</button>
				<button
					type="button"
					class="px-3 py-1.5 text-sm rounded-lg bg-gray-900 text-white hover:bg-gray-800 dark:bg-white dark:text-gray-900 dark:hover:bg-gray-100"
					on:click={apply}
				>
					{$i18n.t('Apply')}
				</button>
			</div>
		</div>
	</div>
</Modal>

<script lang="ts">
	import { createEventDispatcher, getContext } from 'svelte';
	import Button from '$lib/components/common/Button.svelte';
	import Input from '$lib/components/common/Input.svelte';
	import Selector from '$lib/components/common/Selector.svelte';
	import Modal from '$lib/components/common/Modal.svelte';

	const i18n = getContext('i18n');
	const dispatch = createEventDispatcher();

	export let filters: any[] = [];
	export let editMode = false;

	let showAddFilter = false;
	let newFilter = { label: '', type: 'text', field: '', value: '', from_value: '', to_value: '' };

	const FILTER_TYPES = [
		{ value: 'text', label: 'Text' },
		{ value: 'date_range', label: 'Date Range' },
		{ value: 'select', label: 'Select' }
	];

	function resetNewFilter() {
		newFilter = { label: '', type: 'text', field: '', value: '', from_value: '', to_value: '' };
	}

	function addFilter() {
		if (!newFilter.label || !newFilter.field) return;
		filters = [...filters, { ...newFilter, id: crypto.randomUUID() }];
		showAddFilter = false;
		resetNewFilter();
		dispatch('change', filters);
	}

	function removeFilter(id: string) {
		filters = filters.filter((f: any) => f.id !== id);
		dispatch('change', filters);
	}

	function handleFilterValueChange() {
		dispatch('change', filters);
	}
</script>

{#if filters.length > 0 || editMode}
	<div class="flex flex-wrap items-center gap-2">
		{#each filters as filter (filter.id)}
			<div
				class="flex items-center gap-1.5 px-2 py-1 bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg"
			>
				<span class="text-xs font-medium text-gray-600 dark:text-gray-400 whitespace-nowrap">
					{filter.label}
				</span>

				{#if filter.type === 'date_range'}
					<input
						type="date"
						bind:value={filter.from_value}
						on:change={handleFilterValueChange}
						class="text-xs px-1.5 py-0.5 bg-white dark:bg-gray-900 dark:text-gray-200 border border-gray-200 dark:border-gray-700 rounded outline-none"
					/>
					<span class="text-xs text-gray-400">~</span>
					<input
						type="date"
						bind:value={filter.to_value}
						on:change={handleFilterValueChange}
						class="text-xs px-1.5 py-0.5 bg-white dark:bg-gray-900 dark:text-gray-200 border border-gray-200 dark:border-gray-700 rounded outline-none"
					/>
				{:else}
					<input
						type="text"
						bind:value={filter.value}
						on:change={handleFilterValueChange}
						placeholder={filter.field}
						class="text-xs w-24 px-1.5 py-0.5 bg-white dark:bg-gray-900 dark:text-gray-200 border border-gray-200 dark:border-gray-700 rounded outline-none"
					/>
				{/if}

				{#if editMode}
					<button
						class="text-gray-400 hover:text-red-500 transition"
						on:click={() => removeFilter(filter.id)}
					>
						<svg xmlns="http://www.w3.org/2000/svg" class="size-3" viewBox="0 0 20 20" fill="currentColor">
							<path d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z" />
						</svg>
					</button>
				{/if}
			</div>
		{/each}

		{#if editMode}
			<Button kind="outlined" size="sm" on:click={() => (showAddFilter = true)}>
				<svelte:fragment slot="prefix">
					<svg xmlns="http://www.w3.org/2000/svg" class="size-3" viewBox="0 0 20 20" fill="currentColor">
						<path d="M10.75 4.75a.75.75 0 00-1.5 0v4.5h-4.5a.75.75 0 000 1.5h4.5v4.5a.75.75 0 001.5 0v-4.5h4.5a.75.75 0 000-1.5h-4.5v-4.5z" />
					</svg>
				</svelte:fragment>
				{$i18n.t('Add Filter')}
			</Button>
		{/if}
	</div>
{/if}

<!-- Add Filter Modal -->
<Modal bind:show={showAddFilter} size="sm">
	<div class="px-5 py-4">
		<div class="text-lg font-semibold mb-4 dark:text-gray-100">
			{$i18n.t('Add Filter')}
		</div>
		<div class="flex flex-col gap-3">
			<Input
				bind:value={newFilter.label}
				label={$i18n.t('Filter Label')}
				placeholder={$i18n.t('e.g. Period, Country')}
				size="md"
				required
			/>
			<Input
				bind:value={newFilter.field}
				label={$i18n.t('Column Name')}
				placeholder={$i18n.t('e.g. created_date, country')}
				size="md"
				required
			/>
			<Selector
				value={newFilter.type}
				items={FILTER_TYPES}
				size="md"
				contentClassName="z-[99999]"
				on:change={(e) => {
					newFilter.type = e.detail.value;
				}}
			/>
		</div>
		<div class="flex justify-end gap-2 mt-4">
			<Button kind="outlined" size="md" on:click={() => (showAddFilter = false)}>
				{$i18n.t('Cancel')}
			</Button>
			<Button kind="filled" size="md" on:click={addFilter}>
				{$i18n.t('Add')}
			</Button>
		</div>
	</div>
</Modal>

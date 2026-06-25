<script lang="ts">
	import { getContext, onMount } from 'svelte';
	import ResourcePickerModal from '../common/ResourcePickerModal.svelte';
	import ResourceChip from '../common/ResourceChip.svelte';
	import MissingDescriptionWarning from './MissingDescriptionWarning.svelte';
	import { getGlossaries } from '$lib/apis/glossary';

	export let selectedGlossaries: any[] = [];
	export let canWrite = true;
	// KG에서 자동 inherit되는 glossary ID들 — picker에서 숨김
	export let excludeIds: string[] = [];

	const i18n = getContext('i18n');

	let allItems: any[] = [];
	let showPicker = false;

	const fetchItems = async () => {
		const data = (await getGlossaries(localStorage.token)) ?? [];
		allItems = data;
		return data;
	};

	onMount(async () => {
		try {
			await fetchItems();
		} catch {
			allItems = [];
		}
	});

	$: missingDescriptionNames = selectedGlossaries
		.map((sel: any) => {
			const full = allItems.find((it) => it.id === sel.id) ?? sel;
			const desc = full?.meta?.tool_description ?? '';
			return !desc || !String(desc).trim() ? (full?.name ?? sel?.name ?? sel?.id) : null;
		})
		.filter((n: string | null): n is string => !!n);

	const onApply = (e: CustomEvent<any[]>) => {
		selectedGlossaries = e.detail.map((item: any) => ({ id: item.id, name: item.name }));
	};

	const removeAt = (idx: number) => {
		selectedGlossaries = selectedGlossaries.filter((_, i) => i !== idx);
	};

	$: descMap = (() => {
		const m: Record<string, string> = {};
		for (const it of allItems) m[it.id] = (it as any)?.description ?? '';
		return m;
	})();
	$: descFor = (item: any) => descMap[item?.id] || item?.description || '';
</script>

<div>
	<div class="flex w-full justify-between mb-1">
		<div class="self-center text-sm font-semibold">{$i18n.t('Glossary')}</div>
	</div>

	<div class="text-xs dark:text-gray-500">
		{$i18n.t('Select glossaries the agent will use.')}
	</div>

	<div class="flex flex-col">
		{#if selectedGlossaries?.length > 0}
			<div class="flex flex-wrap items-center gap-1.5 mt-2">
				{#each selectedGlossaries as item, idx}
					<ResourceChip
						name={item.name ?? item.id}
						description={descFor(item)}
						badge={$i18n.t('Dictionary')}
						badgeTone="amber"
						dismissible={canWrite}
						on:dismiss={() => removeAt(idx)}
					/>
				{/each}
			</div>
			<MissingDescriptionWarning missingNames={missingDescriptionNames} />
		{/if}

		{#if canWrite}
			<div class="flex flex-wrap text-sm font-medium gap-1.5 mt-2">
				<button
					type="button"
					class="px-3.5 py-1.5 font-medium hover:bg-black/5 dark:hover:bg-white/5 outline outline-1 outline-gray-100 dark:outline-gray-850 rounded-3xl"
					on:click={() => (showPicker = true)}
				>
					{$i18n.t('Select Glossary')}
				</button>
			</div>
		{/if}
	</div>
</div>

<ResourcePickerModal
	bind:show={showPicker}
	title={$i18n.t('Select Glossary')}
	description={$i18n.t('Select glossaries the agent will use.')}
	selected={selectedGlossaries}
	{fetchItems}
	{excludeIds}
	searchKeys={['name', 'description']}
	emptyMessage={$i18n.t('No glossaries found')}
	on:apply={onApply}
>
	<svelte:fragment slot="badges">
		<span
			class="px-1.5 py-0.5 rounded-sm uppercase text-[10px] font-bold leading-none bg-amber-500/15 text-amber-700 dark:text-amber-200"
		>
			{$i18n.t('Dictionary')}
		</span>
	</svelte:fragment>
</ResourcePickerModal>

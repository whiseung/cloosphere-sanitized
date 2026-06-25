<script lang="ts">
	import { getContext, onMount } from 'svelte';
	import ResourcePickerModal from '../common/ResourcePickerModal.svelte';
	import ResourceChip from '../common/ResourceChip.svelte';
	import MissingDescriptionWarning from './MissingDescriptionWarning.svelte';
	import { getDbSpheres } from '$lib/apis/dbsphere';

	export let selectedDbSpheres: any[] = [];
	export let canWrite = true;
	// KG에서 자동 inherit되는 DbSphere ID들 — picker에서 숨김
	export let excludeIds: string[] = [];

	const i18n = getContext('i18n');

	let allItems: any[] = [];
	let showPicker = false;

	const fetchItems = async () => {
		const data = (await getDbSpheres(localStorage.token)) ?? [];
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

	$: missingDescriptionNames = selectedDbSpheres
		.map((sel: any) => {
			const full = allItems.find((it) => it.id === sel.id) ?? sel;
			const desc = full?.meta?.tool_description ?? '';
			return !desc || !String(desc).trim() ? (full?.name ?? sel?.name ?? sel?.id) : null;
		})
		.filter((n: string | null): n is string => !!n);

	const onApply = (e: CustomEvent<any[]>) => {
		selectedDbSpheres = e.detail.map((item: any) => ({ id: item.id, name: item.name }));
	};

	const removeAt = (idx: number) => {
		selectedDbSpheres = selectedDbSpheres.filter((_, i) => i !== idx);
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
		<div class="self-center text-sm font-semibold">{$i18n.t('Database')}</div>
	</div>

	<div class="text-xs dark:text-gray-500">
		{$i18n.t('Select databases the agent will use.')}
	</div>

	<div class="flex flex-col">
		{#if selectedDbSpheres?.length > 0}
			<div class="flex flex-wrap items-center gap-1.5 mt-2">
				{#each selectedDbSpheres as item, idx}
					<ResourceChip
						name={item.name ?? item.id}
						description={descFor(item)}
						badge="DB"
						badgeTone="blue"
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
					{$i18n.t('Select Database')}
				</button>
			</div>
		{/if}
	</div>
</div>

<ResourcePickerModal
	bind:show={showPicker}
	title={$i18n.t('Select Database')}
	description={$i18n.t('Select databases the agent will use.')}
	selected={selectedDbSpheres}
	{fetchItems}
	{excludeIds}
	searchKeys={['name', 'description']}
	emptyMessage={$i18n.t('No databases found')}
	on:apply={onApply}
>
	<svelte:fragment slot="badges">
		<span
			class="px-1.5 py-0.5 rounded-sm uppercase text-[10px] font-bold leading-none bg-blue-500/15 text-blue-700 dark:text-blue-200"
		>
			DB
		</span>
	</svelte:fragment>
</ResourcePickerModal>

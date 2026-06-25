<script lang="ts">
	import { getContext, onMount } from 'svelte';
	import ResourcePickerModal from '../common/ResourcePickerModal.svelte';
	import ResourceChip from '../common/ResourceChip.svelte';
	import MissingDescriptionWarning from './MissingDescriptionWarning.svelte';
	import { getKnowledgeBases } from '$lib/apis/knowledge';

	export let selectedKnowledge: any[] = [];
	export const collections: any[] = [];
	export let canWrite = true;
	// KG에서 자동 inherit되는 KB ID들 — picker에서 숨김
	export let excludeIds: string[] = [];

	const i18n = getContext('i18n');

	let allItems: any[] = [];
	let showPicker = false;

	const fetchItems = async () => {
		const data = (await getKnowledgeBases(localStorage.token)) ?? [];

		const legacy_documents = data.filter((item: any) => item?.meta?.document);
		const legacy_collections =
			legacy_documents.length > 0
				? [
						{
							id: 'all-documents',
							name: 'All Documents',
							legacy: true,
							type: 'collection',
							description: 'Deprecated (legacy collection), please create a new knowledge base.',
							title: $i18n.t('All Documents'),
							collection_names: legacy_documents.map((item: any) => item.id)
						},
						...legacy_documents
							.reduce((a: string[], item: any) => {
								return [...new Set([...a, ...(item?.meta?.tags ?? []).map((tag: any) => tag.name)])];
							}, [])
							.map((tag: string) => ({
								id: `legacy-tag-${tag}`,
								name: tag,
								legacy: true,
								type: 'collection',
								description: 'Deprecated (legacy collection), please create a new knowledge base.',
								collection_names: legacy_documents
									.filter((item: any) =>
										(item?.meta?.tags ?? []).map((tag: any) => tag.name).includes(tag)
									)
									.map((item: any) => item.id)
							}))
					]
				: [];

		const merged = [...data, ...legacy_collections].map((item: any) => ({
			...item,
			...(item?.legacy || item?.meta?.legacy || item?.meta?.document ? { legacy: true } : {}),
			type: item?.meta?.document ? 'document' : 'collection'
		}));
		allItems = merged;
		return merged;
	};

	onMount(async () => {
		try {
			await fetchItems();
		} catch {
			allItems = [];
		}
	});

	$: missingDescriptionNames = selectedKnowledge
		.map((sel: any) => {
			const full = allItems.find((it) => it.id === sel.id) ?? sel;
			const desc = full?.meta?.tool_description ?? '';
			return !desc || !String(desc).trim() ? (full?.name ?? sel?.name ?? sel?.id) : null;
		})
		.filter((n: string | null): n is string => !!n);

	const filters = [
		{
			value: 'collection',
			label: $i18n.t('Collection'),
			predicate: (it: any) => it?.type === 'collection' && !it?.legacy
		},
		{
			value: 'document',
			label: $i18n.t('Document'),
			predicate: (it: any) => it?.type === 'document'
		},
		{ value: 'legacy', label: $i18n.t('Legacy'), predicate: (it: any) => !!it?.legacy }
	];

	const onApply = (e: CustomEvent<any[]>) => {
		selectedKnowledge = e.detail.map((item: any) => ({ ...item }));
	};

	const removeAt = (idx: number) => {
		selectedKnowledge = selectedKnowledge.filter((_, i) => i !== idx);
	};

	const badgeFor = (item: any) => {
		if (item?.legacy) return { label: 'Legacy', tone: 'gray' as const };
		if (item?.meta?.document) return { label: 'Document', tone: 'gray' as const };
		return { label: 'Collection', tone: 'green' as const };
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
		<div class="self-center text-sm font-semibold">{$i18n.t('Knowledge')}</div>
	</div>

	<div class="text-xs dark:text-gray-500">
		{$i18n.t('Select knowledge bases the agent will use.')}
	</div>

	<div class="flex flex-col">
		{#if selectedKnowledge?.length > 0}
			<div class="flex flex-wrap items-center gap-1.5 mt-2">
				{#each selectedKnowledge as item, idx}
					{@const b = badgeFor(item)}
					<ResourceChip
						name={item.name ?? item.id}
						description={descFor(item)}
						badge={b.label}
						badgeTone={b.tone}
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
					{$i18n.t('Select Knowledge')}
				</button>
			</div>
		{/if}
	</div>
</div>

<ResourcePickerModal
	bind:show={showPicker}
	title={$i18n.t('Select Knowledge')}
	description={$i18n.t('Select knowledge bases the agent will use.')}
	selected={selectedKnowledge}
	{fetchItems}
	{excludeIds}
	{filters}
	searchKeys={['name', 'description']}
	emptyMessage={$i18n.t('No knowledge found')}
	on:apply={onApply}
>
	<svelte:fragment slot="badges" let:item>
		{@const b = badgeFor(item)}
		<span
			class="px-1.5 py-0.5 rounded-sm uppercase text-[10px] font-bold leading-none {b.tone === 'green'
				? 'bg-green-500/15 text-green-700 dark:text-green-200'
				: 'bg-gray-500/15 text-gray-700 dark:text-gray-200'}"
		>
			{b.label}
		</span>
	</svelte:fragment>
</ResourcePickerModal>

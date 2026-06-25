<script lang="ts">
	import { getContext, onMount } from 'svelte';
	import {
		getKnowledgeGraphById,
		getKnowledgeGraphs,
		type KnowledgeGraph
	} from '$lib/apis/knowledge-graph';
	import ResourcePickerModal from '../common/ResourcePickerModal.svelte';
	import ResourceChip from '../common/ResourceChip.svelte';
	import MissingDescriptionWarning from './MissingDescriptionWarning.svelte';

	export let selectedKnowledgeGraphs: Array<{ id: string; name?: string }> = [];
	export let canWrite = true;

	// 양방향 바인딩: AgentEditor가 이걸 받아서 Knowledge/DbSphere/Glossary
	// 서브컴포넌트에 excludeIds로 전달 → 중복 추가 방지
	export let inheritedKnowledgeIds: string[] = [];
	export let inheritedDbsphereIds: string[] = [];
	export let inheritedGlossaryIds: string[] = [];

	const i18n = getContext<{ t: (key: string) => string }>('i18n');

	let allItems: KnowledgeGraph[] = [];
	let showPicker = false;

	const fetchItems = async (): Promise<any[]> => {
		const data = (await getKnowledgeGraphs(localStorage.token)) ?? [];
		allItems = data;
		return data as any[];
	};

	onMount(async () => {
		try {
			await fetchItems();
		} catch {
			allItems = [];
		}
	});

	$: missingDescriptionNames = selectedKnowledgeGraphs
		.map((sel) => {
			const full = allItems.find((it) => it.id === sel.id);
			const desc = full?.meta?.tool_description ?? '';
			return !desc || !String(desc).trim() ? (full?.name ?? sel.name ?? sel.id) : null;
		})
		.filter((n): n is string => !!n);

	let kgSourcesCache: Record<
		string,
		{ knowledge_ids: string[]; dbsphere_ids: string[]; glossary_ids: string[]; name?: string }
	> = {};

	$: pickerExcludeIds = selectedKnowledgeGraphs.map((kg) => kg.id);

	$: void resolveInheritance(selectedKnowledgeGraphs);

	const resolveInheritance = async (kgs: Array<{ id: string }>) => {
		const ids = kgs.map((k) => k.id).filter(Boolean);
		const toFetch = ids.filter((id) => !(id in kgSourcesCache));
		if (toFetch.length > 0) {
			type FetchedEntry = [
				string,
				{ knowledge_ids: string[]; dbsphere_ids: string[]; glossary_ids: string[]; name?: string }
			];
			const fetched: FetchedEntry[] = await Promise.all(
				toFetch.map(async (id): Promise<FetchedEntry> => {
					try {
						const kg: KnowledgeGraph | null = await getKnowledgeGraphById(
							localStorage.token,
							id
						);
						const s = kg?.data?.sources ?? {};
						return [
							id,
							{
								knowledge_ids: s.knowledge_ids ?? [],
								dbsphere_ids: s.dbsphere_ids ?? [],
								glossary_ids: s.glossary_ids ?? [],
								name: kg?.name
							}
						];
					} catch (e) {
						console.warn('failed to fetch KG details:', id, e);
						return [
							id,
							{ knowledge_ids: [], dbsphere_ids: [], glossary_ids: [], name: undefined }
						];
					}
				})
			);
			const next = { ...kgSourcesCache };
			for (const [id, sources] of fetched) {
				next[id] = sources;
			}
			kgSourcesCache = next;
		}

		const kbSet = new Set<string>();
		const dbSet = new Set<string>();
		const gSet = new Set<string>();
		for (const id of ids) {
			const s = kgSourcesCache[id];
			if (!s) continue;
			s.knowledge_ids.forEach((x) => kbSet.add(x));
			s.dbsphere_ids.forEach((x) => dbSet.add(x));
			s.glossary_ids.forEach((x) => gSet.add(x));
		}
		inheritedKnowledgeIds = Array.from(kbSet);
		inheritedDbsphereIds = Array.from(dbSet);
		inheritedGlossaryIds = Array.from(gSet);
	};

	const inheritedSummary = (kgId: string): string => {
		const s = kgSourcesCache[kgId];
		if (!s) return '';
		const parts: string[] = [];
		if (s.knowledge_ids.length) parts.push(`KB ${s.knowledge_ids.length}`);
		if (s.dbsphere_ids.length) parts.push(`DB ${s.dbsphere_ids.length}`);
		if (s.glossary_ids.length) parts.push(`Glossary ${s.glossary_ids.length}`);
		return parts.length ? parts.join(' · ') : $i18n.t('no inherited resources');
	};

	const onApply = (e: CustomEvent<any[]>) => {
		selectedKnowledgeGraphs = e.detail.map((item: any) => ({ id: item.id, name: item.name }));
	};

	const removeAt = (idx: number) => {
		selectedKnowledgeGraphs = selectedKnowledgeGraphs.filter((_, i) => i !== idx);
	};

	$: descMap = (() => {
		const m: Record<string, string> = {};
		for (const it of allItems) m[it.id] = (it as any)?.description ?? '';
		return m;
	})();
	$: descFor = (item: { id: string; description?: string }) =>
		descMap[item?.id] || item?.description || '';
</script>

<div>
	<div class="flex w-full justify-between mb-1">
		<div class="self-center text-sm font-semibold">
			{$i18n.t('Knowledge Graph')}
		</div>
	</div>

	<div class="text-xs dark:text-gray-500">
		{$i18n.t('Select knowledge graphs the agent will use.')}
	</div>

	<div class="flex flex-col">
		{#if selectedKnowledgeGraphs?.length > 0}
			<div class="flex flex-wrap items-center gap-1.5 mt-2">
				{#each selectedKnowledgeGraphs as kg, idx}
					<ResourceChip
						name={kg.name ?? kg.id}
						description={descFor(kg)}
						badge={$i18n.t('Graph')}
						badgeTone="purple"
						dismissible={canWrite}
						on:dismiss={() => removeAt(idx)}
					/>
				{/each}
			</div>
			<MissingDescriptionWarning missingNames={missingDescriptionNames} />
			{#if Object.keys(kgSourcesCache).length > 0}
				<div class="flex flex-wrap gap-2 mt-1">
					{#each selectedKnowledgeGraphs as kg}
						{#if kgSourcesCache[kg.id]}
							<span class="text-[11px] text-gray-500 dark:text-gray-400 italic">
								{kg.name ?? kg.id}: ↳ {inheritedSummary(kg.id)}
							</span>
						{/if}
					{/each}
				</div>
			{/if}
		{/if}

		{#if canWrite}
			<div class="flex flex-wrap text-sm font-medium gap-1.5 mt-2">
				<button
					type="button"
					class="px-3.5 py-1.5 font-medium hover:bg-black/5 dark:hover:bg-white/5 outline outline-1 outline-gray-100 dark:outline-gray-850 rounded-3xl"
					on:click={() => (showPicker = true)}
				>
					{$i18n.t('Select Knowledge Graph')}
				</button>
			</div>
		{/if}
	</div>
</div>

<ResourcePickerModal
	bind:show={showPicker}
	title={$i18n.t('Select Knowledge Graph')}
	description={$i18n.t('Select knowledge graphs the agent will use.')}
	selected={selectedKnowledgeGraphs}
	{fetchItems}
	excludeIds={pickerExcludeIds}
	searchKeys={['name', 'description']}
	emptyMessage={$i18n.t('No knowledge graphs found')}
	on:apply={onApply}
>
	<svelte:fragment slot="badges">
		<span
			class="px-1.5 py-0.5 rounded-sm uppercase text-[10px] font-bold leading-none bg-purple-500/15 text-purple-700 dark:text-purple-200"
		>
			{$i18n.t('Graph')}
		</span>
	</svelte:fragment>
</ResourcePickerModal>

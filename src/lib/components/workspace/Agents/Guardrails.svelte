<script lang="ts">
	import { getContext, onMount } from 'svelte';
	import ResourcePickerModal from '../common/ResourcePickerModal.svelte';
	import ResourceChip from '../common/ResourceChip.svelte';
	import { getGuardrails } from '$lib/apis/guardrails';

	export let selectedGuardrails: any[] = [];
	export let canWrite = true;

	const i18n = getContext('i18n');

	let allItems: any[] = [];
	let showPicker = false;

	const fetchItems = async () => {
		const data = (await getGuardrails(localStorage.token)) ?? [];
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

	const labelFor = (item: any) => (item?.llm_judge_enabled ? 'LLM Judge' : 'Rule-based');

	const filters = [
		{
			value: 'llm',
			label: 'LLM Judge',
			predicate: (it: any) => !!it?.llm_judge_enabled
		},
		{
			value: 'rule',
			label: 'Rule-based',
			predicate: (it: any) => !it?.llm_judge_enabled
		}
	];

	const onApply = (e: CustomEvent<any[]>) => {
		selectedGuardrails = e.detail.map((item: any) => ({
			id: item.id,
			name: item.name,
			llm_judge_enabled: item.llm_judge_enabled
		}));
	};

	const removeAt = (idx: number) => {
		selectedGuardrails = selectedGuardrails.filter((_, i) => i !== idx);
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
		<div class="self-center text-sm font-semibold">{$i18n.t('Guardrails')}</div>
	</div>

	<div class="text-xs dark:text-gray-500">
		{$i18n.t('Select guardrails the agent will use.')}
	</div>

	<div class="flex flex-col">
		{#if selectedGuardrails?.length > 0}
			<div class="flex flex-wrap items-center gap-1.5 mt-2">
				{#each selectedGuardrails as item, idx}
					<ResourceChip
						name={item.name ?? item.id}
						description={descFor(item)}
						badge={labelFor(item)}
						badgeTone={item?.llm_judge_enabled ? 'purple' : 'gray'}
						dismissible={canWrite}
						on:dismiss={() => removeAt(idx)}
					/>
				{/each}
			</div>
		{/if}

		{#if canWrite}
			<div class="flex flex-wrap text-sm font-medium gap-1.5 mt-2">
				<button
					type="button"
					class="px-3.5 py-1.5 font-medium hover:bg-black/5 dark:hover:bg-white/5 outline outline-1 outline-gray-100 dark:outline-gray-850 rounded-3xl"
					on:click={() => (showPicker = true)}
				>
					{$i18n.t('Select Guardrail')}
				</button>
			</div>
		{/if}
	</div>
</div>

<ResourcePickerModal
	bind:show={showPicker}
	title={$i18n.t('Select Guardrail')}
	description={$i18n.t('Select guardrails the agent will use.')}
	selected={selectedGuardrails}
	{fetchItems}
	{filters}
	searchKeys={['name', 'description']}
	emptyMessage={$i18n.t('No guardrails found')}
	on:apply={onApply}
>
	<svelte:fragment slot="badges" let:item>
		<span
			class="px-1.5 py-0.5 rounded-sm uppercase text-[10px] font-bold leading-none {item?.llm_judge_enabled
				? 'bg-purple-500/15 text-purple-700 dark:text-purple-200'
				: 'bg-gray-500/15 text-gray-700 dark:text-gray-200'}"
		>
			{labelFor(item)}
		</span>
	</svelte:fragment>
</ResourcePickerModal>

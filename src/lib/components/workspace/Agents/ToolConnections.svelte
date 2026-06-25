<script lang="ts">
	import { getContext, onMount } from 'svelte';
	import ResourcePickerModal from '../common/ResourcePickerModal.svelte';
	import ResourceChip from '../common/ResourceChip.svelte';
	import MissingDescriptionWarning from './MissingDescriptionWarning.svelte';
	import { getToolConnections } from '$lib/apis/tool-connections';

	export let selectedToolConnections: any[] = [];
	export let canWrite = true;

	const i18n = getContext('i18n');

	let allItems: any[] = [];
	let showPicker = false;

	const fetchItems = async () => {
		const data = (await getToolConnections(localStorage.token)) ?? [];
		// 마켓플레이스 출처 연결은 "Marketplace Tools" 섹션에서 관리하므로 일반 피커에서는 제외.
		allItems = data.filter((it: any) => it?.meta?.source !== 'marketplace');
		return allItems;
	};

	onMount(async () => {
		try {
			await fetchItems();
		} catch {
			allItems = [];
		}
	});

	$: missingDescriptionNames = selectedToolConnections
		.map((sel: any) => {
			const full = allItems.find((it) => it.id === sel.id) ?? sel;
			const desc = full?.meta?.tool_description ?? '';
			return !desc || !String(desc).trim() ? (full?.name ?? sel?.name ?? sel?.id) : null;
		})
		.filter((n: string | null): n is string => !!n);

	const labelFor = (item: any) => {
		const t = item?.connection?.type;
		if (t === 'mcp') return 'MCP';
		if (t === 'openapi') return 'OpenAPI';
		return 'Tool';
	};

	const filters = [
		{
			value: 'mcp',
			label: 'MCP',
			predicate: (it: any) => it?.connection?.type === 'mcp'
		},
		{
			value: 'openapi',
			label: 'OpenAPI',
			predicate: (it: any) => it?.connection?.type === 'openapi'
		}
	];

	const onApply = (e: CustomEvent<any[]>) => {
		selectedToolConnections = e.detail.map((item: any) => ({
			id: item.id,
			name: item.name,
			connection: item.connection
		}));
	};

	const removeAt = (idx: number) => {
		selectedToolConnections = selectedToolConnections.filter((_, i) => i !== idx);
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
		<div class="self-center text-sm font-semibold">{$i18n.t('Tool Connections')}</div>
	</div>

	<div class="text-xs dark:text-gray-500">
		{$i18n.t('Select tool connections the agent will use.')}
	</div>

	<div class="flex flex-col">
		{#if selectedToolConnections?.length > 0}
			<div class="flex flex-wrap items-center gap-1.5 mt-2">
				{#each selectedToolConnections as item, idx}
					<ResourceChip
						name={item.name ?? item.id}
						description={descFor(item)}
						badge={labelFor(item)}
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
					{$i18n.t('Select Tool Connection')}
				</button>
			</div>
		{/if}
	</div>
</div>

<ResourcePickerModal
	bind:show={showPicker}
	title={$i18n.t('Select Tool Connection')}
	description={$i18n.t('Select tool connections the agent will use.')}
	selected={selectedToolConnections}
	{fetchItems}
	{filters}
	searchKeys={['name', 'description']}
	emptyMessage={$i18n.t('No tool connections found')}
	on:apply={onApply}
>
	<svelte:fragment slot="badges" let:item>
		<span
			class="px-1.5 py-0.5 rounded-sm uppercase text-[10px] font-bold leading-none bg-blue-500/15 text-blue-700 dark:text-blue-200"
		>
			{labelFor(item)}
		</span>
	</svelte:fragment>
</ResourcePickerModal>

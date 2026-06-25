<script lang="ts">
	import { getContext, onMount } from 'svelte';
	import ResourcePickerModal from '../common/ResourcePickerModal.svelte';
	import ResourceChip from '../common/ResourceChip.svelte';
	import { getToolConnections } from '$lib/apis/tool-connections';

	// 에이전트 meta.marketplaceTools 에 저장되는 항목: [{ id, name, service_id }].
	// id 는 백킹 tool_connection id 이며, 백엔드 AgentConfig 가 tool_connections 로 병합한다
	// (런타임 처리는 일반 tool_connection 과 동일).
	export let selectedMarketplaceTools: any[] = [];
	export let canWrite = true;

	const i18n = getContext('i18n');

	// service_id → 표시 라벨 (카탈로그 정적 매핑).
	const SERVICE_LABELS: Record<string, string> = {
		'google-workspace': 'Google Workspace',
		'microsoft-365': 'Microsoft 365'
	};
	const serviceLabel = (item: any): string =>
		SERVICE_LABELS[item?.meta?.service_id ?? item?.service_id] ?? 'Marketplace';

	// 워크스페이스 > 마켓플레이스에서 만든 연결(tool_connection)만 노출 (기본 카탈로그 서비스 X).
	let allItems: any[] = [];
	let showPicker = false;

	const fetchItems = async () => {
		const data = (await getToolConnections(localStorage.token)) ?? [];
		allItems = data.filter((it: any) => it?.meta?.source === 'marketplace');
		return allItems;
	};

	onMount(async () => {
		try {
			await fetchItems();
		} catch {
			allItems = [];
		}
	});

	const descFor = (item: any): string => {
		const full = allItems.find((it) => it.id === item.id);
		return full?.description ?? item?.description ?? '';
	};

	const onApply = (e: CustomEvent<any[]>) => {
		selectedMarketplaceTools = e.detail.map((item: any) => ({
			id: item.id,
			name: item.name,
			service_id: item?.meta?.service_id ?? item?.service_id
		}));
	};

	const removeAt = (idx: number) => {
		selectedMarketplaceTools = selectedMarketplaceTools.filter((_, i) => i !== idx);
	};
</script>

<div>
	<div class="flex w-full justify-between mb-1">
		<div class="self-center text-sm font-semibold">{$i18n.t('Marketplace Tools')}</div>
	</div>

	<div class="text-xs dark:text-gray-500">
		{$i18n.t(
			'Add tools from connected Marketplace services. Their results are available to the agent while it generates the answer.'
		)}
	</div>

	<div class="flex flex-col">
		{#if selectedMarketplaceTools?.length > 0}
			<div class="flex flex-wrap items-center gap-1.5 mt-2">
				{#each selectedMarketplaceTools as item, idx}
					<ResourceChip
						name={item.name ?? item.id}
						description={descFor(item)}
						badge={serviceLabel(item)}
						badgeTone="blue"
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
					{$i18n.t('Select Marketplace Tool')}
				</button>
			</div>
		{/if}
	</div>
</div>

<ResourcePickerModal
	bind:show={showPicker}
	title={$i18n.t('Select Marketplace Tool')}
	description={$i18n.t(
		'Add tools from connected Marketplace services. Their results are available to the agent while it generates the answer.'
	)}
	selected={selectedMarketplaceTools}
	{fetchItems}
	searchKeys={['name', 'description']}
	emptyMessage={$i18n.t('No marketplace tools available')}
	on:apply={onApply}
>
	<svelte:fragment slot="badges" let:item>
		<span
			class="px-1.5 py-0.5 rounded-sm text-[10px] font-bold leading-none bg-blue-500/15 text-blue-700 dark:text-blue-200"
		>
			{serviceLabel(item)}
		</span>
	</svelte:fragment>
</ResourcePickerModal>

<script lang="ts">
	import Fuse from 'fuse.js';

	import dayjs from 'dayjs';
	import relativeTime from 'dayjs/plugin/relativeTime';
	dayjs.extend(relativeTime);

	import { toast } from 'svelte-sonner';
	import { onMount, getContext } from 'svelte';
	const i18n = getContext('i18n');

	import { WEBUI_NAME, user, workspaceTags, activeWorkspaceFilter } from '$lib/stores';
	import { getWorkspaceTags, getAssignmentsByType } from '$lib/apis/workspace-tags';
	import { getAgentFlows, deleteAgentFlowById } from '$lib/apis/agent-flows';
	import type { AgentFlow } from '$lib/apis/agent-flows';

	import { goto } from '$app/navigation';

	import DeleteConfirmDialog from '../common/ConfirmDialog.svelte';
	import FlowMenu from './Flows/FlowMenu.svelte';
	import Badge from '../common/Badge.svelte';
	import Button from '../common/Button.svelte';
	import Input from '../common/Input.svelte';
	import Search from '../icons/Search.svelte';
	import Plus from '../icons/Plus.svelte';
	import Spinner from '../common/Spinner.svelte';
	import Tooltip from '../common/Tooltip.svelte';
	import { capitalizeFirstLetter } from '$lib/utils';
	import WorkspaceCard from '../common/WorkspaceCard.svelte';

	let loaded = false;

	let query = '';
	let selectedItem: AgentFlow | null = null;
	let showDeleteConfirm = false;

	let fuse: Fuse<AgentFlow> | null = null;

	let flowList: AgentFlow[] = [];
	let filteredItems: AgentFlow[] = [];
	let tagAssignments: Record<string, string[]> = {};

	$: allTags = [...new Set(Object.values(tagAssignments).flat())].sort();

	$: if (flowList) {
		fuse = new Fuse(flowList, {
			keys: ['name', 'description']
		});
	}

	$: if (fuse) {
		let result = query ? fuse.search(query).map((e) => e.item) : flowList;

		if ($activeWorkspaceFilter === 'mine') {
			result = result.filter((item) => item.user_id === $user?.id);
		} else if ($activeWorkspaceFilter.startsWith('tag:')) {
			const tagName = $activeWorkspaceFilter.slice(4);
			result = result.filter((item) => (tagAssignments[item.id] ?? []).includes(tagName));
		}

		filteredItems = result;
	}

	const deleteHandler = async (item: AgentFlow) => {
		const res = await deleteAgentFlowById(localStorage.token, item.id).catch((e) => {
			toast.error($i18n.t(`${e}`));
		});

		if (res) {
			flowList = await getAgentFlows(localStorage.token);
			toast.success($i18n.t('Flow deleted successfully.'));
		}
	};

	const getNodeCount = (flow: AgentFlow) => {
		return flow.flow_data?.nodes?.length || 0;
	};

	const getEdgeCount = (flow: AgentFlow) => {
		return flow.flow_data?.edges?.length || 0;
	};

	onMount(async () => {
		try {
			flowList = (await getAgentFlows(localStorage.token)) || [];
		} catch (e) {
			console.error('Failed to load flows:', e);
			flowList = [];
		}

		try {
			workspaceTags.set(await getWorkspaceTags(localStorage.token));
			tagAssignments = await getAssignmentsByType(localStorage.token, 'flow');
		} catch (e) {
			console.error('Failed to load workspace tags:', e);
		}

		loaded = true;
	});
</script>

<svelte:head>
	<title>
		{$i18n.t('Flows')} | {$WEBUI_NAME}
	</title>
</svelte:head>

{#if loaded}
	<DeleteConfirmDialog
		bind:show={showDeleteConfirm}
		on:confirm={() => {
			if (selectedItem) deleteHandler(selectedItem);
		}}
	/>

	<!-- Header Row -->
	<div class="flex items-center justify-between gap-[var(--cloo-space-2)] mt-2 mb-4">
		<div class="flex items-center gap-2.5">
			<span class="text-lg font-medium text-[var(--cloo-text-primary)]">
				{$i18n.t('Flows')}
			</span>
			<span class="text-lg font-medium text-[var(--token-scale-neutral-400)]">
				{filteredItems.length}
			</span>
		</div>

		<div class="flex items-center gap-[var(--cloo-space-2)]">
			<div class="w-[300px]">
				<Input bind:value={query} placeholder={$i18n.t('Search Flows')} type="search" size="md">
					<svelte:fragment slot="prefix">
						<Search className="size-3.5" />
					</svelte:fragment>
				</Input>
			</div>

			{#if $user?.role === 'admin' || $user?.permissions?.workspace?.agent_flows === 'write'}
				<div class="flex items-center gap-[var(--cloo-space-2)]">
					<Button
						kind="filled"
						size="md"
						on:click={() => {
							goto('/workspace/flows/create');
						}}
					>
						<svelte:fragment slot="prefix">
							<Plus className="size-3.5" />
						</svelte:fragment>
						{$i18n.t('New Flow')}
					</Button>
				</div>
			{/if}
		</div>
	</div>

	<!-- Filter Chips -->
	<div class="flex items-center gap-1.5 mb-4 flex-wrap">
		<button
			class="px-3 py-1 text-xs font-medium rounded-full transition-colors
				{$activeWorkspaceFilter === 'all'
				? 'bg-gray-800 text-white dark:bg-white dark:text-gray-900'
				: 'bg-gray-100 text-gray-600 hover:bg-gray-200 dark:bg-gray-800 dark:text-gray-400 dark:hover:bg-gray-700'}"
			on:click={() => ($activeWorkspaceFilter = 'all')}
		>
			{$i18n.t('All')}
		</button>
		<button
			class="px-3 py-1 text-xs font-medium rounded-full transition-colors
				{$activeWorkspaceFilter === 'mine'
				? 'bg-gray-800 text-white dark:bg-white dark:text-gray-900'
				: 'bg-gray-100 text-gray-600 hover:bg-gray-200 dark:bg-gray-800 dark:text-gray-400 dark:hover:bg-gray-700'}"
			on:click={() => ($activeWorkspaceFilter = 'mine')}
		>
			{$i18n.t('My Flows')}
		</button>
		{#each allTags as tag}
			<button
				class="px-3 py-1 text-xs font-medium rounded-full transition-colors
					{$activeWorkspaceFilter === 'tag:' + tag
					? 'bg-gray-800 text-white dark:bg-white dark:text-gray-900'
					: 'bg-gray-100 text-gray-600 hover:bg-gray-200 dark:bg-gray-800 dark:text-gray-400 dark:hover:bg-gray-700'}"
				on:click={() =>
					($activeWorkspaceFilter = $activeWorkspaceFilter === 'tag:' + tag ? 'all' : 'tag:' + tag)}
			>
				{tag}
			</button>
		{/each}
	</div>

	<div class="workspace-cards-grid mb-5">
		{#each filteredItems as item}
			<WorkspaceCard
				name={item.name}
				description={item.description || ''}
				isActive={item.is_active}
				on:click={() => {
					goto(`/workspace/flows/${item.id}`);
				}}
			>
				<svelte:fragment slot="badge">
					<div class="flex items-center gap-2">
						<Badge
							type={item.is_active ? 'success' : 'muted'}
							content={item.is_active ? $i18n.t('Active') : $i18n.t('Inactive')}
						/>
						<span class="text-xs text-gray-500">
							{getNodeCount(item)}
							{$i18n.t('nodes')}
						</span>
					</div>
				</svelte:fragment>

				<svelte:fragment slot="actions">
					{#if $user?.role === 'admin' || $user?.permissions?.workspace?.agent_flows === 'write'}
						<FlowMenu
							on:delete={() => {
								selectedItem = item;
								showDeleteConfirm = true;
							}}
						/>
					{/if}
				</svelte:fragment>

				<svelte:fragment slot="description-fallback">
					{$i18n.t('No description')}
				</svelte:fragment>

				<svelte:fragment slot="footer-left">
					<div class="text-xs text-gray-500">
						<Tooltip
							content={item?.user?.email ?? $i18n.t('Deleted User')}
							className="flex shrink-0"
							placement="top-start"
						>
							{$i18n.t('By {{name}}', {
								name: capitalizeFirstLetter(
									item?.user?.name ?? item?.user?.email ?? $i18n.t('Deleted User')
								)
							})}
						</Tooltip>
					</div>
				</svelte:fragment>

				<svelte:fragment slot="footer-right">
					<div class="text-xs text-gray-500 line-clamp-1">
						{$i18n.t('Updated')}
						{dayjs(item.updated_at * 1000).fromNow()}
					</div>
				</svelte:fragment>
			</WorkspaceCard>
		{/each}
	</div>

	{#if filteredItems.length === 0}
		<div class="flex flex-col items-center justify-center h-64 text-gray-500 dark:text-gray-400">
			{#if query}
				<div class="text-sm">{$i18n.t('No flows found matching your search.')}</div>
			{:else}
				<div class="text-6xl mb-4">🔀</div>
				<div class="text-xl font-medium mb-2">{$i18n.t('No flows yet')}</div>
				<div class="text-sm">{$i18n.t('Create a flow to get started.')}</div>
			{/if}
		</div>
	{/if}

	<div class=" text-gray-500 text-xs mt-1 mb-2 flex items-center gap-1.5 flex-wrap">
		<span
			class="inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300"
		>
			{$i18n.t('Preview')}
		</span>
		<span>
			ⓘ {$i18n.t(
				'Flows let you visually connect agents, knowledge bases, and tools to create multi-step AI workflows.'
			)}
		</span>
	</div>
{:else}
	<div class="flex justify-center items-center h-64">
		<Spinner />
	</div>
{/if}


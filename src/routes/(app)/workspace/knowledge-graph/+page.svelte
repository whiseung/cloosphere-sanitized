<script lang="ts">
	import dayjs from 'dayjs';
	import relativeTime from 'dayjs/plugin/relativeTime';
	dayjs.extend(relativeTime);

	import { toast } from 'svelte-sonner';
	import { onMount, getContext } from 'svelte';
	import { goto } from '$app/navigation';
	const i18n = getContext<{ t: (key: string, params?: Record<string, unknown>) => string }>(
		'i18n'
	);

	import { WEBUI_NAME, user } from '$lib/stores';
	import {
		deleteKnowledgeGraphById,
		getKnowledgeGraphs,
		type KnowledgeGraph
	} from '$lib/apis/knowledge-graph';

	import DeleteConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';
	import Plus from '$lib/components/icons/Plus.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import Button from '$lib/components/common/Button.svelte';
	import WorkspaceCard from '$lib/components/common/WorkspaceCard.svelte';
	import Badge from '$lib/components/common/Badge.svelte';
	import ItemMenu from '$lib/components/workspace/Knowledge/ItemMenu.svelte';
	import { capitalizeFirstLetter } from '$lib/utils';
	import Tooltip from '$lib/components/common/Tooltip.svelte';

	let loaded = false;
	let items: KnowledgeGraph[] = [];

	let showDeleteConfirm = false;
	let selectedItem: KnowledgeGraph | null = null;

	const reload = async () => {
		try {
			items = await getKnowledgeGraphs(localStorage.token);
		} catch (e) {
			console.error(e);
			items = [];
		}
	};

	const onDeleteClick = (item: KnowledgeGraph) => {
		selectedItem = item;
		showDeleteConfirm = true;
	};

	const deleteHandler = async () => {
		if (!selectedItem) return;
		try {
			await deleteKnowledgeGraphById(localStorage.token, selectedItem.id);
			toast.success($i18n.t('Knowledge graph deleted'));
			await reload();
		} catch (e) {
			toast.error(`${e}`);
		}
	};

	onMount(async () => {
		await reload();
		loaded = true;
	});
</script>

<svelte:head>
	<title>{$i18n.t('Knowledge Graph')} | {$WEBUI_NAME}</title>
</svelte:head>

{#if loaded}
	<DeleteConfirmDialog bind:show={showDeleteConfirm} on:confirm={deleteHandler} />

	<div class="flex items-center justify-between gap-[var(--cloo-space-2)] mt-2 mb-4">
		<div class="flex items-center gap-2.5">
			<span class="text-lg font-medium text-[var(--cloo-text-primary)]">
				{$i18n.t('Knowledge Graph')}
			</span>
			<span class="text-lg font-medium text-[var(--token-scale-neutral-400)]">
				{items.length}
			</span>
		</div>

		<div class="flex items-center gap-[var(--cloo-space-2)]">
			{#if $user?.role === 'admin' || $user?.permissions?.workspace?.knowledge_graphs === 'write'}
				<Button
					kind="filled"
					size="md"
					on:click={() => goto('/workspace/knowledge-graph/create')}
				>
					<svelte:fragment slot="prefix">
						<Plus className="size-3.5" />
					</svelte:fragment>
					{$i18n.t('New Knowledge Graph')}
				</Button>
			{/if}
		</div>
	</div>

	{#if items.length === 0}
		<div class="flex flex-col items-center justify-center h-64 text-gray-500 dark:text-gray-400">
			<div class="text-6xl mb-4">🕸️</div>
			<div class="text-xl font-medium mb-2">{$i18n.t('No knowledge graphs yet')}</div>
			<div class="text-sm">
				{$i18n.t('Create a knowledge graph to connect glossaries, databases, and documents.')}
			</div>
		</div>
	{:else}
		<div class="workspace-cards-grid mb-5">
			{#each items as item}
				<WorkspaceCard
					name={item.name}
					description={item.description ?? ''}
					on:click={() => {
						goto(`/workspace/knowledge-graph/${item.id}`);
					}}
				>
					<svelte:fragment slot="badge">
						<Badge type="info" content={$i18n.t('Graph')} />
					</svelte:fragment>

					<svelte:fragment slot="actions">
						{#if $user?.role === 'admin' || ($user?.permissions?.workspace?.knowledge_graphs === 'write' && item.user_id === $user?.id)}
							<ItemMenu on:delete={() => onDeleteClick(item)} />
						{/if}
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
	{/if}

	<div class="text-gray-500 text-xs mt-1 mb-2">
		ⓘ {$i18n.t(
			'Knowledge graphs link glossary terms, database schemas, and documents into a single semantic layer.'
		)}
	</div>
{:else}
	<div class="w-full h-full flex justify-center items-center">
		<Spinner />
	</div>
{/if}

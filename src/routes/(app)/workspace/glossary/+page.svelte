<script lang="ts">
	import Fuse from 'fuse.js';

	import dayjs from 'dayjs';
	import relativeTime from 'dayjs/plugin/relativeTime';
	dayjs.extend(relativeTime);

	import { toast } from 'svelte-sonner';
	import { onMount, getContext } from 'svelte';
	const i18n = getContext('i18n');

	import { WEBUI_NAME, activeWorkspaceFilter, user, workspaceTags } from '$lib/stores';
	import { getWorkspaceTags, getAssignmentsByType } from '$lib/apis/workspace-tags';
	import {
		getGlossaries,
		deleteGlossaryById,
		getLinkedAgentsByGlossaryId,
		syncGlossaryToSearchEngine
	} from '$lib/apis/glossary';
	import { getGroups } from '$lib/apis/groups';

	import { goto } from '$app/navigation';

	import DeleteConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';
	import ItemMenu from '$lib/components/workspace/Knowledge/ItemMenu.svelte';
	import Badge from '$lib/components/common/Badge.svelte';
	import Search from '$lib/components/icons/Search.svelte';
	import Plus from '$lib/components/icons/Plus.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import Input from '$lib/components/common/Input.svelte';
	import Button from '$lib/components/common/Button.svelte';
	import { capitalizeFirstLetter } from '$lib/utils';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import WorkspaceCard from '$lib/components/common/WorkspaceCard.svelte';
	import CopyGlossaryModal from '$lib/components/workspace/Glossary/CopyGlossaryModal.svelte';

	let loaded = false;

	let query = '';
	let selectedItem = null;
	let showDeleteConfirm = false;
	let showReindexConfirm = false;
	let reindexTarget: any = null;
	let reindexing = false;
	let showLinkedAgentsError = false;
	let linkedAgents: { id: string; name: string }[] = [];

	let fuse = null;

	let items: any[] = [];
	let filteredItems: any[] = [];
	let group_ids: string[] = [];
	let userGroups: { id: string; name: string }[] = [];
	let tagAssignments: Record<string, string[]> = {};

	let showCopyModal = false;
	let copyTarget: any = null;

	$: allTags = [...new Set(Object.values(tagAssignments).flat())].sort();

	$: if (items) {
		fuse = new Fuse(items, {
			keys: ['name', 'description']
		});
	}

	const isGroupShared = (item: any): boolean => {
		if (item.user_id === $user?.id) return false;
		const ac = item.access_control;
		if (ac === null || ac === undefined) return false;
		return true;
	};

	$: hasSharedItems = items.some((item) => isGroupShared(item));

	// governance_meta 기반 filter chip 가시성
	$: hasPublicItems = items.some((item) => item?.governance_meta?.scope_kind === 'public');
	$: hasMyGroupItems = items.some((item) => item?.governance_meta?.is_my_group === true);

	const onCopyClick = (item: any) => {
		copyTarget = item;
		showCopyModal = true;
	};


	$: if (fuse) {
		let result = query
			? fuse.search(query).map((e) => {
					return e.item;
				})
			: items;

		if ($activeWorkspaceFilter === 'mine') {
			result = result.filter((item) => item.user_id === $user?.id);
		} else if ($activeWorkspaceFilter === 'shared') {
			result = result.filter((item) => isGroupShared(item));
		} else if ($activeWorkspaceFilter === 'public') {
			result = result.filter((item) => item?.governance_meta?.scope_kind === 'public');
		} else if ($activeWorkspaceFilter === 'my_group') {
			result = result.filter((item) => item?.governance_meta?.is_my_group === true);
		} else if ($activeWorkspaceFilter.startsWith('tag:')) {
			const tagName = $activeWorkspaceFilter.slice(4);
			result = result.filter((item) => (tagAssignments[item.id] ?? []).includes(tagName));
		}

		filteredItems = result;
	}

	const onDeleteClick = async (item) => {
		selectedItem = item;
		const agents = await getLinkedAgentsByGlossaryId(localStorage.token, item.id).catch(() => []);
		if (agents && agents.length > 0) {
			linkedAgents = agents;
			showLinkedAgentsError = true;
		} else {
			showDeleteConfirm = true;
		}
	};

	const deleteHandler = async (item) => {
		const res = await deleteGlossaryById(localStorage.token, item.id).catch((e) => {
			toast.error($i18n.t(`${e}`));
		});

		if (res) {
			items = await getGlossaries(localStorage.token);
			toast.success($i18n.t('Glossary deleted successfully.'));
		}
	};

	const onReindexClick = (item) => {
		reindexTarget = item;
		showReindexConfirm = true;
	};

	const reindexHandler = async () => {
		if (!reindexTarget) return;
		const item = reindexTarget;
		reindexing = true;
		try {
			const res = await syncGlossaryToSearchEngine(localStorage.token, item.id);
			if (res) {
				toast.success(
					$i18n.t("'{{name}}' search index rebuilt ({{count}} terms).", {
						name: item.name,
						count: res.indexed
					})
				);
			}
		} catch (e) {
			toast.error(`${e}`);
		} finally {
			reindexing = false;
			reindexTarget = null;
		}
	};

	const hasResourceAccess = (item: any, level: 'read' | 'write') => {
		const ac = item.access_control;
		if (!ac) return false;
		const perm = ac[level];
		if (!perm) return false;
		if (perm.user_ids?.includes($user?.id)) return true;
		if (perm.group_ids?.some((gid: string) => group_ids.includes(gid))) return true;
		return false;
	};

	onMount(async () => {
		items =
			(await getGlossaries(localStorage.token).catch((e) => {
				console.error(e);
				return [];
			})) ?? [];

		try {
			const groups = await getGroups(localStorage.token);
			group_ids = groups.map((group: any) => group.id);
			userGroups = groups.map((g: any) => ({ id: g.id, name: g.name }));
		} catch (e) {
			console.error('Failed to load groups:', e);
		}

		try {
			workspaceTags.set(await getWorkspaceTags(localStorage.token));
			tagAssignments = await getAssignmentsByType(localStorage.token, 'glossary');
		} catch (e) {
			console.error('Failed to load workspace tags:', e);
		}

		loaded = true;
	});
</script>

<svelte:head>
	<title>
		{$i18n.t('Glossary')} | {$WEBUI_NAME}
	</title>
</svelte:head>

{#if loaded}
	<DeleteConfirmDialog
		bind:show={showDeleteConfirm}
		on:confirm={() => {
			deleteHandler(selectedItem);
		}}
	/>

	<CopyGlossaryModal
		bind:show={showCopyModal}
		glossary={copyTarget}
		{userGroups}
		on:copied={async () => {
			items = await getGlossaries(localStorage.token);
		}}
	/>

	<DeleteConfirmDialog
		bind:show={showReindexConfirm}
		title={$i18n.t('Rebuild search index')}
		message={reindexTarget
			? $i18n.t("Rebuild search index for '{{name}}'? This will re-push all terms to the search engine.", { name: reindexTarget.name })
			: ''}
		confirmLabel={$i18n.t('Rebuild')}
		on:confirm={reindexHandler}
	/>

	{#if showLinkedAgentsError}
		<!-- svelte-ignore a11y-click-events-have-key-events -->
		<div
			class="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
			on:click|self={() => (showLinkedAgentsError = false)}
		>
			<div
				class="bg-white dark:bg-gray-900 rounded-2xl shadow-xl w-full max-w-md mx-4 p-6 flex flex-col gap-4"
			>
				<div class="flex items-start gap-3">
					<div
						class="flex-shrink-0 w-9 h-9 rounded-full bg-red-100 dark:bg-red-900/30 flex items-center justify-center"
					>
						<svg
							class="w-5 h-5 text-red-500"
							fill="none"
							viewBox="0 0 24 24"
							stroke="currentColor"
							stroke-width="2"
						>
							<path
								stroke-linecap="round"
								stroke-linejoin="round"
								d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z"
							/>
						</svg>
					</div>
					<div>
						<h3 class="text-base font-semibold text-gray-900 dark:text-white">
							{$i18n.t('Cannot delete glossary')}
						</h3>
						<p class="mt-1 text-sm text-gray-500 dark:text-gray-400">
							{$i18n.t(
								'This glossary is connected to the following agents. Please remove it from the agents first.'
							)}
						</p>
					</div>
				</div>

				<ul class="flex flex-col gap-1 pl-1">
					{#each linkedAgents as agent}
						<li class="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300">
							<span class="w-1.5 h-1.5 rounded-full bg-red-400 flex-shrink-0" />
							{agent.name}
						</li>
					{/each}
				</ul>

				<div class="flex justify-end">
					<button
						class="px-4 py-2 rounded-xl text-sm font-medium bg-gray-100 hover:bg-gray-200 dark:bg-gray-800 dark:hover:bg-gray-700 dark:text-white transition"
						on:click={() => (showLinkedAgentsError = false)}
					>
						{$i18n.t('Close')}
					</button>
				</div>
			</div>
		</div>
	{/if}

	<!-- Header Row -->
	<div class="flex items-center justify-between gap-[var(--cloo-space-2)] mt-2 mb-4">
		<div class="flex items-center gap-2.5">
			<span class="text-lg font-medium text-[var(--cloo-text-primary)]">
				{$i18n.t('Glossary')}
			</span>
			<span class="text-lg font-medium text-[var(--token-scale-neutral-400)]">
				{filteredItems.length}
			</span>
		</div>

		<div class="flex items-center gap-[var(--cloo-space-2)]">
			<div class="w-[300px]">
				<Input bind:value={query} placeholder={$i18n.t('Search Glossary')} type="search" size="md">
					<svelte:fragment slot="prefix">
						<Search className="size-3.5" />
					</svelte:fragment>
				</Input>
			</div>

			{#if $user?.role === 'admin' || $user?.permissions?.workspace?.glossaries === 'write'}
				<div class="flex items-center gap-[var(--cloo-space-2)]">
					<Button
						kind="filled"
						size="md"
						on:click={() => {
							goto('/workspace/glossary/create');
						}}
					>
						<svelte:fragment slot="prefix">
							<Plus className="size-3.5" />
						</svelte:fragment>
						{$i18n.t('New Glossary')}
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
		{#if hasPublicItems}
			<button
				class="px-3 py-1 text-xs font-medium rounded-full transition-colors
					{$activeWorkspaceFilter === 'public'
					? 'bg-gray-800 text-white dark:bg-white dark:text-gray-900'
					: 'bg-gray-100 text-gray-600 hover:bg-gray-200 dark:bg-gray-800 dark:text-gray-400 dark:hover:bg-gray-700'}"
				on:click={() => ($activeWorkspaceFilter = 'public')}
			>
				{$i18n.t('Company-wide')}
			</button>
		{/if}
		{#if hasMyGroupItems}
			<button
				class="px-3 py-1 text-xs font-medium rounded-full transition-colors
					{$activeWorkspaceFilter === 'my_group'
					? 'bg-gray-800 text-white dark:bg-white dark:text-gray-900'
					: 'bg-gray-100 text-gray-600 hover:bg-gray-200 dark:bg-gray-800 dark:text-gray-400 dark:hover:bg-gray-700'}"
				on:click={() => ($activeWorkspaceFilter = 'my_group')}
			>
				{$i18n.t('My Group')}
			</button>
		{/if}
		{#if hasSharedItems}
			<button
				class="px-3 py-1 text-xs font-medium rounded-full transition-colors
					{$activeWorkspaceFilter === 'shared'
					? 'bg-gray-800 text-white dark:bg-white dark:text-gray-900'
					: 'bg-gray-100 text-gray-600 hover:bg-gray-200 dark:bg-gray-800 dark:text-gray-400 dark:hover:bg-gray-700'}"
				on:click={() => ($activeWorkspaceFilter = 'shared')}
			>
				{$i18n.t('Shared')}
			</button>
		{/if}
		<button
			class="px-3 py-1 text-xs font-medium rounded-full transition-colors
				{$activeWorkspaceFilter === 'mine'
				? 'bg-gray-800 text-white dark:bg-white dark:text-gray-900'
				: 'bg-gray-100 text-gray-600 hover:bg-gray-200 dark:bg-gray-800 dark:text-gray-400 dark:hover:bg-gray-700'}"
			on:click={() => ($activeWorkspaceFilter = 'mine')}
		>
			{$i18n.t('My Glossaries')}
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

	{#if filteredItems.length === 0}
		<div class="flex flex-col items-center justify-center h-64 text-gray-500 dark:text-gray-400">
			<div class="text-6xl mb-4">📖</div>
			<div class="text-xl font-medium mb-2">{$i18n.t('No terms yet')}</div>
			<div class="text-sm">{$i18n.t('Create a term to get started.')}</div>
		</div>
	{:else}
		<div class="workspace-cards-grid mb-5">
			{#each filteredItems as item}
				<WorkspaceCard
					name={item.name}
					description={item.description ?? ''}
					on:click={() => {
						// 응답에 포함됐다는 것 = backend 가 read 권한 통과시킴.
						// detail page 의 canWrite 가드가 편집/삭제 버튼을 비활성화하므로 read 공유자도 안전하게 진입 가능.
						goto(`/workspace/glossary/${item.id}`);
					}}
				>
					<svelte:fragment slot="badge">
						<Badge type="warning" content={$i18n.t('Dictionary')} />
						{#if item?.governance_meta?.scope_kind === 'public'}
							<Badge type="info" content={$i18n.t('Company-wide')} />
						{:else if item?.governance_meta?.scope_kind === 'group' && item?.governance_meta?.scope_label === 'Shared'}
							<Badge type="info" content={$i18n.t('Shared')} />
						{:else if item?.governance_meta?.scope_kind === 'group' && item?.governance_meta?.steward_group_name}
							<Badge type="info" content={item.governance_meta.steward_group_name} />
						{:else if item?.governance_meta?.scope_kind === 'private'}
							<Badge type="muted" content={$i18n.t('Private')} />
						{/if}
						{#if item?.governance_meta?.can_write && !item?.governance_meta?.is_owner}
							<Badge type="success" content={$i18n.t('Editable')} />
						{/if}
					</svelte:fragment>

					<svelte:fragment slot="actions">
						{#if $user?.role === 'admin' || item?.governance_meta?.can_write}
							<ItemMenu
								showReindex={$user?.role === 'admin' || ($user?.permissions?.workspace?.glossaries === 'write' && item.user_id === $user?.id)}
								showCopy={$user?.role === 'admin' || item?.governance_meta?.can_write}
								on:reindex={() => onReindexClick(item)}
								on:copy={() => onCopyClick(item)}
								on:delete={() => {
									onDeleteClick(item);
								}}
							/>
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

	<div class=" text-gray-500 text-xs mt-1 mb-2">
		ⓘ {$i18n.t('Manage terminology and definitions for consistent communication.')}
	</div>
{:else}
	<div class="w-full h-full flex justify-center items-center">
		<Spinner />
	</div>
{/if}

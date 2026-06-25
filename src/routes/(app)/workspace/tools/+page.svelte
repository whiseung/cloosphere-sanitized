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
	import { getToolConnections, deleteToolConnectionById } from '$lib/apis/tool-connections';
	import { hasPermission } from '$lib/utils/permissions';
	import { getGroups } from '$lib/apis/groups';

	import { goto } from '$app/navigation';

	import DeleteConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';
	import ItemMenu from '$lib/components/workspace/Knowledge/ItemMenu.svelte';
	import Badge from '$lib/components/common/Badge.svelte';
	import Search from '$lib/components/icons/Search.svelte';
	import Plus from '$lib/components/icons/Plus.svelte';
	import Input from '$lib/components/common/Input.svelte';
	import Button from '$lib/components/common/Button.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import { capitalizeFirstLetter } from '$lib/utils';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import WorkspaceCard from '$lib/components/common/WorkspaceCard.svelte';

	// Check permission
	$: if ($user && $user.role !== 'admin' && !hasPermission($user?.permissions?.workspace?.tools)) {
		goto('/workspace');
	}

	let loaded = false;

	let query = '';
	let selectedItem = null;
	let showDeleteConfirm = false;

	let fuse = null;

	let items: any[] = [];
	let filteredItems: any[] = [];
	let group_ids: string[] = [];
	let tagAssignments: Record<string, string[]> = {};

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

	const getShareTag = (item: any): { label: string; type: string } | null => {
		if ($user?.role === 'admin') return null;
		const isOwner = item.user_id === $user?.id;
		const ac = item.access_control;

		if (isOwner) {
			if (ac === null || ac === undefined) return { label: $i18n.t('Public'), type: 'warning' };
			const hasGroupShare = (ac?.read?.group_ids?.length > 0 || ac?.write?.group_ids?.length > 0);
			if ($activeWorkspaceFilter === 'mine') {
				return hasGroupShare ? { label: $i18n.t('Shared'), type: 'info' } : null;
			} else {
				return hasGroupShare ? { label: $i18n.t('Shared'), type: 'info' } : { label: $i18n.t('My Tool'), type: 'muted' };
			}
		}

		if (!ac) return { label: $i18n.t('Public'), type: 'warning' };
		const writeGroups = ac?.write?.group_ids ?? [];
		const readGroups = ac?.read?.group_ids ?? [];
		if (writeGroups.some((gid: string) => group_ids.includes(gid))) return { label: `${$i18n.t('Group')}(W)`, type: 'info' };
		if (readGroups.some((gid: string) => group_ids.includes(gid))) return { label: `${$i18n.t('Group')}(R)`, type: 'info' };
		return null;
	};

	$: if (fuse) {
		let result = query
			? fuse.search(query).map((e) => e.item)
			: items;

		if ($activeWorkspaceFilter === 'mine') {
			result = result.filter((item) => item.user_id === $user?.id);
		} else if ($activeWorkspaceFilter === 'shared') {
			result = result.filter((item) => isGroupShared(item));
		} else if ($activeWorkspaceFilter.startsWith('tag:')) {
			const tagName = $activeWorkspaceFilter.slice(4);
			result = result.filter((item) => (tagAssignments[item.id] ?? []).includes(tagName));
		}

		filteredItems = result;
	}

	const deleteHandler = async (item) => {
		const res = await deleteToolConnectionById(localStorage.token, item.id).catch((e) => {
			toast.error($i18n.t(`${e}`));
		});

		if (res) {
			items = (await getToolConnections(localStorage.token)).filter(
				(it: any) => it?.meta?.source !== 'marketplace'
			);
			toast.success($i18n.t('Tool deleted successfully.'));
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
		items = (await getToolConnections(localStorage.token).catch((e) => {
			console.error(e);
			return [];
		}) ?? []).filter((it: any) => it?.meta?.source !== 'marketplace');

		try {
			const groups = await getGroups(localStorage.token);
			group_ids = groups.map((group: any) => group.id);
		} catch (e) {
			console.error('Failed to load groups:', e);
		}

		try {
			workspaceTags.set(await getWorkspaceTags(localStorage.token));
			tagAssignments = await getAssignmentsByType(localStorage.token, 'tool');
		} catch (e) {
			console.error('Failed to load workspace tags:', e);
		}

		loaded = true;
	});
</script>

<svelte:head>
	<title>
		{$i18n.t('Tools')} | {$WEBUI_NAME}
	</title>
</svelte:head>

{#if loaded}
	<DeleteConfirmDialog
		bind:show={showDeleteConfirm}
		on:confirm={() => {
			deleteHandler(selectedItem);
		}}
	/>

	<!-- Header Row -->
	<div class="flex items-center justify-between gap-[var(--cloo-space-2)] mt-2 mb-4">
		<div class="flex items-center gap-2.5">
			<span class="text-lg font-medium text-[var(--cloo-text-primary)]">
				{$i18n.t('Tools')}
			</span>
			<span class="text-lg font-medium text-[var(--token-scale-neutral-400)]">
				{filteredItems.length}
			</span>
		</div>

		<div class="flex items-center gap-[var(--cloo-space-2)]">
			<div class="w-[300px]">
				<Input
					bind:value={query}
					placeholder={$i18n.t('Search Tools')}
					type="search"
					size="md"
				>
					<svelte:fragment slot="prefix">
						<Search className="size-3.5" />
					</svelte:fragment>
				</Input>
			</div>

			{#if $user?.role === 'admin' || $user?.permissions?.workspace?.tools === 'write'}
				<div class="flex items-center gap-[var(--cloo-space-2)]">
					<Button
						kind="filled"
						size="md"
						on:click={() => {
							goto('/workspace/tools/create');
						}}
					>
						<svelte:fragment slot="prefix">
							<Plus className="size-3.5" />
						</svelte:fragment>
						{$i18n.t('New Tool')}
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
			{$i18n.t('My Tools')}
		</button>
		{#each allTags as tag}
			<button
				class="px-3 py-1 text-xs font-medium rounded-full transition-colors
					{$activeWorkspaceFilter === 'tag:' + tag
						? 'bg-gray-800 text-white dark:bg-white dark:text-gray-900'
						: 'bg-gray-100 text-gray-600 hover:bg-gray-200 dark:bg-gray-800 dark:text-gray-400 dark:hover:bg-gray-700'}"
				on:click={() => ($activeWorkspaceFilter = $activeWorkspaceFilter === 'tag:' + tag ? 'all' : 'tag:' + tag)}
			>
				{tag}
			</button>
		{/each}
	</div>

	{#if filteredItems.length === 0}
		<div class="flex flex-col items-center justify-center h-64 text-gray-500 dark:text-gray-400">
			<div class="text-6xl mb-4">🔧</div>
			<div class="text-xl font-medium mb-2">{$i18n.t('No tools yet')}</div>
			<div class="text-sm">{$i18n.t('Create a tool to get started.')}</div>
		</div>
	{:else}
		<div class="mb-5 grid gap-6 md:grid-cols-2 lg:grid-cols-3">
			{#each filteredItems as item}
				<WorkspaceCard
					name={item.name}
					description={item.description || ''}
					on:click={() => {
						// 응답에 포함됐다는 것 = backend read 통과. detail 페이지 canWrite 가 편집 가드.
						goto(`/workspace/tools/${item.id}`);
					}}
				>
					<svelte:fragment slot="badge">
						<Badge type="muted" content={$i18n.t('Tool')} />
						{#if getShareTag(item)}
							<Badge type={getShareTag(item).type} content={getShareTag(item).label} />
						{/if}
					</svelte:fragment>

					<svelte:fragment slot="actions">
						{#if $user?.role === 'admin' || item.user_id === $user?.id || hasResourceAccess(item, 'write')}
							<ItemMenu
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
						<div class=" text-xs text-gray-500 line-clamp-1">
							{$i18n.t('Updated')}
							{dayjs(item.updated_at * 1000).fromNow()}
						</div>
					</svelte:fragment>
				</WorkspaceCard>
			{/each}
		</div>
	{/if}

	<div class=" text-gray-500 text-xs mt-1 mb-2">
		ⓘ {$i18n.t('Connect to OpenAPI compatible APIs to use as tools.')}
	</div>
{:else}
	<div class="w-full h-full flex justify-center items-center">
		<Spinner />
	</div>
{/if}

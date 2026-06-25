<script lang="ts">
	import Fuse from 'fuse.js';

	import dayjs from 'dayjs';
	import relativeTime from 'dayjs/plugin/relativeTime';
	dayjs.extend(relativeTime);

	import fileSaver from 'file-saver';
	const { saveAs } = fileSaver;

	import { toast } from 'svelte-sonner';
	import { onMount, getContext } from 'svelte';
	const i18n = getContext('i18n');

	import { WEBUI_NAME, guardrails, user, workspaceTags, activeWorkspaceFilter } from '$lib/stores';
	import { getWorkspaceTags, getAssignmentsByType } from '$lib/apis/workspace-tags';
	import {
		getGuardrails,
		deleteGuardrailById,
		getLinkedAgentsByGuardrailId
	} from '$lib/apis/guardrails';
	import { getGroups } from '$lib/apis/groups';

	import { goto } from '$app/navigation';

	import DeleteConfirmDialog from '../common/ConfirmDialog.svelte';
	import GuardrailMenu from './Guardrails/GuardrailMenu.svelte';
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
	let selectedItem = null;
	let showDeleteConfirm = false;
	let showLinkedAgentsError = false;
	let linkedAgents: { id: string; name: string }[] = [];

	let fuse = null;

	let guardrailList = [];
	let filteredItems = [];
	let group_ids: string[] = [];
	let tagAssignments: Record<string, string[]> = {};

	$: allTags = [...new Set(Object.values(tagAssignments).flat())].sort();

	$: if (guardrailList) {
		fuse = new Fuse(guardrailList, {
			keys: ['name', 'description']
		});
	}

	const isGroupShared = (item: any): boolean => {
		if (item.user_id === $user?.id) return false;
		const ac = item.access_control;
		if (ac === null || ac === undefined) return false;
		return true;
	};

	$: hasSharedItems = guardrailList.some((item) => isGroupShared(item));

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
				return hasGroupShare ? { label: $i18n.t('Shared'), type: 'info' } : { label: $i18n.t('My Guardrails'), type: 'muted' };
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
		let result = query ? fuse.search(query).map((e) => e.item) : guardrailList;

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

	const onDeleteClick = async (item) => {
		selectedItem = item;
		const agents = await getLinkedAgentsByGuardrailId(localStorage.token, item.id).catch(() => []);
		if (agents && agents.length > 0) {
			linkedAgents = agents;
			showLinkedAgentsError = true;
		} else {
			showDeleteConfirm = true;
		}
	};

	const deleteHandler = async (item) => {
		const res = await deleteGuardrailById(localStorage.token, item.id).catch((e) => {
			toast.error($i18n.t(`${e}`));
		});

		if (res) {
			guardrailList = await getGuardrails(localStorage.token);
			guardrails.set(await getGuardrails(localStorage.token));
			toast.success($i18n.t('Guardrail deleted successfully.'));
		}
	};

	const getPiiTypesLabel = (piiTypes: string[]) => {
		if (!piiTypes || piiTypes.length === 0) return '-';
		return piiTypes.join(', ');
	};

	const getStrategyLabel = (strategy: string) => {
		const labels: Record<string, string> = {
			block: $i18n.t('Block'),
			redact: $i18n.t('Redact'),
			mask: $i18n.t('Mask'),
			hash: $i18n.t('Hash')
		};
		return labels[strategy] || strategy;
	};

	const cloneHandler = (item) => {
		sessionStorage.guardrail = JSON.stringify({
			...item,
			id: undefined,
			name: `${item.name} (Clone)`
		});
		goto('/workspace/guardrails/create');
	};

	const exportHandler = (item) => {
		const blob = new Blob([JSON.stringify(item, null, 2)], {
			type: 'application/json'
		});
		saveAs(blob, `guardrail-${item.name.replace(/\s+/g, '-').toLowerCase()}-${Date.now()}.json`);
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
		try {
			guardrailList = (await getGuardrails(localStorage.token)) || [];
		} catch (e) {
			console.error('Failed to load guardrails:', e);
			guardrailList = [];
		}

		try {
			const groups = await getGroups(localStorage.token);
			group_ids = groups.map((group: any) => group.id);
		} catch (e) {
			console.error('Failed to load groups:', e);
		}

		try {
			workspaceTags.set(await getWorkspaceTags(localStorage.token));
			tagAssignments = await getAssignmentsByType(localStorage.token, 'guardrail');
		} catch (e) {
			console.error('Failed to load workspace tags:', e);
		}

		loaded = true;
	});
</script>

<svelte:head>
	<title>
		{$i18n.t('Guardrails')} | {$WEBUI_NAME}
	</title>
</svelte:head>

{#if loaded}
	<DeleteConfirmDialog
		bind:show={showDeleteConfirm}
		on:confirm={() => {
			deleteHandler(selectedItem);
		}}
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
							{$i18n.t('Cannot delete guardrail')}
						</h3>
						<p class="mt-1 text-sm text-gray-500 dark:text-gray-400">
							{$i18n.t(
								'This guardrail is connected to the following agents. Please remove it from the agents first.'
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
				{$i18n.t('Guardrails')}
			</span>
			<span class="text-lg font-medium text-[var(--token-scale-neutral-400)]">
				{filteredItems.length}
			</span>
		</div>

		<div class="flex items-center gap-[var(--cloo-space-2)]">
			<div class="w-[300px]">
				<Input
					bind:value={query}
					placeholder={$i18n.t('Search Guardrails')}
					type="search"
					size="md"
				>
					<svelte:fragment slot="prefix">
						<Search className="size-3.5" />
					</svelte:fragment>
				</Input>
			</div>

			{#if $user?.role === 'admin' || $user?.permissions?.workspace?.guardrails === 'write'}
				<div class="flex items-center gap-[var(--cloo-space-2)]">
					<Button
						kind="filled"
						size="md"
						on:click={() => {
							goto('/workspace/guardrails/create');
						}}
					>
						<svelte:fragment slot="prefix">
							<Plus className="size-3.5" />
						</svelte:fragment>
						{$i18n.t('New Guardrail')}
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
			{$i18n.t('My Guardrails')}
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
				on:click={() => {
					if ($user?.role === 'admin' || item.user_id === $user?.id || ($user?.permissions?.workspace?.guardrails === 'write' && hasResourceAccess(item, 'write'))) {
						goto(`/workspace/guardrails/${item.id}`);
					}
				}}
			>
				<svelte:fragment slot="badge">
					<Badge
						type={item.llm_judge_enabled ? 'info' : 'muted'}
						content={item.llm_judge_enabled ? $i18n.t('LLM Judge') : $i18n.t('Rule-based')}
					/>
					{#if getShareTag(item)}
						<Badge type={getShareTag(item).type} content={getShareTag(item).label} />
					{/if}
				</svelte:fragment>

				<svelte:fragment slot="actions">
					{#if $user?.role === 'admin' || ($user?.permissions?.workspace?.guardrails === 'write' && item.user_id === $user?.id)}
						<GuardrailMenu
							on:clone={() => cloneHandler(item)}
							on:export={() => exportHandler(item)}
							on:delete={() => onDeleteClick(item)}
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
				<div class="text-sm">{$i18n.t('No guardrails found matching your search.')}</div>
			{:else}
				<div class="text-6xl mb-4">🛡️</div>
				<div class="text-xl font-medium mb-2">{$i18n.t('No guardrails yet')}</div>
				<div class="text-sm">{$i18n.t('Create a guardrail to get started.')}</div>
			{/if}
		</div>
	{/if}

	<div class=" text-gray-500 text-xs mt-1 mb-2">
		ⓘ {$i18n.t(
			'Guardrails filter sensitive information (PII) and validate content in model inputs/outputs.'
		)}
	</div>
{:else}
	<div class="flex justify-center items-center h-64">
		<Spinner />
	</div>
{/if}

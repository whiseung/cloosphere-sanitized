<script lang="ts">
	import { toast } from 'svelte-sonner';
	import fileSaver from 'file-saver';
	const { saveAs } = fileSaver;

	import { goto } from '$app/navigation';
	import { onMount, getContext } from 'svelte';
	import {
		WEBUI_NAME,
		config,
		prompts as _prompts,
		user,
		workspaceTags,
		activeWorkspaceFilter
	} from '$lib/stores';
	import { getWorkspaceTags, getAssignmentsByType } from '$lib/apis/workspace-tags';

	import { getGroups } from '$lib/apis/groups';
	import {
		createNewPrompt,
		deletePromptByCommand,
		getPrompts
	} from '$lib/apis/prompts';

	import dayjs from 'dayjs';
	import relativeTime from 'dayjs/plugin/relativeTime';
	dayjs.extend(relativeTime);

	import PromptMenu from './Prompts/PromptMenu.svelte';
	import EllipsisHorizontal from '../icons/EllipsisHorizontal.svelte';
	import DeleteConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';
	import Badge from '../common/Badge.svelte';
	import Button from '../common/Button.svelte';
	import Input from '../common/Input.svelte';
	import Search from '../icons/Search.svelte';
	import Plus from '../icons/Plus.svelte';
	import ChevronRight from '../icons/ChevronRight.svelte';
	import Spinner from '../common/Spinner.svelte';
	import Tooltip from '../common/Tooltip.svelte';
	import { capitalizeFirstLetter } from '$lib/utils';
	import WorkspaceCard from '../common/WorkspaceCard.svelte';

	const i18n = getContext('i18n');
	let promptsImportInputElement: HTMLInputElement;
	let loaded = false;

	let importFiles = '';
	let query = '';

	let prompts = [];

	let showDeleteConfirm = false;
	let deletePrompt = null;

	let filteredItems = [];
	let group_ids: string[] = [];
	let tagAssignments: Record<string, string[]> = {};

	$: allTags = [...new Set(Object.values(tagAssignments).flat())].sort();

	const isGroupShared = (item: any): boolean => {
		if (item.user_id === $user?.id) return false;
		const ac = item.access_control;
		if (ac === null || ac === undefined) return false;
		return true;
	};

	$: hasSharedItems = prompts.some((p) => isGroupShared(p));

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
				return hasGroupShare ? { label: $i18n.t('Shared'), type: 'info' } : { label: $i18n.t('My Prompts'), type: 'muted' };
			}
		}

		if (!ac) return { label: $i18n.t('Public'), type: 'warning' };
		const writeGroups = ac?.write?.group_ids ?? [];
		const readGroups = ac?.read?.group_ids ?? [];
		if (writeGroups.some((gid: string) => group_ids.includes(gid))) return { label: `${$i18n.t('Group')}(W)`, type: 'info' };
		if (readGroups.some((gid: string) => group_ids.includes(gid))) return { label: `${$i18n.t('Group')}(R)`, type: 'info' };
		return null;
	};

	$: {
		let result = prompts;

		if ($activeWorkspaceFilter === 'mine') {
			result = result.filter((p) => p.user_id === $user?.id);
		} else if ($activeWorkspaceFilter === 'shared') {
			result = result.filter((p) => isGroupShared(p));
		} else if ($activeWorkspaceFilter.startsWith('tag:')) {
			const tagName = $activeWorkspaceFilter.slice(4);
			result = result.filter((p) => (tagAssignments[p.command] ?? []).includes(tagName));
		}

		if (query) {
			result = result.filter(
				(p) => p.command.includes(query) || p.title?.toLowerCase().includes(query.toLowerCase())
			);
		}

		filteredItems = result;
	}

	const shareHandler = async (prompt) => {
		toast.success($i18n.t('Redirecting you to Open WebUI Community'));

		const url = 'https://openwebui.com';

		const tab = await window.open(`${url}/prompts/create`, '_blank');
		window.addEventListener(
			'message',
			(event) => {
				if (event.origin !== url) return;
				if (event.data === 'loaded') {
					tab.postMessage(JSON.stringify(prompt), '*');
				}
			},
			false
		);
	};

	const cloneHandler = async (prompt) => {
		sessionStorage.prompt = JSON.stringify(prompt);
		goto('/workspace/prompts/create');
	};

	const exportHandler = async (prompt) => {
		let blob = new Blob([JSON.stringify([prompt])], {
			type: 'application/json'
		});
		saveAs(blob, `prompt-export-${Date.now()}.json`);
	};

	const deleteHandler = async (prompt) => {
		const command = prompt.command;
		await deletePromptByCommand(localStorage.token, command);
		await init();
	};

	const init = async () => {
		prompts = await getPrompts(localStorage.token);
		await _prompts.set(await getPrompts(localStorage.token));
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
		await init();

		try {
			const groups = await getGroups(localStorage.token);
			group_ids = groups.map((group: any) => group.id);
		} catch (e) {
			console.error('Failed to load groups:', e);
		}

		try {
			workspaceTags.set(await getWorkspaceTags(localStorage.token));
			tagAssignments = await getAssignmentsByType(localStorage.token, 'prompt');
		} catch (e) {
			console.error('Failed to load workspace tags:', e);
		}

		loaded = true;
	});
</script>

<svelte:head>
	<title>
		{$i18n.t('Prompts')} | {$WEBUI_NAME}
	</title>
</svelte:head>

{#if loaded}
	<DeleteConfirmDialog
		bind:show={showDeleteConfirm}
		title={$i18n.t('Delete prompt?')}
		on:confirm={() => {
			deleteHandler(deletePrompt);
		}}
	>
		<div class=" text-sm text-gray-500">
			{$i18n.t('This will delete')} <span class="  font-semibold">{deletePrompt.command}</span>.
		</div>
	</DeleteConfirmDialog>

	<!-- Header Row -->
	<div class="flex items-center justify-between gap-[var(--cloo-space-2)] mt-2 mb-4">
		<div class="flex items-center gap-2.5">
			<span class="text-lg font-medium text-[var(--cloo-text-primary)]">
				{$i18n.t('Prompts')}
			</span>
			<span class="text-lg font-medium text-[var(--token-scale-neutral-400)]">
				{filteredItems.length}
			</span>
		</div>

		<div class="flex items-center gap-[var(--cloo-space-2)]">
			<!-- Search Input -->
			<div class="w-[300px]">
				<Input bind:value={query} placeholder={$i18n.t('Search Prompts')} type="search" size="md">
					<svelte:fragment slot="prefix">
						<Search className="size-3.5" />
					</svelte:fragment>
				</Input>
			</div>

			<!-- Action Buttons -->
			{#if $user?.role === 'admin' || $user?.permissions?.workspace?.prompts === 'write'}
				<div class="flex items-center gap-[var(--cloo-space-2)]">
					<Button
						kind="filled"
						size="md"
						on:click={() => {
							goto('/workspace/prompts/create');
						}}
					>
						<svelte:fragment slot="prefix">
							<Plus className="size-3.5" />
						</svelte:fragment>
						{$i18n.t('New Prompt')}
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
			{$i18n.t('My Prompts')}
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
			<div class="text-6xl mb-4">💬</div>
			<div class="text-xl font-medium mb-2">{$i18n.t('No prompts yet')}</div>
			<div class="text-sm">{$i18n.t('Create a prompt to get started.')}</div>
		</div>
	{:else}
	<div class="workspace-cards-grid mb-5">
		{#each filteredItems as prompt}
			<WorkspaceCard
				name={prompt.title}
				description={prompt.command}
				on:click={() => {
					if ($user?.role === 'admin' || prompt.user_id === $user?.id || ($user?.permissions?.workspace?.prompts === 'write' && hasResourceAccess(prompt, 'write'))) {
						goto(`/workspace/prompts/edit?command=${encodeURIComponent(prompt.command)}`);
					}
				}}
			>
				<svelte:fragment slot="badge">
					<Badge type="muted" content={$i18n.t('Prompt')} />
					{#if getShareTag(prompt)}
						<Badge type={getShareTag(prompt).type} content={getShareTag(prompt).label} />
					{/if}
				</svelte:fragment>

				<svelte:fragment slot="actions">
					{#if $user?.role === 'admin' || ($user?.permissions?.workspace?.prompts === 'write' && prompt.user_id === $user?.id)}
						<PromptMenu
							shareHandler={() => {
								shareHandler(prompt);
							}}
							cloneHandler={() => {
								cloneHandler(prompt);
							}}
							exportHandler={() => {
								exportHandler(prompt);
							}}
							deleteHandler={async () => {
								deletePrompt = prompt;
								showDeleteConfirm = true;
							}}
							onClose={() => {}}
						>
							<button
								class="self-center w-fit text-sm p-1.5 dark:text-gray-300 dark:hover:text-white hover:bg-black/5 dark:hover:bg-white/5 rounded-xl"
								type="button"
							>
								<EllipsisHorizontal className="size-5" />
							</button>
						</PromptMenu>
					{/if}
				</svelte:fragment>

				<svelte:fragment slot="title">
					<div class="font-semibold line-clamp-1 h-fit capitalize">{prompt.title}</div>
				</svelte:fragment>

				<svelte:fragment slot="footer-left">
					<div class="text-xs text-gray-500">
						<Tooltip
							content={prompt?.user?.email ?? $i18n.t('Deleted User')}
							className="flex shrink-0"
							placement="top-start"
						>
							{$i18n.t('By {{name}}', {
								name: capitalizeFirstLetter(
									prompt?.user?.name ?? prompt?.user?.email ?? $i18n.t('Deleted User')
								)
							})}
						</Tooltip>
					</div>
				</svelte:fragment>

				<svelte:fragment slot="footer-right">
					<div class="text-xs text-gray-500 line-clamp-1">
						{$i18n.t('Updated')}
						{dayjs(prompt.updated_at * 1000).fromNow()}
					</div>
				</svelte:fragment>
			</WorkspaceCard>
		{/each}
	</div>
	{/if}

	{#if $user?.role === 'admin'}
		<div class=" flex justify-end w-full mb-3">
			<div class="flex space-x-2">
				<input
					id="prompts-import-input"
					bind:this={promptsImportInputElement}
					bind:files={importFiles}
					type="file"
					accept=".json"
					hidden
					on:change={() => {
						console.log(importFiles);

						const reader = new FileReader();
						reader.onload = async (event) => {
							const savedPrompts = JSON.parse(event.target.result);
							console.log(savedPrompts);

							for (const prompt of savedPrompts) {
								await createNewPrompt(localStorage.token, {
									command:
										prompt.command.charAt(0) === '/' ? prompt.command.slice(1) : prompt.command,
									title: prompt.title,
									content: prompt.content
								}).catch((error) => {
									toast.error($i18n.t(`${error}`));
									return null;
								});
							}

							prompts = await getPrompts(localStorage.token);
							await _prompts.set(await getPrompts(localStorage.token));

							importFiles = [];
							promptsImportInputElement.value = '';
						};

						reader.readAsText(importFiles[0]);
					}}
				/>

				<button
					class="flex text-xs items-center space-x-1 px-3 py-1.5 rounded-xl bg-gray-50 hover:bg-gray-100 dark:bg-gray-800 dark:hover:bg-gray-700 dark:text-gray-200 transition"
					on:click={() => {
						promptsImportInputElement.click();
					}}
				>
					<div class=" self-center mr-2 font-medium line-clamp-1">{$i18n.t('Import Prompts')}</div>

					<div class=" self-center">
						<svg
							xmlns="http://www.w3.org/2000/svg"
							viewBox="0 0 16 16"
							fill="currentColor"
							class="w-4 h-4"
						>
							<path
								fill-rule="evenodd"
								d="M4 2a1.5 1.5 0 0 0-1.5 1.5v9A1.5 1.5 0 0 0 4 14h8a1.5 1.5 0 0 0 1.5-1.5V6.621a1.5 1.5 0 0 0-.44-1.06L9.94 2.439A1.5 1.5 0 0 0 8.878 2H4Zm4 9.5a.75.75 0 0 1-.75-.75V8.06l-.72.72a.75.75 0 0 1-1.06-1.06l2-2a.75.75 0 0 1 1.06 0l2 2a.75.75 0 1 1-1.06 1.06l-.72-.72v2.69a.75.75 0 0 1-.75.75Z"
								clip-rule="evenodd"
							/>
						</svg>
					</div>
				</button>

				{#if prompts.length}
					<button
						class="flex text-xs items-center space-x-1 px-3 py-1.5 rounded-xl bg-gray-50 hover:bg-gray-100 dark:bg-gray-800 dark:hover:bg-gray-700 dark:text-gray-200 transition"
						on:click={async () => {
							let blob = new Blob([JSON.stringify(prompts)], {
								type: 'application/json'
							});
							saveAs(blob, `prompts-export-${Date.now()}.json`);
						}}
					>
						<div class=" self-center mr-2 font-medium line-clamp-1">
							{$i18n.t('Export Prompts')}
						</div>

						<div class=" self-center">
							<svg
								xmlns="http://www.w3.org/2000/svg"
								viewBox="0 0 16 16"
								fill="currentColor"
								class="w-4 h-4"
							>
								<path
									fill-rule="evenodd"
									d="M4 2a1.5 1.5 0 0 0-1.5 1.5v9A1.5 1.5 0 0 0 4 14h8a1.5 1.5 0 0 0 1.5-1.5V6.621a1.5 1.5 0 0 0-.44-1.06L9.94 2.439A1.5 1.5 0 0 0 8.878 2H4Zm4 3.5a.75.75 0 0 1 .75.75v2.69l.72-.72a.75.75 0 1 1 1.06 1.06l-2 2a.75.75 0 0 1-1.06 0l-2-2a.75.75 0 0 1 1.06-1.06l.72.72V6.25A.75.75 0 0 1 8 5.5Z"
									clip-rule="evenodd"
								/>
							</svg>
						</div>
					</button>
				{/if}
			</div>
		</div>
	{/if}

	{#if $config?.features.enable_community_sharing}
		<div class=" my-16">
			<div class=" text-xl font-medium mb-1 line-clamp-1">
				{$i18n.t('Made by Open WebUI Community')}
			</div>

			<a
				class=" flex cursor-pointer items-center justify-between hover:bg-gray-50 dark:hover:bg-gray-850 w-full mb-2 px-3.5 py-1.5 rounded-xl transition"
				href="https://openwebui.com/#open-webui-community"
				target="_blank"
			>
				<div class=" self-center">
					<div class=" font-semibold line-clamp-1">{$i18n.t('Discover a prompt')}</div>
					<div class=" text-sm line-clamp-1">
						{$i18n.t('Discover, download, and explore custom prompts')}
					</div>
				</div>

				<div>
					<div>
						<ChevronRight />
					</div>
				</div>
			</a>
		</div>
	{/if}
{:else}
	<div class="w-full h-full flex justify-center items-center">
		<Spinner />
	</div>
{/if}

<script lang="ts">
	import { toast } from 'svelte-sonner';
	import { onMount, getContext } from 'svelte';
	const i18n = getContext('i18n');

	import dayjs from 'dayjs';
	import relativeTime from 'dayjs/plugin/relativeTime';
	dayjs.extend(relativeTime);

	import { WEBUI_NAME, user, workspaceTags } from '$lib/stores';
	import {
		getWorkspaceTags,
		createWorkspaceTag,
		updateWorkspaceTag,
		deleteWorkspaceTag,
		type WorkspaceTag
	} from '$lib/apis/workspace-tags';

	import Button from '$lib/components/common/Button.svelte';
	import Input from '$lib/components/common/Input.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import ConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';
	import Search from '$lib/components/icons/Search.svelte';
	import Plus from '$lib/components/icons/Plus.svelte';
	import Pencil from '$lib/components/icons/Pencil.svelte';
	import GarbageBin from '$lib/components/icons/GarbageBin.svelte';

	let loaded = false;
	let query = '';
	let tags: WorkspaceTag[] = [];

	// Create
	let newTagName = '';
	let creating = false;

	// Edit
	let editingId: string | null = null;
	let editingName = '';

	// Delete
	let showDeleteConfirm = false;
	let deleteTarget: WorkspaceTag | null = null;

	$: filteredTags = query
		? tags.filter((t) => t.name.toLowerCase().includes(query.toLowerCase()))
		: tags;

	// read 권한자는 자기 태그라도 수정/삭제 불가 (백엔드 feature gate write 와 일치)
	$: canManageTags = $user?.role === 'admin' || $user?.permissions?.workspace?.tags === 'write';

	const canEditTag = (tag: WorkspaceTag) => {
		return canManageTags && ($user?.role === 'admin' || tag.user_id === $user?.id);
	};

	const loadTags = async () => {
		tags = await getWorkspaceTags(localStorage.token);
		workspaceTags.set(tags);
	};

	const handleCreate = async () => {
		const name = newTagName.trim();
		if (!name) return;

		creating = true;
		try {
			const existing = tags.find((t) => t.name.toLowerCase() === name.toLowerCase());
			if (existing) {
				toast.error($i18n.t('A tag with this name already exists'));
				creating = false;
				return;
			}
			await createWorkspaceTag(localStorage.token, name);
			await loadTags();
			newTagName = '';
			toast.success($i18n.t('Tag created'));
		} catch (e) {
			toast.error($i18n.t(`${e}`));
		}
		creating = false;
	};

	const startEdit = (tag: WorkspaceTag) => {
		editingId = tag.id;
		editingName = tag.name;
	};

	const cancelEdit = () => {
		editingId = null;
		editingName = '';
	};

	const handleUpdate = async () => {
		if (!editingId) return;
		const name = editingName.trim();
		if (!name) {
			toast.error($i18n.t('Tag name is required'));
			return;
		}

		try {
			await updateWorkspaceTag(localStorage.token, editingId, name);
			await loadTags();
			cancelEdit();
			toast.success($i18n.t('Tag updated'));
		} catch (e) {
			toast.error($i18n.t(`${e}`));
		}
	};

	const handleDelete = async () => {
		if (!deleteTarget) return;
		try {
			await deleteWorkspaceTag(localStorage.token, deleteTarget.id);
			await loadTags();
			toast.success($i18n.t('Tag deleted'));
		} catch (e) {
			toast.error($i18n.t(`${e}`));
		}
		deleteTarget = null;
	};

	onMount(async () => {
		await loadTags();
		loaded = true;
	});
</script>

<svelte:head>
	<title>{$i18n.t('Workspace Tags')} | {$WEBUI_NAME}</title>
</svelte:head>

<ConfirmDialog
	bind:show={showDeleteConfirm}
	title={$i18n.t('Delete Tag')}
	message={$i18n.t('Are you sure? This tag will be removed from all workspace items.')}
	on:confirm={handleDelete}
/>

{#if loaded}
	<!-- Header -->
	<div class="flex items-center justify-between gap-[var(--cloo-space-2)] mt-2 mb-4">
		<div class="flex items-center gap-2.5">
			<span class="text-lg font-medium text-[var(--cloo-text-primary)]">
				{$i18n.t('Workspace Tags')}
			</span>
			<span class="text-lg font-medium text-[var(--token-scale-neutral-400)]">
				{filteredTags.length}
			</span>
		</div>

		<div class="flex items-center gap-[var(--cloo-space-2)]">
			<div class="w-[300px]">
				<Input
					bind:value={query}
					placeholder={$i18n.t('Search Tags')}
					type="search"
					size="md"
				>
					<svelte:fragment slot="prefix">
						<Search className="size-3.5" />
					</svelte:fragment>
				</Input>
			</div>
		</div>
	</div>

	<!-- Create New Tag (write 권한자만) -->
	{#if canManageTags}
		<div class="flex items-center gap-2 mb-4">
			<div class="w-64">
				<Input
					bind:value={newTagName}
					placeholder={$i18n.t('New tag name')}
					size="md"
					on:keydown={(e) => {
						if (e.key === 'Enter') {
							e.preventDefault();
							handleCreate();
						}
					}}
				/>
			</div>
			<Button kind="filled" size="md" loading={creating} disabled={!newTagName.trim()} on:click={handleCreate}>
				<svelte:fragment slot="prefix">
					<Plus className="size-3.5" />
				</svelte:fragment>
				{$i18n.t('Create')}
			</Button>
		</div>
	{/if}

	<!-- Tags Table -->
	<div class="border border-gray-200 dark:border-gray-800 rounded-xl overflow-hidden">
		<table class="w-full text-sm">
			<thead>
				<tr class="bg-gray-50 dark:bg-gray-850 text-left text-xs text-gray-500 dark:text-gray-400 uppercase tracking-wider">
					<th class="px-4 py-3 font-medium">{$i18n.t('Tag Name')}</th>
					<th class="px-4 py-3 font-medium w-40">{$i18n.t('Created')}</th>
					<th class="px-4 py-3 font-medium w-24 text-right">{$i18n.t('Actions')}</th>
				</tr>
			</thead>
			<tbody>
				{#if filteredTags.length === 0}
					<tr>
						<td colspan="3" class="px-4 py-12 text-center text-gray-400 dark:text-gray-500">
							{query ? $i18n.t('No tags found') : $i18n.t('No tags created yet')}
						</td>
					</tr>
				{:else}
					{#each filteredTags as tag (tag.id)}
						<tr class="border-t border-gray-100 dark:border-gray-800 hover:bg-gray-50 dark:hover:bg-gray-850 transition">
							<td class="px-4 py-3">
								{#if editingId === tag.id}
									<div class="flex items-center gap-2">
										<input
											class="flex-1 px-2 py-1 text-sm bg-transparent border border-gray-300 dark:border-gray-600 rounded-lg outline-hidden"
											bind:value={editingName}
											on:keydown={(e) => {
												if (e.key === 'Enter') {
													e.preventDefault();
													handleUpdate();
												} else if (e.key === 'Escape') {
													cancelEdit();
												}
											}}
										/>
										<button
											class="p-1 text-green-600 hover:text-green-700 dark:text-green-400 dark:hover:text-green-300 transition"
											on:click={handleUpdate}
										>
											<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor" class="size-4">
												<path fill-rule="evenodd" d="M12.416 3.376a.75.75 0 0 1 .208 1.04l-5 7.5a.75.75 0 0 1-1.154.114l-3-3a.75.75 0 0 1 1.06-1.06l2.353 2.353 4.493-6.74a.75.75 0 0 1 1.04-.207Z" clip-rule="evenodd" />
											</svg>
										</button>
										<button
											class="p-1 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 transition"
											on:click={cancelEdit}
										>
											<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor" class="size-4">
												<path d="M5.28 4.22a.75.75 0 0 0-1.06 1.06L6.94 8l-2.72 2.72a.75.75 0 1 0 1.06 1.06L8 9.06l2.72 2.72a.75.75 0 1 0 1.06-1.06L9.06 8l2.72-2.72a.75.75 0 0 0-1.06-1.06L8 6.94 5.28 4.22Z" />
											</svg>
										</button>
									</div>
								{:else}
									<span class="inline-flex items-center gap-2 px-2.5 py-0.5 rounded-full text-sm font-medium bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-200">
										{tag.name}
									</span>
								{/if}
							</td>
							<td class="px-4 py-3 text-xs text-gray-500 dark:text-gray-400">
								{dayjs(tag.created_at * 1000).fromNow()}
							</td>
							<td class="px-4 py-3 text-right">
								{#if canEditTag(tag)}
									<div class="flex items-center justify-end gap-1">
										<Tooltip content={$i18n.t('Edit')}>
											<button
												class="p-1.5 rounded-lg text-gray-400 hover:text-gray-700 hover:bg-gray-100 dark:hover:text-gray-200 dark:hover:bg-gray-800 transition"
												on:click={() => startEdit(tag)}
											>
												<Pencil className="size-3.5" />
											</button>
										</Tooltip>
										<Tooltip content={$i18n.t('Delete')}>
											<button
												class="p-1.5 rounded-lg text-gray-400 hover:text-red-500 hover:bg-red-50 dark:hover:text-red-400 dark:hover:bg-red-900/20 transition"
												on:click={() => {
													deleteTarget = tag;
													showDeleteConfirm = true;
												}}
											>
												<GarbageBin className="size-3.5" />
											</button>
										</Tooltip>
									</div>
								{/if}
							</td>
						</tr>
					{/each}
				{/if}
			</tbody>
		</table>
	</div>

	<div class="text-gray-500 text-xs mt-3 mb-2">
		ⓘ {$i18n.t('Tags are shared across all workspace items (agents, knowledge, guardrails, etc.)')}
	</div>
{:else}
	<div class="w-full h-full flex justify-center items-center">
		<Spinner />
	</div>
{/if}

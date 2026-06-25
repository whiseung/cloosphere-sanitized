<script lang="ts">
	import { marked } from 'marked';

	import { toast } from 'svelte-sonner';
	import Sortable from 'sortablejs';

	import fileSaver from 'file-saver';
	const { saveAs } = fileSaver;

	import { onMount, getContext, tick } from 'svelte';
	import { goto } from '$app/navigation';
	const i18n = getContext('i18n');

	import {
		WEBUI_NAME,
		config,
		mobile,
		models as _models,
		settings,
		user,
		workspaceTags,
		activeWorkspaceFilter
	} from '$lib/stores';
	import { getWorkspaceTags, getAssignmentsByType } from '$lib/apis/workspace-tags';
	import {
		createNewModel,
		deleteModelById,
		getModels as getWorkspaceModels,
		toggleModelById,
		updateModelById
	} from '$lib/apis/models';

	import { getModels } from '$lib/apis';
	import { getGroups } from '$lib/apis/groups';

	import EllipsisHorizontal from '../icons/EllipsisHorizontal.svelte';
	import AgentMenu from './Agents/AgentMenu.svelte';
	import ModelDeleteConfirmDialog from '../common/ConfirmDialog.svelte';
	import Tooltip from '../common/Tooltip.svelte';
	import Badge from '../common/Badge.svelte';
	import Button from '../common/Button.svelte';
	import Input from '../common/Input.svelte';
	import WorkspaceCard from '../common/WorkspaceCard.svelte';
	import GarbageBin from '../icons/GarbageBin.svelte';
	import Search from '../icons/Search.svelte';
	import Plus from '../icons/Plus.svelte';
	import ArrowRight from '../icons/ArrowRight.svelte';
	import ChevronRight from '../icons/ChevronRight.svelte';
	import Switch from '../common/Switch.svelte';
	import Spinner from '../common/Spinner.svelte';
	import { capitalizeFirstLetter } from '$lib/utils';

	let shiftKey = false;

	let importFiles;
	let modelsImportInputElement: HTMLInputElement;
	let loaded = false;

	let models = [];

	let filteredModels = [];
	let selectedModel = null;

	let showModelDeleteConfirm = false;

	let group_ids = [];

	let searchValue = '';
	let tagAssignments: Record<string, string[]> = {}; // {resource_id: [tag_name, ...]}

	$: allTags = [...new Set(Object.values(tagAssignments).flat())].sort();

	const isGroupSharedModel = (m: any): boolean => {
		if (m.user_id === $user?.id) return false;
		const ac = m.access_control;
		if (ac === null || ac === undefined) return false;
		return true;
	};

	$: hasSharedModels = models.some((m) => isGroupSharedModel(m));

	$: if (models) {
		let result = models;

		if ($activeWorkspaceFilter === 'mine') {
			result = result.filter((m) => m.user_id === $user?.id);
		} else if ($activeWorkspaceFilter === 'shared') {
			result = result.filter((m) => isGroupSharedModel(m));
		} else if ($activeWorkspaceFilter.startsWith('tag:')) {
			const tagName = $activeWorkspaceFilter.slice(4);
			result = result.filter((m) => (tagAssignments[m.id] ?? []).includes(tagName));
		}

		if (searchValue) {
			result = result.filter((m) => m.name.toLowerCase().includes(searchValue.toLowerCase()));
		}

		filteredModels = result;
	}

	const deleteModelHandler = async (model) => {
		const res = await deleteModelById(localStorage.token, model.id).catch((e) => {
			toast.error($i18n.t(`${e}`));
			return null;
		});

		if (res) {
			toast.success($i18n.t(`Deleted {{name}}`, { name: model.id }));
		}

		await _models.set(
			await getModels(
				localStorage.token,
				$config?.features?.enable_direct_connections && ($settings?.directConnections ?? null)
			)
		);
		models = await getWorkspaceModels(localStorage.token);
	};

	const cloneModelHandler = async (model) => {
		sessionStorage.model = JSON.stringify({
			...model,
			id: `${model.id}-clone`,
			name: `${model.name} (Clone)`
		});
		goto('/workspace/agents/create');
	};

	const shareModelHandler = async (model) => {
		toast.success($i18n.t('Redirecting you to Open WebUI Community'));

		const url = 'https://openwebui.com';

		const tab = await window.open(`${url}/models/create`, '_blank');

		const messageHandler = (event) => {
			if (event.origin !== url) return;
			if (event.data === 'loaded') {
				tab.postMessage(JSON.stringify(model), '*');
				window.removeEventListener('message', messageHandler);
			}
		};

		window.addEventListener('message', messageHandler, false);
	};

	const hideModelHandler = async (model) => {
		let info = model.info;

		if (!info) {
			info = {
				id: model.id,
				name: model.name,
				meta: {
					suggestion_prompts: null
				},
				params: {}
			};
		}

		info.meta = {
			...info.meta,
			hidden: !(info?.meta?.hidden ?? false)
		};

		console.log(info);

		const res = await updateModelById(localStorage.token, info.id, info);

		if (res) {
			toast.success(
				$i18n.t(`Agent {{name}} is now {{status}}`, {
					name: info.id,
					status: info.meta.hidden ? 'hidden' : 'visible'
				})
			);
		}

		await _models.set(
			await getModels(
				localStorage.token,
				$config?.features?.enable_direct_connections && ($settings?.directConnections ?? null)
			)
		);
		models = await getWorkspaceModels(localStorage.token);
	};

	const downloadModels = async (models) => {
		let blob = new Blob([JSON.stringify(models)], {
			type: 'application/json'
		});
		saveAs(blob, `models-export-${Date.now()}.json`);
	};

	const exportModelHandler = async (model) => {
		let blob = new Blob([JSON.stringify([model])], {
			type: 'application/json'
		});
		saveAs(blob, `${model.id}-${Date.now()}.json`);
	};

	const getShareTag = (item: any): { label: string; type: string } | null => {
		if ($user?.role === 'admin') return null;
		const isOwner = item.user_id === $user?.id;
		const ac = item.access_control;

		if (isOwner) {
			// 내가 만든 에이전트
			if (ac === null || ac === undefined) return { label: $i18n.t('Public'), type: 'warning' };
			const hasGroupShare = (ac?.read?.group_ids?.length > 0 || ac?.write?.group_ids?.length > 0);
			if ($activeWorkspaceFilter === 'mine') {
				return hasGroupShare ? { label: $i18n.t('Shared'), type: 'info' } : null;
			} else {
				return hasGroupShare ? { label: $i18n.t('Shared'), type: 'info' } : { label: $i18n.t('My Agents'), type: 'muted' };
			}
		}

		// 공유받은 에이전트: 그룹(R/W) 표시
		if (!ac) return { label: $i18n.t('Public'), type: 'warning' };
		const writeGroups = ac?.write?.group_ids ?? [];
		const readGroups = ac?.read?.group_ids ?? [];
		if (writeGroups.some((gid: string) => group_ids.includes(gid))) return { label: `${$i18n.t('Group')}(W)`, type: 'info' };
		if (readGroups.some((gid: string) => group_ids.includes(gid))) return { label: `${$i18n.t('Group')}(R)`, type: 'info' };
		return null;
	};

	onMount(async () => {
		models = await getWorkspaceModels(localStorage.token);
		let groups = await getGroups(localStorage.token);
		group_ids = groups.map((group) => group.id);

		// Load workspace tags
		try {
			workspaceTags.set(await getWorkspaceTags(localStorage.token));
			tagAssignments = await getAssignmentsByType(localStorage.token, 'agent');
		} catch (e) {
			console.error('Failed to load workspace tags:', e);
		}

		loaded = true;

		const onKeyDown = (event) => {
			if (event.key === 'Shift') {
				shiftKey = true;
			}
		};

		const onKeyUp = (event) => {
			if (event.key === 'Shift') {
				shiftKey = false;
			}
		};

		const onBlur = () => {
			shiftKey = false;
		};

		window.addEventListener('keydown', onKeyDown);
		window.addEventListener('keyup', onKeyUp);
		window.addEventListener('blur-sm', onBlur);

		return () => {
			window.removeEventListener('keydown', onKeyDown);
			window.removeEventListener('keyup', onKeyUp);
			window.removeEventListener('blur-sm', onBlur);
		};
	});
</script>

<svelte:head>
	<title>
		{$i18n.t('Agents')} | {$WEBUI_NAME}
	</title>
</svelte:head>

{#if loaded}
	<ModelDeleteConfirmDialog
		bind:show={showModelDeleteConfirm}
		on:confirm={() => {
			deleteModelHandler(selectedModel);
		}}
	/>

	<input
		id="models-import-input"
		bind:this={modelsImportInputElement}
		bind:files={importFiles}
		type="file"
		accept=".json"
		hidden
		on:change={() => {
			let reader = new FileReader();
			reader.onload = async (event) => {
				let savedModels = JSON.parse(event.target.result);

				for (const model of savedModels) {
					if (model?.info ?? false) {
						if ($_models.find((m) => m.id === model.id)) {
							await updateModelById(localStorage.token, model.id, model.info).catch((error) => {
								return null;
							});
						} else {
							await createNewModel(localStorage.token, model.info).catch((error) => {
								return null;
							});
						}
					} else {
						if (model?.id && model?.name) {
							await createNewModel(localStorage.token, model).catch((error) => {
								return null;
							});
						}
					}
				}

				await _models.set(
					await getModels(
						localStorage.token,
						$config?.features?.enable_direct_connections && ($settings?.directConnections ?? null)
					)
				);
				models = await getWorkspaceModels(localStorage.token);
			};

			reader.readAsText(importFiles[0]);
		}}
	/>

	<!-- Header Row -->
	<div class="flex items-center justify-between gap-[var(--cloo-space-2)] mt-2 mb-4">
		<div class="flex items-center gap-2.5">
			<span class="text-lg font-medium text-[var(--cloo-text-primary)]">
				{$i18n.t('Agents')}
			</span>
			<span class="text-lg font-medium text-[var(--token-scale-neutral-400)]">
				{filteredModels.length}
			</span>
		</div>

		<div class="flex items-center gap-[var(--cloo-space-2)]">
			<!-- Search Input -->
			<div class="w-[300px]">
				<Input
					bind:value={searchValue}
					placeholder={$i18n.t('Search Agents')}
					type="search"
					size="md"
				>
					<svelte:fragment slot="prefix">
						<Search className="size-3.5" />
					</svelte:fragment>
				</Input>
			</div>

			<!-- Action Buttons -->
			{#if $user?.role === 'admin' || $user?.permissions?.workspace?.agents === 'write'}
				<div class="flex items-center gap-[var(--cloo-space-2)]">
					<Button
						kind="filled"
						size="md"
						on:click={() => {
							goto('/workspace/agents/create');
						}}
					>
						<svelte:fragment slot="prefix">
							<Plus className="size-3.5" />
						</svelte:fragment>
						{$i18n.t('New Agent')}
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
		{#if hasSharedModels}
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
			{$i18n.t('My Agents')}
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

	<!-- Agent Cards Grid -->
	{#if filteredModels.length === 0}
		<div class="flex flex-col items-center justify-center h-64 text-gray-500 dark:text-gray-400">
			<div class="text-6xl mb-4">🤖</div>
			<div class="text-xl font-medium mb-2">{$i18n.t('No agents yet')}</div>
			<div class="text-sm">{$i18n.t('Create an agent to get started.')}</div>
		</div>
	{:else}
	<div class="workspace-cards-grid mb-5" id="model-list">
		{#each filteredModels as model}
			<WorkspaceCard
				id="model-item-{model.id}"
				profileImage={model?.meta?.profile_image_url}
				showAvatar={true}
				name={model.name}
				description={model?.meta?.description ?? ''}
				isActive={model.is_active}
				on:click={() => {
					if (
						$user?.role === 'admin' ||
						model.user_id === $user?.id ||
						model.access_control?.write?.group_ids?.some((wg) => group_ids.includes(wg))
					) {
						goto(`/workspace/agents/edit?id=${encodeURIComponent(model.id)}`);
					}
				}}
			>
				<svelte:fragment slot="badge">
					{#if model?.meta?.responseFormat?.type === 'json_schema'}
						<Badge type="info" content={$i18n.t('Structured')} />
					{:else}
						<Badge type="muted" content={$i18n.t('Chat')} />
					{/if}
					{#if getShareTag(model)}
						<Badge type={getShareTag(model).type} content={getShareTag(model).label} />
					{/if}
				</svelte:fragment>

				<svelte:fragment slot="actions">
					{#if shiftKey}
						{#if $user?.role === 'admin' || ($user?.permissions?.workspace?.agents === 'write' && model.user_id === $user?.id)}
							<Tooltip content={$i18n.t('Delete')}>
								<Button
									kind="text"
									size="md"
									on:click={() => {
										deleteModelHandler(model);
									}}
								>
									<GarbageBin className="size-3.5" />
								</Button>
							</Tooltip>
						{/if}
					{:else}
						{#if $user?.role === 'admin' || ($user?.permissions?.workspace?.agents === 'write' && model.user_id === $user?.id)}
							<AgentMenu
								user={$user}
								{model}
								shareHandler={() => {
									shareModelHandler(model);
								}}
								cloneHandler={() => {
									cloneModelHandler(model);
								}}
								exportHandler={() => {
									exportModelHandler(model);
								}}
								hideHandler={() => {
									hideModelHandler(model);
								}}
								deleteHandler={() => {
									selectedModel = model;
									showModelDeleteConfirm = true;
								}}
								onClose={() => {}}
							>
								<Button kind="text" size="md">
									<EllipsisHorizontal className="size-3.5" />
								</Button>
							</AgentMenu>
						{/if}

						{#if $user?.role === 'admin' || ($user?.permissions?.workspace?.agents === 'write' && model.user_id === $user?.id)}
							<Tooltip content={model.is_active ? $i18n.t('Enabled') : $i18n.t('Disabled')}>
								<Switch
									bind:state={model.is_active}
									on:change={async (e) => {
										toggleModelById(localStorage.token, model.id);
										_models.set(
											await getModels(
												localStorage.token,
												$config?.features?.enable_direct_connections &&
													($settings?.directConnections ?? null)
											)
										);
									}}
								/>
							</Tooltip>
						{/if}
					{/if}
				</svelte:fragment>

				<svelte:fragment slot="title">
					<Tooltip
						content={marked.parse(model?.meta?.description ?? model.id)}
						className="w-fit"
						placement="top-start"
					>
						<div
							class="text-base font-semibold leading-6 text-[var(--cloo-text-primary)] line-clamp-1"
						>
							{model.name}
						</div>
					</Tooltip>
				</svelte:fragment>

				<svelte:fragment slot="description-fallback">
					{model.id}
				</svelte:fragment>

				<svelte:fragment slot="footer-left">
					<Tooltip
						content={model?.user?.email ?? $i18n.t('Deleted User')}
						className="flex shrink-0"
						placement="top-start"
					>
						<span class="text-xs leading-4 text-[var(--token-scale-neutral-400)]">
							{$i18n.t('By {{name}}', {
								name: capitalizeFirstLetter(
									model?.user?.name ?? model?.user?.email ?? $i18n.t('Deleted User')
								)
							})}
						</span>
					</Tooltip>
				</svelte:fragment>

				<svelte:fragment slot="footer-right">
					<Button
						kind="outlined"
						size="md"
						on:click={() => {
							goto(`/?models=${encodeURIComponent(model.id)}`);
						}}
					>
						{$i18n.t('Start Chat')}
						<svelte:fragment slot="suffix">
							<ArrowRight className="size-3" strokeWidth="2" />
						</svelte:fragment>
					</Button>
				</svelte:fragment>
			</WorkspaceCard>
		{/each}
	</div>
	{/if}

	{#if $user?.role === 'admin'}
		<div class="flex justify-end gap-[var(--cloo-space-2)] mt-4 mb-8">
			<Button
				kind="outlined"
				size="sm"
				on:click={() => {
					modelsImportInputElement.click();
				}}
			>
				<svelte:fragment slot="prefix">
					<svg
						xmlns="http://www.w3.org/2000/svg"
						fill="none"
						viewBox="0 0 24 24"
						stroke-width="1.5"
						stroke="currentColor"
						class="size-3"
					>
						<path
							stroke-linecap="round"
							stroke-linejoin="round"
							d="M3 16.5v2.25A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75V16.5m-13.5-9L12 3m0 0 4.5 4.5M12 3v13.5"
						/>
					</svg>
				</svelte:fragment>
				{$i18n.t('Import Agents')}
			</Button>

			{#if models.length}
				<Button
					kind="outlined"
					size="sm"
					on:click={async () => {
						downloadModels(models);
					}}
				>
					<svelte:fragment slot="prefix">
						<svg
							xmlns="http://www.w3.org/2000/svg"
							fill="none"
							viewBox="0 0 24 24"
							stroke-width="1.5"
							stroke="currentColor"
							class="size-3"
						>
							<path
								stroke-linecap="round"
								stroke-linejoin="round"
								d="M3 16.5v2.25A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75V16.5M16.5 12 12 16.5m0 0L7.5 12m4.5 4.5V3"
							/>
						</svg>
					</svelte:fragment>
					{$i18n.t('Export Agents')}
				</Button>
			{/if}
		</div>
	{/if}
{:else}
	<div class="w-full h-full flex justify-center items-center">
		<Spinner />
	</div>
{/if}

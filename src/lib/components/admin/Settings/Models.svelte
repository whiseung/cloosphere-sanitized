<script lang="ts">
	import { marked } from 'marked';
	import fileSaver from 'file-saver';
	const { saveAs } = fileSaver;

	import { onMount, getContext, tick } from 'svelte';
	const i18n = getContext('i18n');

	import { WEBUI_NAME, config, mobile, models as _models, settings, user } from '$lib/stores';
	import {
		createNewModel,
		deleteAllModels,
		getBaseModels,
		toggleModelById,
		updateModelById
	} from '$lib/apis/models';

	import { getModels } from '$lib/apis';
	import Search from '$lib/components/icons/Search.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import Switch from '$lib/components/common/Switch.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';

	import ModelEditor from './Models/ModelEditor.svelte';
	import { toast } from 'svelte-sonner';
	import ConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';
	import UsageLimitModal from './Models/UsageLimitModal.svelte';
	import OverrideManagerModal from './Models/OverrideManagerModal.svelte';
	import TokenInput from '$lib/components/common/TokenInput.svelte';
	import Button from '$lib/components/common/Button.svelte';
	import ChevronDown from '$lib/components/icons/ChevronDown.svelte';
	import ChevronRight from '$lib/components/icons/ChevronRight.svelte';
	import User from '$lib/components/icons/User.svelte';
	import UsersSolid from '$lib/components/icons/UsersSolid.svelte';
	import Building from '$lib/components/icons/Building.svelte';
	import { getUsageLimitConfig, updateUsageLimitConfig } from '$lib/apis/auths';
	import {
		getModelUsageLimitOverrideCounts,
		getModelsUsageCounts,
		type ModelUsageCounts,
		type OverrideCounts
	} from '$lib/apis/models';
	import ArrowDownTray from '$lib/components/icons/ArrowDownTray.svelte';
	import ManageModelsModal from './Models/ManageModelsModal.svelte';
	import ModelMenu from '$lib/components/admin/Settings/Models/ModelMenu.svelte';
	import EllipsisHorizontal from '$lib/components/icons/EllipsisHorizontal.svelte';
	import EyeSlash from '$lib/components/icons/EyeSlash.svelte';
	import Eye from '$lib/components/icons/Eye.svelte';
	import { brandingUrls } from '$lib/stores/branding';

	let shiftKey = false;

	let importFiles;
	let modelsImportInputElement: HTMLInputElement;

	let models = null;

	let workspaceModels = null;
	let baseModels = null;

	let filteredModels = [];
	let selectedModelId = null;

	let showManageModal = false;
	let showUsageLimitModal = false;

	// per-model accordion state
	let expandedModelIds: Set<string> = new Set();
	let perModelLimits: Record<string, number | null> = {}; // model_id → token limit (null = inherit)
	let usageLimitEnabled = false;
	let overrideCountsCache: Record<string, OverrideCounts> = {};
	let overrideLoading: Record<string, boolean> = {};
	let usageCounts: Record<string, ModelUsageCounts> = {};

	const loadUsageCounts = async () => {
		try {
			usageCounts = await getModelsUsageCounts(localStorage.token);
		} catch {
			usageCounts = {};
		}
	};

	// override sub-modal state
	let showOverrideModal = false;
	let overrideModelId = '';
	let overrideTier: 'users' | 'groups' | 'org_units' = 'users';

	const loadPerModelLimits = async () => {
		try {
			const cfg = await getUsageLimitConfig(localStorage.token);
			perModelLimits = { ...((cfg?.USAGE_LIMIT_PER_MODEL as Record<string, number>) || {}) };
			usageLimitEnabled = !!cfg?.ENABLE_USAGE_LIMIT;
			if (!usageLimitEnabled && expandedModelIds.size > 0) {
				expandedModelIds = new Set();
			}
		} catch {
			perModelLimits = {};
			usageLimitEnabled = false;
		}
	};

	const ensureOverrideCounts = async (modelId: string) => {
		if (overrideCountsCache[modelId]) return;
		overrideLoading = { ...overrideLoading, [modelId]: true };
		try {
			const counts = await getModelUsageLimitOverrideCounts(localStorage.token, modelId);
			overrideCountsCache = { ...overrideCountsCache, [modelId]: counts };
		} catch {
			overrideCountsCache = {
				...overrideCountsCache,
				[modelId]: { users: 0, groups: 0, org_units: 0 }
			};
		}
		overrideLoading = { ...overrideLoading, [modelId]: false };
	};

	const toggleAccordion = async (modelId: string) => {
		if (expandedModelIds.has(modelId)) {
			expandedModelIds.delete(modelId);
		} else {
			expandedModelIds.add(modelId);
			await ensureOverrideCounts(modelId);
		}
		expandedModelIds = new Set(expandedModelIds);
	};

	const savePerModelLimit = async (modelId: string) => {
		try {
			const cfg = await getUsageLimitConfig(localStorage.token);
			const next = { ...((cfg?.USAGE_LIMIT_PER_MODEL as Record<string, number>) || {}) };
			const v = perModelLimits[modelId];
			if (v === null || v === undefined) {
				delete next[modelId];
			} else {
				next[modelId] = Math.max(0, Math.floor(Number(v) || 0));
			}
			await updateUsageLimitConfig(localStorage.token, {
				USAGE_LIMIT_PER_MODEL: next
			});
			perModelLimits = { ...perModelLimits, [modelId]: next[modelId] ?? null };
			toast.success($i18n.t('Saved'));
		} catch {
			toast.error($i18n.t('Failed to save configuration'));
		}
	};

	const openOverrideModal = (modelId: string, tier: 'users' | 'groups' | 'org_units') => {
		overrideModelId = modelId;
		overrideTier = tier;
		showOverrideModal = true;
	};

	const onOverrideClosed = async () => {
		// 모달이 닫힐 때 카운트 새로고침 (편집 반영)
		if (overrideModelId) {
			delete overrideCountsCache[overrideModelId];
			await ensureOverrideCounts(overrideModelId);
		}
	};

	$: if (!showOverrideModal && overrideModelId) {
		void onOverrideClosed();
	}

	let prevUsageLimitModalShown = false;
	$: {
		if (prevUsageLimitModalShown && !showUsageLimitModal) {
			void loadPerModelLimits();
		}
		prevUsageLimitModalShown = showUsageLimitModal;
	}

	$: if (models) {
		filteredModels = models
			.filter((m) => searchValue === '' || m.name.toLowerCase().includes(searchValue.toLowerCase()))
			.sort((a, b) => {
				// // Check if either model is inactive and push them to the bottom
				// if ((a.is_active ?? true) !== (b.is_active ?? true)) {
				// 	return (b.is_active ?? true) - (a.is_active ?? true);
				// }
				// If both models' active states are the same, sort alphabetically
				return a.name.localeCompare(b.name);
			});
	}

	let searchValue = '';

	const downloadModels = async (models) => {
		let blob = new Blob([JSON.stringify(models)], {
			type: 'application/json'
		});
		saveAs(blob, `models-export-${Date.now()}.json`);
	};

	const init = async () => {
		workspaceModels = await getBaseModels(localStorage.token);
		baseModels = await getModels(localStorage.token, null, true);

		models = baseModels.map((m) => {
			const workspaceModel = workspaceModels.find((wm) => wm.id === m.id);

			if (workspaceModel) {
				return {
					...m,
					...workspaceModel
				};
			} else {
				return {
					...m,
					id: m.id,
					name: m.name,

					is_active: true
				};
			}
		});
	};

	const upsertModelHandler = async (model) => {
		model.base_model_id = null;

		if (workspaceModels.find((m) => m.id === model.id)) {
			const res = await updateModelById(localStorage.token, model.id, model).catch((error) => {
				return null;
			});

			if (res) {
				toast.success($i18n.t('Model updated successfully'));
			}
		} else {
			const res = await createNewModel(localStorage.token, {
				meta: {},
				id: model.id,
				name: model.name,
				base_model_id: null,
				params: {},
				access_control: null,
				...model
			}).catch((error) => {
				return null;
			});

			if (res) {
				toast.success($i18n.t('Model updated successfully'));
			}
		}

		_models.set(
			await getModels(
				localStorage.token,
				$config?.features?.enable_direct_connections && ($settings?.directConnections ?? null)
			)
		);
		await init();
	};

	const toggleModelHandler = async (model) => {
		if (!Object.keys(model).includes('base_model_id')) {
			await createNewModel(localStorage.token, {
				id: model.id,
				name: model.name,
				base_model_id: null,
				meta: {},
				params: {},
				access_control: null,
				is_active: model.is_active
			}).catch((error) => {
				return null;
			});
		} else {
			await toggleModelById(localStorage.token, model.id);
		}

		// await init();
		_models.set(
			await getModels(
				localStorage.token,
				$config?.features?.enable_direct_connections && ($settings?.directConnections ?? null)
			)
		);
	};

	const hideModelHandler = async (model) => {
		model.meta = {
			...model.meta,
			hidden: !(model?.meta?.hidden ?? false)
		};

		console.log(model);

		toast.success(
			model.meta.hidden
				? $i18n.t(`Model {{name}} is now hidden`, {
						name: model.id
					})
				: $i18n.t(`Model {{name}} is now visible`, {
						name: model.id
					})
		);

		upsertModelHandler(model);
	};

	const exportModelHandler = async (model) => {
		let blob = new Blob([JSON.stringify([model])], {
			type: 'application/json'
		});
		saveAs(blob, `${model.id}-${Date.now()}.json`);
	};

	onMount(async () => {
		await init();
		await loadPerModelLimits();
		await loadUsageCounts();

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

<ManageModelsModal bind:show={showManageModal} />
<UsageLimitModal bind:show={showUsageLimitModal} />
<OverrideManagerModal
	bind:show={showOverrideModal}
	modelId={overrideModelId}
	tier={overrideTier}
/>

{#if models !== null}
	{#if selectedModelId === null}
		<div class="flex flex-col gap-1 mt-1.5 mb-2">
			<div class="flex justify-between items-center">
				<div class="flex items-center md:self-center text-xl font-medium px-0.5">
					{$i18n.t('Models')}
					<div class="flex self-center w-[1px] h-6 mx-2.5 bg-gray-50 dark:bg-gray-850" />
					<span class="text-lg font-medium text-gray-500 dark:text-gray-300"
						>{filteredModels.length}</span
					>
				</div>

				<div class="flex items-center gap-1.5">
					<!--
					<Tooltip content={$i18n.t('Manage Models')}>
						<button
							class=" p-1 rounded-full flex gap-1 items-center"
							type="button"
							on:click={() => {
								showManageModal = true;
							}}
						>
							<ArrowDownTray />
						</button>
					</Tooltip>
					-->

					<Tooltip content={$i18n.t('Token Limit Management')}>
						<Button
							kind="outlined"
							size="sm"
							on:click={() => {
								showUsageLimitModal = true;
							}}
						>
							{$i18n.t('Token Limit')}
						</Button>
					</Tooltip>
				</div>
			</div>

			<div class=" flex flex-1 items-center w-full space-x-2">
				<div class="flex flex-1 items-center">
					<div class=" self-center ml-1 mr-3">
						<Search className="size-3.5" />
					</div>
					<input
						class=" w-full text-sm py-1 rounded-r-xl outline-hidden bg-transparent"
						bind:value={searchValue}
						placeholder={$i18n.t('Search Models')}
					/>
				</div>
			</div>
		</div>

		<div class=" my-2 mb-5" id="model-list">
			{#if models.length > 0}
				{#each filteredModels as model, modelIdx (model.id)}
					<div class="flex flex-col">
					<div
						class=" flex space-x-4 cursor-pointer w-full px-3 py-2 dark:hover:bg-white/5 hover:bg-black/5 rounded-lg transition {model
							?.meta?.hidden
							? 'opacity-50 dark:opacity-50'
							: ''}"
						id="model-item-{model.id}"
					>
						<button
							class=" flex flex-1 text-left space-x-3.5 cursor-pointer w-full"
							type="button"
							on:click={() => {
								selectedModelId = model.id;
							}}
						>
							<div class=" self-center w-8">
								<div
									class=" rounded-full object-cover {(model?.is_active ?? true)
										? ''
										: 'opacity-50 dark:opacity-50'} "
								>
									<img
										src={model?.meta?.profile_image_url ?? $brandingUrls.favicon}
										alt="modelfile profile"
										class=" rounded-full w-full h-auto object-cover"
									/>
								</div>
							</div>

							<div class=" flex-1 self-center {(model?.is_active ?? true) ? '' : 'text-gray-500'}">
								<Tooltip
									content={marked.parse(
										model?.meta?.description
											? model?.meta?.description
											: model?.ollama?.digest
												? `${model?.ollama?.digest} **(${model?.ollama?.modified_at})**`
												: model.id
									)}
									className=" w-fit"
									placement="top-start"
								>
									<div class="  font-semibold line-clamp-1">{model.name}</div>
								</Tooltip>
								<div class=" text-xs overflow-hidden text-ellipsis line-clamp-1 text-gray-500">
									<span class=" line-clamp-1">
										{model?.meta?.description
											? model?.meta?.description
											: model?.ollama?.digest
												? `${model.id} (${model?.ollama?.digest})`
												: model.id}
									</span>
								</div>

								{#if usageCounts[model.id] && (usageCounts[model.id].agents > 0 || usageCounts[model.id].flows > 0 || usageCounts[model.id].evaluations > 0)}
									<div class="flex flex-wrap items-center gap-1 mt-1">
										{#if usageCounts[model.id].agents > 0}
											<span
												class="inline-flex items-center gap-1 text-xs px-1.5 py-0.5 rounded-md bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-300"
											>
												{$i18n.t('Agents')}
												<span class="font-semibold tabular-nums">{usageCounts[model.id].agents}</span>
											</span>
										{/if}
										{#if usageCounts[model.id].flows > 0}
											<span
												class="inline-flex items-center gap-1 text-xs px-1.5 py-0.5 rounded-md bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-300"
											>
												{$i18n.t('Flows')}
												<span class="font-semibold tabular-nums">{usageCounts[model.id].flows}</span>
											</span>
										{/if}
										{#if usageCounts[model.id].evaluations > 0}
											<span
												class="inline-flex items-center gap-1 text-xs px-1.5 py-0.5 rounded-md bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-300"
											>
												{$i18n.t('Evaluations')}
												<span class="font-semibold tabular-nums">{usageCounts[model.id].evaluations}</span>
											</span>
										{/if}
									</div>
								{/if}
							</div>
						</button>
						<div class="flex flex-row gap-0.5 items-center self-center">
							{#if usageLimitEnabled}
								<button
									class="self-center flex items-center gap-1 text-xs px-2 py-1 mr-1 rounded-full border border-gray-200 dark:border-gray-700 text-gray-600 dark:text-gray-300 hover:bg-black/5 dark:hover:bg-white/5 transition"
									type="button"
									aria-label={$i18n.t('Token Limit')}
									aria-expanded={expandedModelIds.has(model.id)}
									on:click={() => void toggleAccordion(model.id)}
								>
									<span class="font-medium">{$i18n.t('Token Limit')}</span>
									<span
										class="transition-transform {expandedModelIds.has(model.id)
											? 'rotate-180'
											: ''}"
									>
										<ChevronDown className="size-3.5" />
									</span>
								</button>
							{/if}

							{#if shiftKey}
								<Tooltip content={model?.meta?.hidden ? $i18n.t('Show') : $i18n.t('Hide')}>
									<button
										class="self-center w-fit text-sm px-2 py-2 dark:text-gray-300 dark:hover:text-white hover:bg-black/5 dark:hover:bg-white/5 rounded-xl"
										type="button"
										on:click={() => {
											hideModelHandler(model);
										}}
									>
										{#if model?.meta?.hidden}
											<EyeSlash />
										{:else}
											<Eye />
										{/if}
									</button>
								</Tooltip>
							{:else}
								<button
									class="self-center w-fit text-sm px-2 py-2 dark:text-gray-300 dark:hover:text-white hover:bg-black/5 dark:hover:bg-white/5 rounded-xl"
									type="button"
									on:click={() => {
										selectedModelId = model.id;
									}}
								>
									<svg
										xmlns="http://www.w3.org/2000/svg"
										fill="none"
										viewBox="0 0 24 24"
										stroke-width="1.5"
										stroke="currentColor"
										class="w-4 h-4"
									>
										<path
											stroke-linecap="round"
											stroke-linejoin="round"
											d="m16.862 4.487 1.687-1.688a1.875 1.875 0 1 1 2.652 2.652L6.832 19.82a4.5 4.5 0 0 1-1.897 1.13l-2.685.8.8-2.685a4.5 4.5 0 0 1 1.13-1.897L16.863 4.487Zm0 0L19.5 7.125"
										/>
									</svg>
								</button>

								<ModelMenu
									user={$user}
									{model}
									exportHandler={() => {
										exportModelHandler(model);
									}}
									hideHandler={() => {
										hideModelHandler(model);
									}}
									onClose={() => {}}
								>
									<button
										class="self-center w-fit text-sm p-1.5 dark:text-gray-300 dark:hover:text-white hover:bg-black/5 dark:hover:bg-white/5 rounded-xl"
										type="button"
									>
										<EllipsisHorizontal className="size-5" />
									</button>
								</ModelMenu>

								<div class="ml-1">
									<Tooltip
										content={(model?.is_active ?? true) ? $i18n.t('Enabled') : $i18n.t('Disabled')}
									>
										<Switch
											bind:state={model.is_active}
											on:change={async () => {
												toggleModelHandler(model);
											}}
										/>
									</Tooltip>
								</div>
							{/if}
						</div>
					</div>

					{#if usageLimitEnabled && expandedModelIds.has(model.id)}
						<div class="mx-3 mb-3 rounded-xl border border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-gray-900/40 overflow-hidden">
							<div class="px-4 py-3 space-y-2 border-b border-gray-200 dark:border-gray-800">
								<div>
									<div class="text-sm font-medium">
										{$i18n.t("This model's base limit")}
									</div>
									{#if (perModelLimits[model.id] ?? null) === null}
										<div class="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
											{$i18n.t('Inherits from global default')}
										</div>
									{/if}
								</div>
								<div class="flex items-center gap-2">
									<div class="flex-1">
										<TokenInput bind:value={perModelLimits[model.id]} />
									</div>
									<Button kind="filled" size="md" on:click={() => void savePerModelLimit(model.id)}>
										{$i18n.t('Save')}
									</Button>
								</div>
							</div>

							<div class="px-4 py-3">
								<div class="grid grid-cols-1 sm:grid-cols-3 gap-2">
									{#each [{ tier: 'users', label: 'User overrides', icon: User }, { tier: 'groups', label: 'Group overrides', icon: UsersSolid }, { tier: 'org_units', label: 'Org unit overrides', icon: Building }] as tierItem}
										<button
											type="button"
											class="group flex items-center gap-3 px-3 py-2.5 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 hover:border-gray-300 dark:hover:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-850/60 transition text-left"
											on:click={() => openOverrideModal(model.id, tierItem.tier)}
										>
											<div
												class="flex-shrink-0 size-8 rounded-full flex items-center justify-center bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-300"
											>
												<svelte:component this={tierItem.icon} className="size-4" />
											</div>
											<div class="flex-1 min-w-0">
												<div class="text-sm font-semibold tabular-nums leading-tight">
													{overrideLoading[model.id]
														? '—'
														: (overrideCountsCache[model.id]?.[tierItem.tier] ?? 0)}
												</div>
												<div class="text-xs text-gray-500 dark:text-gray-400 truncate">
													{$i18n.t(tierItem.label)}
												</div>
											</div>
											<ChevronRight
												className="size-4 text-gray-400 group-hover:text-gray-600 dark:text-gray-500 dark:group-hover:text-gray-300 transition"
											/>
										</button>
									{/each}
								</div>
							</div>
						</div>
					{/if}
					</div>
				{/each}
			{:else}
				<div class="flex flex-col items-center justify-center w-full h-20">
					<div class="text-gray-500 dark:text-gray-400 text-xs">
						{$i18n.t('No models found')}
					</div>
				</div>
			{/if}
		</div>

		{#if $user?.role === 'admin'}
			<div class=" flex justify-end w-full mb-3">
				<div class="flex space-x-1">
					<input
						id="models-import-input"
						bind:this={modelsImportInputElement}
						bind:files={importFiles}
						type="file"
						accept=".json"
						hidden
						on:change={() => {
							console.log(importFiles);

							let reader = new FileReader();
							reader.onload = async (event) => {
								let savedModels = JSON.parse(event.target.result);
								console.log(savedModels);

								for (const model of savedModels) {
									if (Object.keys(model).includes('base_model_id')) {
										if (model.base_model_id === null) {
											upsertModelHandler(model);
										}
									} else {
										if (model?.info ?? false) {
											if (model.info.base_model_id === null) {
												upsertModelHandler(model.info);
											}
										}
									}
								}

								await _models.set(
									await getModels(
										localStorage.token,
										$config?.features?.enable_direct_connections &&
											($settings?.directConnections ?? null)
									)
								);
								init();
							};

							reader.readAsText(importFiles[0]);
						}}
					/>

					<button
						class="flex text-xs items-center space-x-1 px-3 py-1.5 rounded-xl bg-gray-50 hover:bg-gray-100 dark:bg-gray-800 dark:hover:bg-gray-700 dark:text-gray-200 transition"
						on:click={() => {
							modelsImportInputElement.click();
						}}
					>
						<div class=" self-center mr-2 font-medium line-clamp-1">
							{$i18n.t('Import Presets')}
						</div>

						<div class=" self-center">
							<svg
								xmlns="http://www.w3.org/2000/svg"
								viewBox="0 0 16 16"
								fill="currentColor"
								class="w-3.5 h-3.5"
							>
								<path
									fill-rule="evenodd"
									d="M4 2a1.5 1.5 0 0 0-1.5 1.5v9A1.5 1.5 0 0 0 4 14h8a1.5 1.5 0 0 0 1.5-1.5V6.621a1.5 1.5 0 0 0-.44-1.06L9.94 2.439A1.5 1.5 0 0 0 8.878 2H4Zm4 9.5a.75.75 0 0 1-.75-.75V8.06l-.72.72a.75.75 0 0 1-1.06-1.06l2-2a.75.75 0 0 1 1.06 0l2 2a.75.75 0 1 1-1.06 1.06l-.72-.72v2.69a.75.75 0 0 1-.75.75Z"
									clip-rule="evenodd"
								/>
							</svg>
						</div>
					</button>

					<button
						class="flex text-xs items-center space-x-1 px-3 py-1.5 rounded-xl bg-gray-50 hover:bg-gray-100 dark:bg-gray-800 dark:hover:bg-gray-700 dark:text-gray-200 transition"
						on:click={async () => {
							downloadModels(models);
						}}
					>
						<div class=" self-center mr-2 font-medium line-clamp-1">
							{$i18n.t('Export Presets')}
						</div>

						<div class=" self-center">
							<svg
								xmlns="http://www.w3.org/2000/svg"
								viewBox="0 0 16 16"
								fill="currentColor"
								class="w-3.5 h-3.5"
							>
								<path
									fill-rule="evenodd"
									d="M4 2a1.5 1.5 0 0 0-1.5 1.5v9A1.5 1.5 0 0 0 4 14h8a1.5 1.5 0 0 0 1.5-1.5V6.621a1.5 1.5 0 0 0-.44-1.06L9.94 2.439A1.5 1.5 0 0 0 8.878 2H4Zm4 3.5a.75.75 0 0 1 .75.75v2.69l.72-.72a.75.75 0 1 1 1.06 1.06l-2 2a.75.75 0 0 1-1.06 0l-2-2a.75.75 0 0 1 1.06-1.06l.72.72V6.25A.75.75 0 0 1 8 5.5Z"
									clip-rule="evenodd"
								/>
							</svg>
						</div>
					</button>
				</div>
			</div>
		{/if}
	{:else}
		<ModelEditor
			edit
			model={models.find((m) => m.id === selectedModelId)}
			preset={false}
			onSubmit={(model) => {
				console.log(model);
				upsertModelHandler(model);
				selectedModelId = null;
			}}
			onBack={() => {
				selectedModelId = null;
			}}
		/>
	{/if}
{:else}
	<div class=" h-full w-full flex justify-center items-center">
		<Spinner />
	</div>
{/if}

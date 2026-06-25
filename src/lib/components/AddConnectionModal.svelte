<script lang="ts">
	import { toast } from 'svelte-sonner';
	import { getContext, onMount } from 'svelte';
	const i18n = getContext('i18n');

	import { verifyOpenAIConnection, verifyAzureOpenAIConnection, verifyAzureAIFoundryConnection, verifyVertexAIConnection } from '$lib/apis/openai';
	import { verifyOllamaConnection } from '$lib/apis/ollama';
	import { getModelLinkedUsages, getConnectionLinkedUsages } from '$lib/apis/models';

	import Modal from '$lib/components/common/Modal.svelte';
	import Plus from '$lib/components/icons/Plus.svelte';
	import Minus from '$lib/components/icons/Minus.svelte';
	import XMark from '$lib/components/icons/XMark.svelte';
	import ArrowPath from '$lib/components/icons/ArrowPath.svelte';
	import Info from '$lib/components/icons/Info.svelte';
	import SensitiveInput from '$lib/components/common/SensitiveInput.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import Switch from '$lib/components/common/Switch.svelte';
	import Checkbox from '$lib/components/common/Checkbox.svelte';
	import Button from '$lib/components/common/Button.svelte';
	import Input from '$lib/components/common/Input.svelte';
	import Selector from '$lib/components/common/Selector.svelte';
	import Tags from './common/Tags.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';

	export let onSubmit: Function = () => {};
	export let onDelete: Function = () => {};

	export let show = false;
	export let edit = false;
	export let ollama = false;

	export let connection = null;

	let url = '';
	let key = '';

	let prefixId = '';
	let enable = true;
	let tags = [];

	let modelId = '';
	let modelIds = [];

	let providerType = 'openai'; // 'openai' | 'azure-openai' | 'vertex-ai'
	let apiVersion = ''; // Azure OpenAI API version

	// Vertex AI fields
	let projectId = '';
	let location = 'us-central1';
	let serviceAccountKey = '';
	let useGlobalGcpKey = false;

	let loading = false;
	let verifying = false;
	let fetchedModels: any[] = []; // Models fetched from Vertex AI verification

	$: providerOptions = [
		{ value: 'openai', label: $i18n.t('OpenAI') },
		{ value: 'azure-openai', label: $i18n.t('Azure OpenAI') },
		{ value: 'azure-ai-foundry', label: $i18n.t('Azure AI Foundry') },
		{ value: 'vertex-ai', label: $i18n.t('Vertex AI') }
	];

	let linkedUsagesError = '';
	let showLinkedUsagesError = false;
	let closeOnError = false;
	let isConnectionDeleteError = false;

	const verifyOpenAIHandler = async () => {
		const res = await verifyOpenAIConnection(localStorage.token, url, key).catch(
			(error) => {
				toast.error($i18n.t(`${error}`));
			}
		);

		if (res) {
			toast.success($i18n.t('Server connection verified'));
		}
	};

	const verifyAzureOpenAIHandler = async () => {
		if (!url) {
			toast.error($i18n.t('URL is required'));
			return;
		}
		if (!key) {
			toast.error($i18n.t('API Key is required'));
			return;
		}
		if (!apiVersion) {
			toast.error($i18n.t('API Version is required'));
			return;
		}

		verifying = true;

		try {
			const res = await verifyAzureOpenAIConnection(
				localStorage.token,
				url,
				key,
				apiVersion
			);

			if (res && res.status === 'success') {
				const msg = res.model_count
					? `${$i18n.t('Connection verified')} (${res.model_count} ${$i18n.t('models found')})`
					: $i18n.t('Connection verified');
				toast.success(msg);
				// Optionally populate modelIds from deployments
				if (res.data && res.data.length > 0 && modelIds.length === 0) {
					modelIds = res.data.map((d: any) => d.id);
				}
			}
		} catch (error) {
			toast.error($i18n.t(`${error}`));
		} finally {
			verifying = false;
		}
	};

	const verifyVertexAIHandler = async () => {
		if (!projectId) {
			toast.error($i18n.t('Project ID is required'));
			return;
		}
		if (!serviceAccountKey && !useGlobalGcpKey) {
			toast.error($i18n.t('Service Account Key is required'));
			return;
		}

		verifying = true;
		fetchedModels = [];

		try {
			const res = await verifyVertexAIConnection(
				localStorage.token,
				projectId,
				location,
				serviceAccountKey,
				useGlobalGcpKey
			);

			if (res && res.status === 'success') {
				toast.success($i18n.t('Connection verified'));
				fetchedModels = res.models || [];
			}
		} catch (error) {
			toast.error($i18n.t(`${error}`));
		} finally {
			verifying = false;
		}
	};

	const verifyAzureAIFoundryHandler = async () => {
		if (!url) {
			toast.error($i18n.t('URL is required'));
			return;
		}
		if (!key) {
			toast.error($i18n.t('API Key is required'));
			return;
		}
		if (!apiVersion) {
			toast.error($i18n.t('API Version is required'));
			return;
		}

		verifying = true;

		try {
			const res = await verifyAzureAIFoundryConnection(localStorage.token, url, key, apiVersion);

			if (res && res.status === 'success') {
				const msg = res.model_count
					? `${$i18n.t('Connection verified')} (${res.model_count} ${$i18n.t('models found')})`
					: $i18n.t('Connection verified');
				toast.success(msg);
				if (res.data && res.data.length > 0 && modelIds.length === 0) {
					modelIds = res.data.map((d: any) => d.id);
				}
			}
		} catch (error) {
			toast.error($i18n.t(`${error}`));
		} finally {
			verifying = false;
		}
	};

	const verifyOllamaHandler = async () => {
		verifying = true;
		try {
			const res = await verifyOllamaConnection(localStorage.token, url, key);
			if (res) {
				toast.success($i18n.t('Ollama connection verified'));
			}
		} catch (e) {
			toast.error(e?.toString() || $i18n.t('Connection failed'));
		}
		verifying = false;
	};

	const verifyHandler = () => {
		if (ollama) {
			verifyOllamaHandler();
		} else if (providerType === 'vertex-ai') {
			verifyVertexAIHandler();
		} else if (providerType === 'azure-openai') {
			verifyAzureOpenAIHandler();
		} else if (providerType === 'azure-ai-foundry') {
			verifyAzureAIFoundryHandler();
		} else {
			verifyOpenAIHandler();
		}
	};

	const addFetchedModelHandler = (model: any) => {
		if (model && model.id && !modelIds.includes(model.id)) {
			modelIds = [...modelIds, model.id];
		}
	};

	const addModelHandler = () => {
		if (modelId) {
			if (modelIds.includes(modelId)) {
				toast.error($i18n.t('Model ID already exists'));
				modelId = '';
				return;
			}
			modelIds = [...modelIds, modelId];
			modelId = '';
		}
	};

	const submitHandler = async () => {
		loading = true;

		// Vertex AI: validate required fields and auto-generate URL
		if (providerType === 'vertex-ai') {
			if (!projectId) {
				loading = false;
				toast.error($i18n.t('Project ID is required'));
				return;
			}
			if (!useGlobalGcpKey && !serviceAccountKey) {
				loading = false;
				toast.error($i18n.t('Service Account Key is required'));
				return;
			}
			// Auto-generate URL based on location (for display/identification purposes)
			url = `https://${location}-aiplatform.googleapis.com`;
		} else {
			if (!url) {
				loading = false;
				toast.error($i18n.t('URL is required'));
				return;
			}
		}

		// remove trailing slash from url
		url = url.replace(/\/$/, '');

		const config: any = {
			enable: enable,
			tags: tags,
			model_ids: modelIds,
			provider_type: providerType
		};

		// Add prefix_id for non-Vertex providers
		if (providerType !== 'vertex-ai') {
			config.prefix_id = prefixId;
		}

		// Add provider-specific fields
		if (providerType === 'azure-openai' || providerType === 'azure-ai-foundry') {
			config.api_version = apiVersion;
		} else if (providerType === 'vertex-ai') {
			config.project_id = projectId;
			config.location = location;
			config.service_account_key = useGlobalGcpKey ? '' : serviceAccountKey;
			config.use_global_gcp_key = useGlobalGcpKey;
		}

		const connection: any = {
			url,
			config,
			// Vertex AI uses empty key (authentication via service account)
			key: providerType === 'vertex-ai' ? '' : key
		};

		await onSubmit(connection);

		loading = false;
		show = false;

		url = '';
		key = '';
		prefixId = '';
		tags = [];
		modelId = '';
		modelIds = [];
		providerType = 'openai';
		apiVersion = '';
		projectId = '';
		location = 'us-central1';
		serviceAccountKey = '';
		useGlobalGcpKey = false;
		fetchedModels = [];
	};

	const init = () => {
		if (connection) {
			url = connection.url;
			key = connection.key ?? '';

			enable = connection.config?.enable ?? true;
			tags = connection.config?.tags ?? [];
			prefixId = connection.config?.prefix_id ?? '';
			modelIds = connection.config?.model_ids ?? [];
			providerType = connection.config?.provider_type ?? 'openai';
			apiVersion = connection.config?.api_version ?? '';
			projectId = connection.config?.project_id ?? '';
			location = connection.config?.location ?? 'us-central1';
			serviceAccountKey = connection.config?.service_account_key ?? '';
			useGlobalGcpKey = connection.config?.use_global_gcp_key ?? false;
			fetchedModels = [];
		} else {
			providerType = 'openai';
			url = '';
			key = '';
			prefixId = '';
			tags = [];
			modelId = '';
			modelIds = [];
			apiVersion = '';
			projectId = '';
			location = 'us-central1';
			serviceAccountKey = '';
			useGlobalGcpKey = false;
			fetchedModels = [];
		}
	};

	$: if (show) {
		init();
	} else {
		modelId = '';
	}

	onMount(() => {
		init();
	});
</script>

<Modal size="sm" bind:show>
	<div>
		{#if showLinkedUsagesError}
			<!-- svelte-ignore a11y-click-events-have-key-events -->
			<div
				class="fixed inset-0 z-[60] flex items-center justify-center bg-black/40"
				on:click|self={() => (showLinkedUsagesError = false)}
			>
				<div class="bg-white dark:bg-gray-900 rounded-2xl shadow-xl w-full max-w-sm mx-4 p-6 flex flex-col gap-4">
					<div class="flex items-start gap-3">
						<div class="flex-shrink-0 w-9 h-9 rounded-full bg-red-100 dark:bg-red-900/30 flex items-center justify-center">
							<svg class="w-5 h-5 text-red-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
								<path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
							</svg>
						</div>
						<div>
							<h3 class="text-base font-semibold text-gray-900 dark:text-white">
								{#if isConnectionDeleteError}
									{$i18n.t('Cannot delete connection')}
								{:else}
									{$i18n.t('Cannot remove model ID')}
								{/if}
							</h3>
							<p class="mt-1 text-sm text-gray-500 dark:text-gray-400">
								{#if isConnectionDeleteError}
									{$i18n.t('This connection cannot be deleted because the model is currently in use.')}
								{:else}
									{$i18n.t('This model is currently in use. Please remove it from the following first.')}
								{/if}
							</p>
						</div>
					</div>
					{#if linkedUsagesError}
						<ul class="flex flex-col gap-1 pl-1">
							{#each linkedUsagesError.split('\n') as line}
								<li class="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300">
									<span class="w-1.5 h-1.5 rounded-full bg-red-400 flex-shrink-0" />
									{line}
								</li>
							{/each}
						</ul>
					{/if}
					<div class="flex justify-end">
						<Button
							kind="outlined"
							size="md"
							type="button"
							on:click={() => {
								showLinkedUsagesError = false;
								if (closeOnError) {
									closeOnError = false;
									show = false;
								}
							}}
						>
							{$i18n.t('Close')}
						</Button>
					</div>
				</div>
			</div>
		{/if}

		<div class=" flex justify-between dark:text-gray-100 px-5 pt-4 pb-2">
			<div class=" text-lg font-medium self-center font-primary">
				{#if edit}
					{$i18n.t('Edit Connection')}
				{:else}
					{$i18n.t('Add Connection')}
				{/if}
			</div>
			<Button
				kind="text"
				size="sm"
				type="button"
				on:click={() => {
					show = false;
				}}
			>
				<XMark className="size-5" />
			</Button>
		</div>

		<div class="flex flex-col md:flex-row w-full px-4 pb-4 md:space-x-4 dark:text-gray-200">
			<div class=" flex flex-col w-full sm:flex-row sm:justify-center sm:space-x-6">
				<form
					class="flex flex-col w-full"
					on:submit={(e) => {
						e.preventDefault();
						submitHandler();
					}}
				>
					<div class="px-1">
						{#if !ollama}
							<div class="flex w-full justify-between items-center mb-2 gap-2">
								<div class="self-center text-xs font-medium">{$i18n.t('Provider')}</div>
								<div class="min-w-[180px]">
									<Selector
										value={providerType}
										items={providerOptions}
										size="sm"
										searchEnabled={false}
										on:change={(e) => {
											providerType = e.detail.value;
										}}
									/>
								</div>
							</div>
						{/if}

						{#if providerType !== 'vertex-ai'}
							<!-- URL field for non-Vertex AI providers -->
							<div class="flex gap-2 items-end">
								<div class="flex-1">
									<Input
										bind:value={url}
										label={$i18n.t('URL')}
										placeholder={$i18n.t('API Base URL')}
										size="sm"
										autocomplete="off"
										required
									/>
								</div>

								<Tooltip content={$i18n.t('Verify Connection')}>
									<Button
										kind="text"
										size="sm"
										type="button"
										disabled={verifying}
										loading={verifying}
										on:click={() => {
											verifyHandler();
										}}
									>
										<ArrowPath className="size-4" />
									</Button>
								</Tooltip>

								<div class="shrink-0 self-center pb-1.5">
									<Tooltip content={enable ? $i18n.t('Enabled') : $i18n.t('Disabled')}>
										<Switch bind:state={enable} />
									</Tooltip>
								</div>
							</div>
						{:else}
							<!-- Vertex AI: Verify button and Enable switch -->
							<div class="flex gap-2 justify-end items-center">
								<Tooltip content={$i18n.t('Verify Connection & Fetch Models')}>
									<Button
										kind="text"
										size="sm"
										type="button"
										disabled={verifying ||
											!projectId ||
											(!serviceAccountKey && !useGlobalGcpKey)}
										loading={verifying}
										on:click={verifyVertexAIHandler}
									>
										<ArrowPath className="size-4" />
									</Button>
								</Tooltip>

								<Tooltip content={enable ? $i18n.t('Enabled') : $i18n.t('Disabled')}>
									<Switch bind:state={enable} />
								</Tooltip>
							</div>
						{/if}

						{#if !ollama && providerType === 'vertex-ai'}
							<!-- Vertex AI: Project ID, Location, Service Account Key -->
							<div class="flex gap-2 mt-2">
								<div class="flex-1">
									<Input
										bind:value={projectId}
										label={$i18n.t('Project ID')}
										placeholder={$i18n.t('Project ID')}
										size="sm"
										autocomplete="off"
										required
									/>
								</div>

								<div class="flex-1">
									<Input
										bind:value={location}
										label={$i18n.t('Location')}
										placeholder={$i18n.t('Location (e.g. us-central1)')}
										size="sm"
										autocomplete="off"
									/>
								</div>
							</div>

						<div class="flex items-center gap-2 mt-2">
							<Checkbox
								state={useGlobalGcpKey ? 'checked' : 'unchecked'}
								on:change={(e) => { useGlobalGcpKey = e.detail === 'checked'; }}
							/>
							<span class="text-xs text-gray-600 dark:text-gray-400">
								{$i18n.t('Use Global Google Cloud Key')}
							</span>
						</div>

						{#if !useGlobalGcpKey}
								<div class="flex flex-col w-full mt-2">
									<div class="mb-0.5 text-xs text-gray-500">{$i18n.t('Service Account Key JSON')}</div>
									<div class="flex-1">
										<SensitiveInput
											className="w-full text-sm bg-transparent placeholder:text-gray-300 dark:placeholder:text-gray-700 outline-none"
											bind:value={serviceAccountKey}
											placeholder={$i18n.t('Service Account Key JSON')}
											required={false}
										/>
									</div>
								</div>
							{:else}
								<div class="mt-2 text-xs text-gray-500 dark:text-gray-400">
									{$i18n.t('Using global Google Cloud key from Cloud Accounts')}
								</div>
							{/if}

							<!-- Vertex AI: Fetched Models List -->
							{#if fetchedModels.length > 0}
								<div class="mt-3">
									<div class="mb-1 text-xs text-gray-500">{$i18n.t('Available Models')} ({fetchedModels.length})</div>
									<div class="flex flex-wrap gap-1 max-h-32 overflow-y-auto">
										{#each fetchedModels as model}
											<button
												type="button"
												class="px-2 py-1 text-xs rounded-md transition {modelIds.includes(model.id)
													? 'bg-green-100 dark:bg-green-900 text-green-700 dark:text-green-300'
													: 'bg-gray-100 dark:bg-gray-800 hover:bg-gray-200 dark:hover:bg-gray-700'}"
												on:click={() => addFetchedModelHandler(model)}
												disabled={modelIds.includes(model.id)}
											>
												{model.id}
												{#if modelIds.includes(model.id)}
													<span class="ml-1">✓</span>
												{/if}
											</button>
										{/each}
									</div>
								</div>
							{/if}
						{:else}
							<!-- OpenAI and Azure OpenAI: Key and Prefix ID -->
							<div class="flex gap-2 mt-2">
								<div class="flex flex-col w-full">
									<div class="mb-0.5 text-xs text-gray-500">{$i18n.t('Key')}</div>

									<div class="flex-1">
										<SensitiveInput
											className="w-full text-sm bg-transparent placeholder:text-gray-300 dark:placeholder:text-gray-700 outline-none"
											bind:value={key}
											placeholder={$i18n.t('API Key')}
											required={false}
										/>
									</div>
								</div>

								<div class="flex-1 flex flex-col gap-1">
									<div class="flex items-center gap-1">
										<span class="text-xs leading-4 font-medium text-[var(--cloo-text-primary)]">
											{$i18n.t('Prefix ID')}
										</span>
										<Tooltip
											content={$i18n.t(
												'Prefix ID is used to avoid conflicts with other connections by adding a prefix to the model IDs - leave empty to disable'
											)}
										>
											<Info className="size-3.5 text-[var(--cloo-text-muted)]" />
										</Tooltip>
									</div>
									<Input
										bind:value={prefixId}
										placeholder={$i18n.t('Prefix ID')}
										size="sm"
										autocomplete="off"
									/>
								</div>
							</div>

							<!-- Azure OpenAI: API Version -->
							{#if !ollama && (providerType === 'azure-openai' || providerType === 'azure-ai-foundry')}
								<div class="mt-2">
									<Input
										bind:value={apiVersion}
										label={$i18n.t('API Version')}
										placeholder={$i18n.t('e.g., 2024-02-15-preview')}
										size="sm"
										autocomplete="off"
										required
									/>
								</div>
							{/if}
						{/if}

						<div class="flex gap-2 mt-2">
							<div class="flex flex-col w-full">
								<div class=" mb-1.5 text-xs text-gray-500">{$i18n.t('Tags')}</div>

								<div class="flex-1">
									<Tags
										bind:tags
										on:add={(e) => {
											tags = [
												...tags,
												{
													name: e.detail
												}
											];
										}}
										on:delete={(e) => {
											tags = tags.filter((tag) => tag.name !== e.detail);
										}}
									/>
								</div>
							</div>
						</div>

						<hr class=" border-gray-100 dark:border-gray-700/10 my-2.5 w-full" />

						<div class="flex flex-col w-full">
							<div class="mb-1 flex justify-between">
								<div class="text-xs text-gray-500">{$i18n.t('Model IDs')}</div>
							</div>

							{#if modelIds.length > 0}
								<div class="flex flex-col">
									{#each modelIds as modelId, modelIdx}
										<div class=" flex gap-2 w-full justify-between items-center">
											<div class=" text-sm flex-1 py-1 rounded-lg">
												{modelId}
											</div>
											<div class="shrink-0">
												<Button
													kind="text"
													size="sm"
													type="button"
													on:click={async () => {
														const usages = await getModelLinkedUsages(localStorage.token, modelId).catch(() => null);
														if (usages) {
															const agents = usages.agents ?? [];
															const guardrails = usages.guardrails ?? [];
															if (agents.length > 0 || guardrails.length > 0) {
																const parts = [];
																if (agents.length > 0) parts.push('Agent: ' + agents.map((a) => a.name).join(', '));
																if (guardrails.length > 0) parts.push('Guardrail (Judge): ' + guardrails.map((g) => g.name).join(', '));
																linkedUsagesError = parts.join('\n');
																isConnectionDeleteError = false;
																showLinkedUsagesError = true;
																return;
															}
														}
														modelIds = modelIds.filter((_, idx) => idx !== modelIdx);
													}}
												>
													<Minus strokeWidth="2" className="size-3.5" />
												</Button>
											</div>
										</div>
									{/each}
								</div>
							{:else}
								<div class="text-gray-500 text-xs text-center py-2 px-10">
									{$i18n.t('Leave empty to include all models from "{{url}}/models" endpoint', {
										url: url
									})}
								</div>
							{/if}
						</div>

						<hr class=" border-gray-100 dark:border-gray-700/10 my-2.5 w-full" />

						<div class="flex items-center gap-2">
							<div class="flex-1">
								<Input
									bind:value={modelId}
									placeholder={$i18n.t('Add a model ID')}
									size="sm"
								/>
							</div>

							<Button
								kind="text"
								size="sm"
								type="button"
								on:click={() => {
									addModelHandler();
								}}
							>
								<Plus className="size-3.5" strokeWidth="2" />
							</Button>
						</div>
					</div>

					<div class="flex justify-end pt-3 text-sm font-medium gap-1.5">
						{#if edit}
							<Button
								kind="outlined"
								size="md"
								on:click={async () => {
									if (modelIds.length > 0) {
										const result = await getConnectionLinkedUsages(localStorage.token, modelIds).catch(() => null);
										if (result?.in_use) {
											linkedUsagesError = '';
											isConnectionDeleteError = true;
											closeOnError = true;
											showLinkedUsagesError = true;
											return;
										}
									}
									onDelete();
									show = false;
								}}
							>
								{$i18n.t('Delete')}
							</Button>
						{/if}

						<Button kind="filled" size="md" type="submit" {loading}>
							{$i18n.t('Save')}
						</Button>
					</div>
				</form>
			</div>
		</div>
	</div>
</Modal>

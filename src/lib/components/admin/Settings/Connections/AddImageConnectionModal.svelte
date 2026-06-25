<script lang="ts">
	import { getContext, createEventDispatcher } from 'svelte';
	import Modal from '$lib/components/common/Modal.svelte';
	import Switch from '$lib/components/common/Switch.svelte';
	import SensitiveInput from '$lib/components/common/SensitiveInput.svelte';
	import SensitiveTextarea from '$lib/components/common/SensitiveTextarea.svelte';
	import Button from '$lib/components/common/Button.svelte';
	import Input from '$lib/components/common/Input.svelte';
	import Selector from '$lib/components/common/Selector.svelte';
	import XMark from '$lib/components/icons/XMark.svelte';

	const i18n = getContext('i18n');
	const dispatch = createEventDispatcher();

	export let show = false;
	export let edit = false;
	export let onSubmit: Function = () => {};
	export let onDelete: Function = () => {};

	// Connection data
	export let url: string = '';
	export let key: string = '';
	export let config: Record<string, any> = {};

	// Defaults
	let engine = config?.engine ?? 'openai';
	let name = config?.name ?? '';
	let model = config?.model ?? '';
	let size = config?.size ?? '1024x1024';
	let enable = config?.enable ?? true;
	let promptGeneration = config?.prompt_generation ?? true;

	// Azure-specific
	let azureApiVersion = config?.azure_api_version ?? '2025-04-01-preview';
	let azureDeploymentName = config?.azure_deployment_name ?? '';
	let azureQuality = config?.azure_quality ?? 'auto';
	let azureOutputFormat = config?.azure_output_format ?? 'png';
	let azureBackground = config?.azure_background ?? 'auto';

	// Vertex AI-specific
	let vertexProjectId = config?.vertex_project_id ?? '';
	let vertexLocation = config?.vertex_location ?? 'us-central1';
	let vertexServiceAccountKey = config?.vertex_service_account_key ?? '';

	// Sync from props when editing
	$: if (show && edit) {
		engine = config?.engine ?? 'openai';
		name = config?.name ?? '';
		model = config?.model ?? '';
		size = config?.size ?? '1024x1024';
		enable = config?.enable ?? true;
		promptGeneration = config?.prompt_generation ?? true;
		azureApiVersion = config?.azure_api_version ?? '2025-04-01-preview';
		azureDeploymentName = config?.azure_deployment_name ?? '';
		azureQuality = config?.azure_quality ?? 'auto';
		azureOutputFormat = config?.azure_output_format ?? 'png';
		azureBackground = config?.azure_background ?? 'auto';
		vertexProjectId = config?.vertex_project_id ?? '';
		vertexLocation = config?.vertex_location ?? 'us-central1';
		vertexServiceAccountKey = config?.vertex_service_account_key ?? '';
	}

	$: if (show && !edit) {
		url = '';
		key = '';
		engine = 'openai';
		name = '';
		model = '';
		size = '1024x1024';
		enable = true;
		promptGeneration = true;
		azureApiVersion = '2025-04-01-preview';
		azureDeploymentName = '';
		azureQuality = 'auto';
		azureOutputFormat = 'png';
		azureBackground = 'auto';
		vertexProjectId = '';
		vertexLocation = 'us-central1';
		vertexServiceAccountKey = '';
	}

	const engineOptions = [
		{ value: 'openai', label: 'OpenAI' },
		{ value: 'azure_openai', label: 'Azure OpenAI' },
		{ value: 'gemini', label: 'Gemini' },
		{ value: 'vertex_ai', label: 'Vertex AI' }
	];

	const azureQualityOptions = [
		{ value: 'auto', label: 'auto' },
		{ value: 'low', label: 'low' },
		{ value: 'medium', label: 'medium' },
		{ value: 'high', label: 'high' }
	];

	const azureFormatOptions = [
		{ value: 'png', label: 'PNG' },
		{ value: 'jpeg', label: 'JPEG' },
		{ value: 'webp', label: 'WebP' }
	];

	const azureBackgroundOptions = [
		{ value: 'auto', label: 'auto' },
		{ value: 'transparent', label: 'transparent' },
		{ value: 'opaque', label: 'opaque' }
	];

	$: urlPlaceholder =
		engine === 'openai'
			? 'https://api.openai.com/v1'
			: engine === 'azure_openai'
				? 'https://your-resource.openai.azure.com'
				: 'https://generativelanguage.googleapis.com/v1beta';

	function handleSubmit() {
		const connConfig: Record<string, any> = {
			enable,
			engine,
			name,
			model,
			size,
			prompt_generation: promptGeneration
		};

		if (engine === 'azure_openai') {
			connConfig.azure_api_version = azureApiVersion;
			connConfig.azure_deployment_name = azureDeploymentName;
			connConfig.azure_quality = azureQuality;
			connConfig.azure_output_format = azureOutputFormat;
			connConfig.azure_background = azureBackground;
		} else if (engine === 'vertex_ai') {
			connConfig.vertex_project_id = vertexProjectId;
			connConfig.vertex_location = vertexLocation;
			connConfig.vertex_service_account_key = vertexServiceAccountKey;
		}

		onSubmit({
			url: engine === 'vertex_ai' ? '' : url,
			key: engine === 'vertex_ai' ? '' : key,
			config: connConfig
		});
		show = false;
	}
</script>

<Modal size="sm" bind:show>
	<div>
		<div class="flex justify-between dark:text-gray-300 px-5 pt-4 pb-2">
			<div class="text-lg font-medium self-center">
				{edit ? $i18n.t('Edit Image Connection') : $i18n.t('Add Image Connection')}
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

		<div class="flex flex-col w-full px-5 pb-4">
			<div class="px-1">
				<!-- Image Prompt Generation -->
				<div class="flex w-full justify-between mb-2">
					<div class="self-center text-xs font-medium">{$i18n.t('Image Prompt Generation')}</div>
					<Switch bind:state={promptGeneration} />
				</div>

				<!-- Engine -->
				<div class="flex w-full justify-between items-center mb-2 gap-2">
					<div class="self-center text-xs font-medium">{$i18n.t('Engine')}</div>
					<div class="w-[220px]">
						<Selector
							value={engine}
							items={engineOptions}
							size="sm"
							searchEnabled={false}
							on:change={(e) => {
								engine = e.detail.value;
							}}
						/>
					</div>
				</div>

				<!-- Connection Name -->
				<div class="flex w-full justify-between items-center mb-2 gap-2">
					<div class="self-center text-xs font-medium shrink-0">{$i18n.t('Connection Name')}</div>
					<div class="flex-1 max-w-[220px]">
						<Input
							bind:value={name}
							placeholder={$i18n.t('e.g. DALL-E 3, GPT Image')}
							size="sm"
						/>
					</div>
				</div>

				{#if engine !== 'vertex_ai'}
					<!-- API URL -->
					<div class="my-1.5">
						<Input
							bind:value={url}
							placeholder={urlPlaceholder}
							size="sm"
						/>
					</div>

					<!-- API Key -->
					<div class="my-1.5">
						<SensitiveInput
							bind:value={key}
							placeholder={$i18n.t('API Key')}
							size="sm"
							required={false}
						/>
					</div>
				{/if}

				<!-- Model ID (OpenAI / Gemini) -->
				{#if engine === 'openai' || engine === 'gemini'}
					<div class="flex w-full justify-between items-center mb-2 mt-2 gap-2">
						<div class="self-center text-xs font-medium shrink-0">{$i18n.t('Model ID')}</div>
						<div class="flex-1 max-w-[220px]">
							<Input
								bind:value={model}
								placeholder={engine === 'openai' ? 'dall-e-3' : 'imagen-3.0-generate-002'}
								size="sm"
							/>
						</div>
					</div>
				{/if}

				<!-- Azure OpenAI specific -->
				{#if engine === 'azure_openai'}
					<div class="flex w-full justify-between items-center mb-2 mt-2 gap-2">
						<div class="self-center text-xs font-medium shrink-0">{$i18n.t('Deployment Name')}</div>
						<div class="flex-1 max-w-[220px]">
							<Input
								bind:value={azureDeploymentName}
								placeholder="gpt-image-1"
								size="sm"
							/>
						</div>
					</div>
					<div class="flex w-full justify-between items-center mb-2 gap-2">
						<div class="self-center text-xs font-medium shrink-0">{$i18n.t('API Version')}</div>
						<div class="flex-1 max-w-[220px]">
							<Input
								bind:value={azureApiVersion}
								placeholder="2025-04-01-preview"
								size="sm"
							/>
						</div>
					</div>
					<div class="flex w-full justify-between items-center mb-2 gap-2">
						<div class="self-center text-xs font-medium">{$i18n.t('Quality')}</div>
						<div class="w-[220px]">
							<Selector
								value={azureQuality}
								items={azureQualityOptions}
								size="sm"
								searchEnabled={false}
								on:change={(e) => {
									azureQuality = e.detail.value;
								}}
							/>
						</div>
					</div>
					<div class="flex w-full justify-between items-center mb-2 gap-2">
						<div class="self-center text-xs font-medium">{$i18n.t('Format')}</div>
						<div class="w-[220px]">
							<Selector
								value={azureOutputFormat}
								items={azureFormatOptions}
								size="sm"
								searchEnabled={false}
								on:change={(e) => {
									azureOutputFormat = e.detail.value;
								}}
							/>
						</div>
					</div>
					<div class="flex w-full justify-between items-center mb-2 gap-2">
						<div class="self-center text-xs font-medium">{$i18n.t('Background')}</div>
						<div class="w-[220px]">
							<Selector
								value={azureBackground}
								items={azureBackgroundOptions}
								size="sm"
								searchEnabled={false}
								on:change={(e) => {
									azureBackground = e.detail.value;
								}}
							/>
						</div>
					</div>
				{/if}

				<!-- Vertex AI specific -->
				{#if engine === 'vertex_ai'}
					<div class="my-1.5 flex gap-2">
						<div class="flex-1">
							<Input
								bind:value={vertexProjectId}
								placeholder={$i18n.t('Project ID')}
								size="sm"
							/>
						</div>
						<div class="flex-1">
							<Input
								bind:value={vertexLocation}
								placeholder={$i18n.t('Location (e.g. us-central1)')}
								size="sm"
							/>
						</div>
					</div>
					<div class="flex w-full justify-between items-center mb-2 mt-2 gap-2">
						<div class="self-center text-xs font-medium shrink-0">{$i18n.t('Model ID')}</div>
						<div class="flex-1 max-w-[220px]">
							<Input
								bind:value={model}
								placeholder="imagen-3.0-generate-002"
								size="sm"
							/>
						</div>
					</div>
					<div class="mb-2">
						<div class="text-xs font-medium mb-1">{$i18n.t('Service Account Key (JSON)')}</div>
						<SensitiveTextarea
							className="w-full rounded-lg py-1.5 px-3 text-xs bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-none resize-none font-mono"
							placeholder={'{\n  "type": "service_account",\n  ...\n}'}
							rows={3}
							bind:value={vertexServiceAccountKey}
						/>
					</div>
				{/if}

				<!-- Image Size -->
				<div class="flex w-full justify-between items-center mb-2 gap-2">
					<div class="self-center text-xs font-medium">{$i18n.t('Image Size')}</div>
					<div class="w-[220px]">
						<Input
							bind:value={size}
							placeholder="1024x1024"
							size="sm"
						/>
					</div>
				</div>

				<!-- Buttons -->
				<div class="flex justify-between pt-2">
					<div>
						{#if edit}
							<Button
								kind="text"
								size="md"
								status="error"
								on:click={() => {
									show = false;
									onDelete();
								}}
							>
								{$i18n.t('Delete')}
							</Button>
						{/if}
					</div>
					<Button kind="filled" size="md" on:click={handleSubmit}>
						{edit ? $i18n.t('Save') : $i18n.t('Add')}
					</Button>
				</div>
			</div>
		</div>
	</div>
</Modal>

<script lang="ts">
	import { getContext, onMount } from 'svelte';
	import { toast } from 'svelte-sonner';

	import Modal from '$lib/components/common/Modal.svelte';
	import Button from '$lib/components/common/Button.svelte';
	import Input from '$lib/components/common/Input.svelte';
	import SensitiveInput from '$lib/components/common/SensitiveInput.svelte';
	import SensitiveTextarea from '$lib/components/common/SensitiveTextarea.svelte';
	import Textarea from '$lib/components/common/Textarea.svelte';
	import Switch from '$lib/components/common/Switch.svelte';

	import { getEngineTypes } from '$lib/apis/extraction-engines';
	import type {
		ExtractionEngineProfile,
		ExtractionEngineProfileForm
	} from '$lib/apis/extraction-engines';
	import { models } from '$lib/stores';
	import { formatBackendError } from '$lib/utils/error';

	const i18n = getContext('i18n');

	export let show = false;
	export let engine: ExtractionEngineProfile | null = null;
	export let onSave: (data: ExtractionEngineProfileForm) => Promise<void> = async () => {};
	export let onDelete: (() => Promise<void>) | null = null;

	let name = '';
	let engineType = '';
	let config: Record<string, any> = {};

	let loading = false;
	let _initialized = false;

	// llm_vision 기본 추출 프롬프트 — 백엔드 engine-types 카탈로그에서 단일 소스로 로드.
	// placeholder(빈 값일 때 미리보기) + "기본 프롬프트 불러오기" 버튼에 사용.
	let defaultVisionPrompt = '';

	onMount(async () => {
		try {
			const types = await getEngineTypes(localStorage.token);
			defaultVisionPrompt =
				types.find((t) => t.type === 'llm_vision')?.default_config?.llm_vision_prompt ?? '';
		} catch (e) {
			// 기본 프롬프트 로드 실패는 치명적이지 않음 — 프롬프트 입력은 그대로 동작.
		}
	});

	const loadDefaultVisionPrompt = () => {
		config = { ...config, llm_vision_prompt: defaultVisionPrompt };
	};

	$: {
		if (show && !_initialized) {
			_initialized = true;
			if (engine) {
				name = engine.name;
				engineType = engine.engine_type || '';
				config = { ...(engine.config || {}) };
			} else {
				name = '';
				engineType = '';
				config = {};
			}
		}
		if (!show) {
			_initialized = false;
		}
	}

	const submitHandler = async () => {
		if (!name.trim()) {
			toast.error($i18n.t('Name is required'));
			return;
		}
		if (!engineType) {
			toast.error($i18n.t('Engine Type is required'));
			return;
		}
		loading = true;
		try {
			await onSave({
				name: name.trim(),
				engine_type: engineType,
				config
			});
			show = false;
		} catch (e: any) {
			toast.error(formatBackendError(e, $i18n) || e?.message || $i18n.t('Error'));
		} finally {
			loading = false;
		}
	};
</script>

<Modal size="md" bind:show>
	<div>
		<div class="flex justify-between dark:text-gray-100 px-5 pt-4 pb-2">
			<div class="text-lg font-medium self-center font-primary">
				{engine ? $i18n.t('Edit Extraction Engine') : $i18n.t('Add Extraction Engine')}
			</div>
			<button
				class="self-center"
				on:click={() => {
					show = false;
				}}
			>
				<svg
					xmlns="http://www.w3.org/2000/svg"
					viewBox="0 0 20 20"
					fill="currentColor"
					class="w-5 h-5"
				>
					<path
						d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z"
					/>
				</svg>
			</button>
		</div>

		<form class="px-5 pb-4 space-y-3 text-sm" on:submit|preventDefault={submitHandler}>
			<!-- Name -->
			<div>
				<div class="mb-1 text-xs font-medium">{$i18n.t('Name')}</div>
				<input
					class="w-full rounded-lg py-1.5 px-3 text-sm bg-gray-50 dark:bg-gray-850 dark:text-gray-300 outline-hidden"
					bind:value={name}
					placeholder={$i18n.t('e.g. Azure DI Prod')}
					required
				/>
			</div>

			<!-- Engine Type -->
			<div>
				<div class="flex w-full justify-between items-center">
					<div class="text-xs font-medium">{$i18n.t('Engine Type')}</div>
					<select
						class="dark:bg-gray-900 w-fit pr-8 rounded-sm px-2 text-xs bg-transparent outline-hidden text-right"
						bind:value={engineType}
					>
						<option value="">{$i18n.t('Select an engine type')}</option>
						<option value="tika">{$i18n.t('Tika')}</option>
						<option value="docling">{$i18n.t('Docling')}</option>
						<option value="document_intelligence"
							>{$i18n.t('Document Intelligence')}</option
						>
						<option value="mistral_ocr">{$i18n.t('Mistral OCR')}</option>
						<option value="document_ai">{$i18n.t('Google Cloud Document AI')}</option>
						<option value="llm_vision">{$i18n.t('LLM Vision')}</option>
					</select>
				</div>

				<div class="text-[11px] text-gray-400 dark:text-gray-500 mt-1">
					{#if engineType === 'tika'}
						{$i18n.t(
							'Apache Tika server for broad format support including legacy Office files.'
						)}
					{:else if engineType === 'docling'}
						{$i18n.t(
							'IBM Docling with structure-aware extraction. Good for tables and headings.'
						)}
					{:else if engineType === 'document_intelligence'}
						{$i18n.t(
							'Azure AI Document Intelligence. High accuracy for complex layouts and forms.'
						)}
					{:else if engineType === 'mistral_ocr'}
						{$i18n.t('Mistral OCR for PDF text extraction with vision capabilities.')}
					{:else if engineType === 'document_ai'}
						{$i18n.t('Google Cloud Document AI. Enterprise-grade OCR and document parsing.')}
					{:else if engineType === 'llm_vision'}
						{$i18n.t(
							'Send each page as an image to a vision LLM for markdown extraction, including in-place descriptions of images, diagrams, and charts. Best for scanned docs and complex layouts.'
						)}
					{/if}
				</div>

				{#if engineType === 'tika'}
					<div class="mt-1">
						<Input
							type="url"
							size="sm"
							placeholder={$i18n.t('Enter Tika Server URL')}
							bind:value={config.tika_server_url}
						/>
					</div>
				{:else if engineType === 'docling'}
					<div class="mt-1">
						<Input
							type="url"
							size="sm"
							placeholder={$i18n.t('Enter Docling Server URL')}
							bind:value={config.docling_server_url}
						/>
					</div>
				{:else if engineType === 'document_intelligence'}
					<div class="my-0.5 flex flex-col gap-2 pr-2">
						<Input
							type="url"
							size="sm"
							placeholder={$i18n.t('Enter Document Intelligence Endpoint')}
							bind:value={config.document_intelligence_endpoint}
						/>
						<SensitiveInput
							placeholder={$i18n.t('Enter Document Intelligence Key')}
							bind:value={config.document_intelligence_key}
						/>
						<div class="flex w-full justify-between items-center pt-0.5">
							<div class="text-xs font-medium">{$i18n.t('High Resolution OCR')}</div>
							<Switch bind:state={config.document_intelligence_high_resolution} />
						</div>
						<div class="text-[11px] text-gray-400 dark:text-gray-500">
							{$i18n.t(
								'Improves recognition of dense tables and small fonts (e.g. datasheets/drawings). Slower and higher cost.'
							)}
						</div>
					</div>
				{:else if engineType === 'mistral_ocr'}
					<div class="my-0.5 flex gap-2 pr-2">
						<SensitiveInput
							placeholder={$i18n.t('Enter Mistral API Key')}
							bind:value={config.mistral_ocr_api_key}
						/>
					</div>
				{:else if engineType === 'document_ai'}
					<div class="my-0.5 flex flex-col gap-2 pr-2 w-full">
						<div class="flex gap-2">
							<div class="flex-1">
								<Input
									size="sm"
									placeholder={$i18n.t('Project ID (auto-detected from key)')}
									bind:value={config.document_ai_project_id}
								/>
							</div>
							<div class="flex-1">
								<Input
									size="sm"
									placeholder={$i18n.t('Enter Location')}
									bind:value={config.document_ai_location}
								/>
							</div>
						</div>
						<div class="flex gap-2">
							<div class="flex-1">
								<Input
									size="sm"
									placeholder={$i18n.t('Enter Processor ID')}
									bind:value={config.document_ai_processor_id}
								/>
							</div>
							<div class="flex-1">
								<Input
									size="sm"
									placeholder={$i18n.t('Processor Version (optional)')}
									bind:value={config.document_ai_processor_version}
								/>
							</div>
						</div>
						<SensitiveTextarea
							className="w-full text-sm bg-transparent outline-hidden resize-y"
							rows={3}
							placeholder={$i18n.t('Service Account Key (JSON)')}
							bind:value={config.document_ai_service_account_key}
						/>
					</div>
				{:else if engineType === 'llm_vision'}
					<div class="mt-1 flex flex-col gap-3">
						<div>
							<div class="text-xs font-medium mb-1">{$i18n.t('Vision Model')}</div>
							<select
								class="w-full rounded-lg text-sm bg-gray-50 dark:bg-gray-850 dark:text-gray-300 outline-hidden py-1.5 px-2"
								bind:value={config.llm_vision_model}
							>
								<option value="">{$i18n.t('Select a model')}</option>
								{#each $models.filter((m) => !m.base_model_id && !m.preset && !(m.arena ?? false)) as model}
									<option value={model.id}>{model.name}</option>
								{/each}
							</select>
						</div>

						<div>
							<div class="flex w-full justify-between items-center mb-1">
								<div class="text-xs font-medium">{$i18n.t('Extraction Prompt')}</div>
								<button
									type="button"
									class="text-[11px] text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
									on:click={loadDefaultVisionPrompt}
								>
									{$i18n.t('Load default prompt')}
								</button>
							</div>
							<Textarea
								bind:value={config.llm_vision_prompt}
								placeholder={defaultVisionPrompt}
								rows={6}
								size="sm"
							/>
							<div class="text-[11px] text-gray-400 dark:text-gray-500 mt-1">
								{$i18n.t('Leave empty to use the default prompt, or enter a custom prompt')}
							</div>
						</div>
					</div>
				{/if}
			</div>

			<!-- Actions -->
			<div class="flex justify-between pt-2">
				<div>
					{#if engine && onDelete}
						<Button
							kind="outlined"
							size="sm"
							on:click={async () => {
								if (onDelete) {
									await onDelete();
									show = false;
								}
							}}
						>
							{$i18n.t('Delete')}
						</Button>
					{/if}
				</div>
				<div class="flex gap-2">
					<Button
						kind="outlined"
						size="sm"
						on:click={() => {
							show = false;
						}}
					>
						{$i18n.t('Cancel')}
					</Button>
					<Button kind="filled" size="sm" type="submit" disabled={loading}>
						{$i18n.t('Save')}
					</Button>
				</div>
			</div>
		</form>
	</div>
</Modal>

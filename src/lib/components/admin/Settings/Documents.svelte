<script lang="ts">
	import { toast } from 'svelte-sonner';

	import { onMount, getContext, createEventDispatcher } from 'svelte';

	const dispatch = createEventDispatcher();

	import {
		getQuerySettings,
		updateQuerySettings,
		resetVectorDB,
		getEmbeddingConfig,
		updateEmbeddingConfig,
		getRAGConfig,
		updateRAGConfig
	} from '$lib/apis/retrieval';

	import { reindexKnowledgeFiles } from '$lib/apis/knowledge';
	import { deleteAllFiles } from '$lib/apis/files';

	import {
		getDocumentProfiles,
		createDocumentProfile,
		updateDocumentProfile,
		setDefaultDocumentProfile,
		deleteDocumentProfile,
		migrateDocumentProfileToMapping
	} from '$lib/apis/document-profiles';
	import type { DocumentProfile } from '$lib/apis/document-profiles';
	import {
		getExtractionEngines,
		createExtractionEngine,
		updateExtractionEngine,
		deleteExtractionEngine
	} from '$lib/apis/extraction-engines';
	import type { ExtractionEngineProfile } from '$lib/apis/extraction-engines';


	import Button from '$lib/components/common/Button.svelte';
	import Badge from '$lib/components/common/Badge.svelte';
	import Form, { type FormItem } from '$lib/components/common/Form.svelte';
	import Input from '$lib/components/common/Input.svelte';
	import LabelBase from '$lib/components/common/LabelBase.svelte';
	import Selector from '$lib/components/common/Selector.svelte';
	import Plus from '$lib/components/icons/Plus.svelte';
	import ResetUploadDirConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';
	import ResetVectorDBConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';
	import ReindexKnowledgeFilesConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';
	import SensitiveInput from '$lib/components/common/SensitiveInput.svelte';
	import SensitiveTextarea from '$lib/components/common/SensitiveTextarea.svelte';
	import Switch from '$lib/components/common/Switch.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';

	import DocumentProfileModal from './Documents/DocumentProfileModal.svelte';
	import ExtractionEngineModal from './Documents/ExtractionEngineModal.svelte';

	import { models } from '$lib/stores';
	import { formatBackendError } from '$lib/utils/error';

	const i18n = getContext('i18n');

	let updateEmbeddingModelLoading = false;

	let showResetConfirm = false;
	let showResetUploadDirConfirm = false;
	let showReindexConfirm = false;

	// Profile state
	let documentProfiles: DocumentProfile[] = [];
	let showDocProfileModal = false;
	let editingDocProfile: DocumentProfile | null = null;

	// Extraction engine state
	let extractionEngines: ExtractionEngineProfile[] = [];
	let showEngineModal = false;
	let editingEngine: ExtractionEngineProfile | null = null;

	const ENGINE_LABELS: Record<string, string> = {
		'': 'Built-in Engine',
		tika: 'Tika',
		docling: 'Docling',
		document_intelligence: 'Document Intelligence',
		mistral_ocr: 'Mistral OCR',
		document_ai: 'Document AI',
		llm_vision: 'LLM Vision'
	};

	const loadProfiles = async () => {
		try {
			documentProfiles = await getDocumentProfiles(localStorage.token);
		} catch (e) {
			console.error('Failed to load document profiles', e);
		}
	};

	const loadEngines = async () => {
		try {
			extractionEngines = await getExtractionEngines(localStorage.token);
		} catch (e) {
			console.error('Failed to load extraction engines', e);
		}
	};

	function engineName(id: string): string {
		if (id === 'native') return $i18n.t('Built-in Engine');
		const e = extractionEngines.find((x) => x.id === id);
		return e ? e.name : id;
	}

	async function handleMigrateProfile(dpId: string) {
		if (
			!confirm(
				$i18n.t(
					'Convert this profile to per-extension mapping? Existing single-engine setup will be preserved.'
				)
			)
		) {
			return;
		}
		try {
			await migrateDocumentProfileToMapping(localStorage.token, dpId);
			toast.success($i18n.t('Profile migrated to per-extension mapping'));
			await loadProfiles();
			await loadEngines();
		} catch (err) {
			const e = err as any;
			toast.error(formatBackendError(e, $i18n) || $i18n.t('Migration failed'));
		}
	}

	async function handleSetDefaultProfile(dpId: string) {
		try {
			await setDefaultDocumentProfile(localStorage.token, dpId);
			toast.success($i18n.t('Default profile updated'));
			await loadProfiles();
		} catch (err) {
			toast.error($i18n.t(`${err}`));
		}
	}

	async function handleDeleteEngine() {
		if (!editingEngine) return;
		try {
			await deleteExtractionEngine(localStorage.token, editingEngine.id);
			toast.success($i18n.t('Engine deleted'));
			await loadEngines();
		} catch (err) {
			const e = err as any;
			toast.error(formatBackendError(e, $i18n) || $i18n.t('Failed to delete engine'));
		}
	}

	let embeddingEngine = '';
	let embeddingModel = '';
	let embeddingBatchSize = 1;
	let embeddingDimensions = 0;

	let OpenAIUrl = '';
	let OpenAIKey = '';

	let AzureOpenAIUrl = '';
	let AzureOpenAIKey = '';
	let AzureOpenAIVersion = '';

	let OllamaUrl = '';
	let OllamaKey = '';

	let GeminiKey = '';
	let VertexAIProjectId = '';
	let VertexAILocation = 'us-central1';
	let VertexAIServiceAccountKey = '';

	let documentAICredentialSource: 'global' | 'custom' = 'global';
	let vertexAIEmbeddingCredentialSource: 'global' | 'custom' = 'global';

	let querySettings = {
		template: '',
		r: 0.0,
		k: 4
	};

	let RAGConfig = null;

	$: embeddingEngineOptions = [
		{ value: '', label: $i18n.t('Default (SentenceTransformers)') },
		{ value: 'ollama', label: $i18n.t('Ollama') },
		{ value: 'openai', label: $i18n.t('OpenAI') },
		{ value: 'azure_openai', label: $i18n.t('Azure OpenAI') },
		{ value: 'gemini', label: $i18n.t('Gemini') },
		{ value: 'vertex_ai', label: $i18n.t('Vertex AI') }
	];

	$: vertexCredentialOptions = [
		{ value: 'global', label: $i18n.t('Use Global Google Cloud Key') },
		{ value: 'custom', label: $i18n.t('Use Custom Key') }
	];

	$: questionModelOptions = [
		{ value: '', label: $i18n.t('Select a model') },
		...$models
			.filter((m: any) => !m.base_model_id && !m.preset && !(m.arena ?? false))
			.map((m: any) => ({ value: m.id, label: m.name }))
	];

	$: integrationItems = (RAGConfig
		? [
				{
					id: 'gdrive',
					label: $i18n.t('Google Drive'),
					state: !!RAGConfig.ENABLE_GOOGLE_DRIVE_INTEGRATION
				},
				{
					id: 'onedrive',
					label: $i18n.t('OneDrive'),
					state: !!RAGConfig.ENABLE_ONEDRIVE_INTEGRATION
				},
				{
					id: 'sharepoint',
					label: $i18n.t('SharePoint'),
					state: !!RAGConfig.ENABLE_SHAREPOINT_INTEGRATION
				}
			]
		: []) satisfies FormItem[];

	const handleIntegrationChange = (
		event: CustomEvent<{ index: number; nextState: boolean; item: FormItem }>
	) => {
		if (!RAGConfig) return;
		const { item, nextState } = event.detail;
		switch (item.id) {
			case 'gdrive':
				RAGConfig.ENABLE_GOOGLE_DRIVE_INTEGRATION = nextState;
				break;
			case 'onedrive':
				RAGConfig.ENABLE_ONEDRIVE_INTEGRATION = nextState;
				break;
			case 'sharepoint':
				RAGConfig.ENABLE_SHAREPOINT_INTEGRATION = nextState;
				break;
		}
	};

	const handleEmbeddingEngineChange = (newEngine: string) => {
		embeddingEngine = newEngine;
		if (newEngine === 'ollama') embeddingModel = '';
		else if (newEngine === 'openai') embeddingModel = 'text-embedding-3-small';
		else if (newEngine === 'azure_openai') embeddingModel = 'text-embedding-3-small';
		else if (newEngine === 'gemini') embeddingModel = 'models/text-embedding-004';
		else if (newEngine === 'vertex_ai') embeddingModel = 'text-embedding-005';
		else if (newEngine === '') embeddingModel = 'sentence-transformers/all-MiniLM-L6-v2';
	};

	const handleVertexCredentialSourceChange = (value: string) => {
		vertexAIEmbeddingCredentialSource = value === 'custom' ? 'custom' : 'global';
		if (vertexAIEmbeddingCredentialSource === 'global') VertexAIServiceAccountKey = '';
	};

	const handleAllowedExtensionsChange = (event: CustomEvent<Event>) => {
		const target = event.detail.target as HTMLInputElement;
		RAGConfig.ALLOWED_FILE_EXTENSIONS = target.value
			.split(',')
			.map((s) => s.trim())
			.filter((s) => s.length > 0);
	};

	const handlePdfConvertExtensionsChange = (event: CustomEvent<Event>) => {
		const target = event.detail.target as HTMLInputElement;
		RAGConfig.PDF_CONVERT_EXTENSIONS = target.value
			.split(',')
			.map((s) => s.trim())
			.filter((s) => s.length > 0);
	};

	const embeddingModelUpdateHandler = async () => {
		if (embeddingEngine === '' && embeddingModel.split('/').length - 1 > 1) {
			toast.error(
				$i18n.t(
					'Model filesystem path detected. Model shortname is required for update, cannot continue.'
				)
			);
			return;
		}
		if (embeddingEngine === 'ollama' && embeddingModel === '') {
			toast.error(
				$i18n.t(
					'Model filesystem path detected. Model shortname is required for update, cannot continue.'
				)
			);
			return;
		}

		if (embeddingEngine === 'openai' && embeddingModel === '') {
			toast.error(
				$i18n.t(
					'Model filesystem path detected. Model shortname is required for update, cannot continue.'
				)
			);
			return;
		}

	if (embeddingEngine === 'openai' && (OpenAIKey === '' || OpenAIUrl === '')) {
		toast.error($i18n.t('OpenAI URL/Key required.'));
		return;
	}

		if (
			embeddingEngine === 'azure_openai' &&
			(AzureOpenAIKey === '' || AzureOpenAIUrl === '' || AzureOpenAIVersion === '')
		) {
			toast.error($i18n.t('Azure OpenAI URL/Key/Version required.'));
			return;
		}

		if (embeddingEngine === 'gemini' && GeminiKey === '') {
			toast.error($i18n.t('Gemini API Key required.'));
			return;
		}


		console.log('Update embedding model attempt:', embeddingModel);

		updateEmbeddingModelLoading = true;
		const res = await updateEmbeddingConfig(localStorage.token, {
			embedding_engine: embeddingEngine,
			embedding_model: embeddingModel,
			embedding_batch_size: embeddingBatchSize,
			embedding_dimensions: embeddingDimensions || 0,
			ollama_config: {
				key: OllamaKey,
				url: OllamaUrl
			},
			openai_config: {
				key: OpenAIKey,
				url: OpenAIUrl
			},
			azure_openai_config: {
				key: AzureOpenAIKey,
				url: AzureOpenAIUrl,
				version: AzureOpenAIVersion
			},
			gemini_config: {
				key: GeminiKey
			},
			vertex_ai_config: {
				project_id: VertexAIProjectId,
				location: VertexAILocation,
				service_account_key: VertexAIServiceAccountKey
			}
		}).catch(async (error) => {
			toast.error($i18n.t(`${error}`));
			await setEmbeddingConfig();
			return null;
		});
		updateEmbeddingModelLoading = false;

		if (res) {
			console.log('embeddingModelUpdateHandler:', res);
			if (res.status === true) {
				toast.success($i18n.t('Embedding model set to "{{embedding_model}}"', res), {
					duration: 1000 * 10
				});
			}
		}
	};

	const submitHandler = async () => {
		if (RAGConfig.CONTENT_EXTRACTION_ENGINE === 'tika' && RAGConfig.TIKA_SERVER_URL === '') {
			toast.error($i18n.t('Tika Server URL required.'));
			return;
		}
		if (RAGConfig.CONTENT_EXTRACTION_ENGINE === 'docling' && RAGConfig.DOCLING_SERVER_URL === '') {
			toast.error($i18n.t('Docling Server URL required.'));
			return;
		}

		if (
			RAGConfig.CONTENT_EXTRACTION_ENGINE === 'document_intelligence' &&
			(RAGConfig.DOCUMENT_INTELLIGENCE_ENDPOINT === '' ||
				RAGConfig.DOCUMENT_INTELLIGENCE_KEY === '')
		) {
			toast.error($i18n.t('Document Intelligence endpoint and key required.'));
			return;
		}
		if (
			RAGConfig.CONTENT_EXTRACTION_ENGINE === 'mistral_ocr' &&
			RAGConfig.MISTRAL_OCR_API_KEY === ''
		) {
			toast.error($i18n.t('Mistral OCR API Key required.'));
			return;
		}
		if (
			RAGConfig.CONTENT_EXTRACTION_ENGINE === 'document_ai' &&
			RAGConfig.DOCUMENT_AI_PROCESSOR_ID === ''
		) {
			toast.error($i18n.t('Document AI Processor ID required.'));
			return;
		}

		if (!RAGConfig.BYPASS_EMBEDDING_AND_RETRIEVAL) {
			await embeddingModelUpdateHandler();
		}

		const res = await updateRAGConfig(localStorage.token, RAGConfig);
		dispatch('save');
	};

	const setEmbeddingConfig = async () => {
		const embeddingConfig = await getEmbeddingConfig(localStorage.token);

		if (embeddingConfig) {
			embeddingEngine = embeddingConfig.embedding_engine;
			embeddingModel = embeddingConfig.embedding_model;
			embeddingBatchSize = embeddingConfig.embedding_batch_size ?? 1;
			embeddingDimensions = embeddingConfig.embedding_dimensions ?? 0;

			OpenAIKey = embeddingConfig.openai_config.key;
			OpenAIUrl = embeddingConfig.openai_config.url;

			OllamaKey = embeddingConfig.ollama_config.key;
			OllamaUrl = embeddingConfig.ollama_config.url;

			AzureOpenAIKey = embeddingConfig.azure_openai_config.key;
			AzureOpenAIUrl = embeddingConfig.azure_openai_config.url;
			AzureOpenAIVersion = embeddingConfig.azure_openai_config.version;

			GeminiKey = embeddingConfig?.gemini_config?.key ?? '';
			VertexAIProjectId = embeddingConfig?.vertex_ai_config?.project_id ?? '';
			VertexAILocation = embeddingConfig?.vertex_ai_config?.location ?? 'us-central1';
			VertexAIServiceAccountKey = embeddingConfig?.vertex_ai_config?.service_account_key ?? '';
		}
	};

	onMount(async () => {
		await setEmbeddingConfig();
		await loadProfiles();
		await loadEngines();

		RAGConfig = await getRAGConfig(localStorage.token);

		// Set credential source based on whether feature-specific key exists
		documentAICredentialSource = RAGConfig.DOCUMENT_AI_SERVICE_ACCOUNT_KEY ? 'custom' : 'global';
		vertexAIEmbeddingCredentialSource = VertexAIServiceAccountKey ? 'custom' : 'global';

		// Ensure kb_question_generation has default values
		if (!RAGConfig.kb_question_generation) {
			RAGConfig.kb_question_generation = {
				KB_QUESTION_GENERATION_ENABLED: false,
				KB_QUESTION_GENERATION_MODEL: '',
				KB_MAX_QUESTIONS_PER_CHUNK: 10,
				KB_QUESTION_VECTOR_WEIGHT: 0.5
			};
		}

	});
</script>

<ResetUploadDirConfirmDialog
	bind:show={showResetUploadDirConfirm}
	on:confirm={async () => {
		const res = await deleteAllFiles(localStorage.token).catch((error) => {
			toast.error($i18n.t(`${error}`));
			return null;
		});

		if (res) {
			toast.success($i18n.t('Success'));
		}
	}}
/>

<ResetVectorDBConfirmDialog
	bind:show={showResetConfirm}
	on:confirm={() => {
		const res = resetVectorDB(localStorage.token).catch((error) => {
			toast.error($i18n.t(`${error}`));
			return null;
		});

		if (res) {
			toast.success($i18n.t('Success'));
		}
	}}
/>

<ReindexKnowledgeFilesConfirmDialog
	bind:show={showReindexConfirm}
	on:confirm={async () => {
		const res = await reindexKnowledgeFiles(localStorage.token).catch((error) => {
			toast.error($i18n.t(`${error}`));
			return null;
		});

		if (res) {
			toast.success($i18n.t('Success'));
		}
	}}
/>

<form
	class="flex flex-col h-full justify-between space-y-3 text-sm"
	on:submit|preventDefault={() => {
		submitHandler();
	}}
>
	{#if RAGConfig}
		<div class=" space-y-2.5 overflow-y-scroll scrollbar-hidden h-full pr-1.5">
			<div>
				<!-- Extraction Engines -->
				<div class="mb-3">
					<div class="flex justify-between items-center mb-2.5">
						<div class="text-base font-medium">{$i18n.t('Extraction Engines')}</div>
						<Button
							kind="text"
							size="sm"
							on:click={() => {
								editingEngine = null;
								showEngineModal = true;
							}}
						>
							<svelte:fragment slot="prefix"><Plus className="size-3.5" /></svelte:fragment>
						</Button>
					</div>

					<hr class="border-gray-100 dark:border-gray-850 my-2" />

					<div class="flex flex-col gap-1.5">
						{#each extractionEngines as eng}
							<div
								role="button"
								tabindex="0"
								class="flex w-full items-center justify-between gap-2 px-3 py-2 rounded-lg bg-gray-50 dark:bg-gray-850 hover:bg-gray-100 dark:hover:bg-gray-800 transition text-left cursor-pointer"
								on:click={() => {
									editingEngine = eng;
									showEngineModal = true;
								}}
								on:keydown={(e) => {
									if (e.key === 'Enter' || e.key === ' ') {
										e.preventDefault();
										editingEngine = eng;
										showEngineModal = true;
									}
								}}
							>
								<div class="flex-1 min-w-0">
									<div class="text-xs font-medium truncate">{eng.name}</div>
									<div class="text-[11px] text-gray-500 mt-0.5">
										{$i18n.t(ENGINE_LABELS[eng.engine_type] || eng.engine_type || 'Native')}
									</div>
								</div>
							</div>
						{/each}
						{#if extractionEngines.length === 0}
							<div class="text-xs text-gray-400 py-2 text-center">
								{$i18n.t(
									'No extraction engines configured. Add one to enable per-extension mapping in profiles below.'
								)}
							</div>
						{/if}
					</div>
				</div>

				<!-- Document Processing Profiles -->
				<div class="mb-3">
					<div class="flex justify-between items-center mb-2.5">
						<div class="text-base font-medium">{$i18n.t('Document Processing Profiles')}</div>
						<Button
							kind="text"
							size="sm"
							on:click={() => {
								editingDocProfile = null;
								showDocProfileModal = true;
							}}
						>
							<svelte:fragment slot="prefix"><Plus className="size-3.5" /></svelte:fragment>
						</Button>
					</div>

					<hr class="border-gray-100 dark:border-gray-850 my-2" />

					<div class="flex flex-col gap-1.5">
						{#each documentProfiles as dp}
							<div
								role="button"
								tabindex="0"
								class="flex w-full items-center justify-between gap-2 px-3 py-2 rounded-lg bg-gray-50 dark:bg-gray-850 hover:bg-gray-100 dark:hover:bg-gray-800 transition text-left cursor-pointer"
								on:click={() => {
									editingDocProfile = dp;
									showDocProfileModal = true;
								}}
								on:keydown={(e) => {
									if (e.key === 'Enter' || e.key === ' ') {
										e.preventDefault();
										editingDocProfile = dp;
										showDocProfileModal = true;
									}
								}}
							>
								<div class="flex-1 min-w-0">
									<div class="flex items-center gap-1.5">
										<span class="text-xs font-medium truncate">{dp.name}</span>
										{#if dp.is_default}
											<Badge status="info" size="sm">{$i18n.t('Default')}</Badge>
										{/if}
										{#if (!dp.extension_engine_map || Object.keys(dp.extension_engine_map).length === 0) && dp.content_extraction_engine}
											<Badge status="warning" size="sm">{$i18n.t('Legacy')}</Badge>
										{/if}
									</div>
									{#if dp.extension_engine_map && Object.keys(dp.extension_engine_map).length > 0}
										<div class="text-[11px] text-gray-500 mt-0.5 truncate">
											{$i18n.t('Chunk')}: {dp.chunk_size} ·
											{Object.entries(dp.extension_engine_map)
												.slice(0, 4)
												.map(([ext, eid]) => `${ext} → ${engineName(eid)}`)
												.join(', ')}{Object.keys(dp.extension_engine_map).length > 4
												? ` +${Object.keys(dp.extension_engine_map).length - 4}`
												: ''}
										</div>
									{:else if dp.content_extraction_engine}
										<div class="text-[11px] text-gray-500 mt-0.5">
											{$i18n.t(
												ENGINE_LABELS[dp.content_extraction_engine] ||
													dp.content_extraction_engine
											)} · {$i18n.t('Chunk')}: {dp.chunk_size}
										</div>
									{:else}
										<div class="text-[11px] text-gray-500 mt-0.5">
											{$i18n.t('Built-in only')} · {$i18n.t('Chunk')}: {dp.chunk_size}
										</div>
									{/if}
								</div>
								<div class="shrink-0 flex gap-1.5">
									{#if (!dp.extension_engine_map || Object.keys(dp.extension_engine_map).length === 0) && dp.content_extraction_engine}
										<Button
											kind="outlined"
											size="sm"
											on:click={(e) => {
												e.stopPropagation();
												handleMigrateProfile(dp.id);
											}}
										>
											{$i18n.t('Convert to mapping')}
										</Button>
									{/if}
									{#if !dp.is_default}
										<Button
											kind="outlined"
											size="sm"
											on:click={(e) => {
												e.stopPropagation();
												handleSetDefaultProfile(dp.id);
											}}
										>
											{$i18n.t('Set as Default')}
										</Button>
									{/if}
								</div>
							</div>
						{/each}
						{#if documentProfiles.length === 0}
							<div class="text-xs text-gray-400 py-2 text-center">
								{$i18n.t('No profiles configured')}
							</div>
						{/if}
					</div>
				</div>

				<!-- General Section -->
				<div class="mb-3">
					<div class=" mb-2.5 text-base font-medium">{$i18n.t('General')}</div>

					<hr class=" border-gray-100 dark:border-gray-850 my-2" />

					<div class="pr-2">
						<LabelBase
							label={$i18n.t('Bypass Embedding and Retrieval')}
							caption={RAGConfig.BYPASS_EMBEDDING_AND_RETRIEVAL
								? $i18n.t(
										'Inject the entire content as context for comprehensive processing, this is recommended for complex queries.'
									)
								: $i18n.t(
										'Default to segmented retrieval for focused and relevant content extraction, this is recommended for most cases.'
									)}
							size="md"
						>
							<svelte:fragment slot="right">
								<Switch bind:state={RAGConfig.BYPASS_EMBEDDING_AND_RETRIEVAL} />
							</svelte:fragment>
						</LabelBase>
					</div>
				</div>

				{#if !RAGConfig.BYPASS_EMBEDDING_AND_RETRIEVAL}
					<!-- Embedding Section -->
					<div class="mb-3">
						<div class=" mb-2.5 text-base font-medium">{$i18n.t('Embedding')}</div>

						<hr class=" border-gray-100 dark:border-gray-850 my-2" />

						<div class="flex flex-col gap-3 pr-2">
							<LabelBase label={$i18n.t('Embedding Model Engine')} size="md">
								<svelte:fragment slot="right">
									<div class="min-w-[14rem]">
										<Selector
											value={embeddingEngine}
											items={embeddingEngineOptions}
											size="sm"
											searchEnabled={false}
											on:change={(event) => handleEmbeddingEngineChange(event.detail.value)}
										/>
									</div>
								</svelte:fragment>
							</LabelBase>

							{#if embeddingEngine === 'openai'}
								<div class="flex gap-2">
									<div class="flex-1">
										<Input
											bind:value={OpenAIUrl}
											placeholder={$i18n.t('API Base URL')}
											size="md"
										/>
									</div>
									<div class="flex-1">
										<SensitiveInput
											placeholder={$i18n.t('API Key')}
											bind:value={OpenAIKey}
										/>
									</div>
								</div>
							{:else if embeddingEngine === 'ollama'}
								<div class="flex gap-2">
									<div class="flex-1">
										<Input
											bind:value={OllamaUrl}
											placeholder={$i18n.t('API Base URL')}
											size="md"
										/>
									</div>
									<div class="flex-1">
										<SensitiveInput
											placeholder={$i18n.t('API Key')}
											bind:value={OllamaKey}
											required={false}
										/>
									</div>
								</div>
							{:else if embeddingEngine === 'azure_openai'}
								<div class="flex flex-col gap-2">
									<div class="flex gap-2">
										<div class="flex-1">
											<Input
												bind:value={AzureOpenAIUrl}
												placeholder={$i18n.t('API Base URL')}
												size="md"
											/>
										</div>
										<div class="flex-1">
											<SensitiveInput
												placeholder={$i18n.t('API Key')}
												bind:value={AzureOpenAIKey}
											/>
										</div>
									</div>
									<Input
										bind:value={AzureOpenAIVersion}
										placeholder={$i18n.t('Version')}
										size="md"
									/>
								</div>
							{:else if embeddingEngine === 'gemini'}
								<SensitiveInput
									placeholder={$i18n.t('Enter Gemini API Key')}
									bind:value={GeminiKey}
								/>
							{:else if embeddingEngine === 'vertex_ai'}
								<div class="flex flex-col gap-2">
									<div class="flex gap-2">
										<div class="flex-1">
											<Input
												bind:value={VertexAIProjectId}
												placeholder={$i18n.t('Project ID (auto-detected from key)')}
												size="md"
											/>
										</div>
										<div class="flex-1">
											<Input
												bind:value={VertexAILocation}
												placeholder={$i18n.t('Enter Location')}
												size="md"
											/>
										</div>
									</div>
									<LabelBase label={$i18n.t('Authentication')} size="md">
										<svelte:fragment slot="right">
											<div class="min-w-[14rem]">
												<Selector
													value={vertexAIEmbeddingCredentialSource}
													items={vertexCredentialOptions}
													size="sm"
													searchEnabled={false}
													on:change={(event) =>
														handleVertexCredentialSourceChange(event.detail.value)}
												/>
											</div>
										</svelte:fragment>
									</LabelBase>
									{#if vertexAIEmbeddingCredentialSource === 'custom'}
										<SensitiveTextarea
											className="w-full text-sm bg-transparent outline-hidden resize-y"
											rows={3}
											placeholder={$i18n.t('Service Account Key (JSON)')}
											bind:value={VertexAIServiceAccountKey}
										/>
									{/if}
								</div>
							{/if}

							<Input
								bind:value={embeddingModel}
								label={$i18n.t('Embedding Model')}
								caption={$i18n.t(
									'Warning: If you update or change your embedding model, you will need to re-import all documents.'
								)}
								placeholder={$i18n.t('Set embedding model')}
								size="md"
							/>

							<div class="grid grid-cols-2 gap-3">
								<Input
									bind:value={embeddingBatchSize}
									label={$i18n.t('Embedding Batch Size')}
									type="number"
									size="md"
									min="1"
									max="16000"
									step="1"
								/>
								<Input
									bind:value={embeddingDimensions}
									label={`${$i18n.t('Embedding Dimensions')} (${$i18n.t('0 = auto')})`}
									type="number"
									placeholder="0"
									size="md"
									min="0"
									max="4096"
									step="1"
								/>
							</div>
						</div>
					</div>
				{/if}

				<!-- Files Section -->
				<div class="mb-3">
					<div class=" mb-2.5 text-base font-medium">{$i18n.t('Files')}</div>

					<hr class=" border-gray-100 dark:border-gray-850 my-2" />

					<div class="flex flex-col gap-3 pr-2">
						<div class="grid grid-cols-2 gap-3">
							<Input
								bind:value={RAGConfig.FILE_MAX_SIZE}
								label={$i18n.t('Max Upload Size')}
								caption={$i18n.t(
									'The maximum file size in MB. If the file size exceeds this limit, the file will not be uploaded.'
								)}
								placeholder={$i18n.t('Leave empty for unlimited')}
								type="number"
								size="md"
								min="0"
								autocomplete="off"
							/>
							<Input
								bind:value={RAGConfig.FILE_MAX_COUNT}
								label={$i18n.t('Max Upload Count')}
								caption={$i18n.t(
									'The maximum number of files that can be used at once in chat. If the number of files exceeds this limit, the files will not be uploaded.'
								)}
								placeholder={$i18n.t('Leave empty for unlimited')}
								type="number"
								size="md"
								min="0"
								autocomplete="off"
							/>
						</div>

						<Input
							value={(RAGConfig.ALLOWED_FILE_EXTENSIONS ?? []).join(', ')}
							label={$i18n.t('Allowed File Extensions')}
							caption={$i18n.t(
								'Only allow uploading files with these extensions. Leave empty to allow all file types.'
							)}
							placeholder={$i18n.t('e.g. pdf, docx, txt, csv')}
							size="md"
							on:change={handleAllowedExtensionsChange}
						/>

						<Input
							value={(RAGConfig.PDF_CONVERT_EXTENSIONS ?? []).join(', ')}
							label={$i18n.t('PDF Convert Extensions')}
							caption={$i18n.t(
								'File extensions to automatically convert to PDF using LibreOffice before processing. Leave empty to disable conversion.'
							)}
							placeholder={$i18n.t('e.g. pptx, docx, xlsx')}
							size="md"
							on:change={handlePdfConvertExtensionsChange}
						/>
					</div>
				</div>

				{#if !RAGConfig.BYPASS_EMBEDDING_AND_RETRIEVAL}
					<!-- Question Generation Section -->
					<div class="mb-3">
						<div class=" mb-2.5 text-base font-medium">{$i18n.t('Question Generation')}</div>

						<hr class=" border-gray-100 dark:border-gray-850 my-2" />

						<div class="flex flex-col gap-3 pr-2">
							<LabelBase
								label={$i18n.t('Enable Question Generation')}
								caption={$i18n.t(
									'Generate sample questions from document chunks using LLM for improved retrieval accuracy'
								)}
								size="md"
							>
								<svelte:fragment slot="right">
									<Switch
										bind:state={RAGConfig.kb_question_generation.KB_QUESTION_GENERATION_ENABLED}
									/>
								</svelte:fragment>
							</LabelBase>

							{#if RAGConfig.kb_question_generation?.KB_QUESTION_GENERATION_ENABLED}
								<LabelBase label={$i18n.t('Question Generation Model')} size="md">
									<svelte:fragment slot="right">
										<div class="min-w-[14rem]">
											<Selector
												value={RAGConfig.kb_question_generation.KB_QUESTION_GENERATION_MODEL}
												items={questionModelOptions}
												placeholder={$i18n.t('Select a model')}
												size="sm"
												on:change={(event) => {
													RAGConfig.kb_question_generation.KB_QUESTION_GENERATION_MODEL =
														event.detail.value;
												}}
											/>
										</div>
									</svelte:fragment>
								</LabelBase>

								<div class="grid grid-cols-2 gap-3">
									<Input
										bind:value={RAGConfig.kb_question_generation.KB_MAX_QUESTIONS_PER_CHUNK}
										label={$i18n.t('Max Questions per Chunk')}
										caption={$i18n.t(
											'Maximum number of sample questions to generate per chunk'
										)}
										type="number"
										placeholder="10"
										size="md"
										min="1"
										max="20"
										autocomplete="off"
									/>
									<Input
										bind:value={RAGConfig.kb_question_generation.KB_QUESTION_VECTOR_WEIGHT}
										label={$i18n.t('Question Vector Weight')}
										caption={$i18n.t(
											'Relative weight of question vector vs content vector (0.0-1.0). 0.5 means equal weight, higher values prioritize question matching.'
										)}
										type="number"
										placeholder="0.5"
										size="md"
										step="0.05"
										min="0.0"
										max="1.0"
										autocomplete="off"
									/>
								</div>
							{/if}
						</div>
					</div>
				{/if}

				<!-- Integration Section -->
				<div class="mb-3">
					<div class=" mb-2.5 text-base font-medium">{$i18n.t('Integration')}</div>

					<hr class=" border-gray-100 dark:border-gray-850 my-2" />

					<div class="pr-2">
						<Form items={integrationItems} on:change={handleIntegrationChange} />
					</div>
				</div>

				<!-- Danger Zone Section -->
				<div class="mb-3">
					<div class=" mb-2.5 text-base font-medium">{$i18n.t('Danger Zone')}</div>

					<hr class=" border-gray-100 dark:border-gray-850 my-2" />

					<div class="flex flex-col gap-2.5 pr-2">
						<LabelBase label={$i18n.t('Reset Upload Directory')} size="md">
							<svelte:fragment slot="right">
								<Button
									kind="outlined"
									size="sm"
									status="error"
									type="button"
									on:click={() => {
										showResetUploadDirConfirm = true;
									}}
								>
									{$i18n.t('Reset')}
								</Button>
							</svelte:fragment>
						</LabelBase>

						<LabelBase label={$i18n.t('Reset Vector Storage/Knowledge')} size="md">
							<svelte:fragment slot="right">
								<Button
									kind="outlined"
									size="sm"
									status="error"
									type="button"
									on:click={() => {
										showResetConfirm = true;
									}}
								>
									{$i18n.t('Reset')}
								</Button>
							</svelte:fragment>
						</LabelBase>

						<LabelBase label={$i18n.t('Reindex Knowledge Base Vectors')} size="md">
							<svelte:fragment slot="right">
								<Button
									kind="outlined"
									size="sm"
									type="button"
									on:click={() => {
										showReindexConfirm = true;
									}}
								>
									{$i18n.t('Reindex')}
								</Button>
							</svelte:fragment>
						</LabelBase>
					</div>
				</div>
			</div>
		</div>
		<div class="flex justify-end pt-3 text-sm font-medium">
			<Button kind="filled" size="md" type="submit">
				{$i18n.t('Save')}
			</Button>
		</div>
	{:else}
		<div class="flex items-center justify-center h-full">
			<Spinner />
		</div>
	{/if}
</form>

<DocumentProfileModal
	bind:show={showDocProfileModal}
	profile={editingDocProfile}
	engines={extractionEngines}
	onSave={async (data) => {
		if (editingDocProfile) {
			await updateDocumentProfile(localStorage.token, editingDocProfile.id, data);
			toast.success($i18n.t('Profile updated'));
		} else {
			await createDocumentProfile(localStorage.token, data);
			toast.success($i18n.t('Profile created'));
		}
		await loadProfiles();
	}}
	onDelete={editingDocProfile && !editingDocProfile.is_default
		? async () => {
				if (editingDocProfile) {
					await deleteDocumentProfile(localStorage.token, editingDocProfile.id);
					toast.success($i18n.t('Profile deleted'));
					await loadProfiles();
				}
			}
		: null}
/>

<ExtractionEngineModal
	bind:show={showEngineModal}
	engine={editingEngine}
	onSave={async (data) => {
		if (editingEngine) {
			await updateExtractionEngine(localStorage.token, editingEngine.id, data);
			toast.success($i18n.t('Engine updated'));
		} else {
			await createExtractionEngine(localStorage.token, data);
			toast.success($i18n.t('Engine created'));
		}
		await loadEngines();
	}}
	onDelete={editingEngine ? handleDeleteEngine : null}
/>

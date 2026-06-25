<script lang="ts">
	import { onMount, getContext } from 'svelte';
	const i18n = getContext('i18n');

	import Modal from '$lib/components/common/Modal.svelte';
	import Switch from '$lib/components/common/Switch.svelte';
	import { getSearchEngineConfig, type SearchEngineConfig } from '$lib/apis/retrieval';
	import { getRAGConfig } from '$lib/apis/retrieval';
	import { getDocumentProfileList, type DocumentProfile } from '$lib/apis/document-profiles';
	import { models } from '$lib/stores';

	export let show = false;
	export let searchSettings: Record<string, any> = {};
	export let onSave: (settings: Record<string, any> | null) => void = () => {};

	// Local form state. number 입력은 Svelte가 number|null로 강제 변환하므로 union 타입.
	let topK: string | number | null = '';
	let rerankerTopK: string | number | null = '';
	let rerankerThreshold: number | null = null;
	let enableQuestionGeneration: boolean | null = null;
	let questionGenerationModel = '';
	let maxQuestionsPerChunk: string | number | null = '';
	let questionVectorWeight: string | number | null = '';
	let enableFileSummary: boolean | null = null;
	let fileSummaryModel = '';
	// 심층 요약 모드: 'off' | 'on_demand'(질의 시 캐시) | 'ingest'(업로드 시 즉시)
	let deepSummaryMode = 'on_demand';

	// Global defaults for placeholders
	let globalTopK = 10;
	let globalRerankerTopK = 3;
	let globalRerankerThreshold = 0.0;
	let globalEnableQuestionGeneration = false;
	let globalMaxQuestionsPerChunk = 10;
	let globalQuestionVectorWeight = 0.5;

	// Whether to show reranker section
	let showRerankerSection = false;

	// Profile selectors
	let documentProfileId = '';
	let documentProfiles: DocumentProfile[] = [];

	let loading = true;

	// Available models (non-preset, non-arena)
	$: availableModels = ($models ?? []).filter((m: any) => !m?.preset && !(m?.arena ?? false));

	// Switch UI state (regular variables, NOT $:-derived — bind:state에 derived 쓰면 write-back 버그)
	let enableQuestionGenerationState = false;
	let enableFileSummaryState = true;

	// Computed: effective question generation state (섹션 내부 조건부 렌더링용)
	$: effectiveQuestionGeneration = enableQuestionGenerationState;

	function syncFromSettings() {
		topK = searchSettings?.top_k != null ? String(searchSettings.top_k) : '';
		rerankerTopK = searchSettings?.reranker_top_k != null ? String(searchSettings.reranker_top_k) : '';
		rerankerThreshold = searchSettings?.reranker_threshold ?? null;
		enableQuestionGeneration = searchSettings?.enable_question_generation ?? null;
		enableQuestionGenerationState = enableQuestionGeneration ?? globalEnableQuestionGeneration;
		questionGenerationModel = searchSettings?.question_generation_model ?? '';
		maxQuestionsPerChunk = searchSettings?.max_questions_per_chunk != null ? String(searchSettings.max_questions_per_chunk) : '';
		questionVectorWeight = searchSettings?.question_vector_weight != null ? String(searchSettings.question_vector_weight) : '';
		enableFileSummary = searchSettings?.enable_file_summary ?? null;
		enableFileSummaryState = enableFileSummary ?? true;
		fileSummaryModel = searchSettings?.file_summary_model ?? '';
		deepSummaryMode = searchSettings?.deep_summary_mode ?? 'on_demand';
		documentProfileId = searchSettings?.document_profile_id ?? '';
	}

	// When modal opens, sync from prop
	$: if (show) {
		syncFromSettings();
	}

	// type="number" input은 Svelte가 number/null로 강제 변환하므로 .trim()을 직접 못 씀.
	// string·number 모두 허용되는 안전한 빈값 체크.
	const isFilled = (v: unknown): boolean => {
		if (v === null || v === undefined) return false;
		if (typeof v === 'number') return !Number.isNaN(v);
		return String(v).trim() !== '';
	};

	const saveHandler = () => {
		const settings: Record<string, any> = {};
		if (isFilled(topK)) settings.top_k = Number(topK);
		if (isFilled(rerankerTopK)) settings.reranker_top_k = Number(rerankerTopK);
		if (rerankerThreshold !== null) settings.reranker_threshold = Number(rerankerThreshold);
		if (enableQuestionGeneration !== null)
			settings.enable_question_generation = enableQuestionGeneration;
		if (questionGenerationModel) settings.question_generation_model = questionGenerationModel;
		if (isFilled(maxQuestionsPerChunk))
			settings.max_questions_per_chunk = Number(maxQuestionsPerChunk);
		if (isFilled(questionVectorWeight))
			settings.question_vector_weight = Number(questionVectorWeight);
		if (enableFileSummary !== null) settings.enable_file_summary = enableFileSummary;
		if (fileSummaryModel) settings.file_summary_model = fileSummaryModel;
		if (deepSummaryMode) settings.deep_summary_mode = deepSummaryMode;
		if (documentProfileId) settings.document_profile_id = documentProfileId;

		onSave(Object.keys(settings).length > 0 ? settings : null);
		show = false;
	};

	onMount(async () => {
		try {
			const searchEngineConfig = await getSearchEngineConfig(localStorage.token);
			if (searchEngineConfig) {
				globalTopK = searchEngineConfig.top_k ?? 10;
				globalRerankerTopK = searchEngineConfig.reranker_top_k ?? 3;
				globalRerankerThreshold = searchEngineConfig.reranker_threshold ?? 0.0;

				showRerankerSection =
					searchEngineConfig.engine_type === 'azure_search' ||
					(searchEngineConfig.reranker_type !== '' &&
						searchEngineConfig.reranker_type !== null &&
						searchEngineConfig.reranker_type !== undefined);
			}
		} catch (e) {
			console.error('Failed to load search engine config', e);
		}

		try {
			documentProfiles = await getDocumentProfileList(localStorage.token);
		} catch (e) {
			console.error('Failed to load profiles', e);
		}

		try {
			const ragConfig = await getRAGConfig(localStorage.token);
			if (ragConfig?.kb_question_generation) {
				globalEnableQuestionGeneration =
					ragConfig.kb_question_generation.KB_QUESTION_GENERATION_ENABLED ?? false;
				globalMaxQuestionsPerChunk =
					ragConfig.kb_question_generation.KB_MAX_QUESTIONS_PER_CHUNK ?? 10;
				globalQuestionVectorWeight =
					ragConfig.kb_question_generation.KB_QUESTION_VECTOR_WEIGHT ?? 0.5;
			}
			// Global defaults가 로드된 후 switch 상태 재동기화 (KB 저장값 없을 때 전역값 따라감)
			if (enableQuestionGeneration === null) {
				enableQuestionGenerationState = globalEnableQuestionGeneration;
			}
		} catch (e) {
			console.error('Failed to load RAG config', e);
		}

		loading = false;
	});
</script>

<Modal size="sm" bind:show>
	<div>
		<!-- Header -->
		<div class="flex justify-between dark:text-gray-100 px-5 pt-3 pb-1">
			<div class="text-lg font-medium self-center font-primary">
				{$i18n.t('Search Settings')}
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

		<!-- Body -->
		<div class="w-full px-5 pb-3 dark:text-white">
			{#if loading}
				<div class="flex justify-center py-4">
					<svg
						class="size-5 animate-spin"
						viewBox="0 0 24 24"
						fill="none"
						xmlns="http://www.w3.org/2000/svg"
					>
						<circle
							class="opacity-25"
							cx="12"
							cy="12"
							r="10"
							stroke="currentColor"
							stroke-width="4"
						/>
						<path
							class="opacity-75"
							fill="currentColor"
							d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
						/>
					</svg>
				</div>
			{:else}
				<!-- Document Processing Profile -->
				{#if documentProfiles.length > 0}
					<div class="mb-3">
						<div class="text-sm font-medium mb-2">{$i18n.t('Document Processing')}</div>
						<select
							class="w-full rounded-lg text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden py-1.5 px-2"
							bind:value={documentProfileId}
						>
							<option value="">{$i18n.t('Use Default')} ({documentProfiles.find(p => p.is_default)?.name ?? 'Default'})</option>
							{#each documentProfiles.filter(p => !p.is_default) as p}
								<option value={p.id}>{p.name}</option>
							{/each}
						</select>
					</div>
				{/if}

				<!-- File Summary section -->
				<div class="mb-3">
					<div class="text-sm font-medium mb-2">{$i18n.t('File Summary')}</div>

					<div class="mb-2.5 flex w-full justify-between items-center">
						<div class="self-center text-xs font-medium">
							{$i18n.t('Enable File Summary')}
						</div>
						<Switch
							bind:state={enableFileSummaryState}
							on:change={(e) => {
								enableFileSummary = e.detail ? true : false;
							}}
						/>
					</div>

					{#if enableFileSummaryState}
						<div class="mb-2.5">
							<div class="self-center text-xs font-medium mb-1">{$i18n.t('Summary Model')}</div>
							<select
								class="w-full rounded-lg text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden py-1.5 px-2"
								bind:value={fileSummaryModel}
							>
								<option value="">{$i18n.t('Use Default (Task Model)')}</option>
								{#each availableModels as m}
									<option value={m.id}>{m.name}</option>
								{/each}
							</select>
						</div>
					{/if}

					<!-- Deep Summary mode -->
					<div class="mt-2.5">
						<div class="self-center text-xs font-medium mb-1">{$i18n.t('Deep Summary')}</div>
						<select
							class="w-full rounded-lg text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden py-1.5 px-2"
							bind:value={deepSummaryMode}
						>
							<option value="on_demand">{$i18n.t('Generate on query (cached)')}</option>
							<option value="ingest">{$i18n.t('Generate on upload (precompute)')}</option>
							<option value="off">{$i18n.t('Disabled')}</option>
						</select>
						<div class="text-xs text-gray-500 dark:text-gray-400 mt-1">
							{$i18n.t('Deep summary uses the full document (map-reduce), not just top chunks.')}
						</div>
					</div>
				</div>

				<!-- Search section -->
				<div class="mb-3">
					<div class="text-sm font-medium mb-2">{$i18n.t('Search')}</div>

					<div class="mb-2.5 flex w-full justify-between items-center">
						<div class="self-center text-xs font-medium">{$i18n.t('Top K')}</div>
						<input
							type="number"
							class="w-20 rounded-lg text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden text-center py-1"
							min="1"
							max="100"
							placeholder={`${globalTopK}`}
							bind:value={topK}
						/>
					</div>
				</div>

				<!-- Reranker section -->
				{#if showRerankerSection}
					<div class="mb-3">
						<div class="text-sm font-medium mb-2">{$i18n.t('Reranker')}</div>

						<div class="mb-2.5 flex w-full justify-between items-center">
							<div class="self-center text-xs font-medium">{$i18n.t('Reranker Top K')}</div>
							<input
								type="number"
								class="w-20 rounded-lg text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden text-center py-1"
								min="1"
								max="50"
								placeholder={`${globalRerankerTopK}`}
								bind:value={rerankerTopK}
							/>
						</div>

						<div class="mb-2.5 flex w-full justify-between items-center">
							<div class="self-center text-xs font-medium">
								{$i18n.t('Reranker Threshold')}
							</div>
							<div class="flex items-center gap-2">
								<input
									type="range"
									class="w-24"
									min="0"
									max="1"
									step="0.01"
									value={rerankerThreshold ?? globalRerankerThreshold}
									on:input={(e) => {
										rerankerThreshold = parseFloat(e.target.value);
									}}
								/>
								<span class="text-xs text-gray-500 w-8 text-right">
									{rerankerThreshold !== null
										? rerankerThreshold.toFixed(2)
										: globalRerankerThreshold.toFixed(2)}
								</span>
							</div>
						</div>
					</div>
				{/if}

				<!-- Question Generation section -->
				<div class="mb-3">
					<div class="text-sm font-medium mb-2">{$i18n.t('Question Generation')}</div>

					<div class="mb-2.5 flex w-full justify-between items-center">
						<div class="self-center text-xs font-medium">
							{$i18n.t('Enable Question Generation')}
						</div>
						<Switch
							bind:state={enableQuestionGenerationState}
							on:change={(e) => {
								enableQuestionGeneration = e.detail ? true : false;
							}}
						/>
					</div>

					{#if effectiveQuestionGeneration}
						<div class="mb-2.5">
							<div class="self-center text-xs font-medium mb-1">{$i18n.t('Question Generation Model')}</div>
							<select
								class="w-full rounded-lg text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden py-1.5 px-2"
								bind:value={questionGenerationModel}
							>
								<option value="">{$i18n.t('Use Default (Global Setting)')}</option>
								{#each availableModels as m}
									<option value={m.id}>{m.name}</option>
								{/each}
							</select>
						</div>

						<div class="mb-2.5 flex w-full justify-between items-center">
							<div class="self-center text-xs font-medium">
								{$i18n.t('Max Questions per Chunk')}
							</div>
							<input
								type="number"
								class="w-20 rounded-lg text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden text-center py-1"
								min="1"
								max="50"
								placeholder={`${globalMaxQuestionsPerChunk}`}
								bind:value={maxQuestionsPerChunk}
							/>
						</div>

						<div class="mb-2.5 flex w-full justify-between items-center">
							<div class="self-center text-xs font-medium">
								{$i18n.t('Question Vector Weight')}
							</div>
							<div class="flex items-center gap-2">
								<input
									type="range"
									class="w-24"
									min="0"
									max="1"
									step="0.01"
									value={questionVectorWeight !== '' ? Number(questionVectorWeight) : globalQuestionVectorWeight}
									on:input={(e) => {
										questionVectorWeight = e.target.value;
									}}
								/>
								<span class="text-xs text-gray-500 w-8 text-right">
									{questionVectorWeight !== '' ? Number(questionVectorWeight).toFixed(2) : globalQuestionVectorWeight.toFixed(2)}
								</span>
							</div>
						</div>
					{/if}
				</div>
			{/if}
		</div>

		<!-- Info text -->
		<div class="text-xs text-gray-500 dark:text-gray-400 px-5 pb-3">
			{$i18n.t('Leave empty to use global admin settings.')}
		</div>

		<!-- Footer -->
		<div class="flex justify-end gap-2 px-5 pb-4">
			<button
				class="px-3 py-1 text-sm rounded-lg bg-gray-100 hover:bg-gray-200 dark:bg-gray-800 dark:hover:bg-gray-700 transition"
				on:click={() => {
					show = false;
				}}
			>
				{$i18n.t('Cancel')}
			</button>
			<button
				class="px-3 py-1 text-sm rounded-lg bg-gray-800 hover:bg-gray-700 text-white dark:bg-gray-200 dark:hover:bg-gray-300 dark:text-gray-900 transition"
				on:click={saveHandler}
			>
				{$i18n.t('Save')}
			</button>
		</div>
	</div>
</Modal>

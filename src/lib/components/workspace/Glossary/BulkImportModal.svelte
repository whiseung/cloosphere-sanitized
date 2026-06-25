<script lang="ts">
	import { getContext, createEventDispatcher } from 'svelte';
	import { toast } from 'svelte-sonner';

	import Modal from '$lib/components/common/Modal.svelte';
	import Button from '$lib/components/common/Button.svelte';
	import Checkbox from '$lib/components/common/Checkbox.svelte';
	import Selector from '$lib/components/common/Selector.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import { formatBackendError } from '$lib/utils/error';

	import {
		previewGlossaryImport,
		commitGlossaryImport,
		llmSuggestGlossaryImport,
		type GlossaryImportPreview,
		type GlossaryImportLLMRule,
		type GlossaryImportLLMSuggestResult
	} from '$lib/apis/glossary';

	const i18n: any = getContext('i18n');
	const dispatch = createEventDispatcher();

	export let show = false;
	export let glossaryId: string = '';
	export let initialFile: File | null = null;
	export let modelId: string = '';

	type Stage = 'select' | 'preview' | 'committing';

	let stage: Stage = 'select';
	let selectedFile: File | null = null;
	let isDragging = false;
	let busy = false;
	let preview: GlossaryImportPreview | null = null;
	let mapping: Record<string, string> = {};
	let autoClassify = false;
	let errorMessage = '';

	// LLM-aided rule (옵션). 있으면 commit 시 mapping 무시.
	let llmSuggestion: GlossaryImportLLMSuggestResult | null = null;
	let llmBusy = false;
	let useLlmRule = false;

	const ACCEPT = '.xlsx,.csv,.md,.markdown';

	$: fieldOptions = [
		{ value: 'term', label: $i18n.t('Term (primary)') },
		{ value: 'synonyms', label: $i18n.t('Synonyms (comma-separated)') },
		{ value: 'description', label: $i18n.t('Description') },
		{ value: 'example', label: $i18n.t('Example') },
		{ value: 'category', label: $i18n.t('Category') },
		{ value: 'skip', label: $i18n.t('Skip this column') }
	];

	const reset = () => {
		stage = 'select';
		selectedFile = null;
		preview = null;
		mapping = {};
		autoClassify = false;
		busy = false;
		errorMessage = '';
		llmSuggestion = null;
		llmBusy = false;
		useLlmRule = false;
	};

	const closeModal = () => {
		reset();
		show = false;
	};

	const onFilesPicked = async (files: FileList | null | undefined) => {
		if (!files || files.length === 0) return;
		const file = files[0];
		const name = file.name.toLowerCase();
		if (
			!name.endsWith('.xlsx') &&
			!name.endsWith('.csv') &&
			!name.endsWith('.md') &&
			!name.endsWith('.markdown')
		) {
			toast.error($i18n.t('Unsupported file format. Use .xlsx, .csv, or .md.'));
			return;
		}
		selectedFile = file;
		await runPreview();
	};

	const handleFileChange = (event: Event) => {
		const target = event.currentTarget as HTMLInputElement;
		onFilesPicked(target.files);
		// reset so the same file can be reselected
		target.value = '';
	};

	const handleDrop = (event: DragEvent) => {
		event.preventDefault();
		isDragging = false;
		onFilesPicked(event.dataTransfer?.files);
	};

	const handleDragOver = (event: DragEvent) => {
		event.preventDefault();
		isDragging = true;
	};

	const handleDragLeave = () => {
		isDragging = false;
	};

	const runPreview = async () => {
		if (!selectedFile || !glossaryId) return;
		busy = true;
		errorMessage = '';
		try {
			preview = await previewGlossaryImport(localStorage.token, glossaryId, selectedFile);
			mapping = { ...preview.header_mapping };
			autoClassify = false;
			stage = 'preview';
		} catch (e: any) {
			errorMessage = typeof e === 'string' ? e : formatBackendError(e, $i18n) ?? `${e}`;
			toast.error(errorMessage);
			selectedFile = null;
		} finally {
			busy = false;
		}
	};

	const handleMappingChange = (header: string, value: string) => {
		mapping = { ...mapping, [header]: value };
	};

	const requestLLMSuggestion = async () => {
		if (!preview || !glossaryId) return;
		llmBusy = true;
		errorMessage = '';
		try {
			const result = await llmSuggestGlossaryImport(
				localStorage.token,
				glossaryId,
				preview.upload_token,
				modelId || undefined
			);
			llmSuggestion = result;
			useLlmRule = true;
		} catch (e: any) {
			const detail = typeof e === 'string' ? e : formatBackendError(e, $i18n) ?? `${e}`;
			toast.error(detail);
			errorMessage = detail;
		} finally {
			llmBusy = false;
		}
	};

	const discardLLMSuggestion = () => {
		useLlmRule = false;
	};

	// 사용자가 매핑을 바꿔도 sample 은 서버 응답 기준 — 자동 업데이트는 다음 PR 의 영역.
	// 매핑이 term 을 포함하는지 검증.
	$: hasTermMapping = Object.values(mapping).includes('term');

	$: activeSamples =
		useLlmRule && llmSuggestion ? llmSuggestion.sample_entries : preview?.sample_entries ?? [];

	const submitCommit = async () => {
		if (!preview || !glossaryId) return;
		if (!useLlmRule && !hasTermMapping) {
			toast.error($i18n.t('At least one column must be mapped to Term.'));
			return;
		}
		busy = true;
		stage = 'committing';
		errorMessage = '';
		try {
			const result = await commitGlossaryImport(localStorage.token, glossaryId, {
				upload_token: preview.upload_token,
				mapping,
				auto_classify: autoClassify,
				base_updated_at: preview.base_updated_at,
				llm_rule: useLlmRule && llmSuggestion ? llmSuggestion.rule : null
			});
			toast.success(
				$i18n.t('Imported {{added}} new, {{updated}} updated.', {
					added: result.added,
					updated: result.updated
				})
			);
			dispatch('completed', result);
			closeModal();
		} catch (e: any) {
			const detail = typeof e === 'string' ? e : formatBackendError(e, $i18n) ?? `${e}`;
			errorMessage = detail;
			toast.error(detail);
			stage = 'preview';
		} finally {
			busy = false;
		}
	};

	$: if (!show) {
		// 모달이 외부에서 닫힐 때 state reset
		reset();
	}

	// initialFile 이 주어지면 modal 열림과 동시에 preview 자동 트리거
	$: if (show && initialFile && stage === 'select' && !busy && glossaryId) {
		selectedFile = initialFile;
		// 한 번만 실행되도록 즉시 reset
		initialFile = null;
		runPreview();
	}
</script>

<Modal bind:show size="lg">
	<div class="px-6 py-5 border-b border-gray-200 dark:border-gray-800 flex items-center justify-between">
		<h2 class="text-base font-semibold text-gray-900 dark:text-gray-100">
			{$i18n.t('Bulk import terms')}
		</h2>
		<button
			type="button"
			class="p-1 rounded hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-500"
			on:click={closeModal}
			aria-label={$i18n.t('Close')}
		>
			<svg class="size-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
				<path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
			</svg>
		</button>
	</div>

	<div class="px-6 py-5 max-h-[70vh] overflow-y-auto">
		{#if stage === 'select'}
			<div
				class="rounded-xl border-2 border-dashed text-center p-10 transition
					{isDragging
						? 'border-[var(--cloo-color-info)] bg-[var(--cloo-color-info)]/5'
						: 'border-gray-300 dark:border-gray-700 hover:border-gray-400 dark:hover:border-gray-600'}"
				on:dragover={handleDragOver}
				on:dragleave={handleDragLeave}
				on:drop={handleDrop}
				role="presentation"
			>
				{#if busy}
					<div class="flex flex-col items-center gap-2 py-4">
						<Spinner className="size-6" />
						<div class="text-sm text-gray-500 dark:text-gray-400">
							{$i18n.t('Parsing file...')}
						</div>
					</div>
				{:else}
					<svg
						class="mx-auto size-10 text-gray-300 dark:text-gray-600 mb-3"
						fill="none"
						viewBox="0 0 24 24"
						stroke="currentColor"
						stroke-width="1.5"
					>
						<path
							stroke-linecap="round"
							stroke-linejoin="round"
							d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12m4.5 4.5V3"
						/>
					</svg>
					<p class="text-sm text-gray-700 dark:text-gray-200 mb-1">
						{$i18n.t('Drag and drop a file here, or click to select.')}
					</p>
					<p class="text-xs text-gray-400 mb-4">
						{$i18n.t('Supported formats: XLSX, CSV, Markdown')}
					</p>
					<label
						class="inline-block cursor-pointer text-xs px-3 py-1.5 rounded-md bg-[var(--cloo-color-info)] text-white hover:opacity-90"
					>
						{$i18n.t('Select file')}
						<input
							type="file"
							accept={ACCEPT}
							class="hidden"
							on:change={handleFileChange}
						/>
					</label>
				{/if}
				{#if errorMessage}
					<p class="mt-4 text-xs text-red-500 dark:text-red-400">
						{errorMessage}
					</p>
				{/if}
			</div>
		{:else if stage === 'preview' && preview}
			<div class="flex flex-col gap-4">
				<!-- File summary + stats -->
				<div class="flex items-center justify-between rounded-md px-3 py-2 bg-gray-50 dark:bg-gray-850 text-xs">
					<div class="text-gray-600 dark:text-gray-300">
						<span class="font-medium">{selectedFile?.name}</span>
						<span class="mx-2 text-gray-400">·</span>
						<span class="uppercase">{preview.format}</span>
						{#if preview.encoding}
							<span class="mx-2 text-gray-400">·</span>
							<span>{preview.encoding}</span>
						{/if}
						{#if preview.md_pattern}
							<span class="mx-2 text-gray-400">·</span>
							<span>{preview.md_pattern}</span>
						{/if}
					</div>
					<div class="flex gap-3 text-gray-600 dark:text-gray-300">
						<span>
							{$i18n.t('Total')}: <b>{preview.stats.total_rows}</b>
						</span>
						<span class="text-emerald-600 dark:text-emerald-400">
							{$i18n.t('New')}: <b>{preview.stats.added}</b>
						</span>
						<span class="text-[var(--cloo-color-info)]">
							{$i18n.t('Update')}: <b>{preview.stats.updated}</b>
						</span>
						<span class="text-gray-400">
							{$i18n.t('Skip')}: <b>{preview.stats.skipped_rows}</b>
						</span>
					</div>
				</div>

				<!-- AI 자동 변환 (LLM-aided) -->
				<div class="rounded-md border border-purple-200 dark:border-purple-900/50 bg-purple-50/40 dark:bg-purple-900/10 p-3">
					{#if !llmSuggestion}
						<div class="flex items-start gap-3">
							<svg class="size-4 text-purple-600 dark:text-purple-400 mt-0.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
								<path stroke-linecap="round" stroke-linejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.456 2.456L21.75 6l-1.035.259a3.375 3.375 0 00-2.456 2.456z" />
							</svg>
							<div class="flex-1 min-w-0">
								<div class="text-xs font-medium text-gray-800 dark:text-gray-100">
									{$i18n.t('AI auto-convert (recommended for raw data)')}
								</div>
								<div class="text-[10px] text-gray-500 dark:text-gray-400 mt-0.5">
									{$i18n.t('Let AI infer how to combine columns into glossary entries (term, synonyms, description, category).')}
								</div>
							</div>
							<button
								type="button"
								class="text-[11px] px-2.5 py-1 rounded-md bg-purple-600 text-white hover:bg-purple-700 disabled:opacity-50 shrink-0"
								disabled={llmBusy}
								on:click={requestLLMSuggestion}
							>
								{llmBusy ? $i18n.t('Inferring...') : $i18n.t('Run AI inference')}
							</button>
						</div>
					{:else}
						<div class="flex items-start gap-3">
							<svg class="size-4 text-purple-600 dark:text-purple-400 mt-0.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
								<path stroke-linecap="round" stroke-linejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z" />
							</svg>
							<div class="flex-1 min-w-0">
								<div class="text-xs font-medium text-gray-800 dark:text-gray-100">
									{$i18n.t('AI conversion rule')}
									{#if useLlmRule}
										<span class="ml-2 text-[10px] text-purple-600 dark:text-purple-400">
											{$i18n.t('(active)')}
										</span>
									{/if}
								</div>
								{#if llmSuggestion.rule.rationale}
									<div class="text-[10px] text-gray-600 dark:text-gray-300 mt-0.5">
										{llmSuggestion.rule.rationale}
									</div>
								{/if}
							</div>
							<div class="flex items-center gap-1 shrink-0">
								{#if useLlmRule}
									<button
										type="button"
										class="text-[11px] px-2 py-0.5 rounded text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800"
										on:click={discardLLMSuggestion}
									>
										{$i18n.t('Use manual mapping')}
									</button>
								{:else}
									<button
										type="button"
										class="text-[11px] px-2 py-0.5 rounded bg-purple-600 text-white hover:bg-purple-700"
										on:click={() => (useLlmRule = true)}
									>
										{$i18n.t('Apply AI rule')}
									</button>
								{/if}
								<button
									type="button"
									class="text-[11px] px-2 py-0.5 rounded text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-800"
									disabled={llmBusy}
									on:click={requestLLMSuggestion}
								>
									{$i18n.t('Re-run')}
								</button>
							</div>
						</div>
					{/if}
				</div>

				<!-- Header mapping -->
				<div class:opacity-50={useLlmRule}>
					<div class="text-xs font-medium text-gray-700 dark:text-gray-200 mb-2">
						{$i18n.t('Column mapping')}
						{#if useLlmRule}
							<span class="text-[10px] text-gray-400 ml-2 font-normal">
								{$i18n.t('(disabled while AI rule is active)')}
							</span>
						{:else if !hasTermMapping}
							<span class="text-red-500 ml-2 font-normal">
								{$i18n.t('At least one column must be mapped to Term.')}
							</span>
						{/if}
					</div>
					<div class="flex flex-col gap-1.5">
						{#each preview.headers as header (header)}
							<div class="flex items-center gap-2">
								<div class="w-44 shrink-0 text-xs text-gray-700 dark:text-gray-200 truncate" title={header}>
									{header || '(empty)'}
								</div>
								<div class="flex-1 min-w-0">
									<Selector
										value={mapping[header] ?? 'skip'}
										items={fieldOptions}
										on:change={(e) => handleMappingChange(header, e.detail.value)}
										size="sm"
										disabled={useLlmRule}
									/>
								</div>
							</div>
						{/each}
					</div>
				</div>

				<!-- Auto-classify -->
				<div
					class="flex items-start gap-2 rounded-md p-2 hover:bg-gray-50 dark:hover:bg-gray-850 cursor-pointer"
					on:click={() => (autoClassify = !autoClassify)}
					role="presentation"
				>
					<Checkbox state={autoClassify ? 'checked' : 'unchecked'} />
					<div class="flex flex-col">
						<span class="text-xs font-medium text-gray-700 dark:text-gray-200">
							{$i18n.t('Auto-classify empty categories')}
						</span>
						<span class="text-[10px] text-gray-400">
							{$i18n.t('Apply keyword-based classification (9 categories) when category column is empty.')}
						</span>
					</div>
				</div>

				<!-- Sample preview — LLM rule 활성 시 LLM 결과, 아니면 기본 매핑 결과 -->
				<div>
					<div class="text-xs font-medium text-gray-700 dark:text-gray-200 mb-1.5">
						{$i18n.t('Preview (first {{count}} rows)', { count: activeSamples.length })}
						{#if useLlmRule}
							<span class="ml-2 text-[10px] text-purple-600 dark:text-purple-400">
								{$i18n.t('AI rule applied')}
							</span>
						{/if}
					</div>
					<div class="overflow-x-auto border border-gray-200 dark:border-gray-700 rounded-md">
						<table class="w-full text-[11px]">
							<thead class="bg-gray-50 dark:bg-gray-850 text-gray-600 dark:text-gray-400">
								<tr>
									<th class="px-2 py-1.5 text-left font-medium">{$i18n.t('Term')}</th>
									<th class="px-2 py-1.5 text-left font-medium">{$i18n.t('Synonyms')}</th>
									<th class="px-2 py-1.5 text-left font-medium">{$i18n.t('Category')}</th>
									<th class="px-2 py-1.5 text-left font-medium">{$i18n.t('Description')}</th>
								</tr>
							</thead>
							<tbody>
								{#each activeSamples as entry}
									<tr class="border-t border-gray-100 dark:border-gray-800">
										<td class="px-2 py-1 font-medium text-gray-900 dark:text-gray-100">
											{entry.term}
										</td>
										<td class="px-2 py-1 text-gray-600 dark:text-gray-400 truncate max-w-[140px]">
											{(entry.synonyms || []).join(', ')}
										</td>
										<td class="px-2 py-1 text-gray-500">
											{entry.category ?? ''}
										</td>
										<td class="px-2 py-1 text-gray-500 truncate max-w-[260px]">
											{entry.description ?? ''}
										</td>
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
				</div>

				{#if errorMessage}
					<p class="text-xs text-red-500 dark:text-red-400">
						{errorMessage}
					</p>
				{/if}
			</div>
		{:else if stage === 'committing'}
			<div class="flex flex-col items-center gap-3 py-10">
				<Spinner className="size-6" />
				<div class="text-sm text-gray-500 dark:text-gray-400">
					{$i18n.t('Importing...')}
				</div>
			</div>
		{/if}
	</div>

	<div class="px-6 py-4 border-t border-gray-200 dark:border-gray-800 flex justify-end gap-2">
		{#if stage === 'preview'}
			<Button kind="outlined" size="md" on:click={() => reset()} disabled={busy}>
				{$i18n.t('Reselect file')}
			</Button>
		{/if}
		<Button kind="outlined" size="md" on:click={closeModal} disabled={busy}>
			{$i18n.t('Cancel')}
		</Button>
		{#if stage === 'preview'}
			<Button
				kind="filled"
				size="md"
				on:click={submitCommit}
				disabled={busy || (!useLlmRule && !hasTermMapping)}
				loading={busy}
			>
				{$i18n.t('Import')}
			</Button>
		{/if}
	</div>
</Modal>

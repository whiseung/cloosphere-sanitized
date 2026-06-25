<script lang="ts">
	import { getContext, createEventDispatcher, onDestroy } from 'svelte';
	import { toast } from 'svelte-sonner';

	import { WEBUI_API_BASE_URL } from '$lib/constants';

	import Button from '$lib/components/common/Button.svelte';
	import Checkbox from '$lib/components/common/Checkbox.svelte';
	import Selector from '$lib/components/common/Selector.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import ArrowLeft from '$lib/components/icons/ArrowLeft.svelte';
	import ArrowDownTray from '$lib/components/icons/ArrowDownTray.svelte';
	import CloudArrowUp from '$lib/components/icons/CloudArrowUp.svelte';
	import LockClosed from '$lib/components/icons/LockClosed.svelte';
	import Sparkles from '$lib/components/icons/Sparkles.svelte';
	import SparklesSolid from '$lib/components/icons/SparklesSolid.svelte';

	import {
		previewGlossaryImport,
		commitGlossaryImport,
		llmSuggestGlossaryImport,
		downloadGlossaryImportTemplate,
		extractErrorMessage,
		type GlossaryImportPreview,
		type GlossaryImportLLMSuggestResult,
		type GlossaryImportSegment
	} from '$lib/apis/glossary';

	const i18n: any = getContext('i18n');
	const dispatch = createEventDispatcher();

	export let glossaryId: string = '';
	export let aiModelId: string = '';
	export let initialFile: File | null = null;

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
	let conservativeMode = false;
	// AI 제안 적용 후 미리보기로 자동 스크롤 (사용자가 결과를 즉시 볼 수 있도록).
	let samplePreviewEl: HTMLDivElement | undefined;

	// AbortController for in-flight fetches (critique M2)
	let abortController: AbortController | null = null;
	// Track upload_token so we can best-effort clean up orphan files on unmount.
	let committedSuccessfully = false;

	const ACCEPT = '.xlsx,.csv,.md,.markdown';

	$: fieldOptions = [
		{ value: 'term', label: $i18n.t('Term (primary)'), tip: $i18n.t('Primary term. Search key (required)') },
		{
			value: 'synonyms',
			label: $i18n.t('Synonyms (comma-separated)'),
			tip: $i18n.t('Search anchors (abbreviations, full names, other notations)')
		},
		{
			value: 'description',
			label: $i18n.t('Description'),
			tip: $i18n.t('Definition. Directly exposed to AI answers')
		},
		{ value: 'example', label: $i18n.t('Example'), tip: $i18n.t('Practical usage example (optional)') },
		{ value: 'category', label: $i18n.t('Category'), tip: $i18n.t('Classification meta. Not in AI prompt') },
		{ value: 'skip', label: $i18n.t('Skip this column'), tip: $i18n.t('Exclude this column') }
	];

	$: fieldOptionsForSelector = fieldOptions.map((o) => ({ value: o.value, label: o.label }));

	const newAbort = () => {
		if (abortController) {
			abortController.abort();
		}
		abortController = new AbortController();
		return abortController;
	};

	const cleanupOrphanToken = async () => {
		const token = preview?.upload_token;
		if (!token || committedSuccessfully) return;
		// Best-effort orphan cleanup. We don't wait or surface errors.
		try {
			await fetch(`${WEBUI_API_BASE_URL}/files/${token}`, {
				method: 'DELETE',
				headers: { authorization: `Bearer ${localStorage.token}` }
			});
		} catch {
			// ignore — token sweeper handles fallback
		}
	};

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
		conservativeMode = false;
		committedSuccessfully = false;
		if (abortController) {
			abortController.abort();
			abortController = null;
		}
	};

	const handleBack = () => {
		// If user has an in-flight upload or unconfirmed preview, confirm before leaving.
		if (busy) return;
		if (preview && !committedSuccessfully) {
			const ok = confirm(
				$i18n.t('Discard the current upload? Uploaded data has not been committed yet.')
			);
			if (!ok) return;
		}
		dispatch('back');
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
		newAbort();
		try {
			// previewGlossaryImport doesn't accept signal yet; relying on parent
			// component unmount + onDestroy cleanup for token orphan handling.
			preview = await previewGlossaryImport(localStorage.token, glossaryId, selectedFile);
			mapping = { ...preview.header_mapping };
			autoClassify = false;
			stage = 'preview';
		} catch (e: any) {
			errorMessage = extractErrorMessage(e);
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
		newAbort();
		try {
			const result = await llmSuggestGlossaryImport(
				localStorage.token,
				glossaryId,
				preview.upload_token,
				aiModelId || undefined,
				{ conservativeDescription: conservativeMode }
			);
			llmSuggestion = result;
			useLlmRule = true;
			// 사용자가 적용 결과를 즉시 확인할 수 있도록 미리보기로 부드럽게 스크롤.
			// reactive update 가 DOM 에 반영된 다음 tick 에 실행.
			setTimeout(() => {
				samplePreviewEl?.scrollIntoView({ behavior: 'smooth', block: 'start' });
			}, 50);
		} catch (e: any) {
			const detail = extractErrorMessage(e);
			toast.error(detail);
			errorMessage = detail;
		} finally {
			llmBusy = false;
		}
	};

	const discardLLMSuggestion = () => {
		useLlmRule = false;
	};

	$: hasTermMapping = Object.values(mapping).includes('term');

	$: activeSamples =
		useLlmRule && llmSuggestion ? llmSuggestion.sample_entries : preview?.sample_entries ?? [];
	$: activeSegments = useLlmRule && llmSuggestion ? llmSuggestion.sample_entries_segments ?? [] : [];

	const getDescriptionSegments = (
		index: number,
		fallback: string
	): GlossaryImportSegment[] => {
		const segs = activeSegments[index]?.description;
		if (Array.isArray(segs) && segs.length > 0) return segs;
		// fallback: render fallback string as a single data segment
		return [{ kind: 'data', text: fallback ?? '' }];
	};

	$: hasAnyLiteralInDescription = (() => {
		if (!useLlmRule || !llmSuggestion || activeSegments.length === 0) return false;
		for (const row of activeSegments) {
			const segs = row?.description;
			if (Array.isArray(segs) && segs.some((s) => s.kind === 'literal' && (s.text ?? '').length > 0)) {
				return true;
			}
		}
		return false;
	})();

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
			committedSuccessfully = true;
			dispatch('completed', result);
		} catch (e: any) {
			const detail = extractErrorMessage(e);
			errorMessage = detail;
			toast.error(detail);
			stage = 'preview';
		} finally {
			busy = false;
		}
	};

	const downloadTemplate = async () => {
		try {
			const blob = await downloadGlossaryImportTemplate(localStorage.token);
			const url = URL.createObjectURL(blob);
			const a = document.createElement('a');
			a.href = url;
			a.download = 'glossary-import-template.xlsx';
			document.body.appendChild(a);
			a.click();
			document.body.removeChild(a);
			// release the object URL on next tick to avoid breaking the download.
			setTimeout(() => URL.revokeObjectURL(url), 0);
		} catch (e: any) {
			toast.error(extractErrorMessage(e));
		}
	};

	// initialFile 이 주어지면 mount 시 즉시 preview 트리거 (parent 가 .json 외 파일을 넘김)
	$: if (initialFile && stage === 'select' && !busy && glossaryId) {
		const f = initialFile;
		initialFile = null;
		selectedFile = f;
		runPreview();
	}

	onDestroy(() => {
		if (abortController) {
			abortController.abort();
			abortController = null;
		}
		// fire-and-forget orphan cleanup; resolution happens after unmount.
		void cleanupOrphanToken();
	});
</script>

<div class="px-6 py-5 max-h-[70vh] overflow-y-auto">
	<div class="flex items-center justify-between mb-3">
		<Button kind="text" size="sm" on:click={handleBack}>
			<svelte:fragment slot="prefix">
				<ArrowLeft className="size-3.5" strokeWidth="2" />
			</svelte:fragment>
			{$i18n.t('Back')}
		</Button>
		<Button kind="text" size="sm" on:click={downloadTemplate}>
			<svelte:fragment slot="prefix">
				<ArrowDownTray className="size-3.5" strokeWidth="2" />
			</svelte:fragment>
			{$i18n.t('Download standard template')}
		</Button>
	</div>

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
				<div class="mx-auto size-10 text-gray-300 dark:text-gray-600 mb-3 flex items-center justify-center">
					<CloudArrowUp className="size-10" strokeWidth="1.5" />
				</div>
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
					<input type="file" accept={ACCEPT} class="hidden" on:change={handleFileChange} />
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
			<div
				class="flex items-center justify-between rounded-md px-3 py-2 bg-gray-50 dark:bg-gray-850 text-xs"
			>
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
			<div
				class="rounded-md border border-purple-200 dark:border-purple-900/50 bg-purple-50/40 dark:bg-purple-900/10 p-3"
			>
				{#if !llmSuggestion}
					<div class="flex items-start gap-3">
						<Sparkles className="size-4 text-purple-600 dark:text-purple-400 mt-0.5 shrink-0" strokeWidth="2" />
						<div class="flex-1 min-w-0">
							<div class="text-xs font-medium text-gray-800 dark:text-gray-100">
								{$i18n.t('AI auto-convert (recommended for raw data)')}
							</div>
							<div class="text-[10px] text-gray-500 dark:text-gray-400 mt-0.5">
								{$i18n.t(
									'Let AI infer how to combine columns into glossary entries (term, synonyms, description, category).'
								)}
							</div>
							<label
								class="flex items-center gap-1.5 mt-1.5 cursor-pointer text-[10px] text-gray-600 dark:text-gray-300"
							>
								<Checkbox
									state={conservativeMode ? 'checked' : 'unchecked'}
									on:change={(e) => {
										conservativeMode = e.detail === 'checked';
									}}
								/>
								<span>{$i18n.t('Conservative mode (description uses column values only)')}</span>
							</label>
						</div>
						<Button
							kind="filled"
							size="sm"
							className="shrink-0 bg-purple-600 hover:bg-purple-700 active:bg-purple-800 text-white"
							disabled={llmBusy}
							on:click={requestLLMSuggestion}
						>
							{llmBusy ? $i18n.t('Inferring...') : $i18n.t('Run AI inference')}
						</Button>
					</div>

					<details class="mt-2 text-[11px]">
						<summary class="cursor-pointer select-none text-purple-700 dark:text-purple-300 hover:underline">
							{$i18n.t('What does AI synthesize?')}
						</summary>
						<ul class="mt-2 space-y-2 text-gray-600 dark:text-gray-300 leading-relaxed list-none">
							<li class="flex gap-2">
								<span class="text-purple-500 dark:text-purple-400 select-none shrink-0 leading-relaxed">—</span>
								<div class="flex-1 min-w-0">
									<span class="font-semibold text-gray-800 dark:text-gray-100">{$i18n.t('AI infers (rule design):')}</span>
									{$i18n.t('which column maps to term / synonyms / description / category, and how to combine multiple columns (e.g., country code + city code → UN/LOCODE).')}
								</div>
							</li>
							<li class="flex gap-2">
								<span class="text-purple-500 dark:text-purple-400 select-none shrink-0 leading-relaxed">—</span>
								<div class="flex-1 min-w-0">
									<span class="font-semibold text-gray-800 dark:text-gray-100">{$i18n.t('AI synthesizes (wording):')}</span>
									{$i18n.t('connector phrases inside the description template, and the category label when the table is homogeneous. These literal words are shown in purple in the preview.')}
								</div>
							</li>
							<li class="flex gap-2">
								<span class="text-purple-500 dark:text-purple-400 select-none shrink-0 leading-relaxed">—</span>
								<div class="flex-1 min-w-0">
									<span class="font-semibold text-gray-800 dark:text-gray-100">{$i18n.t('From your file (data):')}</span>
									{$i18n.t('all actual values come from your file columns — AI never invents data values.')}
								</div>
							</li>
						</ul>

						<!-- 안전 모드 강조 박스 -->
						<div class="mt-3 rounded-md border border-amber-300 dark:border-amber-700/60 bg-amber-50 dark:bg-amber-900/20 p-2.5 flex items-start gap-2">
							<LockClosed className="size-4 text-amber-600 dark:text-amber-400 shrink-0 mt-0.5" strokeWidth="2" />
							<div class="flex-1 text-[11px] text-amber-900 dark:text-amber-100 leading-relaxed">
								<span class="font-semibold">{$i18n.t('Conservative mode')}:</span>
								{$i18n.t('forbids AI-written wording inside description. Enable when AI-guessed phrasing might be inaccurate for your domain — description will use raw column values only.')}
							</div>
						</div>
					</details>
				{:else}
					<div class="flex items-start gap-3">
						<Sparkles className="size-4 text-purple-600 dark:text-purple-400 mt-0.5 shrink-0" strokeWidth="2" />
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
							<label
								class="flex items-center gap-1.5 mt-1.5 cursor-pointer text-[10px] text-gray-600 dark:text-gray-300"
							>
								<Checkbox
									state={conservativeMode ? 'checked' : 'unchecked'}
									on:change={(e) => {
										conservativeMode = e.detail === 'checked';
									}}
								/>
								<span>{$i18n.t('Conservative mode (description uses column values only)')}</span>
							</label>
						</div>
						<div class="flex items-center gap-1 shrink-0">
							{#if useLlmRule}
								<Button kind="text" size="sm" on:click={discardLLMSuggestion}>
									{$i18n.t('Use manual mapping')}
								</Button>
							{:else}
								<Button
									kind="filled"
									size="sm"
									className="bg-purple-600 hover:bg-purple-700 active:bg-purple-800 text-white"
									on:click={() => (useLlmRule = true)}
								>
									{$i18n.t('Apply AI rule')}
								</Button>
							{/if}
							<Button kind="text" size="sm" disabled={llmBusy} on:click={requestLLMSuggestion}>
								{$i18n.t('Re-run')}
							</Button>
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
							<div
								class="w-44 shrink-0 text-xs text-gray-700 dark:text-gray-200 truncate"
								title={header}
							>
								{header || '(empty)'}
							</div>
							<div class="flex-1 min-w-0">
								<Tooltip
									content={fieldOptions.find((o) => o.value === (mapping[header] ?? 'skip'))?.tip ??
										''}
									placement="top"
								>
									<Selector
										value={mapping[header] ?? 'skip'}
										items={fieldOptionsForSelector}
										on:change={(e) => handleMappingChange(header, e.detail.value)}
										size="sm"
										disabled={useLlmRule}
									/>
								</Tooltip>
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
						{$i18n.t(
							'Apply keyword-based classification (9 categories) when category column is empty.'
						)}
					</span>
				</div>
			</div>

			<!-- Sample preview -->
			<div bind:this={samplePreviewEl}>
				<div class="text-xs font-medium text-gray-700 dark:text-gray-200 mb-1.5 flex items-center gap-2">
					<span>
						{$i18n.t('Preview (first {{count}} rows)', { count: activeSamples.length })}
					</span>
					{#if useLlmRule}
						<span class="text-[10px] text-purple-600 dark:text-purple-400">
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
							{#each activeSamples as entry, i}
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
									<td class="px-2 py-1 text-gray-500 max-w-[280px]">
										{#if useLlmRule && activeSegments.length > 0}
											{#each getDescriptionSegments(i, entry.description ?? '') as seg}
												{#if seg.kind === 'literal'}
													<span class="text-purple-600 dark:text-purple-400">{seg.text}</span>
												{:else}
													<span class="text-gray-700 dark:text-gray-200">{seg.text}</span>
												{/if}
											{/each}
										{:else}
											<span class="truncate">{entry.description ?? ''}</span>
										{/if}
									</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
				{#if useLlmRule && hasAnyLiteralInDescription}
					<div class="mt-1 text-[10px] text-gray-500 dark:text-gray-400 flex items-center gap-2">
						<span class="inline-flex items-center gap-1">
							<SparklesSolid className="size-3 text-purple-600 dark:text-purple-400" />
							<span class="text-purple-600 dark:text-purple-400 font-medium">
								{$i18n.t('AI-written wording')}
							</span>
						</span>
						<span class="text-gray-400">·</span>
						<span>{$i18n.t('File data')}</span>
					</div>
				{/if}
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
		<Button kind="outlined" size="md" on:click={reset} disabled={busy}>
			{$i18n.t('Reselect file')}
		</Button>
	{/if}
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

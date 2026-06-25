<script lang="ts">
	import { getContext, createEventDispatcher } from 'svelte';
	import { toast } from 'svelte-sonner';

	import Modal from '$lib/components/common/Modal.svelte';
	import Button from '$lib/components/common/Button.svelte';
	import Cube from '$lib/components/icons/Cube.svelte';
	import Document from '$lib/components/icons/Document.svelte';
	import Info from '$lib/components/icons/Info.svelte';
	import { downloadGlossaryImportTemplate, extractErrorMessage } from '$lib/apis/glossary';

	import BulkImportFileStage from './BulkImportFileStage.svelte';
	import BulkImportDbStage from './BulkImportDbStage.svelte';

	const i18n: any = getContext('i18n');
	const dispatch = createEventDispatcher();

	export let show = false;
	export let glossaryId: string = '';
	export let aiModelId: string = '';
	export let canWrite: boolean = false;
	export let extractJob: any = null;
	export let initialFile: File | null = null;

	type Mode = 'pick' | 'file' | 'db';
	let mode: Mode = 'pick';
	let pendingInitialFile: File | null = null;
	let fileInputEl: HTMLInputElement;

	// Reset mode whenever modal closes (critique M1).
	// Conditional render of stage children ensures their state is naturally
	// discarded when mode changes back to 'pick'.
	$: if (!show) {
		mode = 'pick';
		pendingInitialFile = null;
	}

	// If initialFile is provided when opening, jump directly to file stage.
	$: if (show && initialFile && mode === 'pick') {
		pendingInitialFile = initialFile;
		// Clear the prop so re-opening with no file doesn't re-trigger.
		initialFile = null;
		mode = 'file';
	}

	const closeModal = () => {
		show = false;
	};

	const handleFilePicked = async (event: Event) => {
		const target = event.currentTarget as HTMLInputElement;
		const files = target.files;
		if (!files || files.length === 0) return;
		const file = files[0];
		// Reset input so the same file can be re-selected later.
		target.value = '';

		const lower = file.name.toLowerCase();
		if (
			!lower.endsWith('.xlsx') &&
			!lower.endsWith('.csv') &&
			!lower.endsWith('.md') &&
			!lower.endsWith('.markdown')
		) {
			toast.error($i18n.t('Unsupported file format. Use .xlsx, .csv, or .md.'));
			return;
		}
		pendingInitialFile = file;
		mode = 'file';
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
			setTimeout(() => URL.revokeObjectURL(url), 0);
		} catch (e: any) {
			toast.error(extractErrorMessage(e));
		}
	};

	const handleFileCardClick = () => {
		if (!canWrite) return;
		fileInputEl?.click();
	};

	const handleDbCardClick = () => {
		if (!canWrite) return;
		mode = 'db';
	};

	// Note: native <button> 은 Enter/Space 에서 click 자동 발화. 별도 on:keydown 핸들러 불필요.

	const handleFileCompleted = (e: CustomEvent) => {
		dispatch('file-completed', e.detail);
		closeModal();
	};

	const handleDbJobStarted = (e: CustomEvent) => {
		// Parent owns extractJob state + polling timer (critique H1/H2).
		dispatch('db-job-started', e.detail);
		closeModal();
	};

	const handleStageBack = () => {
		mode = 'pick';
		pendingInitialFile = null;
	};

	$: dbJobInProgress =
		extractJob && (extractJob.status === 'queued' || extractJob.status === 'running');
</script>

<input
	bind:this={fileInputEl}
	type="file"
	accept=".xlsx,.csv,.md,.markdown"
	hidden
	on:change={handleFilePicked}
/>

<Modal bind:show size="lg">
	<div
		class="px-6 py-5 border-b border-gray-200 dark:border-gray-800 flex items-center justify-between"
	>
		<h2 class="text-base font-semibold text-gray-900 dark:text-gray-100">
			{#if mode === 'pick'}
				{$i18n.t('Bring in glossary entries')}
			{:else if mode === 'file'}
				{$i18n.t('Import from file')}
			{:else}
				{$i18n.t('Import from database')}
			{/if}
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

	{#if mode === 'pick'}
		<div class="px-6 py-5 max-h-[70vh] overflow-y-auto">
			<!-- Info box: domain quality reminder -->
			<div
				class="rounded-md border border-purple-200 dark:border-purple-900/40 bg-purple-50/40 dark:bg-purple-900/10 p-3 mb-3 flex items-start gap-2"
			>
				<Info className="size-4 shrink-0 text-purple-600 dark:text-purple-400 mt-0.5" />
				<div class="flex-1 text-xs text-gray-700 dark:text-gray-200 leading-relaxed">
					{$i18n.t(
						'Your company domain terms. Mistakes directly affect AI answer accuracy.'
					)}
				</div>
				<Button
					kind="text"
					size="sm"
					className="shrink-0 whitespace-nowrap text-[var(--cloo-color-info)] hover:underline"
					on:click={downloadTemplate}
				>
					{$i18n.t('Download standard template')}
				</Button>
			</div>

			<!-- Field impact guide -->
			<details class="mb-4 rounded-md border border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-gray-900/40 text-xs">
				<summary class="cursor-pointer select-none px-3 py-2 font-medium text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-800/60 rounded-md flex items-center justify-between">
					<span>{$i18n.t('How glossary entries affect AI answers')}</span>
					<span class="text-[10px] text-gray-500 dark:text-gray-400">{$i18n.t('Click to expand')}</span>
				</summary>
				<div class="px-3 pb-3 pt-1">
					<table class="w-full text-left">
						<thead>
							<tr class="text-[10px] uppercase tracking-wide text-gray-500 dark:text-gray-400 border-b border-gray-200 dark:border-gray-800">
								<th class="py-1 pr-2 font-medium">{$i18n.t('Field name')}</th>
								<th class="py-1 pr-2 font-medium">{$i18n.t('Role')}</th>
								<th class="py-1 font-medium">{$i18n.t('Impact on AI answer')}</th>
							</tr>
						</thead>
						<tbody class="text-gray-700 dark:text-gray-200">
							<tr class="border-b border-gray-100 dark:border-gray-800/60">
								<td class="py-1.5 pr-2">
									<span>{$i18n.t('Term')}</span>
									<span class="ml-1 font-mono text-[10px] text-gray-400">term</span>
								</td>
								<td class="py-1.5 pr-2">{$i18n.t('Match key (required)')}</td>
								<td class="py-1.5 text-gray-500 dark:text-gray-400">{$i18n.t('Decides whether the entry is retrieved')}</td>
							</tr>
							<tr class="border-b border-gray-100 dark:border-gray-800/60">
								<td class="py-1.5 pr-2">
									<span>{$i18n.t('Synonyms')}</span>
									<span class="ml-1 font-mono text-[10px] text-gray-400">synonyms</span>
								</td>
								<td class="py-1.5 pr-2">{$i18n.t('Search anchors')}</td>
								<td class="py-1.5 text-gray-500 dark:text-gray-400">{$i18n.t('Improves recall for abbreviations / alternate notations')}</td>
							</tr>
							<tr class="border-b border-gray-100 dark:border-gray-800/60">
								<td class="py-1.5 pr-2 text-purple-700 dark:text-purple-300 font-semibold">
									<span>{$i18n.t('Description')}</span>
									<span class="ml-1 font-mono text-[10px] opacity-70">description</span>
								</td>
								<td class="py-1.5 pr-2 font-semibold">{$i18n.t('Definition (most important)')}</td>
								<td class="py-1.5 text-purple-700 dark:text-purple-300">{$i18n.t('Inserted directly into the AI answer prompt')}</td>
							</tr>
							<tr class="border-b border-gray-100 dark:border-gray-800/60">
								<td class="py-1.5 pr-2">
									<span>{$i18n.t('Example')}</span>
									<span class="ml-1 font-mono text-[10px] text-gray-400">example</span>
								</td>
								<td class="py-1.5 pr-2">{$i18n.t('Usage example')}</td>
								<td class="py-1.5 text-gray-500 dark:text-gray-400">{$i18n.t('Reinforces embedding (auxiliary)')}</td>
							</tr>
							<tr>
								<td class="py-1.5 pr-2">
									<span>{$i18n.t('Category')}</span>
									<span class="ml-1 font-mono text-[10px] text-gray-400">category</span>
								</td>
								<td class="py-1.5 pr-2">{$i18n.t('Classification metadata')}</td>
								<td class="py-1.5 text-gray-500 dark:text-gray-400">{$i18n.t('Filter only — not exposed to AI prompt')}</td>
							</tr>
						</tbody>
					</table>
				</div>
			</details>

			<div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
				<!-- DB card -->
				<button
					type="button"
					class="text-left rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-4 hover:border-[var(--cloo-color-info)] hover:bg-[var(--cloo-color-info)]/5 focus:outline-none focus:ring-2 focus:ring-[var(--cloo-color-info)] disabled:opacity-50 disabled:cursor-not-allowed transition"
					on:click={handleDbCardClick}
					disabled={!canWrite || dbJobInProgress}
				>
					<div class="flex items-center gap-2 mb-2">
						<Cube className="size-5 text-gray-500 dark:text-gray-400" strokeWidth="1.75" />
						<span class="text-sm font-medium text-gray-900 dark:text-gray-100">
							{$i18n.t('Import from database')}
						</span>
					</div>
					<div class="text-xs text-gray-500 dark:text-gray-400 leading-relaxed">
						{$i18n.t(
							'Extract glossary entries from a DbSphere column. LLM enrichment optional.'
						)}
					</div>
					{#if dbJobInProgress}
						<div class="mt-2 text-[10px] text-amber-600 dark:text-amber-400">
							{$i18n.t('Extraction is in progress. Wait for completion before starting a new one.')}
						</div>
					{/if}
				</button>

				<!-- File card -->
				<button
					type="button"
					class="text-left rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-4 hover:border-[var(--cloo-color-info)] hover:bg-[var(--cloo-color-info)]/5 focus:outline-none focus:ring-2 focus:ring-[var(--cloo-color-info)] disabled:opacity-50 disabled:cursor-not-allowed transition"
					on:click={handleFileCardClick}
					disabled={!canWrite}
				>
					<div class="flex items-center gap-2 mb-2">
						<Document className="size-5 text-gray-500 dark:text-gray-400" strokeWidth="1.75" />
						<span class="text-sm font-medium text-gray-900 dark:text-gray-100">
							{$i18n.t('Import from file')}
						</span>
					</div>
					<div class="text-xs text-gray-500 dark:text-gray-400 leading-relaxed">
						{$i18n.t('Upload XLSX, CSV, Markdown, or JSON. Column mapping + optional AI rule.')}
					</div>
				</button>
			</div>
		</div>
	{:else if mode === 'file'}
		<BulkImportFileStage
			{glossaryId}
			{aiModelId}
			initialFile={pendingInitialFile}
			on:back={handleStageBack}
			on:completed={handleFileCompleted}
		/>
	{:else if mode === 'db'}
		<BulkImportDbStage
			{glossaryId}
			{aiModelId}
			on:back={handleStageBack}
			on:job-started={handleDbJobStarted}
		/>
	{/if}
</Modal>

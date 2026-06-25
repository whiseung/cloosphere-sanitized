<script lang="ts">
	import dayjs from 'dayjs';
	import relativeTime from 'dayjs/plugin/relativeTime';
	import { getContext, onMount } from 'svelte';
	import { toast } from 'svelte-sonner';

	import {
		deleteDocumentTemplate,
		downloadDocumentTemplate,
		getDocumentTemplatesConfig,
		uploadDocumentTemplate,
		type DocumentTemplateKind,
		type DocumentTemplatesConfig
	} from '$lib/apis/document-templates';
	import Badge from '$lib/components/common/Badge.svelte';
	import Button from '$lib/components/common/Button.svelte';
	import LabelBase from '$lib/components/common/LabelBase.svelte';
	import { formatBackendError } from '$lib/utils/error';

	dayjs.extend(relativeTime);

	const i18n = getContext('i18n') as any;

	type TemplateItem = {
		kind: DocumentTemplateKind;
		labelKey: string;
		descKey: string;
		accept: string;
	};

	// i18n parser hints — these keys are dynamic above, this block ensures they're picked up.
	void [
		$i18n.t('Document Templates'),
		$i18n.t('Upload PPT template'),
		$i18n.t('Upload Word template'),
		$i18n.t('Upload Excel template'),
		$i18n.t('PowerPoint template for slide generation (PPTX)'),
		$i18n.t('Word template for document generation (DOCX)'),
		$i18n.t('Excel template for spreadsheet generation (XLSX)'),
		$i18n.t('Document template uploaded'),
		$i18n.t('Failed to upload document template'),
		$i18n.t('Template file is corrupt or not a valid Office document'),
		$i18n.t('Document template removed'),
		$i18n.t('Failed to remove document template'),
		$i18n.t('Failed to download document template'),
		$i18n.t('No template set'),
		$i18n.t('Use empty master templates'),
		$i18n.t('Applied only to agents with document_tools enabled'),
		$i18n.t('Download'),
		$i18n.t('Upload'),
		$i18n.t('Replace'),
		$i18n.t('Remove template'),
		$i18n.t('Click or drag and drop to upload'),
		$i18n.t('Custom'),
		$i18n.t('Not set')
	];

	// MS Office 색상 컨벤션 — PPT 주황, Word 파랑, Excel 초록.
	// raw HTML 대신 작은 색칠된 chip 으로 파일 종류 시각화 (전용 SVG 아이콘 없음).
	const KIND_COLORS: Record<DocumentTemplateKind, string> = {
		pptx: 'bg-[#D24726]',
		docx: 'bg-[#185ABD]',
		xlsx: 'bg-[#107C41]'
	};
	const KIND_BADGE: Record<DocumentTemplateKind, string> = {
		pptx: 'PPT',
		docx: 'DOC',
		xlsx: 'XLS'
	};

	const TEMPLATE_ITEMS: TemplateItem[] = [
		{
			kind: 'pptx',
			labelKey: 'Upload PPT template',
			descKey: 'PowerPoint template for slide generation (PPTX)',
			accept:
				'.pptx,application/vnd.openxmlformats-officedocument.presentationml.presentation'
		},
		{
			kind: 'docx',
			labelKey: 'Upload Word template',
			descKey: 'Word template for document generation (DOCX)',
			accept:
				'.docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document'
		},
		{
			kind: 'xlsx',
			labelKey: 'Upload Excel template',
			descKey: 'Excel template for spreadsheet generation (XLSX)',
			accept:
				'.xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
		}
	];

	let templates: Partial<DocumentTemplatesConfig> = {};
	let loading = false;
	let draggingOver: Record<string, boolean> = {};
	let fileInputs: Record<string, HTMLInputElement | null> = {};

	const loadConfig = async () => {
		try {
			templates = await getDocumentTemplatesConfig(localStorage.token);
		} catch (e) {
			console.error(e);
		}
	};

	const triggerFilePick = (kind: DocumentTemplateKind) => {
		fileInputs[kind]?.click();
	};

	const handleFileInput = async (kind: DocumentTemplateKind, e: Event) => {
		const input = e.target as HTMLInputElement | null;
		const file = input?.files?.[0];
		if (!file) return;
		await uploadFile(kind, file);
		if (input) input.value = '';
	};

	const handleDragOver = (e: DragEvent, kind: DocumentTemplateKind) => {
		e.preventDefault();
		draggingOver[kind] = true;
	};

	const handleDragLeave = (e: DragEvent, kind: DocumentTemplateKind) => {
		e.preventDefault();
		draggingOver[kind] = false;
	};

	const handleDrop = async (e: DragEvent, kind: DocumentTemplateKind) => {
		e.preventDefault();
		draggingOver[kind] = false;
		const file = e.dataTransfer?.files?.[0];
		if (!file) return;
		await uploadFile(kind, file);
	};

	const uploadFile = async (kind: DocumentTemplateKind, file: File) => {
		const ext = '.' + kind;
		if (!file.name.toLowerCase().endsWith(ext)) {
			toast.error($i18n.t('Failed to upload document template'));
			return;
		}
		loading = true;
		try {
			await uploadDocumentTemplate(localStorage.token, kind, file);
			// 서버에서 다시 가져와 카드 즉시 갱신 (Svelte reactivity 의존 최소화)
			await loadConfig();
			toast.success($i18n.t('Document template uploaded'));
		} catch (e: any) {
			const detail = formatBackendError(e, $i18n) ?? $i18n.t('Failed to upload document template');
			toast.error(detail);
			console.error(e);
		} finally {
			loading = false;
		}
	};

	const handleDelete = async (kind: DocumentTemplateKind) => {
		loading = true;
		try {
			await deleteDocumentTemplate(localStorage.token, kind);
			await loadConfig();
			toast.success($i18n.t('Document template removed'));
		} catch (e: any) {
			const detail = formatBackendError(e, $i18n) ?? $i18n.t('Failed to remove document template');
			toast.error(detail);
			console.error(e);
		} finally {
			loading = false;
		}
	};

	const handleDownload = async (kind: DocumentTemplateKind) => {
		loading = true;
		try {
			const blob = await downloadDocumentTemplate(localStorage.token, kind);
			const meta = templates[kind] ?? {};
			const filename = meta.original_filename || `template.${kind}`;
			const url = URL.createObjectURL(blob);
			const a = document.createElement('a');
			a.href = url;
			a.download = filename;
			document.body.appendChild(a);
			a.click();
			document.body.removeChild(a);
			URL.revokeObjectURL(url);
		} catch (e: any) {
			const detail = formatBackendError(e, $i18n) ?? $i18n.t('Failed to download document template');
			toast.error(detail);
			console.error(e);
		} finally {
			loading = false;
		}
	};

	onMount(loadConfig);
</script>

<div class="flex flex-col h-full text-sm">
	<div class="mt-0.5 space-y-3 overflow-y-scroll scrollbar-hidden h-full">
		<div class="mb-3.5">
			<div class="mb-2.5 text-base font-medium">{$i18n.t('Document Templates')}</div>

			<hr class="border-gray-100 dark:border-gray-850 my-2" />

			<div class="text-xs text-gray-500 dark:text-gray-400 space-y-1 mb-3">
				<div>{$i18n.t('Use empty master templates')}</div>
				<div>{$i18n.t('Applied only to agents with document_tools enabled')}</div>
			</div>

			<div class="grid grid-cols-1 md:grid-cols-3 gap-4">
				{#each TEMPLATE_ITEMS as item}
					{@const meta = templates[item.kind] ?? {}}
					{@const custom = !!templates[item.kind]?.is_custom}

					<div class="flex flex-col gap-2">
						<LabelBase label={$i18n.t(item.labelKey)} caption={$i18n.t(item.descKey)} size="md">
							<svelte:fragment slot="right">
								{#if custom}
									<Badge status="success" size="sm">{$i18n.t('Custom')}</Badge>
								{:else}
									<Badge status="secondary" size="sm">{$i18n.t('Not set')}</Badge>
								{/if}
							</svelte:fragment>
						</LabelBase>

						<input
							bind:this={fileInputs[item.kind]}
							type="file"
							accept={item.accept}
							hidden
							on:change={(e) => handleFileInput(item.kind, e)}
						/>

						<!-- svelte-ignore a11y-click-events-have-key-events -->
						<!-- svelte-ignore a11y-no-static-element-interactions -->
						<div
							role="button"
							tabindex="0"
							class="relative flex flex-col items-center justify-center rounded-lg border-2 border-dashed transition-all cursor-pointer p-4
								{draggingOver[item.kind]
								? 'border-blue-500 bg-blue-50 dark:bg-blue-900/20'
								: 'border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-gray-900 hover:border-gray-300 dark:hover:border-gray-700'}"
							style="min-height: 110px;"
							on:click={() => triggerFilePick(item.kind)}
							on:keydown={(e) => (e.key === 'Enter' ? triggerFilePick(item.kind) : null)}
							on:dragover={(e) => handleDragOver(e, item.kind)}
							on:dragleave={(e) => handleDragLeave(e, item.kind)}
							on:drop={(e) => handleDrop(e, item.kind)}
						>
							{#if custom}
								<div class="flex flex-col items-center gap-1 text-center max-w-full">
									<div class="flex items-center gap-1.5 max-w-full min-w-0">
										<span
											class="shrink-0 inline-flex items-center justify-center w-7 h-7 rounded text-[9px] font-bold tracking-wide text-white {KIND_COLORS[
												item.kind
											]}"
											aria-hidden="true"
										>
											{KIND_BADGE[item.kind]}
										</span>
										<div class="text-sm font-medium truncate min-w-0" title={meta.original_filename}>
											{meta.original_filename}
										</div>
									</div>
									{#if meta.uploaded_at}
										<div class="text-xs text-gray-500 dark:text-gray-400">
											{dayjs((meta.uploaded_at ?? 0) * 1000).fromNow()}
										</div>
									{/if}
								</div>
							{:else}
								<div class="flex flex-col items-center gap-1 text-gray-500 dark:text-gray-400">
									<svg
										xmlns="http://www.w3.org/2000/svg"
										viewBox="0 0 24 24"
										fill="none"
										stroke="currentColor"
										stroke-width="1.5"
										class="w-6 h-6"
									>
										<path
											stroke-linecap="round"
											stroke-linejoin="round"
											d="M3 16.5v2.25A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75V16.5M16.5 12 12 16.5m0 0L7.5 12m4.5 4.5V3"
										/>
									</svg>
									<div class="text-xs">{$i18n.t('Click or drag and drop to upload')}</div>
									<div class="text-[10px] uppercase tracking-wide">.{item.kind}</div>
								</div>
							{/if}
						</div>

						<div class="flex items-center gap-2">
							<Button
								kind="outlined"
								size="sm"
								type="button"
								disabled={loading || !custom}
								on:click={() => handleDownload(item.kind)}
							>
								{$i18n.t('Download')}
							</Button>
							<Button
								kind="outlined"
								size="sm"
								type="button"
								disabled={loading}
								on:click={() => triggerFilePick(item.kind)}
							>
								{custom ? $i18n.t('Replace') : $i18n.t('Upload')}
							</Button>
							{#if custom}
								<Button
									kind="outlined"
									size="sm"
									status="error"
									type="button"
									disabled={loading}
									on:click={() => handleDelete(item.kind)}
								>
									{$i18n.t('Remove template')}
								</Button>
							{/if}
						</div>

						{#if !custom}
							<div class="text-[11px] text-gray-400 dark:text-gray-500">
								{$i18n.t('No template set')}
							</div>
						{/if}
					</div>
				{/each}
			</div>
		</div>
	</div>
</div>

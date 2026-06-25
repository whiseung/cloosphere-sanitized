<script lang="ts">
	import { createEventDispatcher, getContext } from 'svelte';
	const i18n = getContext('i18n');
	const dispatch = createEventDispatcher();

	import FileItem from '$lib/components/common/FileItem.svelte';
	import Checkbox from '$lib/components/common/Checkbox.svelte';
	import Badge from '$lib/components/common/Badge.svelte';
	import Button from '$lib/components/common/Button.svelte';

	export let selectedFileId = null;
	export let files = [];
	export let small = false;
	export let selectable = false;
	export let checkedFileIds: Set<string> = new Set();
	/** filter_schema가 있으면 각 파일 행에 [메타] 버튼 표시 */
	export let filterSchema: any[] = [];
	/** 파일별 현재 저장된 메타데이터 (메타 설정 여부 표시용) */
	export let fileMetadataValues: Record<string, Record<string, any>> = {};
	/** 현재 AI 추출 중인 파일 ID 목록 */
	export let extractingFileIds: Set<string> = new Set();

	type MetaStatus = 'complete' | 'missing_required' | 'partial' | 'empty';
	type LegacyBadgeType = 'info' | 'success' | 'warning' | 'error' | 'muted';

	const META_STATUS_BADGE: Record<MetaStatus, LegacyBadgeType> = {
		complete: 'success',
		missing_required: 'warning',
		partial: 'info',
		empty: 'muted'
	};
	const META_STATUS_LABEL_KEY: Record<MetaStatus, string> = {
		complete: 'Metadata complete ({{filled}}/{{total}})',
		missing_required: 'Required metadata missing ({{filled}}/{{total}})',
		partial: 'Metadata partially set ({{filled}}/{{total}})',
		empty: 'No metadata extracted'
	};

	function isFieldFilled(val: any): boolean {
		if (Array.isArray(val)) return val.length > 0;
		return val !== undefined && val !== null && val !== '';
	}

	function getMetaInfo(fileId: string): { status: MetaStatus; filled: number; total: number } {
		const total = filterSchema.length;
		if (!total) return { status: 'empty', filled: 0, total: 0 };

		const meta = fileMetadataValues[fileId];
		const requiredFields = filterSchema.filter((f) => f.required);

		if (!meta) {
			return {
				status: requiredFields.length > 0 ? 'missing_required' : 'empty',
				filled: 0,
				total
			};
		}

		const filled = filterSchema.filter((f) => isFieldFilled(meta[f.slot])).length;
		const missingRequired = requiredFields.some((f) => !isFieldFilled(meta[f.slot]));

		if (missingRequired) return { status: 'missing_required', filled, total };
		if (filled === total) return { status: 'complete', filled, total };
		if (filled > 0) return { status: 'partial', filled, total };
		return { status: 'empty', filled, total };
	}

	/** 요약 펼침 상태: file.id → boolean */
	let expandedSummaries: Record<string, boolean> = {};

	function toggleSummary(fileId: string) {
		expandedSummaries[fileId] = !expandedSummaries[fileId];
		expandedSummaries = expandedSummaries;
	}
</script>

<div class=" max-h-full flex flex-col w-full">
	{#each files as file}
		{@const summary = file?.meta?.summary}
		{@const job = file?.data?.processing_job}
		{@const isFailed = job?.status === 'failed'}
		{@const isProcessing =
			file.status === 'uploading' ||
			file.status === 'processing' ||
			job?.status === 'pending' ||
			job?.status === 'processing' ||
			job?.status === 'queued'}
		<div class="mt-1 px-3">
			<div class="flex items-center gap-2">
				{#if selectable}
					<div class="shrink-0" on:click|stopPropagation>
						<Checkbox
							state={checkedFileIds.has(file.id) ? 'checked' : 'unchecked'}
							on:change={() => {
								if (checkedFileIds.has(file.id)) {
									checkedFileIds.delete(file.id);
								} else {
									checkedFileIds.add(file.id);
								}
								checkedFileIds = checkedFileIds;
							}}
						/>
					</div>
				{/if}
				<div class="flex-1 min-w-0">
					<FileItem
						className="w-full"
						colorClassName="{isFailed
							? 'bg-red-50/50 dark:bg-red-950/20 border-l-2 border-l-red-400'
							: selectedFileId === file.id
								? ' bg-gray-50 dark:bg-gray-850'
								: 'bg-transparent'} hover:bg-gray-50 dark:hover:bg-gray-850 transition"
						{small}
						item={file}
						name={file?.name ?? file?.meta?.name}
						type="file"
						size={file?.size ?? file?.meta?.size ?? ''}
						loading={isProcessing}
						dismissible={file.status !== 'uploading'}
						on:click={() => {
							if (file.status === 'uploading' || file.status === 'processing') {
								return;
							}
							dispatch('click', file.id);
						}}
						on:dismiss={() => {
							if (file.status === 'uploading') {
								return;
							}
							dispatch('delete', file.id);
						}}
					/>
					{#if isFailed}
						<div class="flex items-center gap-2 ml-1 mt-0.5 mb-1">
							<span class="text-[10px] text-red-500 dark:text-red-400 truncate flex-1" title={job.error}>
								{job.error?.length > 50 ? job.error.slice(0, 50) + '...' : job.error || 'Processing failed'}
							</span>
							<Button
								kind="text"
								size="sm"
								on:click={(e) => { e.stopPropagation(); dispatch('retry', file.id); }}
							>
								{$i18n.t('Retry')}
							</Button>
						</div>
					{/if}
				</div>

				{#if isFailed}
					<span class="shrink-0" title={job?.error || $i18n.t('Failed')}>
						<Badge type="error" size="sm">{$i18n.t('Failed')}</Badge>
					</span>
				{:else if isProcessing}
					<span class="shrink-0">
						<Badge type="warning" size="sm" loading>{$i18n.t('Processing')}</Badge>
					</span>
				{/if}

				{#if summary && !isProcessing}
					<!-- 요약 토글 버튼 -->
					<div class="shrink-0">
						<Button
							kind="text"
							size="sm"
							className={expandedSummaries[file.id]
								? 'text-blue-500 dark:text-blue-400 bg-blue-50 dark:bg-blue-950/30'
								: ''}
							title={$i18n.t('File Summary')}
							on:click={(e) => { e.stopPropagation(); toggleSummary(file.id); }}
						>
							{$i18n.t('Summary')}
						</Button>
					</div>
				{/if}

				{#if filterSchema.length > 0 && !isProcessing}
					{#if extractingFileIds.has(file.id)}
						<span class="shrink-0" title={$i18n.t('Extracting metadata...')}>
							<Badge type="info" size="sm" loading>{$i18n.t('Extracting')}</Badge>
						</span>
					{:else}
						{@const info = getMetaInfo(file.id)}
						<span class="shrink-0" title={$i18n.t(META_STATUS_LABEL_KEY[info.status], { filled: info.filled, total: info.total })}>
							<Badge type={META_STATUS_BADGE[info.status]} size="sm">
								{info.filled}/{info.total}
							</Badge>
						</span>
					{/if}
				{/if}
			</div>

			{#if summary && expandedSummaries[file.id]}
				<div class="mt-1 ml-2 mr-1 mb-2 px-3 py-2 rounded-lg
					bg-gray-50 dark:bg-gray-850 border border-gray-100 dark:border-gray-800">
					<p class="text-xs text-gray-600 dark:text-gray-400 leading-relaxed whitespace-pre-wrap">
						{summary}
					</p>
				</div>
			{/if}
		</div>
	{/each}
</div>

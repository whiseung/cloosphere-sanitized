<script lang="ts">
	import { getContext } from 'svelte';
	import { toast } from 'svelte-sonner';

	import Modal from '$lib/components/common/Modal.svelte';
	import Button from '$lib/components/common/Button.svelte';
	import Switch from '$lib/components/common/Switch.svelte';
	import Input from '$lib/components/common/Input.svelte';

	import type { DocumentProfile, DocumentProfileForm } from '$lib/apis/document-profiles';
	import type { ExtractionEngineProfile } from '$lib/apis/extraction-engines';
	import { models } from '$lib/stores';
	import { formatBackendError } from '$lib/utils/error';

	const i18n = getContext('i18n');

	export let show = false;
	export let profile: DocumentProfile | null = null;
	export let engines: ExtractionEngineProfile[] = [];
	export let onSave: (data: DocumentProfileForm) => Promise<void> = async () => {};
	export let onDelete: (() => Promise<void>) | null = null;

	let name = '';
	let textSplitter = '';
	let chunkSize = 1000;
	let chunkOverlap = 100;
	let config: Record<string, any> = {};
	let defaultEngineId = '';

	// 확장자별 매핑 UI — 한 행이 "포맷 그룹" 또는 "사용자 정의 단일 확장자"를
	// 가리킨다. 저장 시 그룹은 자기가 포함한 모든 확장자로 expand 되어
	// extension_engine_map JSON 에 개별 entry 로 들어간다.
	type MappingRow = { groupId: string; customExt: string; engine_id: string };
	let mappingRows: MappingRow[] = [];

	// 포맷 그룹 — 사용자가 한 줄에 한 그룹씩 선택. 같은 그룹의 모든 확장자는
	// 자동으로 같은 엔진에 매핑된다.
	const EXTENSION_GROUPS: { id: string; label: string; exts: string[] }[] = [
		{ id: 'pdf', label: 'PDF', exts: ['.pdf'] },
		{ id: 'word', label: 'Word', exts: ['.doc', '.docx'] },
		{ id: 'excel', label: 'Excel', exts: ['.xls', '.xlsx'] },
		{ id: 'powerpoint', label: 'PowerPoint', exts: ['.ppt', '.pptx'] },
		{
			id: 'image',
			label: 'Image',
			exts: ['.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.tiff', '.tif']
		},
		{ id: 'html', label: 'HTML', exts: ['.htm', '.html'] },
		{
			id: 'text',
			label: 'Text',
			exts: ['.txt', '.md', '.csv', '.xml', '.rst']
		},
		{ id: 'email', label: 'Email', exts: ['.msg'] },
		{ id: 'epub', label: 'EPUB', exts: ['.epub'] }
	];
	const CUSTOM_SENTINEL = '__custom__';

	function rowsFromMap(map: Record<string, string> | null): MappingRow[] {
		if (!map || Object.keys(map).length === 0) return [];
		const remaining = { ...map };
		const rows: MappingRow[] = [];

		// 그룹 row 추출: 그룹의 절반 이상 확장자가 같은 engine_id 면 dominant 엔진을
		// 그룹 row 로 표현. 나머지(소수 deviation)는 custom row 로 별도 표시 — 이렇게
		// 하면 "Image 그룹 → A, 단 .gif 만 별도로 B" 같은 구성이 자연스럽게 보존된다.
		for (const group of EXTENSION_GROUPS) {
			const count: Record<string, number> = {};
			for (const ext of group.exts) {
				const eid = remaining[ext];
				if (eid) count[eid] = (count[eid] || 0) + 1;
			}
			const entries = Object.entries(count).sort((a, b) => b[1] - a[1]);
			if (entries.length === 0) continue;
			const [dominantEngine, dominantCount] = entries[0];
			if (dominantCount >= Math.ceil(group.exts.length / 2)) {
				rows.push({ groupId: group.id, customExt: '', engine_id: dominantEngine });
				for (const ext of group.exts) {
					if (remaining[ext] === dominantEngine) delete remaining[ext];
				}
			}
		}

		// 남은 확장자(그룹 dominant 와 다른 엔진을 가진 deviation, 또는 다수결 실패) → custom row
		for (const [ext, engine_id] of Object.entries(remaining)) {
			rows.push({ groupId: CUSTOM_SENTINEL, customExt: ext, engine_id });
		}
		return rows;
	}

	function buildMapFromRows(
		rows: MappingRow[]
	): { mapping: Record<string, string>; error: string | null } {
		// 두 단계: 1) 그룹 row 를 먼저 expand. 2) custom row 로 overwrite — custom 우선.
		const groupMapping: Record<string, string> = {};
		const customMapping: Record<string, string> = {};
		const seenGroupIds = new Set<string>();

		for (const row of rows) {
			if (!row.engine_id && !row.groupId && !row.customExt) continue;
			if (!row.engine_id || !row.groupId) {
				return {
					mapping: {},
					error: $i18n.t('Each mapping row must have both an extension and an engine.')
				};
			}
			if (row.groupId === CUSTOM_SENTINEL) {
				const ext = normalizeExt(row.customExt);
				if (!ext) {
					return {
						mapping: {},
						error: $i18n.t('Each mapping row must have both an extension and an engine.')
					};
				}
				if (customMapping[ext]) {
					return { mapping: {}, error: $i18n.t('Duplicate extension: {{ext}}', { ext }) };
				}
				customMapping[ext] = row.engine_id;
			} else {
				if (seenGroupIds.has(row.groupId)) {
					const group = EXTENSION_GROUPS.find((g) => g.id === row.groupId);
					return {
						mapping: {},
						error: $i18n.t('Duplicate group: {{label}}', { label: group?.label || row.groupId })
					};
				}
				seenGroupIds.add(row.groupId);
				const group = EXTENSION_GROUPS.find((g) => g.id === row.groupId);
				if (group) {
					for (const ext of group.exts) {
						groupMapping[ext] = row.engine_id;
					}
				}
			}
		}

		// custom 행이 그룹 expansion 을 덮어쓴다 (확장자 단위 우선순위 보장).
		return { mapping: { ...groupMapping, ...customMapping }, error: null };
	}

	let loading = false;
	let _initialized = false;

	$: {
		if (show && !_initialized) {
			_initialized = true;
			if (profile) {
				name = profile.name;
				textSplitter = profile.text_splitter;
				chunkSize = profile.chunk_size;
				chunkOverlap = profile.chunk_overlap;
				config = { ...(profile.config || {}) };
				mappingRows = rowsFromMap(profile.extension_engine_map);
				defaultEngineId = profile.default_engine_id || '';
			} else {
				name = '';
				textSplitter = '';
				chunkSize = 1000;
				chunkOverlap = 100;
				config = {};
				mappingRows = [];
				defaultEngineId = '';
			}
		}
		if (!show) {
			_initialized = false;
		}
	}

	function addMappingRow() {
		mappingRows = [...mappingRows, { groupId: '', customExt: '', engine_id: '' }];
	}

	function removeMappingRow(idx: number) {
		mappingRows = mappingRows.filter((_, i) => i !== idx);
	}

	function normalizeExt(raw: string): string {
		const v = raw.trim().toLowerCase();
		if (!v) return '';
		return v.startsWith('.') ? v : `.${v}`;
	}

	function handleGroupSelect(idx: number, value: string) {
		mappingRows[idx].groupId = value;
		if (value !== CUSTOM_SENTINEL) {
			mappingRows[idx].customExt = '';
		}
		mappingRows = mappingRows;
	}

	const submitHandler = async () => {
		if (!name.trim()) {
			toast.error($i18n.t('Name is required'));
			return;
		}

		const built = buildMapFromRows(mappingRows);
		if (built.error) {
			toast.error(built.error);
			return;
		}
		const mapping = built.mapping;

		loading = true;
		try {
			await onSave({
				name: name.trim(),
				text_splitter: textSplitter,
				chunk_size: chunkSize,
				chunk_overlap: chunkOverlap,
				config,
				extension_engine_map: Object.keys(mapping).length > 0 ? mapping : null,
				default_engine_id: defaultEngineId || null
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
				{profile ? $i18n.t('Edit Document Processing Profile') : $i18n.t('Add Document Processing Profile')}
			</div>
			<button class="self-center" on:click={() => { show = false; }}>
				<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-5 h-5">
					<path d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z" />
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
					placeholder={$i18n.t('e.g. Tika + Large Chunks')}
					required
				/>
			</div>

			<!-- Default Engine -->
			<div>
				<div class="flex w-full justify-between items-center">
					<div class="text-xs font-medium">{$i18n.t('Default Engine')}</div>
					<select
						class="dark:bg-gray-900 w-fit pr-8 rounded-sm px-2 text-xs bg-transparent outline-hidden text-right"
						bind:value={defaultEngineId}
					>
						<option value="">{$i18n.t('Built-in Engine')}</option>
						{#each engines as eng}
							<option value={eng.id}>{eng.name} ({eng.engine_type})</option>
						{/each}
					</select>
				</div>
				<div class="text-[11px] text-gray-400 dark:text-gray-500 mt-1">
					{$i18n.t(
						'Engine used for extensions not listed in the mapping below.'
					)}
				</div>
			</div>

			<hr class="border-gray-100 dark:border-gray-850" />

			<!-- Extension -> Engine Mapping -->
			<div>
				<div class="flex w-full justify-between items-center mb-1">
					<div class="text-xs font-medium">{$i18n.t('Extension → Engine Mapping')}</div>
					<Button kind="outlined" size="sm" type="button" on:click={addMappingRow}>
						{$i18n.t('Add Extension')}
					</Button>
				</div>
				<div class="text-[11px] text-gray-400 dark:text-gray-500 mb-2">
					{$i18n.t(
						'Only extensions listed here use the selected engine. Anything else uses the Default Engine above.'
					)}
				</div>

				{#if mappingRows.length === 0}
					<div
						class="text-[11px] text-gray-400 dark:text-gray-500 italic py-2 text-center border border-dashed border-gray-200 dark:border-gray-700 rounded"
					>
						{$i18n.t(
							'No per-extension overrides — all files use the Default Engine.'
						)}
					</div>
				{:else}
					<div class="space-y-1.5">
						{#each mappingRows as row, idx (idx)}
							<div class="flex gap-2 items-center">
								<div class="flex-[3] min-w-0 flex gap-1.5">
									<select
										class="flex-1 min-w-0 rounded-lg py-1.5 px-2 text-sm bg-gray-50 dark:bg-gray-850 dark:text-gray-300 outline-hidden"
										value={row.groupId}
										title={EXTENSION_GROUPS.find((g) => g.id === row.groupId)?.exts.join(
											', '
										) || ''}
										on:change={(e) => {
											const target = e.currentTarget;
											handleGroupSelect(idx, target.value);
										}}
									>
										<option value="">{$i18n.t('Select format')}</option>
										{#each EXTENSION_GROUPS as group}
											<option value={group.id} title={group.exts.join(', ')}
												>{group.label}</option
											>
										{/each}
										<option value={CUSTOM_SENTINEL}
											>{$i18n.t('Custom extension...')}</option
										>
									</select>
									{#if row.groupId === CUSTOM_SENTINEL}
										<div class="w-24 shrink-0">
											<Input
												size="sm"
												placeholder=".foo"
												bind:value={row.customExt}
												on:blur={() => {
													row.customExt = normalizeExt(row.customExt);
													mappingRows = mappingRows;
												}}
											/>
										</div>
									{/if}
								</div>
								<select
									class="flex-[7] min-w-0 rounded-lg py-1.5 px-2 text-sm bg-gray-50 dark:bg-gray-850 dark:text-gray-300 outline-hidden"
									bind:value={row.engine_id}
								>
									<option value="">{$i18n.t('Select an engine')}</option>
									<option value="native">{$i18n.t('Built-in Engine')}</option>
									{#each engines as eng}
										<option value={eng.id}>{eng.name} ({eng.engine_type})</option>
									{/each}
								</select>
								<button
									type="button"
									class="text-gray-400 hover:text-red-500 dark:hover:text-red-400 p-1"
									on:click={() => removeMappingRow(idx)}
									aria-label={$i18n.t('Remove')}
								>
									<svg
										xmlns="http://www.w3.org/2000/svg"
										viewBox="0 0 20 20"
										fill="currentColor"
										class="w-4 h-4"
									>
										<path
											d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z"
										/>
									</svg>
								</button>
							</div>
						{/each}
					</div>
				{/if}
			</div>

			<hr class="border-gray-100 dark:border-gray-850" />

			<!-- Text Splitter -->
			<div class="flex w-full justify-between items-center">
				<div class="text-xs font-medium">{$i18n.t('Text Splitter')}</div>
				<select
					class="dark:bg-gray-900 w-fit pr-8 rounded-sm px-2 text-xs bg-transparent outline-hidden text-right"
					bind:value={textSplitter}
				>
					<option value="">{$i18n.t('Default')} ({$i18n.t('Character')})</option>
					<option value="token">{$i18n.t('Token')} ({$i18n.t('Tiktoken')})</option>
					<option value="semantic">{$i18n.t('Semantic')}</option>
				</select>
			</div>
			<div class="text-[11px] text-gray-400 dark:text-gray-500">
				{#if textSplitter === '' || textSplitter === 'character'}
					{$i18n.t('Splits text by character count with overlap. Simple and fast.')}
				{:else if textSplitter === 'token'}
					{$i18n.t('Splits by token count (tiktoken). More accurate for LLM context limits.')}
				{:else if textSplitter === 'semantic'}
					{$i18n.t('Splits at semantic boundaries using embedding similarity. Chunks preserve complete ideas instead of cutting mid-sentence.')}
				{/if}
			</div>

			<!-- Semantic Chunking options -->
			{#if textSplitter === 'semantic'}
				<div class="flex gap-1.5 w-full">
					<div class="w-full">
						<div class="text-xs font-medium mb-1">{$i18n.t('Threshold Type')}</div>
						<select
							class="w-full rounded-lg py-1.5 px-2 text-sm bg-gray-50 dark:bg-gray-850 dark:text-gray-300 outline-hidden"
							bind:value={config.semantic_threshold_type}
						>
							<option value="percentile">{$i18n.t('Percentile (recommended)')}</option>
							<option value="standard_deviation">{$i18n.t('Standard Deviation')}</option>
							<option value="interquartile">{$i18n.t('Interquartile Range')}</option>
						</select>
						<div class="text-[11px] text-gray-400 dark:text-gray-500 mt-0.5">
							{#if (config.semantic_threshold_type || 'percentile') === 'percentile'}
								{$i18n.t('Split when similarity drops below this percentile. Higher = fewer, larger chunks.')}
							{:else if config.semantic_threshold_type === 'standard_deviation'}
								{$i18n.t('Split when similarity drop exceeds N standard deviations from mean.')}
							{:else if config.semantic_threshold_type === 'interquartile'}
								{$i18n.t('Split when similarity drop exceeds N × IQR from median. Robust to outliers.')}
							{/if}
						</div>
					</div>
					<div class="w-full">
						<div class="text-xs font-medium mb-1">{$i18n.t('Threshold')}</div>
						<input
							class="w-full rounded-lg py-1.5 px-4 text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden"
							type="number"
							bind:value={config.semantic_threshold}
							min="0"
							step="1"
							placeholder={config.semantic_threshold_type === 'standard_deviation' ? '3' : config.semantic_threshold_type === 'interquartile' ? '1.5' : '95'}
						/>
						<div class="text-[11px] text-gray-400 dark:text-gray-500 mt-0.5">
							{#if (config.semantic_threshold_type || 'percentile') === 'percentile'}
								{$i18n.t('Recommended: 85-95. Higher = fewer splits.')}
							{:else if config.semantic_threshold_type === 'standard_deviation'}
								{$i18n.t('Recommended: 1-3. Higher = fewer splits.')}
							{:else if config.semantic_threshold_type === 'interquartile'}
								{$i18n.t('Recommended: 1.0-2.0. Higher = fewer splits.')}
							{/if}
						</div>
					</div>
				</div>
				<div class="w-full">
					<div class="text-xs font-medium mb-1">{$i18n.t('Chunk Overlap')}</div>
					<input
						class="w-full rounded-lg py-1.5 px-4 text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden"
						type="number"
						bind:value={chunkOverlap}
						min="0"
						placeholder="100"
					/>
					<div class="text-[11px] text-gray-400 dark:text-gray-500 mt-0.5">
						{$i18n.t('Characters from previous chunk prepended to current. Helps preserve context across boundaries.')}
					</div>
				</div>
			{/if}

			<!-- Chunk Size / Overlap (not shown for semantic) -->
			{#if textSplitter !== 'semantic'}
			<div class="flex gap-1.5 w-full">
				<div class="w-full">
					<div class="text-xs font-medium mb-1">{$i18n.t('Chunk Size')}</div>
					<input
						class="w-full rounded-lg py-1.5 px-4 text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden"
						type="number"
						bind:value={chunkSize}
						min="0"
					/>
				</div>
				<div class="w-full">
					<div class="text-xs font-medium mb-1">{$i18n.t('Chunk Overlap')}</div>
					<input
						class="w-full rounded-lg py-1.5 px-4 text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden"
						type="number"
						bind:value={chunkOverlap}
						min="0"
					/>
				</div>
			</div>
			{/if}

			<!-- Token Limits (embedding safety net, applies to all splitters) -->
			<div class="flex gap-1.5 w-full">
				<div class="w-full">
					<div class="text-xs font-medium mb-1">{$i18n.t('Min Tokens per Chunk')}</div>
					<input
						class="w-full rounded-lg py-1.5 px-4 text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden"
						type="number"
						bind:value={config.chunk_min_tokens}
						min="0"
						placeholder="0"
					/>
					<div class="text-[11px] text-gray-400 dark:text-gray-500 mt-0.5">
						{$i18n.t('Chunks smaller than this are merged with the next chunk. Leave empty or 0 to disable.')}
					</div>
				</div>
				<div class="w-full">
					<div class="text-xs font-medium mb-1">{$i18n.t('Max Tokens per Chunk')}</div>
					<input
						class="w-full rounded-lg py-1.5 px-4 text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden"
						type="number"
						bind:value={config.chunk_max_tokens}
						min="0"
						placeholder="2000"
					/>
					<div class="text-[11px] text-gray-400 dark:text-gray-500 mt-0.5">
						{$i18n.t('Chunks exceeding this token count are re-split before embedding, preventing embedding API failures. Leave empty for the global default; 0 disables.')}
					</div>
				</div>
			</div>

			<hr class="border-gray-100 dark:border-gray-850" />

			<!-- Preserve Tables -->
			<div class="flex w-full justify-between items-center">
				<div class="text-xs font-medium">{$i18n.t('Preserve Tables')}</div>
				<Switch bind:state={config.preserve_tables} />
			</div>
			<div class="text-[11px] text-gray-400 dark:text-gray-500">
				{$i18n.t('Keep tables intact during chunking by attaching them to the preceding text chunk.')}
			</div>

			<hr class="border-gray-100 dark:border-gray-850" />

			<!-- Contextual Chunking -->
			<div class="flex w-full justify-between items-center">
				<div class="text-xs font-medium">{$i18n.t('Contextual Chunking')}</div>
				<Switch bind:state={config.contextual_chunking_enabled} />
			</div>
			{#if config.contextual_chunking_enabled}
				<div>
					<div class="text-xs font-medium mb-1">{$i18n.t('Context Model')}</div>
					<select
						class="w-full rounded-lg text-sm bg-gray-50 dark:bg-gray-850 dark:text-gray-300 outline-hidden py-1.5 px-2"
						bind:value={config.contextual_chunking_model}
					>
						<option value="">{$i18n.t('Select a model')}</option>
						{#each $models.filter((m) => !m.base_model_id && !m.preset && !(m.arena ?? false)) as model}
							<option value={model.id}>{model.name}</option>
						{/each}
					</select>
				</div>
				<div class="text-[11px] text-gray-400 dark:text-gray-500">
					{$i18n.t('Adds context summary to each chunk for better retrieval. Increases processing cost.')}
				</div>
			{/if}

			<!-- Actions -->
			<div class="flex justify-between pt-2">
				<div>
					{#if profile && onDelete}
						<Button kind="outlined" size="sm" on:click={async () => { if (onDelete) { await onDelete(); show = false; } }}>
							{$i18n.t('Delete')}
						</Button>
					{/if}
				</div>
				<div class="flex gap-2">
					<Button kind="outlined" size="sm" on:click={() => { show = false; }}>
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

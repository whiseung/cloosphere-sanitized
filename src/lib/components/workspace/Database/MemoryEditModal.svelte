<script lang="ts">
	import { toast } from 'svelte-sonner';
	import { createEventDispatcher, getContext } from 'svelte';
	import type { Readable } from 'svelte/store';
	const i18n = getContext<Readable<{ t: (key: string) => string }>>('i18n');
	const dispatch = createEventDispatcher();

	import Modal from '$lib/components/common/Modal.svelte';
	import Button from '$lib/components/common/Button.svelte';
	import Input from '$lib/components/common/Input.svelte';
	import Textarea from '$lib/components/common/Textarea.svelte';
	import Selector from '$lib/components/common/Selector.svelte';
	import CodeEditor from '$lib/components/common/CodeEditor.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import XMark from '$lib/components/icons/XMark.svelte';
	import DocumentDuplicate from '$lib/components/icons/DocumentDuplicate.svelte';
	import { format as formatSqlBase } from 'sql-formatter';
	import { copyToClipboard } from '$lib/utils';

	import { createDbSphereMemory, updateDbSphereMemory } from '$lib/apis/dbsphere';
	import type { MemoryItem, MemoryCreateForm, MemoryUpdateForm } from '$lib/apis/dbsphere';
	import type { SqlDialectName } from '$lib/utils/sqlDialect';

	export let show = false;
	export let dbsphereId: string;
	export let mode: 'view' | 'edit' | 'create' = 'view';
	export let memory: MemoryItem | null = null;
	export let canWrite: boolean = true;
	/** SQL syntax dialect for the CodeEditor inside this modal — fed by
	 * the parent so the highlighting matches the connected DB (Postgres,
	 * MySQL, Oracle, etc.). */
	export let dialect: SqlDialectName = 'standard';
	/** 문서 관련테이블 다중선택용 — 존재하는 테이블명 목록. */
	export let tables: string[] = [];

	let saving = false;
	let editing = false;

	type CreateType = 'sql_memory' | 'documentation' | 'sql_example';
	let createType: CreateType = 'sql_memory';

	// Create mode fields
	let question = '';
	let sql = '';
	let docContent = '';
	let docType = 'context';
	let docTitle = '';
	let exampleSql = '';
	let exampleDesc = '';
	let exampleUseCase = '';
	let exampleTags = '';

	// Edit mode fields
	let editTableDescription = '';
	let editColumns: {
		name: string;
		data_type: string;
		description: string;
		is_primary_key?: boolean;
		is_foreign_key?: boolean;
		foreign_table?: string;
	}[] = [];
	let editQuestion = '';
	let editSqlQuery = '';
	let editDocTitle = '';
	let editDocType = 'context';
	let editDocContent = '';
	let editDocRelatedTablesList: string[] = [];
	let tableAddValue = '';
	let editExampleSql = '';
	let editExampleDesc = '';
	let editExampleUseCase = '';

	$: if (show) {
		if (mode === 'create') {
			editing = false;
			resetCreateFields();
		} else if (mode === 'edit') {
			editing = true;
			initEditFields();
		} else {
			editing = false;
			initEditFields(); // also load for view-mode CodeEditor binding
		}
	}

	function initEditFields() {
		if (!memory) return;
		const meta = memory.metadata || {};

		if (memory.entity_type === 'ddl_schema') {
			editTableDescription = (meta.table_description as string) || '';
			try {
				const cols = meta.column_info_json
					? JSON.parse(String(meta.column_info_json))
					: [];
				editColumns = cols.map((c: Record<string, unknown>) => ({
					name: String(c.name ?? c.column_name ?? ''),
					data_type: String(c.data_type ?? ''),
					description: String(c.description ?? ''),
					is_primary_key: Boolean(c.is_primary_key),
					is_foreign_key: Boolean(c.is_foreign_key),
					foreign_table: c.foreign_table ? String(c.foreign_table) : undefined
				}));
			} catch {
				editColumns = [];
			}
		} else if (memory.entity_type === 'sql_memory') {
			editQuestion = memory.content || '';
			editSqlQuery = (meta.sql_query as string) || '';
		} else if (memory.entity_type === 'documentation') {
			editDocTitle = (meta.title as string) || '';
			editDocType = (meta.doc_type as string) || 'context';
			editDocContent = docBody(memory);
			editDocRelatedTablesList = docRelatedTables(memory);
			tableAddValue = '';
		} else if (memory.entity_type === 'sql_example') {
			editExampleSql = (meta.sql_query as string) || '';
			editExampleDesc = (meta.description as string) || memory.content || '';
			editExampleUseCase = (meta.use_case as string) || '';
		}
	}

	const startEditing = () => {
		initEditFields();
		editing = true;
	};
	const cancelEditing = () => {
		editing = false;
	};

	function resetCreateFields() {
		question = '';
		sql = '';
		docContent = '';
		docType = 'context';
		docTitle = '';
		editDocRelatedTablesList = [];
		tableAddValue = '';
		exampleSql = '';
		exampleDesc = '';
		exampleUseCase = '';
		exampleTags = '';
	}

	async function handleCreate() {
		saving = true;
		try {
			let form: MemoryCreateForm;
			if (createType === 'sql_memory') {
				if (!question.trim() || !sql.trim()) {
					toast.error($i18n.t('Question and SQL are required'));
					saving = false;
					return;
				}
				form = { entity_type: 'sql_memory', question: question.trim(), sql: sql.trim() };
			} else if (createType === 'documentation') {
				if (!docContent.trim()) {
					toast.error($i18n.t('Content is required'));
					saving = false;
					return;
				}
				form = {
					entity_type: 'documentation',
					content: docContent.trim(),
					doc_type: docType,
					title: docTitle.trim() || undefined,
					related_tables: editDocRelatedTablesList.length
						? editDocRelatedTablesList
						: undefined
				};
			} else {
				if (!exampleSql.trim() || !exampleDesc.trim()) {
					toast.error($i18n.t('SQL and description are required'));
					saving = false;
					return;
				}
				form = {
					entity_type: 'sql_example',
					sql: exampleSql.trim(),
					description: exampleDesc.trim(),
					use_case: exampleUseCase.trim() || undefined,
					tags: exampleTags.trim()
						? exampleTags.split(',').map((s) => s.trim())
						: undefined
				};
			}
			const result = await createDbSphereMemory(localStorage.token, dbsphereId, form);
			if (result) {
				toast.success($i18n.t('Memory created successfully'));
				resetCreateFields();
				// 인덱싱 지연으로 즉시 재조회엔 신규가 안 잡힘 → 생성 응답(MemoryItem)을 부모에
				// 넘겨 목록에 낙관적으로 바로 추가하게 한다.
				dispatch('save', { created: result });
				show = false;
			}
		} catch (e) {
			toast.error((e as string) || $i18n.t('Failed to create memory'));
		}
		saving = false;
	}

	async function handleUpdate() {
		if (!memory) return;
		saving = true;
		try {
			let form: MemoryUpdateForm = {};
			if (memory.entity_type === 'ddl_schema') {
				form = {
					metadata: {
						table_description: editTableDescription,
						column_info_json: JSON.stringify(editColumns)
					}
				};
			} else if (memory.entity_type === 'sql_memory') {
				form = { content: editQuestion, metadata: { sql_query: editSqlQuery } };
			} else if (memory.entity_type === 'documentation') {
				form = {
					content: editDocContent,
					metadata: {
						title: editDocTitle,
						doc_type: editDocType,
						// content 가 편집 시 clean 본문으로 덮어써지므로 doc_content 도 동기화.
						doc_content: editDocContent,
						related_tables_json: JSON.stringify(editDocRelatedTablesList)
					}
				};
			} else if (memory.entity_type === 'sql_example') {
				form = {
					content: editExampleDesc,
					metadata: {
						sql_query: editExampleSql,
						description: editExampleDesc,
						use_case: editExampleUseCase
					}
				};
			}
			const result = await updateDbSphereMemory(
				localStorage.token,
				dbsphereId,
				memory.memory_id,
				form
			);
			if (result) {
				toast.success($i18n.t('Memory updated successfully'));
				dispatch('save');
				show = false;
			}
		} catch (e) {
			toast.error((e as string) || $i18n.t('Failed to update memory'));
		}
		saving = false;
	}

	function entityLabel(type: string): string {
		switch (type) {
			case 'ddl_schema':
				return $i18n.t('DDL Schema');
			case 'sql_memory':
				return $i18n.t('SQL Few-shot');
			case 'documentation':
				return $i18n.t('Documentation');
			case 'sql_example':
				return $i18n.t('SQL Example');
			default:
				return type;
		}
	}

	function entityAccent(type: string): string {
		// Dot color reflects the same palette used in ExtractionTabs badges.
		switch (type) {
			case 'ddl_schema':
				return 'var(--cloo-color-info, #155dfc)';
			case 'sql_memory':
				return 'var(--cloo-color-success, #008236)';
			case 'documentation':
				return 'var(--cloo-color-warning, #ea580c)';
			case 'sql_example':
				return 'var(--cloo-color-accent, #7c3aed)';
			default:
				return 'var(--cloo-text-muted, #6b7280)';
		}
	}

	// 마지막 참조(주입) 시각 — epoch(초) → 로컬 날짜시간.
	function formatUsedAt(epoch: number | null | undefined): string {
		if (!epoch) return '-';
		try {
			return new Date(epoch * 1000).toLocaleString();
		} catch {
			return '-';
		}
	}

	// ISO8601 문자열 → 로컬 날짜시간 (초까지만, 마이크로초/타임존 제거). 생성일·최종수정일.
	function formatIsoDate(iso: string | null | undefined): string {
		if (!iso) return '-';
		try {
			return new Date(iso).toLocaleString(undefined, {
				year: 'numeric',
				month: '2-digit',
				day: '2-digit',
				hour: '2-digit',
				minute: '2-digit',
				second: '2-digit',
				hour12: false
			});
		} catch {
			return '-';
		}
	}

	// 문서 본문 — content 는 rich_content(Title:/Related tables: 접두사 포함)라 clean 본문만 추출.
	// 신규 문서는 metadata.doc_content(clean), legacy 는 접두사 줄 제거 폴백.
	function docBody(m: MemoryItem | null): string {
		if (!m) return '';
		const meta = m.metadata || {};
		if (meta.doc_content) return String(meta.doc_content);
		const titleLine = meta.title ? `Title: ${meta.title}` : null;
		return (m.content || '')
			.split('\n')
			.filter((line, idx) => {
				if (idx === 0 && titleLine && line === titleLine) return false;
				if (line.startsWith('Related tables: ')) return false;
				if (line.startsWith('Related columns: ')) return false;
				return true;
			})
			.join('\n')
			.trim();
	}

	// 문서 관련 테이블 — metadata.related_tables_json 파싱.
	function docRelatedTables(m: MemoryItem | null): string[] {
		const raw = m?.metadata?.related_tables_json;
		if (!raw) return [];
		try {
			const arr = JSON.parse(String(raw));
			return Array.isArray(arr) ? arr : [];
		} catch {
			return [];
		}
	}

	// 관련테이블 다중선택 — 아직 선택 안 된 테이블만 드롭다운에 노출.
	$: availableTableOptions = tables
		.filter((t) => !editDocRelatedTablesList.includes(t))
		.map((t) => ({ value: t, label: t }));

	function addRelTable(name: string) {
		if (name && !editDocRelatedTablesList.includes(name)) {
			editDocRelatedTablesList = [...editDocRelatedTablesList, name];
		}
		tableAddValue = ''; // 드롭다운 선택값 리셋 (다음 추가 대비)
	}
	function removeRelTable(name: string) {
		editDocRelatedTablesList = editDocRelatedTablesList.filter((t) => t !== name);
	}

	const docTypes = [
		{ value: 'context', label: 'Context' },
		{ value: 'term', label: 'Term' },
		{ value: 'rule', label: 'Rule' }
	];

	const createTypes: { value: CreateType; label: string }[] = [
		{ value: 'sql_memory', label: 'SQL Few-shot' },
		{ value: 'documentation', label: 'Documentation' },
		{ value: 'sql_example', label: 'SQL Example' }
	];

	const handleDocTypeChange = (e: CustomEvent<{ value: string | number }>) => {
		docType = String(e.detail.value);
	};
	const handleEditDocTypeChange = (e: CustomEvent<{ value: string | number }>) => {
		editDocType = String(e.detail.value);
	};

	// Map our CodeMirror dialect names to sql-formatter language names so the
	// formatter applies vendor-correct keyword casing + indentation rules.
	const formatterLang = (d: SqlDialectName): string => {
		switch (d) {
			case 'postgresql':
				return 'postgresql';
			case 'mysql':
				return 'mysql';
			case 'mariadb':
				return 'mariadb';
			case 'mssql':
				return 'tsql';
			case 'sqlite':
				return 'sqlite';
			case 'plsql':
				return 'plsql';
			default:
				return 'sql'; // ANSI / standard
		}
	};

	const prettifySql = (raw: string): string => {
		if (!raw || !raw.trim()) return raw;
		try {
			return formatSqlBase(raw, {
				language: formatterLang(dialect) as never,
				keywordCase: 'upper',
				linesBetweenQueries: 2,
				tabWidth: 2
			});
		} catch {
			// Malformed SQL: return as-is rather than throwing
			return raw;
		}
	};

	// View-mode SQL is auto-prettified for readability. Edit-mode keeps raw
	// content so the user's in-progress text isn't reflowed mid-typing.
	$: viewSqlMemory = !editing
		? prettifySql(String(memory?.metadata?.sql_query ?? ''))
		: '';
	$: viewSqlExample = !editing
		? prettifySql(String(memory?.metadata?.sql_query ?? ''))
		: '';
	// DDL 원문은 편집 대상이 아니라 항상 읽기 전용(CodeEditor readOnly)으로 표시한다.
	// sql_query/sql_example 과 달리 편집 입력이 없어 in-progress 텍스트 우려가 없으므로,
	// 편집 모드에서도 빈칸 대신 전체 DDL 을 그대로 prettify 해서 보여준다.
	$: viewDdl = prettifySql(String(memory?.metadata?.ddl_statement ?? ''));

	const copyText = async (text: string) => {
		const ok = await copyToClipboard(text);
		if (ok) toast.success($i18n.t('Copied to clipboard'));
		else toast.error($i18n.t('Failed to copy'));
	};

	// Manual format action for edit-mode SQL: reformats the bound variable
	// in-place so the CodeEditor picks it up on the next reactive cycle.
	const formatEditSqlMemory = () => {
		editSqlQuery = prettifySql(editSqlQuery);
	};
	const formatEditSqlExample = () => {
		editExampleSql = prettifySql(editExampleSql);
	};
	const formatCreateSql = () => {
		sql = prettifySql(sql);
	};
	const formatCreateExampleSql = () => {
		exampleSql = prettifySql(exampleSql);
	};

	$: currentType = mode === 'create' ? createType : memory?.entity_type ?? '';
	$: headerTitle =
		mode === 'create'
			? $i18n.t('Add Memory')
			: editing
				? $i18n.t('Edit Memory')
				: $i18n.t('Memory Detail');
</script>

<Modal bind:show size="lg">
	<div class="cloo-memory-modal flex flex-col">
		<!-- Header: dot + title + type chip + close -->
		<header
			class="flex items-center gap-2.5 px-6 py-4 border-b border-[var(--cloo-border-subtle)]"
		>
			<span
				class="cloo-memory-modal__dot"
				style="background: {currentType ? entityAccent(currentType) : 'var(--cloo-text-muted)'};"
				aria-hidden="true"
			/>
			<h3 class="text-base font-semibold text-[var(--cloo-text-primary)]">
				{headerTitle}
			</h3>
			{#if currentType}
				<span
					class="cloo-memory-modal__type-chip"
					style="--accent: {entityAccent(currentType)};"
				>
					{entityLabel(currentType)}
				</span>
			{/if}
			<button
				type="button"
				class="ml-auto p-1.5 rounded hover:bg-[var(--cloo-surface-hover)] transition-colors"
				aria-label={$i18n.t('Close')}
				on:click={() => (show = false)}
			>
				<XMark className="size-4" strokeWidth="2" />
			</button>
		</header>

		<!-- Body -->
		<div class="cloo-memory-modal__body px-6 py-5 flex flex-col gap-5 overflow-y-auto">
			{#if mode === 'create'}
				<!-- Type selector -->
				<section class="flex flex-col gap-2">
					<span class="cloo-section-label">{$i18n.t('Type')}</span>
					<div class="flex gap-2 flex-wrap">
						{#each createTypes as opt}
							<Button
								kind={createType === opt.value ? 'filled' : 'outlined'}
								size="sm"
								on:click={() => (createType = opt.value)}
							>
								{$i18n.t(opt.label)}
							</Button>
						{/each}
					</div>
				</section>

				<!-- SQL Few-shot create -->
				{#if createType === 'sql_memory'}
					<section class="flex flex-col gap-1.5">
						<span class="cloo-section-label">{$i18n.t('Question')}</span>
						<Textarea
							size="md"
							rows={3}
							placeholder={$i18n.t('Natural language question…')}
							bind:value={question}
						/>
					</section>
					<section class="flex flex-col gap-1.5">
						<div class="flex items-center gap-2">
							<span class="cloo-section-label">SQL</span>
							<div class="cloo-code-actions ml-auto">
								<button
									type="button"
									class="cloo-code-action"
									on:click={formatCreateSql}
									title={$i18n.t('Format')}
								>{$i18n.t('Format')}</button>
								<Tooltip content={$i18n.t('Copy SQL')} placement="top">
									<button
										type="button"
										class="cloo-code-action cloo-code-action--icon"
										aria-label={$i18n.t('Copy SQL')}
										on:click={() => copyText(sql)}
									>
										<DocumentDuplicate className="size-3.5" strokeWidth="2" />
									</button>
								</Tooltip>
							</div>
						</div>
						<div class="cloo-code-shell" style="height: 220px;">
							<CodeEditor
								id="memory-create-sql-memory"
								lang="sql"
								{dialect}
								value={sql}
								onChange={(v) => (sql = v)}
							/>
						</div>
					</section>

				<!-- Documentation create -->
				{:else if createType === 'documentation'}
					<div class="grid grid-cols-2 gap-4">
						<section class="flex flex-col gap-1.5">
							<span class="cloo-section-label">{$i18n.t('Title')}</span>
							<Input
								size="md"
								placeholder={$i18n.t('Title (optional)')}
								bind:value={docTitle}
							/>
						</section>
						<section class="flex flex-col gap-1.5">
							<span class="cloo-section-label">{$i18n.t('Doc Type')}</span>
							<Selector
								value={docType}
								items={docTypes.map((dt) => ({ value: dt.value, label: $i18n.t(dt.label) }))}
								size="md"
								portal="body"
								contentClassName="z-[10000]"
								on:change={handleDocTypeChange}
							/>
						</section>
					</div>
					<section class="flex flex-col gap-1.5">
						<span class="cloo-section-label">{$i18n.t('Content')}</span>
						<Textarea
							size="md"
							rows={8}
							placeholder={$i18n.t('Business rules, terms, context…')}
							bind:value={docContent}
						/>
					</section>
					<section class="flex flex-col gap-1.5">
						<span class="cloo-section-label">{$i18n.t('Related Tables')}</span>
						<div class="flex flex-col gap-2">
							{#if editDocRelatedTablesList.length > 0}
								<div class="flex flex-wrap gap-1.5">
									{#each editDocRelatedTablesList as t}
										<span class="cloo-rel-table cloo-rel-table--removable">
											{t}
											<button
												type="button"
												class="cloo-rel-table__x"
												aria-label={$i18n.t('Remove')}
												on:click={() => removeRelTable(t)}
											>
												×
											</button>
										</span>
									{/each}
								</div>
							{/if}
							{#if availableTableOptions.length > 0}
								<Selector
									value={tableAddValue}
									items={availableTableOptions}
									size="md"
									searchEnabled
									portal="body"
									contentClassName="z-[10000]"
									placeholder={$i18n.t('Add a table')}
									on:change={(e) => addRelTable(e.detail.value)}
								/>
							{/if}
						</div>
					</section>

				<!-- SQL Example create -->
				{:else}
					<section class="flex flex-col gap-1.5">
						<span class="cloo-section-label">{$i18n.t('Description')}</span>
						<Textarea
							size="md"
							rows={3}
							placeholder={$i18n.t('What this SQL does…')}
							bind:value={exampleDesc}
						/>
					</section>
					<section class="flex flex-col gap-1.5">
						<div class="flex items-center gap-2">
							<span class="cloo-section-label">SQL</span>
							<div class="cloo-code-actions ml-auto">
								<button
									type="button"
									class="cloo-code-action"
									on:click={formatCreateExampleSql}
									title={$i18n.t('Format')}
								>{$i18n.t('Format')}</button>
								<Tooltip content={$i18n.t('Copy SQL')} placement="top">
									<button
										type="button"
										class="cloo-code-action cloo-code-action--icon"
										aria-label={$i18n.t('Copy SQL')}
										on:click={() => copyText(exampleSql)}
									>
										<DocumentDuplicate className="size-3.5" strokeWidth="2" />
									</button>
								</Tooltip>
							</div>
						</div>
						<div class="cloo-code-shell" style="height: 220px;">
							<CodeEditor
								id="memory-create-sql-example"
								lang="sql"
								{dialect}
								value={exampleSql}
								onChange={(v) => (exampleSql = v)}
							/>
						</div>
					</section>
					<div class="grid grid-cols-2 gap-4">
						<section class="flex flex-col gap-1.5">
							<span class="cloo-section-label">{$i18n.t('Use Case')}</span>
							<Input size="md" bind:value={exampleUseCase} />
						</section>
						<section class="flex flex-col gap-1.5">
							<span class="cloo-section-label">{$i18n.t('Tags')}</span>
							<Input
								size="md"
								placeholder={$i18n.t('Comma separated tags (optional)')}
								bind:value={exampleTags}
							/>
						</section>
					</div>
				{/if}

			<!-- VIEW / EDIT existing memory -->
			{:else if memory}
				<!-- 메타: 생성자 + 최종수정자 + 최종수정일 (+ sql_memory 는 참조) -->
				<div class="cloo-mem-meta flex flex-wrap items-center gap-2">
					<span class="cloo-mem-meta__chip" title={memory.creator || $i18n.t('Creator')}>
						<span class="cloo-mem-meta__k">{$i18n.t('Creator')}</span>
						<span class="cloo-mem-meta__email">{memory.creator || '-'}</span>
					</span>
					{#if memory.last_modified_by}
						<span class="cloo-mem-meta__chip" title={memory.last_modified_by}>
							<span class="cloo-mem-meta__k">{$i18n.t('Last modified by')}</span>
							<span class="cloo-mem-meta__email">{memory.last_modified_by}</span>
						</span>
					{/if}
					{#if memory.entity_type === 'sql_memory'}
						<span
							class="cloo-mem-meta__chip"
							title={$i18n.t('Injection events (retrieval), not LLM usage')}
						>
							<span class="cloo-mem-meta__k">{$i18n.t('References')}</span>
							<span>{memory.use_count ?? 0} {$i18n.t('refs')}</span>
						</span>
						{#if memory.last_used_at}
							<span class="cloo-mem-meta__chip">
								<span class="cloo-mem-meta__k">{$i18n.t('Last used')}</span>
								<span>{formatUsedAt(memory.last_used_at)}</span>
							</span>
						{/if}
					{/if}
				</div>
				{#if memory.entity_type === 'ddl_schema'}
					<section class="flex flex-col gap-1.5">
						<span class="cloo-section-label">{$i18n.t('Table')}</span>
						<p class="text-sm font-mono text-[var(--cloo-text-primary)]">
							{memory.metadata?.table_name || '-'}
						</p>
					</section>
					<section class="flex flex-col gap-1.5">
						<span class="cloo-section-label">{$i18n.t('Description')}</span>
						{#if editing}
							<Textarea size="md" rows={3} bind:value={editTableDescription} />
						{:else}
							<p class="text-sm text-[var(--cloo-text-default)] whitespace-pre-wrap">
								{memory.metadata?.table_description || '-'}
							</p>
						{/if}
					</section>

					{#if editColumns.length > 0 || memory.metadata?.column_info_json}
						{@const cols = editing
							? editColumns
							: (() => {
									try {
										return JSON.parse(String(memory.metadata?.column_info_json ?? '[]'));
									} catch {
										return [];
									}
								})()}
						{#if cols.length > 0}
							<section class="flex flex-col gap-1.5">
								<span class="cloo-section-label">
									{$i18n.t('Columns')} ({cols.length})
								</span>
								<div class="cloo-cols-table-wrap">
									<table class="cloo-cols-table">
										<thead>
											<tr>
												<th>{$i18n.t('Name')}</th>
												<th>{$i18n.t('Type')}</th>
												<th>{$i18n.t('Description')}</th>
											</tr>
										</thead>
										<tbody>
											{#each cols as col, i}
												<tr>
													<td class="font-mono">
														{col.name}
														{#if col.is_primary_key}<span
																class="text-amber-500 ml-1 text-[10px] font-semibold">PK</span
															>{/if}
														{#if col.is_foreign_key}<span
																class="text-blue-500 ml-1 text-[10px] font-semibold">FK</span
															>{/if}
													</td>
													<td class="text-[var(--cloo-text-tertiary)] font-mono">
														{col.data_type}
													</td>
													<td>
														{#if editing}
															<Input
																size="sm"
																placeholder={$i18n.t('Column description…')}
																bind:value={editColumns[i].description}
															/>
														{:else}
															<span class="text-[var(--cloo-text-muted)]"
																>{col.description || ''}</span
															>
														{/if}
													</td>
												</tr>
											{/each}
										</tbody>
									</table>
								</div>
							</section>
						{/if}
					{/if}

					{#if memory.metadata?.ddl_statement}
						<section class="flex flex-col gap-1.5">
							<div class="flex items-center gap-2">
								<span class="cloo-section-label">DDL</span>
								<div class="cloo-code-actions ml-auto">
									<Tooltip content={$i18n.t('Copy SQL')} placement="top">
										<button
											type="button"
											class="cloo-code-action cloo-code-action--icon"
											aria-label={$i18n.t('Copy SQL')}
											on:click={() => copyText(viewDdl)}
										>
											<DocumentDuplicate className="size-3.5" strokeWidth="2" />
										</button>
									</Tooltip>
								</div>
							</div>
							<div class="cloo-code-shell" style="height: 260px;">
								<CodeEditor
									id="memory-view-ddl-{memory.memory_id}"
									lang="sql"
									{dialect}
									readOnly={true}
									value={viewDdl}
								/>
							</div>
						</section>
					{/if}

				{:else if memory.entity_type === 'sql_memory'}
					<section class="flex flex-col gap-1.5">
						<span class="cloo-section-label">{$i18n.t('Question')}</span>
						{#if editing}
							<Textarea size="md" rows={3} bind:value={editQuestion} />
						{:else}
							<p class="text-sm text-[var(--cloo-text-default)] whitespace-pre-wrap">
								{memory.content || '-'}
							</p>
						{/if}
					</section>
					<section class="flex flex-col gap-1.5">
						<div class="flex items-center gap-2">
							<span class="cloo-section-label">SQL</span>
							<div class="cloo-code-actions ml-auto">
								{#if editing}
									<button
										type="button"
										class="cloo-code-action"
										on:click={formatEditSqlMemory}
										title={$i18n.t('Format')}
									>{$i18n.t('Format')}</button>
								{/if}
								<Tooltip content={$i18n.t('Copy SQL')} placement="top">
									<button
										type="button"
										class="cloo-code-action cloo-code-action--icon"
										aria-label={$i18n.t('Copy SQL')}
										on:click={() =>
											copyText(editing ? editSqlQuery : viewSqlMemory)}
									>
										<DocumentDuplicate className="size-3.5" strokeWidth="2" />
									</button>
								</Tooltip>
							</div>
						</div>
						<div class="cloo-code-shell" style="height: 280px;">
							{#if editing}
								<CodeEditor
									id="memory-edit-sql-memory-{memory.memory_id}"
									lang="sql"
									{dialect}
									value={editSqlQuery}
									onChange={(v) => (editSqlQuery = v)}
								/>
							{:else}
								<CodeEditor
									id="memory-view-sql-memory-{memory.memory_id}"
									lang="sql"
									{dialect}
									readOnly={true}
									value={viewSqlMemory}
								/>
							{/if}
						</div>
					</section>

				{:else if memory.entity_type === 'documentation'}
					<div class="grid grid-cols-2 gap-4">
						<section class="flex flex-col gap-1.5">
							<span class="cloo-section-label">{$i18n.t('Title')}</span>
							{#if editing}
								<Input size="md" bind:value={editDocTitle} />
							{:else}
								<p class="text-sm text-[var(--cloo-text-default)]">
									{memory.metadata?.title || '-'}
								</p>
							{/if}
						</section>
						<section class="flex flex-col gap-1.5">
							<span class="cloo-section-label">{$i18n.t('Doc Type')}</span>
							{#if editing}
								<Selector
									value={editDocType}
									items={docTypes.map((dt) => ({ value: dt.value, label: $i18n.t(dt.label) }))}
									size="md"
									portal="body"
									contentClassName="z-[10000]"
									on:change={handleEditDocTypeChange}
								/>
							{:else}
								<p class="text-sm text-[var(--cloo-text-default)]">
									{$i18n.t(String(memory.metadata?.doc_type ?? 'context'))}
								</p>
							{/if}
						</section>
					</div>
					<section class="flex flex-col gap-1.5">
						<span class="cloo-section-label">{$i18n.t('Content')}</span>
						{#if editing}
							<Textarea size="md" rows={10} bind:value={editDocContent} />
						{:else}
							<p
								class="text-sm text-[var(--cloo-text-default)] whitespace-pre-wrap leading-relaxed"
							>
								{docBody(memory) || '-'}
							</p>
						{/if}
					</section>
					{#if editing || docRelatedTables(memory).length > 0}
						<section class="flex flex-col gap-1.5">
							<span class="cloo-section-label">{$i18n.t('Related Tables')}</span>
							{#if editing}
								<div class="flex flex-col gap-2">
									{#if editDocRelatedTablesList.length > 0}
										<div class="flex flex-wrap gap-1.5">
											{#each editDocRelatedTablesList as t}
												<span class="cloo-rel-table cloo-rel-table--removable">
													{t}
													<button
														type="button"
														class="cloo-rel-table__x"
														aria-label={$i18n.t('Remove')}
														on:click={() => removeRelTable(t)}
													>
														×
													</button>
												</span>
											{/each}
										</div>
									{/if}
									{#if availableTableOptions.length > 0}
										<Selector
											value={tableAddValue}
											items={availableTableOptions}
											size="md"
											searchEnabled
											portal="body"
											contentClassName="z-[10000]"
											placeholder={$i18n.t('Add a table')}
											on:change={(e) => addRelTable(e.detail.value)}
										/>
									{/if}
								</div>
							{:else}
								<div class="flex flex-wrap gap-1.5">
									{#each docRelatedTables(memory) as t}
										<span class="cloo-rel-table">{t}</span>
									{/each}
								</div>
							{/if}
						</section>
					{/if}

				{:else if memory.entity_type === 'sql_example'}
					<section class="flex flex-col gap-1.5">
						<span class="cloo-section-label">{$i18n.t('Description')}</span>
						{#if editing}
							<Textarea size="md" rows={3} bind:value={editExampleDesc} />
						{:else}
							<p class="text-sm text-[var(--cloo-text-default)] whitespace-pre-wrap">
								{memory.metadata?.description || memory.content || '-'}
							</p>
						{/if}
					</section>
					<section class="flex flex-col gap-1.5">
						<div class="flex items-center gap-2">
							<span class="cloo-section-label">SQL</span>
							<div class="cloo-code-actions ml-auto">
								{#if editing}
									<button
										type="button"
										class="cloo-code-action"
										on:click={formatEditSqlExample}
										title={$i18n.t('Format')}
									>{$i18n.t('Format')}</button>
								{/if}
								<Tooltip content={$i18n.t('Copy SQL')} placement="top">
									<button
										type="button"
										class="cloo-code-action cloo-code-action--icon"
										aria-label={$i18n.t('Copy SQL')}
										on:click={() =>
											copyText(editing ? editExampleSql : viewSqlExample)}
									>
										<DocumentDuplicate className="size-3.5" strokeWidth="2" />
									</button>
								</Tooltip>
							</div>
						</div>
						<div class="cloo-code-shell" style="height: 280px;">
							{#if editing}
								<CodeEditor
									id="memory-edit-sql-example-{memory.memory_id}"
									lang="sql"
									{dialect}
									value={editExampleSql}
									onChange={(v) => (editExampleSql = v)}
								/>
							{:else}
								<CodeEditor
									id="memory-view-sql-example-{memory.memory_id}"
									lang="sql"
									{dialect}
									readOnly={true}
									value={viewSqlExample}
								/>
							{/if}
						</div>
					</section>
					<section class="flex flex-col gap-1.5">
						<span class="cloo-section-label">{$i18n.t('Use Case')}</span>
						{#if editing}
							<Input size="md" bind:value={editExampleUseCase} />
						{:else}
							<p class="text-sm text-[var(--cloo-text-default)]">
								{memory.metadata?.use_case || '-'}
							</p>
						{/if}
					</section>
				{/if}

				{#if !editing && memory.created_at}
					<div class="flex flex-wrap gap-x-6 gap-y-1 text-[11px] text-[var(--cloo-text-tertiary)] pt-2 border-t border-[var(--cloo-border-subtle)]">
						<span>
							<span class="font-semibold">{$i18n.t('Created')}</span>: {formatIsoDate(memory.created_at)}
						</span>
						{#if memory.last_modified_at}
							<span>
								<span class="font-semibold">{$i18n.t('Last modified')}</span>: {formatIsoDate(memory.last_modified_at)}
							</span>
						{/if}
					</div>
				{/if}
			{/if}
		</div>

		<!-- Footer -->
		<footer
			class="flex justify-end gap-2 px-6 py-4 border-t border-[var(--cloo-border-subtle)]"
		>
			{#if mode === 'create'}
				<Button kind="outlined" size="md" on:click={() => (show = false)}>
					{$i18n.t('Cancel')}
				</Button>
				<Button kind="filled" size="md" loading={saving} disabled={saving} on:click={handleCreate}>
					{$i18n.t('Create')}
				</Button>
			{:else if editing}
				<Button kind="outlined" size="md" on:click={cancelEditing}>
					{$i18n.t('Cancel')}
				</Button>
				<Button kind="filled" size="md" loading={saving} disabled={saving} on:click={handleUpdate}>
					{$i18n.t('Save')}
				</Button>
			{:else}
				{#if canWrite}
					<Button kind="outlined" size="md" on:click={startEditing}>
						{$i18n.t('Edit')}
					</Button>
				{/if}
				<Button kind="filled" size="md" on:click={() => (show = false)}>
					{$i18n.t('Close')}
				</Button>
			{/if}
		</footer>
	</div>
</Modal>

<style>
	.cloo-memory-modal {
		max-height: 85vh;
	}
	.cloo-memory-modal__body {
		flex: 1 1 auto;
		min-height: 0;
	}
	.cloo-memory-modal__dot {
		width: 8px;
		height: 8px;
		border-radius: 50%;
		flex-shrink: 0;
	}
	.cloo-memory-modal__type-chip {
		display: inline-flex;
		align-items: center;
		height: 22px;
		padding: 0 10px;
		border-radius: 999px;
		font-size: 11px;
		font-weight: 500;
		letter-spacing: 0.02em;
		background: color-mix(in srgb, var(--accent) 12%, transparent);
		color: var(--accent);
		border: 1px solid color-mix(in srgb, var(--accent) 25%, transparent);
	}

	.cloo-mem-meta__chip {
		display: inline-flex;
		align-items: center;
		gap: 5px;
		height: 24px;
		padding: 0 10px;
		border-radius: 999px;
		border: 1px solid var(--cloo-border-subtle, #e3e4e9);
		background: var(--cloo-bg-surface, #fff);
		font-size: 11px;
		color: var(--cloo-text-default, #1a1a1a);
		font-variant-numeric: tabular-nums;
		white-space: nowrap;
	}
	.cloo-mem-meta__k {
		color: var(--cloo-text-muted, #6b7280);
		font-weight: 600;
		text-transform: uppercase;
		font-size: 10px;
		letter-spacing: 0.02em;
	}
	.cloo-mem-meta__email {
		color: var(--cloo-text-tertiary, #9ca3af);
		max-width: 220px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.cloo-rel-table {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		height: 22px;
		padding: 0 8px;
		border-radius: 999px;
		font-size: 11px;
		font-family: monospace;
		background: var(--cloo-bg-neutral-hovered, #f3f4f6);
		color: var(--cloo-text-default, #1a1a1a);
		white-space: nowrap;
	}
	.cloo-rel-table--removable {
		padding-right: 4px;
	}
	.cloo-rel-table__x {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 14px;
		height: 14px;
		border-radius: 50%;
		font-size: 12px;
		line-height: 1;
		color: var(--cloo-text-muted, #6b7280);
		cursor: pointer;
	}
	.cloo-rel-table__x:hover {
		background: var(--cloo-danger-soft, #fee2e2);
		color: var(--cloo-danger-solid, #dc2626);
	}

	:global(.cloo-section-label) {
		font-size: 11px;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--cloo-text-tertiary, #9d9ea9);
	}

	.cloo-code-shell {
		border: 1px solid var(--cloo-border-default, #d5d5da);
		border-radius: 6px;
		overflow: hidden;
		background: var(--cloo-bg-surface, #fff);
		display: flex;
	}
	.cloo-code-shell :global(.cm-editor) {
		flex: 1;
		min-height: 0;
	}

	.cloo-code-actions {
		display: inline-flex;
		align-items: center;
		gap: 4px;
	}
	.cloo-code-action {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		height: 22px;
		padding: 0 8px;
		border-radius: 4px;
		border: 1px solid transparent;
		background: transparent;
		color: var(--cloo-text-muted, #6b7280);
		font-size: 11px;
		font-weight: 500;
		cursor: pointer;
		transition: background-color 80ms ease, color 80ms ease, border-color 80ms ease;
	}
	.cloo-code-action:hover {
		background: var(--cloo-surface-hover, #f5f5f7);
		color: var(--cloo-text-default, #1a1a1a);
		border-color: var(--cloo-border-subtle, #e3e4e9);
	}
	.cloo-code-action--icon {
		padding: 0 6px;
	}

	.cloo-cols-table-wrap {
		border: 1px solid var(--cloo-border-default, #d5d5da);
		border-radius: 6px;
		overflow: hidden;
		max-height: 280px;
		overflow-y: auto;
	}
	.cloo-cols-table {
		width: 100%;
		font-size: 12px;
		border-collapse: collapse;
	}
	.cloo-cols-table th {
		text-align: left;
		padding: 8px 10px;
		font-weight: 500;
		color: var(--cloo-text-default, #1a1a1a);
		background: var(--cloo-bg-surface, #f5f5f7);
		border-bottom: 1px solid var(--cloo-border-subtle, #e3e4e9);
		position: sticky;
		top: 0;
		z-index: 1;
	}
	.cloo-cols-table td {
		padding: 6px 10px;
		border-bottom: 1px solid var(--cloo-border-subtle, #e3e4e9);
		vertical-align: middle;
	}
	.cloo-cols-table tr:last-child td {
		border-bottom: none;
	}
</style>

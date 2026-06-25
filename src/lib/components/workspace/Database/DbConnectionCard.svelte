<script lang="ts" context="module">
	export type DbConnectionTab = 'all' | 'extracted' | 'memory';

	export type DbTableEntry = {
		id: string;
		name: string;
	};
</script>

<script lang="ts">
	import { createEventDispatcher, getContext } from 'svelte';
	import type { Readable } from 'svelte/store';

	import Card from '$lib/components/common/Card.svelte';
	import Button from '$lib/components/common/Button.svelte';
	import Input from '$lib/components/common/Input.svelte';
	import Selector from '$lib/components/common/Selector.svelte';
	import Switch from '$lib/components/common/Switch.svelte';
	import Badge from '$lib/components/common/Badge.svelte';
	import Checkbox from '$lib/components/common/Checkbox.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import ConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';
	import MagnifyingGlass from '$lib/components/icons/MagnifyingGlass.svelte';
	import Info from '$lib/components/icons/Info.svelte';
	import { models } from '$lib/stores';

	type I18nStore = Readable<{ t: (key: string) => string }>;
	const i18n = getContext<I18nStore>('i18n');
	const dispatch = createEventDispatcher();

	export let connected: boolean = false;
	/** True only when a Test Connection ran this session and failed. Drives the
	 * red badge. The badge is a *test-result* indicator: nothing shows until the
	 * user actually tests, so an untested (but configured) connection no longer
	 * looks "disconnected". */
	export let connectionFailed: boolean = false;
	export let testing: boolean = false;
	export let extracting: boolean = false;
	/** Editor button is always rendered (never hidden) for clear affordance.
	 * It is enabled only when the parent says the connection is verified in
	 * this session. */
	export let editorEnabled: boolean = true;
	/** True when the SQL Editor panel is currently shown — the button then
	 * acts as a close toggle (icon flips to a "Close" affordance). */
	export let editorOpen: boolean = false;

	export let activeTab: DbConnectionTab = 'all';
	export let counts: { all: number; extracted: number; memory: number } = {
		all: 0,
		extracted: 0,
		memory: 0
	};

	export let tables: DbTableEntry[] = [];
	export let selectedTableIds: string[] = [];
	export let search: string = '';
	/** Names of tables that already have an extracted-schema row. Used to
	 * mark them in the DB All list and to power the "Unextracted/Extracted"
	 * filter chips so the user can focus on todo work. */
	export let extractedTableNames: Set<string> = new Set();
	/** Live extraction progress fed by parent (polled every 2s). Shows
	 * inline panel in DB All tab during running/pending phase. */
	export let extractionStatus: {
		status: 'none' | 'pending' | 'running' | 'cancelling' | 'cancelled' | 'completed' | 'failed';
		cancel_requested?: boolean;
		current_table?: string;
		current_phase?: string;
		tables_total: number;
		tables_processed: number;
		tables_in_progress?: number;
		tables_saved: number;
		qa_saved: number;
	} | null = null;

	// --- Inline extraction options (formerly ExtractSchemaOptionsModal) ---
	// Bound two-way to the parent so its existing `handleExtract` reads the
	// model / sample-row / Q&A choices unchanged — only the UI surface moved
	// from a cog-triggered modal into this toolbar row.
	export let extractModelId: string = '';
	export let sampleRowCount: number = 5;
	export let generateSampleQA: boolean = true;

	// Translate the raw `phase` key from the server into the user's locale.
	const phaseLabel = (phase: string | undefined): string => {
		switch (phase) {
			case 'extracting':
				return $i18n.t('Extracting schema');
			case 'saving_ddl':
				return $i18n.t('Saving DDL');
			case 'generating_qa':
				return $i18n.t('Generating Q&A');
			case 'saving_qa':
				return $i18n.t('Saving Q&A');
			default:
				return $i18n.t('Processing');
		}
	};

	$: isExtractionActive =
		extractionStatus?.status === 'running' ||
		extractionStatus?.status === 'pending' ||
		extractionStatus?.status === 'cancelling';
	// "Stopping…" once cancel is requested but the job hasn't confirmed
	// terminal yet (in-flight tables finish their current step first).
	$: isCancelling =
		extractionStatus?.status === 'cancelling' || extractionStatus?.cancel_requested === true;
	$: extractionPercent =
		extractionStatus && extractionStatus.tables_total > 0
			? Math.min(
					100,
					Math.round((extractionStatus.tables_processed / extractionStatus.tables_total) * 100)
				)
			: 0;

	type DbAllFilter = 'all' | 'unextracted' | 'extracted';
	let dbAllFilter: DbAllFilter = 'all';

	$: counts_filter = (() => {
		let extracted = 0;
		let unextracted = 0;
		for (const t of tables) {
			if (extractedTableNames.has(t.name)) extracted++;
			else unextracted++;
		}
		return { all: tables.length, extracted, unextracted };
	})();

	// Pre-typed chip list so the template doesn't need a TS cast on the
	// inline literal (Svelte template parses inline expressions as plain JS,
	// not TS — see frontend-component.md).
	$: filterChips = [
		{ id: 'all' as DbAllFilter, label: $i18n.t('All'), n: counts_filter.all },
		{ id: 'unextracted' as DbAllFilter, label: $i18n.t('Unextracted'), n: counts_filter.unextracted },
		{ id: 'extracted' as DbAllFilter, label: $i18n.t('Extracted'), n: counts_filter.extracted }
	];

	// Model dropdown for the inline extraction options. First item ("None")
	// clears the model, which also disables Q&A generation downstream.
	$: modelItems = [
		{ value: '', label: $i18n.t('None') },
		...(($models ?? []) as Array<{ id: string; name?: string; preset?: boolean; arena?: boolean }>)
			.filter((m) => !m?.preset && !(m?.arena ?? false))
			.map((m) => ({ value: m.id, label: m.name ?? m.id }))
	];

	$: filteredTables = (() => {
		const q = search.trim().toLowerCase();
		let base = tables;
		if (dbAllFilter === 'extracted') {
			base = base.filter((t) => extractedTableNames.has(t.name));
		} else if (dbAllFilter === 'unextracted') {
			base = base.filter((t) => !extractedTableNames.has(t.name));
		}
		if (!q) return base;
		return base.filter((t) => t.name.toLowerCase().includes(q));
	})();

	$: filteredIds = filteredTables.map((t) => t.id);
	$: selectedFilteredCount = filteredIds.filter((id) =>
		selectedTableIds.includes(id)
	).length;
	$: selectAllState =
		filteredIds.length === 0
			? 'unchecked'
			: selectedFilteredCount === filteredIds.length
				? 'checked'
				: selectedFilteredCount > 0
					? 'indeterminate'
					: 'unchecked';

	const setTab = (tab: DbConnectionTab) => {
		activeTab = tab;
		dispatch('tabChange', tab);
	};

	const handleTestConnection = () => dispatch('testConnection');
	const handleOpenEditor = () => dispatch('openEditor');
	const handleExtract = () => dispatch('extract');

	// Re-extracting an already-extracted table can wipe its loaded memory
	// (few-shot examples, docs) if the schema changed, so confirm first.
	// dbAllRows uses the table name as its id, so checking a selected id
	// against extractedTableNames tells us whether any already-extracted table
	// is in the selection — independent of the current search filter.
	let showReextractConfirm = false;
	$: hasExtractedSelected = selectedTableIds.some((id) => extractedTableNames.has(id));
	const handleRunClick = () => {
		if (hasExtractedSelected) {
			showReextractConfirm = true;
		} else {
			handleExtract();
		}
	};

	const handleCancelExtract = () => dispatch('cancelExtract');

	// Inline option controls mutate the bound props directly; Svelte's
	// two-way binding propagates each change up to the parent so the next
	// `handleExtract` (dispatched 'extract') sees the latest selection.
	const handleModelChange = (e: CustomEvent<{ value: string | number }>) => {
		extractModelId = String(e.detail.value);
	};
	// The common Input re-dispatches its native input event as the CustomEvent
	// `detail` (the CustomEvent's own target is the wrapper div, not the
	// <input>). Reading `e.target.value` would hit the div → NaN → silently
	// reset to 5, so pull the real field off `e.detail`.
	const handleSampleRowChange = (e: CustomEvent<Event>) => {
		const native = e.detail;
		const target = (native?.target ?? native?.currentTarget) as HTMLInputElement | null;
		if (!target) return;
		const parsed = Number(target.value);
		sampleRowCount = Number.isNaN(parsed) ? 5 : Math.max(0, Math.min(parsed, 100));
	};
	const handleQAToggle = (e: CustomEvent<boolean>) => {
		generateSampleQA = e.detail;
	};

	const toggleSelectAll = () => {
		if (selectAllState === 'checked') {
			dispatch('selectionChange', selectedTableIds.filter((id) => !filteredIds.includes(id)));
		} else {
			const merged = Array.from(new Set([...selectedTableIds, ...filteredIds]));
			dispatch('selectionChange', merged);
		}
	};

	const toggleRow = (id: string) => {
		const next = selectedTableIds.includes(id)
			? selectedTableIds.filter((x) => x !== id)
			: [...selectedTableIds, id];
		dispatch('selectionChange', next);
	};

	const tabConfig: { id: DbConnectionTab; labelKey: string; countKey: keyof typeof counts }[] = [
		{ id: 'all', labelKey: 'DB All', countKey: 'all' },
		{ id: 'extracted', labelKey: 'Extracted', countKey: 'extracted' },
		{ id: 'memory', labelKey: 'Memory', countKey: 'memory' }
	];
</script>

<Card padding="none" className="cloo-db-connection">
	<svelte:fragment slot="header">
		<div class="flex items-center px-6 py-3 gap-2">
			<h3 class="text-base font-semibold text-[var(--cloo-text-primary)] flex-1 min-w-0">
				{$i18n.t('DB Connection')}
			</h3>
			<div class="flex items-center gap-2.5">
				{#if connected}
					<Badge status="success" size="sm" content={$i18n.t('Connected')} />
				{:else if connectionFailed}
					<Badge status="danger" size="sm" content={$i18n.t('Disconnected')} />
				{/if}
				<Button kind="outlined" size="md" loading={testing} on:click={handleTestConnection}>
					{$i18n.t('Test Connection')}
				</Button>
				<Tooltip
					content={!editorEnabled
						? $i18n.t('Run Test Connection first')
						: editorOpen
							? $i18n.t('Close SQL Editor')
							: $i18n.t('Open SQL Editor')}
					placement="top"
				>
					<Button
						kind={editorOpen ? 'filled' : 'outlined'}
						size="md"
						disabled={!editorEnabled}
						on:click={handleOpenEditor}
					>
						{$i18n.t('Editor')}
					</Button>
				</Tooltip>
			</div>
		</div>
	</svelte:fragment>

	<!-- Tabs row -->
	<div class="flex items-center border-b border-[var(--cloo-border-default)]">
		{#each tabConfig as tab (tab.id)}
			<button
				type="button"
				class="cloo-db-connection__tab flex-1 px-3.5 py-2.5 text-sm transition-colors {tab.id ===
				activeTab
					? 'is-selected'
					: 'is-default'}"
				aria-current={tab.id === activeTab ? 'page' : undefined}
				on:click={() => setTab(tab.id)}
			>
				{$i18n.t(tab.labelKey)} ({counts[tab.countKey]})
			</button>
		{/each}
	</div>

	<!-- Tab content -->
	{#if activeTab === 'all'}
		<div class="px-6 py-5 flex flex-col gap-3">
			{#if isExtractionActive && extractionStatus}
				<!-- Live extraction progress panel — backend polls every 2s and
				     fills in current_table / counts. Auto-hides on completion
				     (parent toggles tab to "Extracted" then). -->
				<div class="cloo-extract-progress">
					<div class="cloo-extract-progress__header">
						<div class="flex items-center gap-2">
							<Spinner className="size-3.5" />
							<span class="text-sm font-medium text-[var(--cloo-text-default)]">
								{isCancelling ? $i18n.t('Stopping…') : $i18n.t('Extracting schema')}
							</span>
						</div>
						<div class="flex items-center gap-2">
							<span class="text-xs text-[var(--cloo-text-muted)] tabular-nums">
								{extractionStatus.tables_processed}/{extractionStatus.tables_total} ·
								{extractionPercent}%
							</span>
							<button
								type="button"
								class="cloo-extract-progress__stop"
								on:click={handleCancelExtract}
								disabled={isCancelling}
								title={$i18n.t('Stop schema extraction')}
							>
								{isCancelling ? $i18n.t('Stopping…') : $i18n.t('Stop extraction')}
							</button>
						</div>
					</div>
					<div class="cloo-extract-progress__bar" aria-hidden="true">
						<div
							class="cloo-extract-progress__fill"
							style="width: {extractionPercent}%"
						/>
					</div>
					<div class="cloo-extract-progress__meta">
						{#if extractionStatus.current_table}
							<span class="truncate">
								{phaseLabel(extractionStatus.current_phase)}:
								<strong class="font-mono">{extractionStatus.current_table}</strong>
							</span>
						{:else}
							<span>{$i18n.t('Initializing…')}</span>
						{/if}
						<span class="ml-auto text-[var(--cloo-text-tertiary)] tabular-nums shrink-0">
							{#if (extractionStatus.tables_in_progress ?? 0) > 0}
								{extractionStatus.tables_in_progress}
								{$i18n.t('in progress')} ·
							{/if}
							{extractionStatus.tables_saved} {$i18n.t('saved')} ·
							{extractionStatus.qa_saved} {$i18n.t('Q&A')}
						</span>
					</div>
				</div>
			{/if}

			<!-- Row 1 — list controls: filter chips + search. Both narrow the
			     visible table list, so they share a row and stay visually
			     separate from the extraction-action row below. Chips (broad
			     scope) sit at the left, search (narrow-down) grows to the
			     right — matching the broad→specific reading order and aligning
			     the left "controls" column with row 2. -->
			<div class="flex items-center gap-2.5">
				<div class="cloo-db-connection__filter-chips flex items-center gap-1.5 shrink-0">
					{#each filterChips as chip}
						<button
							type="button"
							class="cloo-chip"
							class:is-active={dbAllFilter === chip.id}
							on:click={() => (dbAllFilter = chip.id)}
						>
							<span>{chip.label}</span>
							<span class="cloo-chip__count">{chip.n}</span>
						</button>
					{/each}
				</div>
				<div class="flex-1 min-w-[140px]">
					<Input size="sm" placeholder={$i18n.t('Search tables')} bind:value={search}>
						<MagnifyingGlass slot="prefix" className="size-3.5" strokeWidth="2" />
					</Input>
				</div>
			</div>

			<!-- Row 2 — extraction action: a leading section title names the
				 action; Model / Rows / Q&A configure the run; the Run button
				 sits right beside them. Left-aligned at a uniform gap so the
				 controls stay grouped. Wraps on narrow widths. -->
			<div class="flex items-center gap-2.5 flex-wrap">
				<span class="text-sm font-semibold text-[var(--cloo-text-primary)] whitespace-nowrap shrink-0 mr-3">
					{$i18n.t('Extract Schema')}
				</span>

				<div class="flex-1 min-w-[200px]">
					<Selector
						value={extractModelId}
						items={modelItems}
						size="sm"
						placeholder={$i18n.t('Model')}
						searchEnabled={true}
						on:change={handleModelChange}
					/>
				</div>

				<div class="flex items-center gap-1.5 shrink-0">
					<span class="text-xs text-[var(--cloo-text-muted)] whitespace-nowrap">
						{$i18n.t('Rows')}
					</span>
					<div class="w-[64px]">
						<Input
							size="sm"
							type="number"
							value={String(sampleRowCount)}
							on:input={handleSampleRowChange}
						/>
					</div>
				</div>

				<div class="flex items-center gap-1.5 shrink-0">
					<span class="text-xs text-[var(--cloo-text-muted)] whitespace-nowrap">
						{$i18n.t('Generate Sample Q&A')}
					</span>
					<Tooltip
						content={`${$i18n.t('Creates example questions for few-shot learning')}<br>${$i18n.t('Select a model to enable Q&A generation')}`}
						placement="top"
					>
						<Info className="size-3.5 cursor-help text-[var(--cloo-text-muted)]" />
					</Tooltip>
					<Switch
						state={Boolean(extractModelId) && generateSampleQA}
						disabled={!extractModelId}
						on:change={handleQAToggle}
					/>
				</div>

				<Tooltip
					content={selectedTableIds.length === 0
						? $i18n.t('Select one or more tables to extract')
						: ''}
					placement="top"
					className="flex shrink-0"
				>
					<Button
						kind="filled"
						size="md"
						loading={extracting}
						disabled={extracting || selectedTableIds.length === 0}
						on:click={handleRunClick}
					>
						{$i18n.t('Run')}
					</Button>
				</Tooltip>
			</div>

			<!-- Area divider: separates the extraction controls above from the
			     table list below. Full-bleed (-mx-6) so the section break spans
			     the whole card width. -->
			<div class="-mx-6 border-t border-[var(--cloo-border-subtle)]"></div>

			<div class="flex flex-col">
				<div
					class="flex items-center gap-2.5 px-3 py-3 min-w-[160px]"
				>
					<Checkbox
						state={selectAllState === 'checked' ? 'checked' : 'unchecked'}
						indeterminate={selectAllState === 'indeterminate'}
						on:change={toggleSelectAll}
					/>
					<span class="text-sm text-[var(--cloo-text-primary)] flex-1">
						{$i18n.t('Select All')}
					</span>
					{#if selectedFilteredCount > 0}
						<span class="text-sm text-[var(--cloo-color-info)]">
							{selectedFilteredCount}
							{$i18n.t('selected')}
						</span>
					{/if}
				</div>

				{#each filteredTables as table (table.id)}
					{@const isSelected = selectedTableIds.includes(table.id)}
					{@const isExtracted = extractedTableNames.has(table.name)}
					<!-- svelte-ignore a11y-click-events-have-key-events -->
					<!-- svelte-ignore a11y-no-static-element-interactions -->
					<div
						class="cloo-db-connection__row flex items-center gap-2.5 px-3 py-3 min-w-[160px] cursor-pointer {isSelected
							? 'is-selected'
							: ''} {isExtracted ? 'is-extracted' : ''}"
						on:click={() => toggleRow(table.id)}
					>
						<!-- Visual-only Checkbox: row-level on:click already toggles.
						     If Checkbox handled clicks itself, the same event would
						     bubble up and double-toggle, producing a no-op when the
						     user clicks the checkbox directly. -->
						<span class="cloo-db-connection__cb">
							<Checkbox state={isSelected ? 'checked' : 'unchecked'} />
						</span>
						<span class="text-sm flex-1 min-w-0 truncate {isExtracted ? 'text-[var(--cloo-text-tertiary)]' : 'text-[var(--cloo-text-primary)]'}">
							{table.name}
						</span>
						{#if isExtracted}
							<span
								class="cloo-extracted-marker"
								aria-label={$i18n.t('Already extracted')}
								title={$i18n.t('Already extracted')}
							>
								<svg viewBox="0 0 16 16" class="size-3" aria-hidden="true">
									<path
										fill="currentColor"
										d="M13.78 4.22a.75.75 0 0 1 0 1.06l-7 7a.75.75 0 0 1-1.06 0l-3.5-3.5a.75.75 0 1 1 1.06-1.06L6.25 10.69l6.47-6.47a.75.75 0 0 1 1.06 0Z"
									/>
								</svg>
							</span>
						{/if}
					</div>
				{/each}

				{#if filteredTables.length === 0}
					<div class="text-sm text-[var(--cloo-text-tertiary)] px-3 py-6 text-center">
						{search
							? $i18n.t('No tables match the search.')
							: $i18n.t('No tables yet. Test the connection and extract schema to begin.')}
					</div>
				{/if}
			</div>
		</div>
	{:else if activeTab === 'extracted'}
		<!-- Extracted / Memory tabs are rendered by named slots so the parent
			 can mount FF8 (ExtractionTabs) without coupling this card to its
			 internals. Slot names must be static strings in Svelte. -->
		<div class="px-6 py-5">
			<slot name="extracted" />
		</div>
	{:else if activeTab === 'memory'}
		<div class="px-6 py-5">
			<slot name="memory" />
		</div>
	{/if}
</Card>

<ConfirmDialog
	bind:show={showReextractConfirm}
	title={$i18n.t('Re-extract schema?')}
	message={$i18n.t(
		'Re-running extraction resets the loaded few-shot examples, documents, and other memory if the schema has changed. Continue?'
	)}
	confirmLabel={$i18n.t('Continue')}
	on:confirm={handleExtract}
/>

<style>
	:global(.cloo-db-connection) {
		overflow: hidden;
	}
	.cloo-db-connection__tab.is-selected {
		color: var(--cloo-text-primary);
		font-weight: 600;
		border-bottom: 2px solid var(--cloo-text-primary);
	}
	.cloo-db-connection__tab.is-default {
		color: var(--cloo-text-tertiary);
	}
	.cloo-db-connection__tab:hover {
		background-color: var(--cloo-surface-hover);
	}
	.cloo-db-connection__row.is-selected {
		background-color: var(--cloo-bg-neutral-hovered, var(--cloo-surface-hover));
	}
	.cloo-db-connection__row:hover {
		background-color: var(--cloo-surface-hover);
	}
	.cloo-db-connection__cb {
		display: inline-flex;
		pointer-events: none;
	}

	.cloo-chip {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		height: 26px;
		padding: 0 10px;
		border-radius: 999px;
		border: 1px solid var(--cloo-border-subtle, #e3e4e9);
		background: var(--cloo-bg-surface, #fff);
		color: var(--cloo-text-default, #1a1a1a);
		font-size: 12px;
		line-height: 1;
		cursor: pointer;
		transition: background-color 100ms ease, border-color 100ms ease, color 100ms ease;
	}
	.cloo-chip:hover {
		background: var(--cloo-surface-hover, #f5f5f7);
	}
	.cloo-chip.is-active {
		background: var(--cloo-text-default, #1a1a1a);
		color: var(--cloo-bg-surface, #fff);
		border-color: var(--cloo-text-default, #1a1a1a);
	}
	.cloo-chip__count {
		opacity: 0.65;
		font-variant-numeric: tabular-nums;
		font-size: 11px;
	}
	.cloo-chip.is-active .cloo-chip__count {
		opacity: 0.7;
	}

	.cloo-extracted-marker {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 18px;
		height: 18px;
		border-radius: 50%;
		background: var(--cloo-color-success-soft, #dcfce7);
		color: var(--cloo-color-success, #008236);
		flex-shrink: 0;
	}

	.cloo-extract-progress {
		display: flex;
		flex-direction: column;
		gap: 8px;
		padding: 12px 14px;
		border-radius: 8px;
		border: 1px solid var(--cloo-color-info, #155dfc);
		background: var(--cloo-color-info-soft, #dbeafe);
	}
	.cloo-extract-progress__header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 8px;
	}
	.cloo-extract-progress__stop {
		display: inline-flex;
		align-items: center;
		padding: 2px 10px;
		font-size: 12px;
		font-weight: 500;
		line-height: 1.4;
		border-radius: 6px;
		border: 1px solid var(--cloo-danger-solid, #dc2626);
		color: var(--cloo-danger-solid, #dc2626);
		background: transparent;
		transition:
			background 120ms ease,
			color 120ms ease;
		white-space: nowrap;
	}
	.cloo-extract-progress__stop:hover:not(:disabled) {
		background: var(--cloo-danger-solid, #dc2626);
		color: #fff;
	}
	.cloo-extract-progress__stop:disabled {
		opacity: 0.55;
		cursor: default;
	}
	.cloo-extract-progress__bar {
		position: relative;
		height: 6px;
		border-radius: 999px;
		background: var(--cloo-bg-surface, rgba(255, 255, 255, 0.6));
		overflow: hidden;
	}
	.cloo-extract-progress__fill {
		position: absolute;
		left: 0;
		top: 0;
		bottom: 0;
		background: var(--cloo-color-info, #155dfc);
		border-radius: 999px;
		transition: width 300ms ease-out;
	}
	.cloo-extract-progress__meta {
		display: flex;
		align-items: center;
		gap: 8px;
		font-size: 12px;
		color: var(--cloo-text-muted, #6b7280);
	}
</style>

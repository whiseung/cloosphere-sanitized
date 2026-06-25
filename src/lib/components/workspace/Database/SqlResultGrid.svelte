<script lang="ts">
	import { getContext, onMount, onDestroy } from 'svelte';
	import type { Readable } from 'svelte/store';
	import { toast } from 'svelte-sonner';
	import Button from '$lib/components/common/Button.svelte';
	import Badge from '$lib/components/common/Badge.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import ChevronUp from '$lib/components/icons/ChevronUp.svelte';
	import ChevronDown from '$lib/components/icons/ChevronDown.svelte';
	import ChevronUpDown from '$lib/components/icons/ChevronUpDown.svelte';
	import Funnel from '$lib/components/icons/Funnel.svelte';
	import type { SqlExecuteResponse } from '$lib/apis/dbsphere';

	import SqlColumnFilterMenu, {
		type ColumnFilter,
		filterIsActive,
		filterAccepts
	} from './SqlColumnFilterMenu.svelte';

	type I18nStore = Readable<{ t: (key: string) => string }>;
	const i18n = getContext<I18nStore>('i18n');

	export let result: SqlExecuteResponse | null = null;
	export let onExpand: (() => void) | null = null;
	export let expanded: boolean = false;
	// When true: hide the internal toolbar (the parent renders its own bar).
	// Used by SqlEditorPanel where the dock-bar already shows op/rows/time.
	export let compact: boolean = false;

	// L2 mitigation: cells that begin with =, +, -, @ are interpreted as formulas
	// by Excel/Sheets. Prefix a single quote so the value is rendered as text.
	const FORMULA_PREFIX_RE = /^[=+\-@]/;

	const escapeCsvCell = (value: unknown): string => {
		const str = value === null || value === undefined ? '' : String(value);
		const guarded = FORMULA_PREFIX_RE.test(str) ? `'${str}` : str;
		// `\t` is included because some spreadsheet apps (LibreOffice Calc)
		// interpret tab-leading cells as formulas — wrap-and-quote them too.
		if (/[",\n\r\t]/.test(guarded)) {
			return `"${guarded.replace(/"/g, '""')}"`;
		}
		return guarded;
	};

	const toCsv = (cols: string[], rs: unknown[][]): string => {
		const header = cols.map(escapeCsvCell).join(',');
		const body = rs.map((row) => row.map(escapeCsvCell).join(',')).join('\n');
		return body ? `${header}\n${body}` : header;
	};

	export const handleExportCsv = () => {
		if (!result || !result.columns || !result.rows) return;
		try {
			const csv = toCsv(result.columns, result.rows);
			const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
			const url = URL.createObjectURL(blob);
			const anchor = document.createElement('a');
			anchor.href = url;
			const stamp = new Date().toISOString().replace(/[:.]/g, '-');
			anchor.download = `query-result-${stamp}.csv`;
			document.body.appendChild(anchor);
			anchor.click();
			document.body.removeChild(anchor);
			URL.revokeObjectURL(url);
		} catch (err) {
			console.error('CSV export failed', err);
			toast.error($i18n.t('CSV export failed'));
		}
	};

	const formatCell = (value: unknown): string => {
		if (value === null || value === undefined) return '';
		if (typeof value === 'object') return JSON.stringify(value);
		return String(value);
	};

	$: rows = result?.rows ?? [];
	$: columns = result?.columns ?? [];
	$: rowCount = result?.row_count ?? rows.length;
	$: totalRowCount = result?.total_row_count ?? rowCount;
	$: truncated = result?.truncated === true;
	$: execMs = result?.exec_ms ?? null;
	$: affectedRows = result?.affected_rows;
	$: hasGrid = columns.length > 0;
	$: opIsWrite = result?.op === 'WRITE';

	// ===================================================================
	// Sort / Filter / Selection state
	// ===================================================================
	type SortState = { colIdx: number; dir: 'asc' | 'desc' } | null;
	let sort: SortState = null;
	let filters: Record<number, ColumnFilter> = {};
	/** Set of *original* row indices currently selected. Survives sort/filter
	 * because identity is the source-row index. */
	let selected: Set<number> = new Set();
	/** Last clicked display index — used as the shift-click range anchor. */
	let anchorDisplayIdx: number | null = null;

	// Reset all derived state when the underlying result changes.
	let lastResultRef: unknown = null;
	$: if (result !== lastResultRef) {
		lastResultRef = result;
		sort = null;
		filters = {};
		selected = new Set();
		anchorDisplayIdx = null;
	}

	/** Per-column unique stringified value catalog — built lazily for the
	 * column the user clicks on (avoids paying the cost for unused columns). */
	const uniqueCache = new Map<number, string[]>();
	const getUniqueValues = (colIdx: number): string[] => {
		if (uniqueCache.has(colIdx)) return uniqueCache.get(colIdx)!;
		const seen = new Set<string>();
		for (const row of rows) {
			seen.add(formatCell(row[colIdx]));
		}
		const arr = Array.from(seen).sort((a, b) => a.localeCompare(b));
		uniqueCache.set(colIdx, arr);
		return arr;
	};
	// Reading `rows` in the body (not just listing it as a dep) guarantees
	// Svelte's compiler registers the reactive dependency reliably.
	$: if (rows) uniqueCache.clear();

	// ===================================================================
	// Comparator — uses original cell type when stable, falls back to string.
	// Numbers, dates, booleans are recognised by typeof + a date heuristic.
	// ===================================================================
	const cmp = (a: unknown, b: unknown): number => {
		// NULL/undefined always sort last regardless of direction (Postgres/MSSQL
		// convention varies but DataGrip default puts them at the bottom).
		const aNil = a === null || a === undefined;
		const bNil = b === null || b === undefined;
		if (aNil && bNil) return 0;
		if (aNil) return 1;
		if (bNil) return -1;
		if (typeof a === 'number' && typeof b === 'number') return a - b;
		if (typeof a === 'boolean' && typeof b === 'boolean') return a === b ? 0 : a ? 1 : -1;
		const aStr = formatCell(a);
		const bStr = formatCell(b);
		// Try numeric coercion when both look like numbers (string columns
		// that happen to hold numerics — common with CHAR/VARCHAR).
		const aNum = Number(aStr);
		const bNum = Number(bStr);
		if (!Number.isNaN(aNum) && !Number.isNaN(bNum) && aStr !== '' && bStr !== '') {
			return aNum - bNum;
		}
		return aStr.localeCompare(bStr, undefined, { numeric: true });
	};

	/** Original row indices that survive every active column filter. */
	$: filteredIndices = (() => {
		if (Object.keys(filters).length === 0) return rows.map((_, i) => i);
		return rows
			.map((_, i) => i)
			.filter((rowIdx) => {
				for (const [colIdxStr, f] of Object.entries(filters)) {
					if (!filterIsActive(f)) continue;
					const colIdx = Number(colIdxStr);
					if (!filterAccepts(f, formatCell(rows[rowIdx][colIdx]))) return false;
				}
				return true;
			});
	})();

	/** Filtered indices arranged in the requested sort order. */
	$: displayedIndices = (() => {
		if (!sort) return filteredIndices;
		const dir = sort.dir === 'asc' ? 1 : -1;
		const col = sort.colIdx;
		// Copy to avoid mutating filteredIndices.
		return [...filteredIndices].sort(
			(a, b) => dir * cmp(rows[a][col], rows[b][col])
		);
	})();

	const cycleSort = (colIdx: number) => {
		if (!sort || sort.colIdx !== colIdx) {
			sort = { colIdx, dir: 'asc' };
			return;
		}
		if (sort.dir === 'asc') sort = { colIdx, dir: 'desc' };
		else sort = null;
	};

	// ===================================================================
	// Filter menu — only one open at a time.
	// ===================================================================
	let openFilterColIdx: number | null = null;
	let filterAnchorEl: HTMLElement | null = null;

	const openFilter = (colIdx: number, anchor: HTMLElement) => {
		// Clicking the same funnel that opened the menu toggles it closed.
		// The window-level outside-click would otherwise dispatch close,
		// then this handler would immediately re-open it on the same click.
		if (openFilterColIdx === colIdx) {
			closeFilter();
			return;
		}
		openFilterColIdx = colIdx;
		filterAnchorEl = anchor;
	};
	const closeFilter = () => {
		openFilterColIdx = null;
		filterAnchorEl = null;
	};
	const onFilterChange = (colIdx: number, nextFilter: ColumnFilter) => {
		if (nextFilter.mode === 'all') {
			const { [colIdx]: _drop, ...rest } = filters;
			filters = rest;
		} else {
			filters = { ...filters, [colIdx]: nextFilter };
		}
		// Filtering changes which rows are visible — drop selection anchors
		// that may now point at a different row.
		anchorDisplayIdx = null;
	};

	/** Handler attached to the menu's `change` event — closes over the
	 * currently open column so the template doesn't need template-level
	 * type narrowing on `openFilterColIdx`. */
	const handleFilterMenuChange = (e: CustomEvent<{ filter: ColumnFilter }>) => {
		if (openFilterColIdx === null) return;
		onFilterChange(openFilterColIdx, e.detail.filter);
	};

	// ===================================================================
	// Selection — click / shift-click / cmd-click
	// ===================================================================
	const handleRowMouseDown = (event: MouseEvent, displayIdx: number) => {
		// Skip selection logic when the click originated on a header control
		// (handled separately). For row clicks: prevent text-selection drag
		// so shift-click range works cleanly.
		if (event.shiftKey) event.preventDefault();
		const rowIdx = displayedIndices[displayIdx];
		const isModifier = event.ctrlKey || event.metaKey;

		if (event.shiftKey && anchorDisplayIdx !== null) {
			const [lo, hi] =
				anchorDisplayIdx < displayIdx
					? [anchorDisplayIdx, displayIdx]
					: [displayIdx, anchorDisplayIdx];
			const next = new Set(isModifier ? selected : []);
			for (let i = lo; i <= hi; i++) next.add(displayedIndices[i]);
			selected = next;
			return;
		}
		if (isModifier) {
			const next = new Set(selected);
			if (next.has(rowIdx)) next.delete(rowIdx);
			else next.add(rowIdx);
			selected = next;
			anchorDisplayIdx = displayIdx;
			return;
		}
		// Plain click — replace selection.
		selected = new Set([rowIdx]);
		anchorDisplayIdx = displayIdx;
	};

	const selectAllVisible = () => {
		selected = new Set(displayedIndices);
	};
	const clearSelection = () => {
		selected = new Set();
		anchorDisplayIdx = null;
	};

	// ===================================================================
	// Copy — Cmd/Ctrl+C → TSV of selected rows (or all visible if none).
	// ===================================================================
	const tsvEscape = (s: string): string => {
		// TSV: replace tab with space, newlines with \\n placeholder so the
		// row stays on one line when pasted into Excel/Sheets.
		return s.replace(/\t/g, ' ').replace(/\r?\n/g, '\\n');
	};

	const buildTsv = (rowIdxs: number[], includeHeader: boolean): string => {
		const lines: string[] = [];
		if (includeHeader) {
			lines.push(columns.map((c) => tsvEscape(c)).join('\t'));
		}
		for (const i of rowIdxs) {
			lines.push(rows[i].map((c) => tsvEscape(formatCell(c))).join('\t'));
		}
		return lines.join('\n');
	};

	const handleCopy = async () => {
		// Copy selected rows in display order; fall back to all visible rows
		// when nothing is selected (matches DataGrip's "no selection = copy
		// what you see" behavior).
		const selectionOrdered = displayedIndices.filter((i) => selected.has(i));
		const toCopy = selectionOrdered.length > 0 ? selectionOrdered : displayedIndices;
		if (toCopy.length === 0) return;
		const tsv = buildTsv(toCopy, /* includeHeader */ selectionOrdered.length === 0);
		try {
			await navigator.clipboard.writeText(tsv);
			toast.success(
				$i18n.t('{{count}} rows copied').replace('{{count}}', String(toCopy.length))
			);
		} catch (err) {
			console.error('Clipboard write failed', err);
			toast.error($i18n.t('Copy failed'));
		}
	};

	// ===================================================================
	// Keyboard — Cmd/Ctrl+C copies; Cmd/Ctrl+A selects all visible rows.
	// Attached to a focusable wrapper so the shortcuts don't fight with
	// the editor's Cmd+C when the grid isn't focused.
	// ===================================================================
	const handleKeyDown = (event: KeyboardEvent) => {
		const target = event.target as HTMLElement | null;
		// Let inputs (search box in filter menu, etc.) handle their own keys.
		if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA')) return;
		const mod = event.ctrlKey || event.metaKey;
		if (!mod) return;
		if (event.key === 'c' || event.key === 'C') {
			if (selected.size === 0) return; // don't hijack global copy
			event.preventDefault();
			handleCopy();
		} else if (event.key === 'a' || event.key === 'A') {
			event.preventDefault();
			selectAllVisible();
		}
	};

	let wrapperEl: HTMLElement | null = null;
	onMount(() => {
		wrapperEl?.addEventListener('keydown', handleKeyDown);
	});
	onDestroy(() => {
		wrapperEl?.removeEventListener('keydown', handleKeyDown);
	});

	$: hasActiveFilters = Object.values(filters).some((f) => filterIsActive(f));
</script>

<!-- svelte-ignore a11y-no-noninteractive-tabindex -->
<div
	bind:this={wrapperEl}
	class="cloo-sql-result flex flex-col h-full min-h-0"
	tabindex="0"
>
	{#if result}
		{#if !compact}
			<div
				class="cloo-sql-result__status flex items-center gap-3 text-xs text-[var(--cloo-text-muted)] px-3 py-2 border-b border-[var(--cloo-border-subtle)]"
			>
				<span class="cloo-op-dot" class:is-write={opIsWrite} aria-hidden="true" />
				<span class="font-medium text-[var(--cloo-text-default)]">{result.op}</span>

				{#if execMs !== null}
					<span>{$i18n.t('Time')}: {execMs}ms</span>
				{/if}

				{#if hasGrid}
					<span
						>{$i18n.t('Rows')}: {displayedIndices.length}{displayedIndices.length !==
						rowCount
							? ` / ${rowCount}`
							: ''}{totalRowCount !== rowCount ? ` (${totalRowCount})` : ''}</span
					>
				{:else if affectedRows !== null && affectedRows !== undefined}
					<span>{$i18n.t('Affected rows')}: {affectedRows}</span>
				{/if}

				{#if truncated}
					<Badge status="warning" size="sm" content={$i18n.t('Result truncated')} />
				{/if}

				{#if result.message}
					<span class="truncate">{result.message}</span>
				{/if}

				<div class="ml-auto flex items-center gap-2">
					{#if hasGrid}
						<Button kind="text" size="sm" on:click={handleExportCsv}>
							{$i18n.t('Export CSV')}
						</Button>
					{/if}
					{#if onExpand}
						<Button kind="text" size="sm" on:click={onExpand}>
							{expanded ? $i18n.t('Collapse') : $i18n.t('Expand')}
						</Button>
					{/if}
				</div>
			</div>
		{/if}

		<div class="cloo-sql-result__body flex-1 min-h-0 overflow-auto">
			{#if hasGrid}
				<table class="cloo-sql-result__table text-xs border-collapse">
					<thead>
						<tr>
							<th class="cloo-sql-result__th-rownum">#</th>
							{#each columns as col, colIdx (colIdx)}
								{@const isSorted = sort?.colIdx === colIdx}
								{@const filterActive = filterIsActive(filters[colIdx])}
								<th class="cloo-sql-result__th" title={col}>
									<div class="cloo-sql-result__th-inner">
										<!-- svelte-ignore a11y-click-events-have-key-events -->
										<button
											type="button"
											class="cloo-sql-result__th-funnel"
											class:is-active={filterActive}
											aria-label={$i18n.t('Filter column')}
											title={$i18n.t('Filter column')}
											on:click={(e) => openFilter(colIdx, e.currentTarget)}
										>
											<Funnel className="w-3 h-3" strokeWidth="1.6" filled={filterActive} />
										</button>
										<span class="cloo-sql-result__th-label">{col}</span>
										<button
											type="button"
											class="cloo-sql-result__th-sort"
											class:is-active={isSorted}
											aria-label={$i18n.t('Sort column')}
											title={$i18n.t('Sort column')}
											on:click={() => cycleSort(colIdx)}
										>
											{#if isSorted && sort?.dir === 'asc'}
												<ChevronUp className="w-3 h-3" strokeWidth="2" />
											{:else if isSorted && sort?.dir === 'desc'}
												<ChevronDown className="w-3 h-3" strokeWidth="2" />
											{:else}
												<ChevronUpDown className="w-3 h-3" strokeWidth="1.6" />
											{/if}
										</button>
									</div>
								</th>
							{/each}
						</tr>
					</thead>
					<tbody>
						{#each displayedIndices as rowIdx, displayIdx (rowIdx)}
							{@const row = rows[rowIdx]}
							{@const isSelected = selected.has(rowIdx)}
							<!-- svelte-ignore a11y-click-events-have-key-events -->
							<!-- svelte-ignore a11y-no-noninteractive-element-interactions -->
							<tr
								class="cloo-sql-result__row"
								class:is-selected={isSelected}
								on:mousedown={(e) => handleRowMouseDown(e, displayIdx)}
							>
								<td class="cloo-sql-result__td-rownum">{rowIdx + 1}</td>
								{#each row as cell, colIdx (colIdx)}
									{@const cellText = formatCell(cell)}
									<td
										class="cloo-sql-result__td"
										class:is-null={cell === null || cell === undefined}
									>
										{#if cell === null || cell === undefined}
											<span class="cloo-null">NULL</span>
										{:else if cellText.length > 64}
											<Tooltip content={cellText} placement="top">
												<span class="cloo-sql-result__td-text">{cellText}</span>
											</Tooltip>
										{:else}
											<span class="cloo-sql-result__td-text">{cellText}</span>
										{/if}
									</td>
								{/each}
							</tr>
						{/each}
					</tbody>
				</table>

				{#if hasActiveFilters && displayedIndices.length === 0}
					<div class="cloo-sql-result__empty">
						{$i18n.t('No rows match the active filters.')}
						<button type="button" class="cloo-sql-result__clear-filters" on:click={() => (filters = {})}>
							{$i18n.t('Clear Filters')}
						</button>
					</div>
				{/if}
			{:else}
				<div
					class="flex items-center justify-center h-full text-sm text-[var(--cloo-text-muted)] px-4 py-6"
				>
					{result.message ?? $i18n.t('Statement executed.')}
				</div>
			{/if}
		</div>

		<!-- Selection summary footer — only when something is selected. -->
		{#if selected.size > 0}
			<div class="cloo-sql-result__selection-bar">
				<span>
					{$i18n.t('{{count}} rows selected').replace('{{count}}', String(selected.size))}
				</span>
				<button type="button" class="cloo-sql-result__sel-action" on:click={handleCopy}>
					{$i18n.t('Copy')} <kbd>⌘C</kbd>
				</button>
				<button type="button" class="cloo-sql-result__sel-action" on:click={clearSelection}>
					{$i18n.t('Clear')}
				</button>
			</div>
		{/if}
	{:else}
		<div class="flex-1 flex items-center justify-center text-sm text-[var(--cloo-text-muted)]">
			{$i18n.t('Run a query to see results.')}
		</div>
	{/if}
</div>

{#if openFilterColIdx !== null && filterAnchorEl}
	<SqlColumnFilterMenu
		values={getUniqueValues(openFilterColIdx)}
		filter={filters[openFilterColIdx] ?? { mode: 'all' }}
		anchor={filterAnchorEl}
		on:change={handleFilterMenuChange}
		on:close={closeFilter}
	/>
{/if}

<style>
	.cloo-sql-result {
		outline: none;
	}

	.cloo-sql-result__table {
		border-spacing: 0;
		min-width: 100%;
		width: max-content;
	}

	.cloo-sql-result__th,
	.cloo-sql-result__th-rownum {
		position: sticky;
		top: 0;
		z-index: 3;
		background: var(--cloo-bg-surface, #fff);
		text-align: left;
		font-weight: 500;
		color: var(--cloo-text-default, #1a1a1a);
		padding: 4px 4px 4px 6px;
		border-bottom: 1px solid var(--cloo-border-default, #d5d5da);
		white-space: nowrap;
		font-family: 'Pretendard Variable', 'Pretendard', sans-serif;
		font-size: 12px;
		line-height: 16px;
	}

	.cloo-sql-result__th {
		min-width: 110px;
		max-width: 320px;
		border-right: 1px solid var(--cloo-border-subtle, #e3e4e9);
	}
	.cloo-sql-result__th:last-child {
		border-right: none;
	}

	.cloo-sql-result__th-inner {
		display: flex;
		align-items: center;
		gap: 4px;
		min-width: 0;
	}

	.cloo-sql-result__th-label {
		flex: 1;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.cloo-sql-result__th-funnel,
	.cloo-sql-result__th-sort {
		flex-shrink: 0;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 18px;
		height: 18px;
		border-radius: 3px;
		border: none;
		background: transparent;
		color: var(--cloo-text-muted, #6b7280);
		cursor: pointer;
		transition: background-color 80ms ease, color 80ms ease;
	}
	.cloo-sql-result__th-funnel:hover,
	.cloo-sql-result__th-sort:hover {
		background: var(--cloo-surface-hover, #f5f5f7);
		color: var(--cloo-text-default, #1a1a1a);
	}
	.cloo-sql-result__th-funnel.is-active,
	.cloo-sql-result__th-sort.is-active {
		color: var(--cloo-color-primary, #155dfc);
	}

	/* Sticky row-number column */
	.cloo-sql-result__th-rownum,
	.cloo-sql-result__td-rownum {
		position: sticky;
		left: 0;
		z-index: 2;
		width: 44px;
		min-width: 44px;
		max-width: 44px;
		text-align: right;
		color: var(--cloo-text-muted, #6b7280);
		background: var(--cloo-bg-surface, #fff);
		padding: 4px 10px;
		border-right: 1px solid var(--cloo-border-subtle, #e3e4e9);
		font-variant-numeric: tabular-nums;
		user-select: none;
	}
	.cloo-sql-result__th-rownum {
		z-index: 4;
	}

	.cloo-sql-result__td {
		padding: 4px 10px;
		vertical-align: top;
		border-bottom: 1px solid var(--cloo-border-subtle, #e3e4e9);
		border-right: 1px solid var(--cloo-border-subtle, #e3e4e9);
		font-family: 'JetBrains Mono', 'SF Mono', Consolas, monospace;
		font-size: 12px;
		line-height: 18px;
		max-width: 320px;
		min-width: 80px;
		user-select: none;
	}
	.cloo-sql-result__td:last-child {
		border-right: none;
	}

	.cloo-sql-result__td-text {
		display: block;
		max-width: 320px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.cloo-sql-result__row:hover .cloo-sql-result__td,
	.cloo-sql-result__row:hover .cloo-sql-result__td-rownum {
		background: var(--cloo-surface-hover, #f5f5f7);
	}

	/* Selected row — blue tint that survives hover. */
	.cloo-sql-result__row.is-selected .cloo-sql-result__td,
	.cloo-sql-result__row.is-selected .cloo-sql-result__td-rownum {
		background: var(--cloo-color-info-soft, #dbeafe);
		color: var(--cloo-text-default, #1a1a1a);
	}
	.cloo-sql-result__row.is-selected:hover .cloo-sql-result__td,
	.cloo-sql-result__row.is-selected:hover .cloo-sql-result__td-rownum {
		background: var(--cloo-color-info-soft, #c7dcfd);
	}

	.cloo-null {
		color: var(--cloo-text-tertiary, #9d9ea9);
		font-style: italic;
	}

	.cloo-op-dot {
		width: 8px;
		height: 8px;
		border-radius: 50%;
		display: inline-block;
		background: var(--cloo-color-info, #155dfc);
		flex-shrink: 0;
	}
	.cloo-op-dot.is-write {
		background: var(--cloo-color-warning, #ea580c);
	}

	.cloo-sql-result__empty {
		padding: 24px;
		text-align: center;
		color: var(--cloo-text-muted, #6b7280);
		font-size: 13px;
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 8px;
	}
	.cloo-sql-result__clear-filters {
		font-size: 12px;
		color: var(--cloo-color-primary, #155dfc);
		background: transparent;
		border: none;
		cursor: pointer;
		padding: 4px 8px;
		border-radius: 4px;
	}
	.cloo-sql-result__clear-filters:hover {
		background: var(--cloo-surface-hover, #f5f5f7);
	}

	.cloo-sql-result__selection-bar {
		display: flex;
		align-items: center;
		gap: 12px;
		padding: 4px 12px;
		font-size: 11px;
		color: var(--cloo-text-muted, #6b7280);
		background: var(--cloo-color-info-soft, #eef4ff);
		border-top: 1px solid var(--cloo-border-subtle, #e3e4e9);
	}
	.cloo-sql-result__sel-action {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		font-size: 11px;
		font-weight: 500;
		color: var(--cloo-color-primary, #155dfc);
		background: transparent;
		border: none;
		padding: 2px 6px;
		border-radius: 3px;
		cursor: pointer;
	}
	.cloo-sql-result__sel-action:hover {
		background: var(--cloo-surface-hover, #f5f5f7);
	}
	.cloo-sql-result__sel-action kbd {
		font-family: 'JetBrains Mono', 'SF Mono', Consolas, monospace;
		font-size: 10px;
		color: var(--cloo-text-muted, #6b7280);
		background: var(--cloo-bg-surface, #fff);
		border: 1px solid var(--cloo-border-subtle, #e3e4e9);
		border-radius: 3px;
		padding: 0 4px;
	}
</style>

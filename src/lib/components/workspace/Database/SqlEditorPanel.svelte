<script lang="ts">
	import { getContext, onMount, onDestroy } from 'svelte';
	import type { Readable } from 'svelte/store';
	import { slide } from 'svelte/transition';
	import { toast } from 'svelte-sonner';

	import Button from '$lib/components/common/Button.svelte';
	import CodeEditor from '$lib/components/common/CodeEditor.svelte';
	import Badge from '$lib/components/common/Badge.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import ChevronUp from '$lib/components/icons/ChevronUp.svelte';
	import ChevronDown from '$lib/components/icons/ChevronDown.svelte';
	import ArrowsPointingOut from '$lib/components/icons/ArrowsPointingOut.svelte';
	import ArrowDownTray from '$lib/components/icons/ArrowDownTray.svelte';
	import Play from '$lib/components/icons/Play.svelte';
	import Stop from '$lib/components/icons/Stop.svelte';
	import Eye from '$lib/components/icons/Eye.svelte';
	import EyeSlash from '$lib/components/icons/EyeSlash.svelte';
	import Info from '$lib/components/icons/Info.svelte';
	import Plus from '$lib/components/icons/Plus.svelte';
	import XMark from '$lib/components/icons/XMark.svelte';

	import {
		acceptServerCopy,
		cancelActiveExecution,
		closeTab,
		confirmPending,
		executeActiveTab,
		loadSqlFiles,
		openNewTab,
		persistTabs,
		rejectPending,
		removeTab,
		renameTab,
		saveTab,
		setActiveTab,
		sqlEditorStore,
		updateTabContent
	} from '$lib/stores/sqlEditor';
	import { showSidebar, mobile } from '$lib/stores';
	import type { SqlFileConflict } from '$lib/apis/dbsphere';
	import type { SqlDialectName } from '$lib/utils/sqlDialect';

	import SqlResultGrid from './SqlResultGrid.svelte';
	import PendingConfirmCard from './PendingConfirmCard.svelte';

	type I18nStore = Readable<{ t: (key: string, vars?: Record<string, unknown>) => string }>;
	const i18n = getContext<I18nStore>('i18n');

	export let show: boolean = false;
	export let dbsphereId: string;
	export let dialect: SqlDialectName = 'standard';
	/** Table → columns map fed by parent for schema-aware autocomplete. */
	export let schema: Record<string, string[]> | null = null;
	/** Connection context for the DataGrip-style indicator in the tabs row.
	 * Format: `{databaseName}.{schemaName}` when both present, else just db. */
	export let databaseName: string = '';
	export let schemaName: string = '';

	// CodeEditor instance — for getSelection() (Run Selection feature).
	let codeEditorRef: CodeEditor | null = null;

	// ===================================================================
	// Read-only mode — client-side gate that blocks non-READ statements
	// regardless of the dbsphere's `allow_data_modifications` setting.
	// State persists per dbsphere in localStorage. Backend remains the
	// authoritative enforcer (server inspects SQL ops too) — this is a
	// user-facing safety net to prevent accidental writes in exploration.
	// ===================================================================
	const READ_ONLY_KEY_PREFIX = 'cloo.sqlEditor.readOnly.';
	let readOnlyMode = false;
	const toggleReadOnly = () => {
		readOnlyMode = !readOnlyMode;
		if (dbsphereId) {
			try {
				localStorage.setItem(READ_ONLY_KEY_PREFIX + dbsphereId, readOnlyMode ? '1' : '0');
			} catch {
				// ignore
			}
		}
	};

	// Strip block comments and line comments before sniffing the first
	// keyword. Liberal but conservative: anything we can't confidently
	// classify as READ is treated as a write.
	const READ_FIRST_KEYWORDS = /^(SELECT|WITH|SHOW|DESCRIBE|DESC|EXPLAIN|PRAGMA|VALUES|TABLE)\b/;
	const looksLikeReadOnly = (sql: string): boolean => {
		const stripped = sql
			.replace(/\/\*[\s\S]*?\*\//g, ' ')
			.replace(/--.*$/gm, ' ')
			.trim()
			.toUpperCase();
		return READ_FIRST_KEYWORDS.test(stripped);
	};

	// ===================================================================
	// Result section state machine:
	//   'hidden' | 'collapsed' | 'open'
	// - hidden:    no result data (or user dismissed)
	// - collapsed: 36px bar with summary only
	// - open:      bar + grid, user-resizable height (default after Run)
	//
	// `isMaximized` is orthogonal: when true AND state === 'open', the result
	// renders as a full-page-width drawer at the bottom of the viewport
	// (escaping the narrow aside) so that many SQL result columns are visible.
	// The drawer is NOT a floating overlay — the parent layout reserves
	// `maximizedResultHeight` of bottom padding via the exported binding,
	// so the editor/page content above shrinks rather than being covered.
	// Inline (non-maximized) and drawer (maximized) have separate heights.
	// ===================================================================
	type ResultState = 'hidden' | 'collapsed' | 'open';
	let resultState: ResultState = 'hidden';
	let resultHeight = 280; // inline height (inside aside)
	let isMaximized = false;
	const MIN_RESULT_HEIGHT = 100;
	const RESULT_KEY = 'cloo.sqlEditorPanel.resultHeight';
	let resultResizing = false;
	let resultDragStartY = 0;
	let resultDragStartHeight = 0;

	// Drawer height (full-page-width mode)
	const DRAWER_KEY = 'cloo.sqlEditorPanel.drawerHeight';
	const MIN_DRAWER_HEIGHT = 200;
	let drawerHeight = 0; // initialized in onMount
	let drawerResizing = false;
	let drawerDragStartY = 0;
	let drawerDragStartHeight = 0;

	/**
	 * Exposed to parent so it can reserve bottom padding on the page body row.
	 * Equals current drawerHeight while a result is being shown in drawer mode,
	 * else 0. Parent should bind: this and apply as padding-bottom on the
	 * scrolling region above so the drawer never visually overlaps content.
	 */
	export let maximizedResultHeight: number = 0;

	const cycleResult = () => {
		if (resultState === 'collapsed') resultState = 'open';
		else if (resultState === 'open') {
			resultState = 'collapsed';
			isMaximized = false;
		}
	};
	const toggleMaximize = () => {
		if (resultState !== 'open') resultState = 'open';
		isMaximized = !isMaximized;
	};
	const dismissResult = () => {
		resultState = 'hidden';
		isMaximized = false;
	};

	const maxAllowedResultHeight = (): number => {
		if (typeof window === 'undefined') return 800;
		// Keep at least 160px for editor visible (header + tabs + filename + some editor).
		return Math.max(MIN_RESULT_HEIGHT, window.innerHeight - 240);
	};
	const clampResultHeight = (h: number): number => {
		const max = maxAllowedResultHeight();
		return Math.max(MIN_RESULT_HEIGHT, Math.min(max, h));
	};

	const handleResultDragStart = (event: MouseEvent) => {
		if (resultState !== 'open') return;
		event.preventDefault();
		event.stopPropagation();
		resultResizing = true;
		resultDragStartY = event.clientY;
		resultDragStartHeight = resultHeight;
		window.addEventListener('mousemove', handleResultDragMove);
		window.addEventListener('mouseup', handleResultDragEnd);
		document.body.style.cursor = 'ns-resize';
		document.body.style.userSelect = 'none';
	};
	const handleResultDragMove = (event: MouseEvent) => {
		if (!resultResizing) return;
		// Dragging up: handle moves up → result grows
		const delta = resultDragStartY - event.clientY;
		resultHeight = clampResultHeight(resultDragStartHeight + delta);
	};
	const handleResultDragEnd = () => {
		if (!resultResizing) return;
		resultResizing = false;
		window.removeEventListener('mousemove', handleResultDragMove);
		window.removeEventListener('mouseup', handleResultDragEnd);
		document.body.style.cursor = '';
		document.body.style.userSelect = '';
		try {
			localStorage.setItem(RESULT_KEY, String(resultHeight));
		} catch {
			// ignore
		}
	};

	// Drawer (full-page-width mode) — separate height + drag handlers
	const computeMaxDrawerHeight = (): number => {
		if (typeof window === 'undefined') return 800;
		// Leave a small editor + header strip visible above the drawer
		return Math.max(MIN_DRAWER_HEIGHT, window.innerHeight - 160);
	};
	const clampDrawerHeight = (h: number): number => {
		const max = computeMaxDrawerHeight();
		return Math.max(MIN_DRAWER_HEIGHT, Math.min(max, h));
	};

	const handleDrawerDragStart = (event: MouseEvent) => {
		event.preventDefault();
		drawerResizing = true;
		drawerDragStartY = event.clientY;
		drawerDragStartHeight = drawerHeight;
		window.addEventListener('mousemove', handleDrawerDragMove);
		window.addEventListener('mouseup', handleDrawerDragEnd);
		document.body.style.cursor = 'ns-resize';
		document.body.style.userSelect = 'none';
	};
	const handleDrawerDragMove = (event: MouseEvent) => {
		if (!drawerResizing) return;
		// Top-edge handle: dragging up grows the drawer.
		const delta = drawerDragStartY - event.clientY;
		drawerHeight = clampDrawerHeight(drawerDragStartHeight + delta);
	};
	const handleDrawerDragEnd = () => {
		if (!drawerResizing) return;
		drawerResizing = false;
		window.removeEventListener('mousemove', handleDrawerDragMove);
		window.removeEventListener('mouseup', handleDrawerDragEnd);
		document.body.style.cursor = '';
		document.body.style.userSelect = '';
		try {
			localStorage.setItem(DRAWER_KEY, String(drawerHeight));
		} catch {
			// ignore
		}
	};

	// Keep the exported `maximizedResultHeight` in sync so the parent
	// can reserve matching bottom padding (no overlap, embedded feel).
	$: maximizedResultHeight =
		show && isMaximized && resultState === 'open' && activeTab?.lastResult
			? drawerHeight
			: 0;
	// Drawer must clear the app's left sidebar — on mobile the sidebar is
	// an overlay (no horizontal footprint), on desktop it's 260px open or
	// 68px collapsed. Falls back to a CSS transition so the drawer slides
	// smoothly when the user toggles the sidebar while the drawer is up.
	$: drawerLeftOffset = $mobile ? 0 : $showSidebar ? 260 : 68;
	// Closing the editor must drop maximize state — parent stops reserving
	// padding and reopen lands in inline mode.
	$: if (!show && isMaximized) isMaximized = false;

	// ===================================================================
	// Panel width (left-edge resize)
	// ===================================================================
	const STORAGE_KEY = 'cloo.sqlEditorPanel.width';
	const MIN_WIDTH = 320;
	const DEFAULT_WIDTH = 520;

	let panelWidth = DEFAULT_WIDTH;
	let widthResizing = false;
	let widthDragStartX = 0;
	let widthDragStartWidth = 0;

	const computeMaxPanelWidth = (): number => {
		if (typeof window === 'undefined') return 1200;
		return Math.max(MIN_WIDTH, window.innerWidth - 360);
	};
	const clampPanelWidth = (w: number): number => {
		const max = computeMaxPanelWidth();
		if (w < MIN_WIDTH) return MIN_WIDTH;
		if (w > max) return max;
		return w;
	};

	const handleWidthResizeStart = (event: MouseEvent) => {
		event.preventDefault();
		widthResizing = true;
		widthDragStartX = event.clientX;
		widthDragStartWidth = panelWidth;
		window.addEventListener('mousemove', handleWidthResizeMove);
		window.addEventListener('mouseup', handleWidthResizeEnd);
		document.body.style.cursor = 'col-resize';
		document.body.style.userSelect = 'none';
	};
	const handleWidthResizeMove = (event: MouseEvent) => {
		if (!widthResizing) return;
		const delta = widthDragStartX - event.clientX;
		panelWidth = clampPanelWidth(widthDragStartWidth + delta);
	};
	const handleWidthResizeEnd = () => {
		if (!widthResizing) return;
		widthResizing = false;
		window.removeEventListener('mousemove', handleWidthResizeMove);
		window.removeEventListener('mouseup', handleWidthResizeEnd);
		document.body.style.cursor = '';
		document.body.style.userSelect = '';
		try {
			localStorage.setItem(STORAGE_KEY, String(panelWidth));
		} catch {
			// ignore
		}
	};
	const handleWidthResizeKeyDown = (event: KeyboardEvent) => {
		const step = event.shiftKey ? 40 : 16;
		if (event.key === 'ArrowLeft') {
			event.preventDefault();
			panelWidth = clampPanelWidth(panelWidth + step);
		} else if (event.key === 'ArrowRight') {
			event.preventDefault();
			panelWidth = clampPanelWidth(panelWidth - step);
		}
	};

	const handleWindowResize = () => {
		panelWidth = clampPanelWidth(panelWidth);
		resultHeight = clampResultHeight(resultHeight);
		drawerHeight = clampDrawerHeight(drawerHeight);
	};

	// ===================================================================
	// Editor status bar — Ln/Col + char count fed by CodeEditor events
	// ===================================================================
	let cursorLine = 1;
	let cursorCol = 1;
	let docLength = 0;
	let selectionLength = 0;
	$: hasSelection = selectionLength > 0;
	const handleSelectionChange = (
		event: CustomEvent<{ line: number; col: number; length: number; selectionLength: number }>
	) => {
		cursorLine = event.detail.line;
		cursorCol = event.detail.col;
		docLength = event.detail.length;
		selectionLength = event.detail.selectionLength;
	};

	// ===================================================================
	// Tab/editor handlers (unchanged behavior)
	// ===================================================================
	const handleClose = () => {
		show = false;
	};

	const handleNewTab = () => {
		openNewTab(`untitled-${$sqlEditorStore.tabs.length + 1}.sql`);
	};

	const handleCloseTab = async (tabId: string) => {
		const tab = $sqlEditorStore.tabs.find((t) => t.id === tabId);
		if (!tab) return;
		if (tab.dirty) {
			if (!confirm($i18n.t('Discard unsaved changes in this tab?'))) return;
		}
		if (tab.fileId) {
			if (!confirm($i18n.t('Delete this SQL file permanently?'))) {
				closeTab(tabId);
				return;
			}
			try {
				await removeTab(localStorage.token, tabId);
			} catch (err) {
				toast.error(String(err));
			}
		} else {
			closeTab(tabId);
		}
	};

	const handleSave = async () => {
		const active = $sqlEditorStore.activeTabId;
		if (!active) return;
		try {
			await saveTab(localStorage.token, active);
			toast.success($i18n.t('Saved'));
		} catch (err) {
			const conflict = err as SqlFileConflict;
			if (conflict && conflict.code === 'conflict' && conflict.server) {
				const ok = confirm(
					$i18n.t('This file was modified elsewhere') +
						'\n\n' +
						$i18n.t('Discard your changes and load the server copy?')
				);
				if (ok) {
					acceptServerCopy(active, conflict.server);
					toast.success($i18n.t('Server copy loaded'));
				}
			} else {
				toast.error(String(err));
			}
		}
	};

	const handleRun = async () => {
		// Use selection if non-empty, otherwise the full tab content.
		const selection = codeEditorRef?.getSelection?.();
		const sqlToRun = selection && selection.trim() ? selection : activeTab?.content ?? '';
		if (!sqlToRun.trim()) return;

		if (readOnlyMode && !looksLikeReadOnly(sqlToRun)) {
			toast.error($i18n.t('Read-only mode is on — disable to run write queries.'));
			return;
		}
		try {
			await executeActiveTab(localStorage.token, selection ?? undefined);
		} catch (err) {
			// AbortError = user pressed Stop; not an error to surface.
			if ((err as { name?: string })?.name === 'AbortError') return;
			toast.error(String(err));
		}
	};

	const handleStop = () => {
		const aborted = cancelActiveExecution();
		if (aborted) {
			toast.success($i18n.t('Execution cancelled.'));
		}
	};

	const handleCommit = async () => {
		try {
			await confirmPending(localStorage.token);
			toast.success($i18n.t('Executed'));
		} catch (err) {
			toast.error(String(err));
		}
	};

	const handleRollback = async () => {
		try {
			await rejectPending(localStorage.token);
		} catch (err) {
			toast.error(String(err));
		}
	};

	const handleContentChange = (tabId: string) => (value: string) => {
		updateTabContent(tabId, value);
	};

	const handleRenameTab = (tabId: string, event: Event) => {
		const input = event.target as HTMLInputElement;
		renameTab(tabId, input.value);
	};

	// Inline and drawer grids are rendered in mutually-exclusive `{#if}`
	// branches, so exactly one ref is non-null at a time. A single shared
	// `bind:this` would briefly resolve to null during the maximize toggle.
	let inlineGridRef: SqlResultGrid | null = null;
	let drawerGridRef: SqlResultGrid | null = null;
	const handleExportCsvBar = () =>
		(inlineGridRef ?? drawerGridRef)?.handleExportCsv();

	$: activeTab = $sqlEditorStore.tabs.find((t) => t.id === $sqlEditorStore.activeTabId) ?? null;
	$: pending = $sqlEditorStore.pendingConfirm;

	// Track last seen result identity so we re-show the bar only on a *new* result.
	let lastSeenResult: unknown = null;
	$: {
		const lr = activeTab?.lastResult ?? null;
		if (lr && lr !== lastSeenResult) {
			lastSeenResult = lr;
			// Fresh result: open the grid immediately. Maximize stays sticky
			// across runs — if the user maximized, the next result stays max.
			if (resultState === 'hidden' || resultState === 'collapsed') {
				resultState = 'open';
			}
		} else if (!lr && lastSeenResult) {
			lastSeenResult = null;
			resultState = 'hidden';
			isMaximized = false;
		}
	}

	// Derived result summary
	$: result = activeTab?.lastResult ?? null;
	$: opIsWrite = result?.op === 'WRITE';
	const formatRowCount = (n: number): string => n.toLocaleString();
	$: resultSummary = (() => {
		if (!result) return '';
		const hasCols = (result.columns?.length ?? 0) > 0;
		const rowCount = result.row_count ?? result.rows?.length ?? 0;
		const total = result.total_row_count ?? rowCount;
		if (hasCols) {
			// Universal "X of Y rows" pattern (Gmail/Excel/Tableau convention).
			return total !== rowCount
				? `${formatRowCount(rowCount)} ${$i18n.t('of')} ${formatRowCount(total)} ${$i18n.t('rows')}`
				: `${formatRowCount(rowCount)} ${$i18n.t('rows')}`;
		}
		if (result.affected_rows !== null && result.affected_rows !== undefined) {
			return `${formatRowCount(result.affected_rows)} ${$i18n.t('rows affected')}`;
		}
		return $i18n.t('Statement executed.');
	})();

	// Load files whenever the panel opens against a (new) dbsphere.
	let loadedDbsphereId: string | null = null;
	$: if (show && dbsphereId && loadedDbsphereId !== dbsphereId) {
		loadedDbsphereId = dbsphereId;
		loadSqlFiles(localStorage.token, dbsphereId).catch((err) => {
			toast.error(String(err));
		});
	}

	// Auto-persist store on any tab change. Debounced 300ms to coalesce
	// rapid keystrokes (typing in the editor fires updateTabContent on
	// every character). Set lazily on first store update so we don't write
	// before the dbsphereId is known.
	let persistTimer: ReturnType<typeof setTimeout> | null = null;
	let storeUnsub: (() => void) | null = null;

	onMount(() => {
		// Default drawer height — half the window; user-resizable later.
		drawerHeight = clampDrawerHeight(Math.floor(window.innerHeight * 0.5));
		try {
			const sw = localStorage.getItem(STORAGE_KEY);
			if (sw) {
				const p = Number(sw);
				if (Number.isFinite(p)) panelWidth = clampPanelWidth(p);
			}
			const sh = localStorage.getItem(RESULT_KEY);
			if (sh) {
				const p = Number(sh);
				if (Number.isFinite(p)) resultHeight = clampResultHeight(p);
			}
			const dh = localStorage.getItem(DRAWER_KEY);
			if (dh) {
				const p = Number(dh);
				if (Number.isFinite(p)) drawerHeight = clampDrawerHeight(p);
			}
			if (dbsphereId) {
				const ro = localStorage.getItem(READ_ONLY_KEY_PREFIX + dbsphereId);
				readOnlyMode = ro === '1';
			}
		} catch {
			// ignore
		}
		window.addEventListener('resize', handleWindowResize);

		// Subscribe to store changes for auto-persist.
		storeUnsub = sqlEditorStore.subscribe((state) => {
			if (!state.dbsphereId) return;
			if (persistTimer) clearTimeout(persistTimer);
			persistTimer = setTimeout(() => {
				persistTabs(state);
				persistTimer = null;
			}, 300);
		});
	});

	onDestroy(() => {
		if (typeof window === 'undefined') return;
		window.removeEventListener('resize', handleWindowResize);
		window.removeEventListener('mousemove', handleWidthResizeMove);
		window.removeEventListener('mouseup', handleWidthResizeEnd);
		window.removeEventListener('mousemove', handleResultDragMove);
		window.removeEventListener('mouseup', handleResultDragEnd);
		window.removeEventListener('mousemove', handleDrawerDragMove);
		window.removeEventListener('mouseup', handleDrawerDragEnd);
		document.body.style.cursor = '';
		document.body.style.userSelect = '';
		// Flush any pending persist before unsubscribing so the user's
		// final edits survive the close.
		if (persistTimer) {
			clearTimeout(persistTimer);
			persistTimer = null;
			const snapshot = $sqlEditorStore;
			if (snapshot.dbsphereId) persistTabs(snapshot);
		}
		if (storeUnsub) {
			storeUnsub();
			storeUnsub = null;
		}
		// IMPORTANT: do NOT call resetSqlEditor() here. We want tabs to
		// survive panel close (DataGrip scratch behavior). Volatile state
		// like `executing` is benign on next open.
	});

	$: runHotkeyHint =
		typeof navigator !== 'undefined' && /Mac|iPhone|iPad/i.test(navigator.platform)
			? '⌘+Enter'
			: 'Ctrl+Enter';
</script>

{#if show}
	<aside
		class="cloo-sql-editor-panel flex flex-col h-full shrink-0 relative bg-white dark:bg-gray-900 border-l border-[var(--cloo-border-default)]"
		style="width: {panelWidth}px;"
		aria-label={$i18n.t('SQL Editor')}
	>
		<!-- Width resize handle (left edge of panel) -->
		<!-- svelte-ignore a11y-no-noninteractive-tabindex -->
		<!-- svelte-ignore a11y-no-noninteractive-element-interactions -->
		<div
			class="cloo-sql-editor-panel__resize-handle"
			class:is-active={widthResizing}
			role="separator"
			aria-orientation="vertical"
			aria-label={$i18n.t('Resize panel')}
			tabindex="0"
			on:mousedown={handleWidthResizeStart}
			on:keydown={handleWidthResizeKeyDown}
		/>

		<!-- Header -->
		<header
			class="cloo-sql-editor-panel__header flex items-center gap-2 px-3 h-12 border-b border-[var(--cloo-border-subtle)] bg-[var(--cloo-bg-surface)] shrink-0"
		>
			<h2 class="text-sm font-semibold text-[var(--cloo-text-default)]">
				{$i18n.t('SQL Editor')}
			</h2>
			<Badge status="secondary" size="sm" content={dialect} />
			{#if readOnlyMode}
				<Badge status="info" size="sm" content={$i18n.t('Read-only')} />
			{/if}

			<div class="ml-auto flex items-center gap-1.5">
				<Tooltip
					content={readOnlyMode
						? $i18n.t('Read-only mode is on — click to allow writes')
						: $i18n.t('Click to enable read-only mode')}
					placement="bottom"
				>
					<button
						type="button"
						class="cloo-icon-btn"
						class:is-active={readOnlyMode}
						aria-pressed={readOnlyMode}
						aria-label={$i18n.t('Read-only mode')}
						on:click={toggleReadOnly}
					>
						{#if readOnlyMode}
							<EyeSlash className="size-4" strokeWidth="2" />
						{:else}
							<Eye className="size-4" strokeWidth="2" />
						{/if}
					</button>
				</Tooltip>
				<Button
					kind="outlined"
					size="sm"
					disabled={!activeTab || $sqlEditorStore.executing}
					on:click={handleSave}
				>
					{$i18n.t('Save')}
				</Button>
				{#if $sqlEditorStore.executing}
					<!-- Stop — same slot/position as Run, swapped to danger styling.
					     Aborts the in-flight HTTP request (client-side); DB-side
					     cancel is a follow-up per-runner change. -->
					<Button kind="filled" status="error" size="sm" on:click={handleStop}>
						<Stop slot="prefix" className="w-3 h-3" strokeWidth="1.5" />
						{$i18n.t('Stop')}
					</Button>
				{:else}
					<Button
						kind="filled"
						size="sm"
						disabled={!activeTab || !activeTab.content}
						on:click={handleRun}
					>
						<Play slot="prefix" className="w-3 h-3" strokeWidth="1.5" />
						{hasSelection ? $i18n.t('Run selection') : $i18n.t('Run')}
					</Button>
				{/if}
				<button
					type="button"
					class="cloo-icon-btn"
					aria-label={$i18n.t('Close')}
					on:click={handleClose}
				>
					<XMark className="size-4" strokeWidth="2" />
				</button>
			</div>
		</header>

		<!-- Tabs row: scrollable tab strip + right-aligned connection
		     indicator (DataGrip-style "database.schema" chip). -->
		<div
			class="cloo-sql-tabs flex items-center px-2 py-1 border-b border-[var(--cloo-border-subtle)] shrink-0 gap-2"
		>
			<div class="flex items-center gap-1 overflow-x-auto flex-1 min-w-0">
				{#each $sqlEditorStore.tabs as tab (tab.id)}
					<div
						class="cloo-sql-tab flex items-center gap-1 px-2 py-1 rounded text-xs cursor-pointer shrink-0
							{tab.id === $sqlEditorStore.activeTabId
							? 'bg-[var(--cloo-surface-selected,var(--cloo-surface-hover))]'
							: 'hover:bg-[var(--cloo-surface-hover)]'}"
						role="tab"
						aria-selected={tab.id === $sqlEditorStore.activeTabId}
						tabindex="0"
						on:click={() => setActiveTab(tab.id)}
						on:keydown={(e) => {
							if (e.key === 'Enter' || e.key === ' ') {
								e.preventDefault();
								setActiveTab(tab.id);
							}
						}}
					>
						<span class="truncate max-w-[10rem]">
							{tab.name}{tab.dirty ? ' •' : ''}
						</span>
						<button
							type="button"
							class="opacity-60 hover:opacity-100 ml-1"
							aria-label={$i18n.t('Close tab')}
							on:click|stopPropagation={() => handleCloseTab(tab.id)}
						>
							<XMark className="size-3" strokeWidth="2" />
						</button>
					</div>
				{/each}
				<button
					type="button"
					class="p-1 rounded hover:bg-[var(--cloo-surface-hover)] flex items-center gap-1 text-xs shrink-0"
					aria-label={$i18n.t('New tab')}
					on:click={handleNewTab}
				>
					<Plus className="size-3.5" strokeWidth="2" />
					<span>{$i18n.t('New tab')}</span>
				</button>
			</div>

			{#if databaseName}
				<!-- Connection context — non-scrolling, right-aligned. -->
				<div
					class="cloo-conn-indicator"
					title={schemaName
						? `${databaseName}.${schemaName}`
						: databaseName}
				>
					<svg
						class="cloo-conn-indicator__icon"
						viewBox="0 0 24 24"
						fill="none"
						stroke="currentColor"
						stroke-width="1.5"
						aria-hidden="true"
					>
						<path
							stroke-linecap="round"
							stroke-linejoin="round"
							d="M20.25 6.375c0 2.278-3.694 4.125-8.25 4.125S3.75 8.653 3.75 6.375m16.5 0c0-2.278-3.694-4.125-8.25-4.125S3.75 4.097 3.75 6.375m16.5 0v11.25c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125V6.375m16.5 0v3.75m-16.5-3.75v3.75m16.5 0v3.75C20.25 16.153 16.556 18 12 18s-8.25-1.847-8.25-4.125v-3.75m16.5 0c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125"
						/>
					</svg>
					<span class="cloo-conn-indicator__text">
						{databaseName}{#if schemaName}<span
								class="cloo-conn-indicator__sep">.</span
							>{schemaName}{/if}
					</span>
				</div>
			{/if}
		</div>

		<!-- Body: editor area + (inline) result dock -->
		<div class="flex-1 min-h-0 flex flex-col">
			{#if activeTab}
				<div class="cloo-sql-editor-area flex-1 min-h-0 flex flex-col">
					<!-- Filename row -->
					<div class="px-3 py-1.5 border-b border-[var(--cloo-border-subtle)] shrink-0">
						<input
							type="text"
							class="w-full bg-transparent outline-none text-xs text-[var(--cloo-text-muted)]"
							value={activeTab.name}
							on:input={(e) => handleRenameTab(activeTab.id, e)}
							aria-label={$i18n.t('File name')}
						/>
					</div>

					<!-- Editor -->
					<div class="flex-1 min-h-0 overflow-hidden">
						<CodeEditor
							bind:this={codeEditorRef}
							id="sql-editor-{activeTab.id}"
							lang="sql"
							{dialect}
							{schema}
							value={activeTab.content}
							onChange={handleContentChange(activeTab.id)}
							onSave={handleSave}
							onRun={handleRun}
							on:selectionChange={handleSelectionChange}
						/>
					</div>

					<!-- Editor status bar -->
					<div
						class="cloo-sql-editor-statusbar flex items-center gap-3 px-3 h-6 text-[11px] text-[var(--cloo-text-muted)] border-t border-[var(--cloo-border-subtle)] bg-[var(--cloo-bg-surface)] shrink-0 select-none"
					>
						<span class="tabular-nums">Ln {cursorLine}, Col {cursorCol}</span>
						<span class="opacity-60">·</span>
						<span>{docLength} {$i18n.t('chars')}</span>
						{#if hasSelection}
							<span class="opacity-60">·</span>
							<span class="text-[var(--cloo-color-info)] tabular-nums"
								>{selectionLength} {$i18n.t('selected')}</span
							>
						{/if}
						<span class="ml-auto opacity-70"
							>{runHotkeyHint}
							{hasSelection ? $i18n.t('to Run selection') : $i18n.t('to Run')}</span
						>
					</div>
				</div>

				{#if pending}
					<PendingConfirmCard
						{pending}
						busy={$sqlEditorStore.executing}
						onCommit={handleCommit}
						onRollback={handleRollback}
					/>
				{/if}

				<!-- Inline result dock — lives inside the editor panel column-flex
				     stack. When the user toggles Maximize, the result moves to a
				     full-page-width drawer rendered below (sibling of <aside>);
				     the parent reserves matching padding-bottom so it does not
				     overlap content above. -->
				{#if (resultState === 'collapsed' || (resultState === 'open' && !isMaximized)) && result}
					<section
						class="cloo-sql-result-dock cloo-sql-result-dock--inline flex flex-col border-t border-[var(--cloo-border-default)] bg-[var(--cloo-bg-surface)] shrink-0 relative"
						style={resultState === 'open' ? `height: ${resultHeight}px` : 'height: 36px'}
					>
						{#if resultState === 'open'}
							<!-- svelte-ignore a11y-no-noninteractive-tabindex -->
							<!-- svelte-ignore a11y-no-noninteractive-element-interactions -->
							<div
								class="cloo-sql-result-dock__drag-handle"
								class:is-active={resultResizing}
								role="separator"
								aria-orientation="horizontal"
								aria-label={$i18n.t('Resize result panel')}
								tabindex="0"
								on:mousedown={handleResultDragStart}
							/>
						{/if}

						<!-- svelte-ignore a11y-click-events-have-key-events -->
						<!-- svelte-ignore a11y-no-static-element-interactions -->
						<div
							class="cloo-sql-result-dock__bar flex items-center gap-2 px-3 h-9 cursor-pointer select-none"
							on:click={cycleResult}
							on:dblclick={toggleMaximize}
							title={resultState === 'collapsed'
								? $i18n.t('Click to expand')
								: $i18n.t('Click to collapse')}
						>
							<span class="cloo-op-dot" class:is-write={opIsWrite} aria-hidden="true" />
							<span class="text-xs font-medium text-[var(--cloo-text-default)]">{result.op}</span>
							<span class="text-xs text-[var(--cloo-text-muted)]">{resultSummary}</span>
							{#if result.exec_ms !== null && result.exec_ms !== undefined}
								<span class="text-xs text-[var(--cloo-text-muted)] opacity-70">·</span>
								<span class="text-xs text-[var(--cloo-text-muted)] tabular-nums"
									>{result.exec_ms}ms</span
								>
							{/if}
							{#if result.truncated}
								<Tooltip
									content={$i18n.t(
										'Server capped the result. Add LIMIT to your query for a smaller, faster fetch.'
									)}
									placement="top"
								>
									<span
										class="inline-flex items-center text-[var(--cloo-color-warning,#ea580c)] cursor-help"
										aria-label={$i18n.t('Result was capped')}
									>
										<Info className="size-3.5" strokeWidth="2" />
									</span>
								</Tooltip>
							{/if}

							<div class="ml-auto flex items-center gap-1">
								{#if resultState === 'open' && (result.columns?.length ?? 0) > 0}
									<button
										type="button"
										class="cloo-icon-btn"
										aria-label={$i18n.t('Export CSV')}
										title={$i18n.t('Export CSV')}
										on:click|stopPropagation={handleExportCsvBar}
									>
										<ArrowDownTray className="size-3.5" strokeWidth="2" />
									</button>
								{/if}
								<button
									type="button"
									class="cloo-icon-btn"
									class:is-active={isMaximized}
									aria-label={isMaximized ? $i18n.t('Restore') : $i18n.t('Maximize')}
									title={isMaximized ? $i18n.t('Restore') : $i18n.t('Maximize')}
									on:click|stopPropagation={toggleMaximize}
								>
									<ArrowsPointingOut className="size-3.5" strokeWidth="2" />
								</button>
								<button
									type="button"
									class="cloo-icon-btn"
									aria-label={resultState === 'collapsed' ? $i18n.t('Expand') : $i18n.t('Collapse')}
									title={resultState === 'collapsed' ? $i18n.t('Expand') : $i18n.t('Collapse')}
									on:click|stopPropagation={cycleResult}
								>
									{#if resultState === 'collapsed'}
										<ChevronUp className="size-3.5" strokeWidth="2" />
									{:else}
										<ChevronDown className="size-3.5" strokeWidth="2" />
									{/if}
								</button>
								<button
									type="button"
									class="cloo-icon-btn"
									aria-label={$i18n.t('Close')}
									title={$i18n.t('Close')}
									on:click|stopPropagation={dismissResult}
								>
									<XMark className="size-3.5" strokeWidth="2" />
								</button>
							</div>
						</div>

						{#if resultState === 'open'}
							<div class="flex-1 min-h-0" transition:slide={{ duration: 160, axis: 'y' }}>
								<SqlResultGrid bind:this={inlineGridRef} {result} compact={true} />
							</div>
						{/if}
					</section>
				{/if}
			{:else}
				<div class="flex-1 flex items-center justify-center text-sm text-[var(--cloo-text-muted)]">
					{$i18n.t('Open or create a SQL file to start.')}
				</div>
			{/if}
		</div>
	</aside>

	<!-- Maximized result drawer — full-page-width, bottom-anchored.
	     Although technically position:fixed (escaping the narrow aside so
	     many SQL result columns can fit horizontally), the parent layout
	     reserves `maximizedResultHeight` of bottom padding so content above
	     ends exactly where the drawer begins → looks/behaves embedded,
	     never overlapping. Top edge is draggable to resize. -->
	{#if isMaximized && resultState === 'open' && result}
		<section
			class="cloo-sql-result-dock cloo-sql-result-dock--drawer fixed right-0 bottom-0 z-30 flex flex-col bg-[var(--cloo-bg-surface)] dark:bg-gray-900 border-t border-[var(--cloo-border-default)] shadow-lg"
			style="left: {drawerLeftOffset}px; height: {drawerHeight}px"
			transition:slide={{ duration: 180, axis: 'y' }}
		>
			<!-- Top-edge drag handle -->
			<!-- svelte-ignore a11y-no-noninteractive-tabindex -->
			<!-- svelte-ignore a11y-no-noninteractive-element-interactions -->
			<div
				class="cloo-sql-result-dock__drag-handle"
				class:is-active={drawerResizing}
				role="separator"
				aria-orientation="horizontal"
				aria-label={$i18n.t('Resize result panel')}
				tabindex="0"
				on:mousedown={handleDrawerDragStart}
			/>

			<!-- svelte-ignore a11y-click-events-have-key-events -->
			<!-- svelte-ignore a11y-no-static-element-interactions -->
			<div
				class="cloo-sql-result-dock__bar flex items-center gap-2 px-3 h-10 cursor-pointer select-none border-b border-[var(--cloo-border-subtle)]"
				on:dblclick={toggleMaximize}
				title={$i18n.t('Double-click to restore')}
			>
				<span class="cloo-op-dot" class:is-write={opIsWrite} aria-hidden="true" />
				<span class="text-xs font-medium text-[var(--cloo-text-default)]">{result.op}</span>
				<span class="text-xs text-[var(--cloo-text-muted)]">{resultSummary}</span>
				{#if result.exec_ms !== null && result.exec_ms !== undefined}
					<span class="text-xs text-[var(--cloo-text-muted)] opacity-70">·</span>
					<span class="text-xs text-[var(--cloo-text-muted)] tabular-nums">{result.exec_ms}ms</span>
				{/if}
				{#if result.truncated}
					<Tooltip
						content={$i18n.t(
							'Server capped the result. Add LIMIT to your query for a smaller, faster fetch.'
						)}
						placement="top"
					>
						<span
							class="inline-flex items-center text-[var(--cloo-color-warning,#ea580c)] cursor-help"
							aria-label={$i18n.t('Result was capped')}
						>
							<Info className="size-3.5" strokeWidth="2" />
						</span>
					</Tooltip>
				{/if}

				<div class="ml-auto flex items-center gap-1">
					{#if (result.columns?.length ?? 0) > 0}
						<button
							type="button"
							class="cloo-icon-btn"
							aria-label={$i18n.t('Export CSV')}
							title={$i18n.t('Export CSV')}
							on:click|stopPropagation={handleExportCsvBar}
						>
							<ArrowDownTray className="size-3.5" strokeWidth="2" />
						</button>
					{/if}
					<button
						type="button"
						class="cloo-icon-btn"
						aria-label={$i18n.t('Restore')}
						title={$i18n.t('Restore')}
						on:click|stopPropagation={toggleMaximize}
					>
						<ChevronDown className="size-4" strokeWidth="2" />
					</button>
					<button
						type="button"
						class="cloo-icon-btn"
						aria-label={$i18n.t('Close')}
						title={$i18n.t('Close')}
						on:click|stopPropagation={dismissResult}
					>
						<XMark className="size-4" strokeWidth="2" />
					</button>
				</div>
			</div>

			<div class="flex-1 min-h-0">
				<SqlResultGrid bind:this={drawerGridRef} {result} compact={true} />
			</div>
		</section>
	{/if}
{/if}

<style>
	.cloo-sql-editor-panel__resize-handle {
		position: absolute;
		top: 0;
		left: -3px;
		bottom: 0;
		width: 6px;
		cursor: col-resize;
		z-index: 20;
		background: transparent;
		transition: background-color 120ms ease;
	}
	.cloo-sql-editor-panel__resize-handle:hover,
	.cloo-sql-editor-panel__resize-handle:focus-visible,
	.cloo-sql-editor-panel__resize-handle.is-active {
		background-color: var(--cloo-color-primary, #155dfc);
		opacity: 0.6;
		outline: none;
	}

	/* Drawer follows sidebar collapse/expand with a CSS transition so the
	   left edge slides smoothly when the user toggles the app sidebar
	   while the maximized result is open. */
	.cloo-sql-result-dock--drawer {
		transition: left 200ms ease;
	}

	.cloo-sql-result-dock__drag-handle {
		position: absolute;
		top: -3px;
		left: 0;
		right: 0;
		height: 6px;
		cursor: ns-resize;
		z-index: 5;
		background: transparent;
		transition: background-color 120ms ease;
	}
	.cloo-sql-result-dock__drag-handle:hover,
	.cloo-sql-result-dock__drag-handle:focus-visible,
	.cloo-sql-result-dock__drag-handle.is-active {
		background-color: var(--cloo-color-primary, #155dfc);
		opacity: 0.5;
		outline: none;
	}

	.cloo-sql-result-dock__bar:hover {
		background-color: var(--cloo-surface-hover, transparent);
	}

	.cloo-icon-btn {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 24px;
		height: 24px;
		border-radius: 4px;
		color: var(--cloo-text-muted, #6b7280);
		background: transparent;
		border: none;
		cursor: pointer;
		transition: background-color 80ms ease, color 80ms ease;
	}
	.cloo-icon-btn:hover {
		background: var(--cloo-surface-hover, rgba(0, 0, 0, 0.04));
		color: var(--cloo-text-default, #1a1a1a);
	}
	.cloo-icon-btn.is-active {
		background: var(--cloo-color-info-soft, #dbeafe);
		color: var(--cloo-color-info, #155dfc);
	}
	.cloo-icon-btn.is-active:hover {
		background: var(--cloo-color-info-soft, #dbeafe);
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

	.cloo-sql-editor-statusbar {
		font-family: 'Pretendard Variable', 'Pretendard', sans-serif;
		font-variant-numeric: tabular-nums;
	}

	.cloo-conn-indicator {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		flex-shrink: 0;
		height: 24px;
		padding: 0 8px;
		border-radius: 4px;
		border: 1px solid var(--cloo-border-subtle, #e3e4e9);
		background: var(--cloo-bg-surface, #fff);
		color: var(--cloo-text-muted, #6b7280);
		font-size: 11px;
		font-family: 'Pretendard Variable', 'Pretendard', sans-serif;
		max-width: 240px;
		overflow: hidden;
	}
	.cloo-conn-indicator__icon {
		width: 12px;
		height: 12px;
		flex-shrink: 0;
	}
	.cloo-conn-indicator__text {
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		color: var(--cloo-text-default, #1a1a1a);
		font-weight: 500;
	}
	.cloo-conn-indicator__sep {
		color: var(--cloo-text-tertiary, #9d9ea9);
		font-weight: 400;
	}
</style>

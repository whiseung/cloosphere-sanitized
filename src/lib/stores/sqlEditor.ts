/**
 * SQL Editor state for the DbSphere detail page.
 *
 * Holds the tabs (server-persisted .sql files + unsaved scratch tabs),
 * the active tab id, per-tab dirty flag + last execution result, and the
 * pending DML/DDL confirmation payload.
 *
 * Single-DbSphere at a time: opening another DbSphere's editor calls
 * `resetSqlEditor()` to clear state. Multi-instance is not a 1차 use case.
 *
 * 409 conflict handling: `saveTab` throws the SqlFileConflict object verbatim
 * so the consuming component can render a merge dialog with the server copy.
 */
import { get, writable } from 'svelte/store';
import {
	confirmSqlExecution,
	createSqlFile,
	deleteSqlFile,
	executeSql,
	getSqlFiles,
	rejectSqlExecution,
	updateSqlFile,
	type SqlExecuteResponse,
	type SqlFile,
	type SqlFileConflict,
	type SqlPendingPayload
} from '$lib/apis/dbsphere';

export type SqlTab = {
	/** Local id — for unsaved tabs this is a uuid prefixed with `local:`. */
	id: string;
	/** Server file id once persisted; null while unsaved. */
	fileId: string | null;
	name: string;
	content: string;
	/** Server-side `updated_at` used for optimistic concurrency (If-Match). */
	persistedUpdatedAt: number | null;
	dirty: boolean;
	/** Last execution snapshot, scoped to this tab. */
	lastResult: SqlExecuteResponse | null;
};

export type SqlEditorState = {
	dbsphereId: string | null;
	tabs: SqlTab[];
	activeTabId: string | null;
	loading: boolean;
	executing: boolean;
	pendingConfirm: SqlPendingPayload | null;
	/** Tab that owns the current pending confirmation (so result lands in the
	 * correct tab once the user commits). */
	pendingTabId: string | null;
};

const initial: SqlEditorState = {
	dbsphereId: null,
	tabs: [],
	activeTabId: null,
	loading: false,
	executing: false,
	pendingConfirm: null,
	pendingTabId: null
};

export const sqlEditorStore = writable<SqlEditorState>(initial);

const localId = () => `local:${crypto.randomUUID()}`;

const tabFromFile = (file: SqlFile): SqlTab => ({
	id: `file:${file.id}`,
	fileId: file.id,
	name: file.name,
	content: file.content,
	persistedUpdatedAt: file.updated_at,
	dirty: false,
	lastResult: null
});

const newScratchTab = (name = 'untitled.sql'): SqlTab => ({
	id: localId(),
	fileId: null,
	name,
	content: '',
	persistedUpdatedAt: null,
	dirty: false,
	lastResult: null
});

export const resetSqlEditor = () => sqlEditorStore.set(initial);

// =====================================================================
// DataGrip-style scratch persistence
// ---------------------------------------------------------------------
// Tabs (including unsaved scratch + dirty edits to server files) are
// persisted to localStorage keyed by dbsphereId. On `loadSqlFiles`,
// server files are merged with persisted state so dirty edits survive a
// panel close, page navigation, or full reload. The volatile `lastResult`
// is stripped — recomputing it on reload would require re-running the
// query, which we never want to do silently.
// =====================================================================
const PERSIST_PREFIX = 'cloo.sqlEditor.tabs.';

type PersistedShape = {
	tabs: SqlTab[];
	activeTabId: string | null;
};

const stripVolatile = (tab: SqlTab): SqlTab => ({ ...tab, lastResult: null });

export const persistTabs = (state: SqlEditorState) => {
	if (!state.dbsphereId || typeof localStorage === 'undefined') return;
	try {
		const payload: PersistedShape = {
			tabs: state.tabs.map(stripVolatile),
			activeTabId: state.activeTabId
		};
		localStorage.setItem(PERSIST_PREFIX + state.dbsphereId, JSON.stringify(payload));
	} catch {
		// quota / disabled storage — silent
	}
};

const hydrateTabs = (dbsphereId: string): PersistedShape | null => {
	if (typeof localStorage === 'undefined') return null;
	try {
		const raw = localStorage.getItem(PERSIST_PREFIX + dbsphereId);
		if (!raw) return null;
		const parsed = JSON.parse(raw) as PersistedShape;
		if (!parsed || !Array.isArray(parsed.tabs)) return null;
		return parsed;
	} catch {
		return null;
	}
};

export const loadSqlFiles = async (token: string, dbsphereId: string) => {
	sqlEditorStore.update((s) => ({ ...s, loading: true, dbsphereId }));
	try {
		const files = await getSqlFiles(token, dbsphereId);
		const persisted = hydrateTabs(dbsphereId);
		sqlEditorStore.update((s) => {
			let tabs: SqlTab[];
			let activeTabId: string | null = s.activeTabId;

			if (persisted && persisted.tabs.length > 0) {
				// Build server-file tabs, preferring persisted local edits when
				// they exist (preserves dirty content + last-edited name).
				const persistedByFileId = new Map<string, SqlTab>();
				for (const t of persisted.tabs) {
					if (t.fileId) persistedByFileId.set(t.fileId, t);
				}
				const serverTabs: SqlTab[] = files.map((f) => {
					const local = persistedByFileId.get(f.id);
					if (!local) return tabFromFile(f);
					// Reconcile: server file is newer than the persistedUpdatedAt
					// we remembered → keep local edits but flag dirty (user saves
					// → 409 surfaces the merge dialog).
					return {
						...local,
						persistedUpdatedAt: f.updated_at,
						lastResult: null
					};
				});
				// Carry over scratch tabs (fileId === null) that the user had
				// open at the time of the last persist.
				const scratchTabs = persisted.tabs
					.filter((t) => t.fileId === null)
					.map((t) => ({ ...t, lastResult: null }));
				tabs = [...serverTabs, ...scratchTabs];
				// Restore previously active tab if it still exists.
				if (
					persisted.activeTabId &&
					tabs.some((t) => t.id === persisted.activeTabId)
				) {
					activeTabId = persisted.activeTabId;
				}
			} else {
				// First time on this dbsphere — preserve any in-memory scratch
				// tabs the user has open right now.
				const scratch = s.tabs.filter((t) => t.fileId === null);
				tabs = [...files.map(tabFromFile), ...scratch];
			}

			if (!activeTabId || !tabs.some((t) => t.id === activeTabId)) {
				activeTabId = tabs[0]?.id ?? null;
			}

			return { ...s, tabs, activeTabId, loading: false };
		});
	} catch (err) {
		sqlEditorStore.update((s) => ({ ...s, loading: false }));
		throw err;
	}
};

export const openNewTab = (name = 'untitled.sql') => {
	const tab = newScratchTab(name);
	sqlEditorStore.update((s) => ({
		...s,
		tabs: [...s.tabs, tab],
		activeTabId: tab.id
	}));
	return tab.id;
};

export const setActiveTab = (tabId: string) =>
	sqlEditorStore.update((s) => ({ ...s, activeTabId: tabId }));

export const closeTab = (tabId: string) =>
	sqlEditorStore.update((s) => {
		const tabs = s.tabs.filter((t) => t.id !== tabId);
		const activeTabId =
			s.activeTabId === tabId ? tabs[tabs.length - 1]?.id ?? null : s.activeTabId;
		return { ...s, tabs, activeTabId };
	});

export const updateTabContent = (tabId: string, content: string) =>
	sqlEditorStore.update((s) => ({
		...s,
		tabs: s.tabs.map((t) =>
			t.id === tabId ? { ...t, content, dirty: content !== t.content } : t
		)
	}));

export const renameTab = (tabId: string, name: string) =>
	sqlEditorStore.update((s) => ({
		...s,
		tabs: s.tabs.map((t) => (t.id === tabId ? { ...t, name, dirty: true } : t))
	}));

/**
 * Persist the tab to the server. On 409 conflict throws the SqlFileConflict
 * object so the component can present a merge dialog.
 */
export const saveTab = async (token: string, tabId: string) => {
	const state = get(sqlEditorStore);
	if (!state.dbsphereId) throw new Error('No active dbsphere');
	const tab = state.tabs.find((t) => t.id === tabId);
	if (!tab) throw new Error('Tab not found');

	if (tab.fileId === null) {
		const created = await createSqlFile(token, state.dbsphereId, {
			name: tab.name,
			content: tab.content
		});
		const persisted = tabFromFile(created);
		sqlEditorStore.update((s) => ({
			...s,
			tabs: s.tabs.map((t) => (t.id === tabId ? persisted : t)),
			activeTabId: s.activeTabId === tabId ? persisted.id : s.activeTabId
		}));
		return persisted;
	}

	// updateSqlFile throws SqlFileConflict (409) untouched — propagated up so
	// the UI can render the merge dialog.
	const updated = await updateSqlFile(token, state.dbsphereId, tab.fileId, {
		name: tab.name,
		content: tab.content,
		expected_updated_at: tab.persistedUpdatedAt ?? undefined
	});
	sqlEditorStore.update((s) => ({
		...s,
		tabs: s.tabs.map((t) =>
			t.id === tabId
				? {
						...t,
						content: updated.content,
						name: updated.name,
						persistedUpdatedAt: updated.updated_at,
						dirty: false
					}
				: t
		)
	}));
	return updated;
};

/**
 * Replace the local tab content with the server copy returned by a 409.
 * Use after the user accepts "discard mine" in the merge dialog.
 */
export const acceptServerCopy = (tabId: string, server: SqlFile) =>
	sqlEditorStore.update((s) => ({
		...s,
		tabs: s.tabs.map((t) => (t.id === tabId ? tabFromFile(server) : t))
	}));

export const removeTab = async (token: string, tabId: string) => {
	const state = get(sqlEditorStore);
	if (!state.dbsphereId) return;
	const tab = state.tabs.find((t) => t.id === tabId);
	if (!tab) return;
	if (tab.fileId) {
		await deleteSqlFile(token, state.dbsphereId, tab.fileId);
	}
	closeTab(tabId);
};

// Holds the AbortController for the currently-running execution so the UI
// Stop button can interrupt the HTTP request. Module-scoped (not on the
// store) because AbortController is not a serializable value.
let currentExecutionAbort: AbortController | null = null;

/**
 * Abort the currently-running SQL execution (client-side fetch abort).
 *
 * NOTE: this only releases the UI — the server-side query continues until it
 * completes on its own. Server-side cancel (DB connection.cancel() /
 * pg_cancel_backend / KILL QUERY) requires per-runner work and is tracked
 * separately. The UX trade-off is intentional: instant UI release is the
 * primary value to the user; the DB-side termination is a follow-up PR.
 */
export const cancelActiveExecution = (): boolean => {
	if (!currentExecutionAbort) return false;
	currentExecutionAbort.abort();
	currentExecutionAbort = null;
	sqlEditorStore.update((s) => ({ ...s, executing: false }));
	return true;
};

export const executeActiveTab = async (token: string, sqlOverride?: string) => {
	const state = get(sqlEditorStore);
	if (!state.dbsphereId || !state.activeTabId) return;
	const tab = state.tabs.find((t) => t.id === state.activeTabId);
	if (!tab) return;

	// Run Selection: when a non-empty `sqlOverride` is passed, execute that
	// instead of the full tab content. The result still belongs to the
	// active tab so it shows in the dock with the right tab context.
	const sqlToRun = sqlOverride && sqlOverride.trim() ? sqlOverride : tab.content;

	currentExecutionAbort = new AbortController();
	sqlEditorStore.update((s) => ({ ...s, executing: true }));
	try {
		const result = await executeSql(
			token,
			state.dbsphereId,
			sqlToRun,
			currentExecutionAbort.signal
		);
		if (result.op === 'WRITE' && result.pending) {
			sqlEditorStore.update((s) => ({
				...s,
				executing: false,
				pendingConfirm: result.pending,
				pendingTabId: tab.id
			}));
		} else {
			sqlEditorStore.update((s) => ({
				...s,
				executing: false,
				tabs: s.tabs.map((t) => (t.id === tab.id ? { ...t, lastResult: result } : t))
			}));
		}
		return result;
	} catch (err) {
		sqlEditorStore.update((s) => ({ ...s, executing: false }));
		throw err;
	} finally {
		currentExecutionAbort = null;
	}
};

export const confirmPending = async (token: string) => {
	const state = get(sqlEditorStore);
	if (!state.dbsphereId || !state.pendingConfirm) return;
	const resultId = state.pendingConfirm.result_id;
	const tabId = state.pendingTabId;

	sqlEditorStore.update((s) => ({ ...s, executing: true }));
	try {
		const result = await confirmSqlExecution(token, state.dbsphereId, resultId);
		sqlEditorStore.update((s) => ({
			...s,
			executing: false,
			pendingConfirm: null,
			pendingTabId: null,
			tabs: tabId
				? s.tabs.map((t) => (t.id === tabId ? { ...t, lastResult: result } : t))
				: s.tabs
		}));
		return result;
	} catch (err) {
		sqlEditorStore.update((s) => ({ ...s, executing: false }));
		throw err;
	}
};

export const rejectPending = async (token: string) => {
	const state = get(sqlEditorStore);
	if (!state.dbsphereId || !state.pendingConfirm) return;
	const resultId = state.pendingConfirm.result_id;

	try {
		await rejectSqlExecution(token, state.dbsphereId, resultId);
	} finally {
		sqlEditorStore.update((s) => ({
			...s,
			pendingConfirm: null,
			pendingTabId: null
		}));
	}
};

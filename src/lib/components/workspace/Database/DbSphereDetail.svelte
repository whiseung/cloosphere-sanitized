<script lang="ts">
	import { toast } from 'svelte-sonner';
	import { onMount, onDestroy, getContext } from 'svelte';
	import type { Readable } from 'svelte/store';

	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import { user, models, userPermissions } from '$lib/stores';

	import {
		getDbSphereById,
		updateDbSphereById,
		testDbConnection,
		getDbTables,
		extractSchema,
		cancelSchemaExtraction,
		getExtractedTables,
		getExtractionStatus,
		deleteExtractedTable,
		deleteAllExtractedTables,
		getDbSphereMemories,
		getDbSphereMemoryStats,
		deleteDbSphereMemory,
		getJoinGraph
	} from '$lib/apis/dbsphere';
	import type {
		ConnectionTestForm,
		TableInfo,
		ExtractSchemaForm,
		ExtractedTableInfo,
		ExtractionJobStatus,
		MemoryItem,
		RelationshipGraphResponse
	} from '$lib/apis/dbsphere';
	import { getGroups } from '$lib/apis/groups';
	import { resolveSqlDialect, type SqlDialectName } from '$lib/utils/sqlDialect';
	import { WEBUI_BASE_URL } from '$lib/constants';

	// Common UI
	import Button from '$lib/components/common/Button.svelte';
	import Badge from '$lib/components/common/Badge.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import Card from '$lib/components/common/Card.svelte';
	import WorkspaceTagSelector from '$lib/components/common/WorkspaceTagSelector.svelte';
	import Modal from '$lib/components/common/Modal.svelte';
	import AccessControlModal from '../common/AccessControlModal.svelte';

	// Database feature
	import DBConfigureModal from './DBConfigureModal.svelte';
	import DbConnectionCard, {
		type DbConnectionTab,
		type DbTableEntry
	} from './DbConnectionCard.svelte';
	import ExtractionTabs, {
		type ExtractedTableRow,
		type MemoryRow
	} from './ExtractionTabs.svelte';
	import ToolDescriptionPopover from './ToolDescriptionPopover.svelte';
	import UnusedMemoryModal from './UnusedMemoryModal.svelte';
	import SqlEditorPanel from './SqlEditorPanel.svelte';
	import MemoryEditModal from './MemoryEditModal.svelte';
	import RelationshipPanel from './RelationshipPanel.svelte';

	// Icons
	import ArrowLeft from '$lib/components/icons/ArrowLeft.svelte';
	import ArrowsPointingOut from '$lib/components/icons/ArrowsPointingOut.svelte';
	import LockClosed from '$lib/components/icons/LockClosed.svelte';
	import { formatBackendError } from '$lib/utils/error';


	type I18nStore = Readable<{ t: (key: string, vars?: Record<string, unknown>) => string }>;
	const i18n = getContext<I18nStore>('i18n');

	let id: string | null = null;
	let dbsphere: any = null;
	let tagSelector: WorkspaceTagSelector | null = null;
	let group_ids: string[] = [];

	// Connection + test
	let testingConnection = false;
	let loadingTables = false;
	let connectionTestResult: any = null;
	// Session-scoped verification flag — true ONLY after the user explicitly
	// clicks "Test Connection" and the backend confirms success in the
	// current session. Resets on page load and on any config change.
	// Editor & "Connected" badge gate on this; never on the persisted config.
	let connectionVerified = false;
	// True only when a test ran this session and failed → drives the red badge.
	// Untested connections show no badge (the badge is a test-result indicator).
	$: connectionFailed = Boolean(connectionTestResult) && connectionTestResult?.success === false;

	// Editing state
	let isSavingSettings = false;
	let settingsDirty = false;

	// Tables / extracted / memories
	let tables: TableInfo[] = [];
	let extractedTables: ExtractedTableInfo[] = [];
	let loadingExtractedTables = false;
	let memories: MemoryItem[] = [];
	let memoryTotals: Record<string, number> = {};
	let loadingMemories = false;

	// Relationship graph (#4) — loaded read-only, rendered in a modal (@xyflow ERD).
	let joinGraph: RelationshipGraphResponse | null = null;
	let loadingJoinGraph = false;
	let showRelationshipModal = false;
	// ERD modal can expand to fill the viewport — the graph is space-hungry on dense
	// schemas. Reset on close so the chip always reopens at the framed modal size.
	let relationshipFullscreen = false;
	$: if (!showRelationshipModal) relationshipFullscreen = false;

	// Tab selection (mirrors DbConnectionCard's tabs)
	let activeTab: DbConnectionTab = 'all';

	// Schema extraction
	let extractionStatus: ExtractionJobStatus | null = null;
	let statusPollingInterval: ReturnType<typeof setInterval> | null = null;
	let extractingSchema = false;
	// Empty string = no model (mirrors the inline Selector's "None" item).
	// `extractModelId || null` downstream still coerces it to null for the API.
	let extractModelId = '';
	let extractSampleRowCount = 5;
	let generateSampleQA = true;
	let selectedTableNames: string[] = [];

	// Memory edit modal
	let showMemoryModal = false;
	let showUnusedModal = false;
	let memoryModalMode: 'view' | 'edit' | 'create' = 'view';
	let selectedMemory: MemoryItem | null = null;

	// Tool description
	let toolDescription = '';
	let aiModelId = '';
	let generatingToolDesc = false;

	// Allow data modifications (also surfaces inside DBConfigureModal)
	let allowDataModifications = false;

	// Search filter for DB All tab
	let searchTables = '';

	// Modal / panel visibility
	let showAccessControlModal = false;
	let showDbConfigureModal = false;
	let showToolDescriptionPopover = false;
	let showSqlEditor = false;
	// Bound from SqlEditorPanel: when its result is maximized to a full-page-
	// width drawer, this is the drawer's pixel height so we can reserve
	// matching `padding-bottom` on the page body row → no visual overlap.
	let sqlEditorMaximizedHeight = 0;

	// Saved title (read-only display once persisted)
	let pendingName = '';
	let pendingDescription = '';

	$: isOwnerOrAdmin = $user?.role === 'admin' || dbsphere?.user_id === $user?.id;
	$: canWrite =
		$user?.role === 'admin' ||
		($userPermissions?.workspace?.databases === 'write' &&
			(dbsphere?.user_id === $user?.id ||
				dbsphere?.access_control?.write?.user_ids?.includes($user?.id) ||
				dbsphere?.access_control?.write?.group_ids?.some((gid: string) =>
					group_ids.includes(gid)
				)));

	$: dbType = (dbsphere?.data?.connection?.db_type ?? '') as string;
	$: sqlEditorDialect = resolveSqlDialect(dbType) as SqlDialectName;
	$: hasConnection = Boolean(dbsphere?.data?.connection?.host);
	// Editor is gated on session-scoped verification — the user MUST click
	// "Test Connection" successfully before opening the editor. We do not
	// trust persisted config across sessions: a stored host/password could
	// be stale or compromised, and clicking Run would silently retry it.
	$: canOpenSqlEditor = Boolean(id) && connectionVerified;

	// Connection display for the SQL Editor tab-row indicator.
	$: connDatabaseName = String(dbsphere?.data?.connection?.database ?? '');
	$: connSchemaName = String(dbsphere?.data?.connection?.schema_name ?? '');

	// Schema map for SQL editor autocomplete: { table_name: [col1, col2, ...] }
	// Built from ddl_schema memories — each row stores `table_name` plus a
	// JSON-encoded array of column descriptors in `column_info_json`.
	$: sqlEditorSchema = (() => {
		const out: Record<string, string[]> = {};
		for (const m of memories) {
			if (m.entity_type !== 'ddl_schema') continue;
			const meta = m.metadata ?? {};
			const tableName = (meta.table_name as string | undefined) ?? '';
			if (!tableName) continue;
			let cols: string[] = [];
			const raw = meta.column_info_json;
			if (typeof raw === 'string' && raw.trim()) {
				try {
					const parsed = JSON.parse(raw);
					if (Array.isArray(parsed)) {
						cols = parsed
							.map((c: unknown) => {
								if (typeof c === 'string') return c;
								if (c && typeof c === 'object') {
									const obj = c as Record<string, unknown>;
									return String(obj.column_name ?? obj.name ?? '');
								}
								return '';
							})
							.filter(Boolean);
					}
				} catch {
					// malformed json — skip columns, keep table for keyword completion
				}
			}
			out[tableName] = cols;
		}
		return out;
	})();

	// DbConnectionCard data shaping
	$: dbAllRows = tables
		.filter((t) => t.type === 'TABLE')
		.filter((t) =>
			!searchTables.trim()
				? true
				: t.name.toLowerCase().includes(searchTables.trim().toLowerCase())
		)
		.map<DbTableEntry>((t) => ({ id: t.name, name: t.name }));

	$: extractedRows = extractedTables.map<ExtractedTableRow>((t) => ({
		id: t.table_name,
		name: t.table_name,
		column_count: t.column_count,
		description: t.description ?? null
	}));

	// 문서 관련테이블 다중선택용 테이블명 목록 — DB 전체 테이블 우선, 없으면 추출 테이블.
	$: tableNameList = (() => {
		const fromDb = tables.filter((t) => t.type === 'TABLE').map((t) => t.name);
		return fromDb.length > 0 ? fromDb : extractedRows.map((t) => t.name);
	})();

	$: memoryRows = memories.map<MemoryRow>((m) => {
		const meta = m.metadata ?? {};
		let title = '';
		let subtitle: string | null = null;
		if (m.entity_type === 'ddl_schema') {
			title = String(meta.table_name ?? '-');
			subtitle = (meta.table_description as string) ?? null;
		} else if (m.entity_type === 'sql_memory') {
			title = m.content || '-';
			subtitle = (meta.sql_query as string) ?? null;
		} else if (m.entity_type === 'documentation') {
			title = (meta.title as string) || m.content || '-';
			// content 는 rich_content(접두사 포함)라 clean 본문(doc_content) 우선.
			subtitle = (meta.doc_content as string) || m.content;
		} else if (m.entity_type === 'sql_example') {
			title = (meta.description as string) || m.content || '-';
			subtitle = (meta.sql_query as string) ?? null;
		}
		return {
			memory_id: m.memory_id,
			entity_type: m.entity_type,
			title,
			subtitle,
			origin: (meta.origin as string) ?? null,
			use_count: m.use_count ?? null,
			last_used_at: m.last_used_at ?? null,
			user_email: m.user_email ?? null,
			creator: m.creator ?? null,
			last_modified_by: m.last_modified_by ?? null,
			last_modified_at: m.last_modified_at ?? null
		};
	});

	$: counts = {
		all: tables.filter((t) => t.type === 'TABLE').length,
		extracted: extractedTables.length,
		memory: memories.length
	};

	// Relationship chip (ExtractionTabs): visible once the schema is extracted —
	// reader-reachable, independent of write-permission / memory count. Count = edges.
	$: relationshipsReady = !!joinGraph?.success && joinGraph.extracted;
	$: relationshipCount = joinGraph?.success ? joinGraph.edges.length : 0;

	// A: marker set for DB All rows that already have an extracted entry.
	$: extractedTableNames = new Set(extractedTables.map((t) => t.table_name));

	// D: linked-memory count per table (only memories whose metadata
	// references a table_name contribute). This powers the "N memories"
	// pill on each extracted row.
	$: memoryCountByTable = (() => {
		const map: Record<string, number> = {};
		for (const m of memories) {
			const tn = (m.metadata?.table_name as string | undefined) ?? '';
			if (!tn) continue;
			map[tn] = (map[tn] ?? 0) + 1;
		}
		return map;
	})();

	// D (continued): when user clicks "N memories" on an extracted row,
	// switch to Memory tab + pre-filter the memory list to that table.
	let memoryTableFilter: string | null = null;
	$: filteredMemoryRows = memoryTableFilter
		? memoryRows.filter((row) => {
				const memory = memories.find((m) => m.memory_id === row.memory_id);
				return (memory?.metadata?.table_name as string | undefined) === memoryTableFilter;
			})
		: memoryRows;

	const handleJumpToMemory = (event: CustomEvent<{ tableName: string }>) => {
		memoryTableFilter = event.detail.tableName;
		activeTab = 'memory';
	};
	const clearMemoryTableFilter = () => {
		memoryTableFilter = null;
	};
	const handleSelectMemoryTable = (event: CustomEvent<{ tableName: string | null }>) => {
		memoryTableFilter = event.detail.tableName;
	};


	// ===================================================================
	// Data loading
	// ===================================================================
	const loadDbSphere = async () => {
		const res = await getDbSphereById(localStorage.token, id!).catch((e) => {
			toast.error($i18n.t(`${e}`));
			return null;
		});
		if (res) {
			dbsphere = res;
			pendingName = dbsphere.name ?? '';
			pendingDescription = dbsphere.description ?? '';
			toolDescription = dbsphere.meta?.tool_description ?? '';
			aiModelId = dbsphere.meta?.tool_description_model_id ?? '';
			allowDataModifications =
				dbsphere.data?.allow_data_modifications ??
				dbsphere.meta?.allow_dml ??
				false;
		} else {
			goto('/workspace/database');
		}
	};

	const loadExtractedTables = async () => {
		if (!id) return;
		loadingExtractedTables = true;
		const res = await getExtractedTables(localStorage.token, id).catch(() => null);
		if (res && res.success) extractedTables = res.tables;
		loadingExtractedTables = false;
	};

	const loadMemories = async () => {
		if (!id) return;
		loadingMemories = true;
		const [res, statsRes] = await Promise.all([
			getDbSphereMemories(localStorage.token, id, undefined, 1000).catch(() => null),
			getDbSphereMemoryStats(localStorage.token, id).catch(() => null)
		]);
		if (res && res.success) memories = res.memories;
		// Authoritative per-type counts (independent of the list page size) so the
		// filter chips stay correct even when memories exceed the fetched page.
		memoryTotals = statsRes && statsRes.success ? statsRes.counts : {};
		loadingMemories = false;
	};

	const loadJoinGraph = async () => {
		if (!id) return;
		loadingJoinGraph = true;
		joinGraph = await getJoinGraph(localStorage.token, id).catch(() => null);
		loadingJoinGraph = false;
	};

	const loadExtractionStatus = async () => {
		if (!id) return;
		const res = await getExtractionStatus(localStorage.token, id).catch(() => null);
		if (res) {
			const prev = extractionStatus?.status;
			extractionStatus = res;
			if (prev === 'running' && res.status === 'completed') {
				// Build a stat-rich toast — backend already tracked the counts,
				// surface them so the user sees exactly what was added without
				// having to count rows themselves.
				const tableTemplate = $i18n.t('Extracted {{n}} tables');
				const qaTemplate = $i18n.t('{{n}} Q&A pairs');
				const tablePart = tableTemplate.replace('{{n}}', String(res.tables_saved));
				const qaPart =
					res.qa_saved > 0 ? ` · ${qaTemplate.replace('{{n}}', String(res.qa_saved))}` : '';
				toast.success(`${tablePart}${qaPart}`);
				stopStatusPolling();
				await Promise.all([loadExtractedTables(), loadMemories(), loadJoinGraph()]);
				// Auto-redirect to Extracted tab so the new rows appear without
				// the user having to hunt for them. Done AFTER loading so the
				// list is populated when the tab becomes visible.
				activeTab = 'extracted';
			} else if (prev === 'running' && res.status === 'failed') {
				toast.error($i18n.t('Schema extraction failed.'));
				stopStatusPolling();
			} else if (
				(prev === 'running' || prev === 'pending' || prev === 'cancelling') &&
				res.status === 'cancelled'
			) {
				// Stopped by the user — surface what was already saved (partial)
				// and refresh the lists so any committed tables show up.
				toast.info($i18n.t('Schema extraction stopped.'));
				stopStatusPolling();
				await Promise.all([loadExtractedTables(), loadMemories(), loadJoinGraph()]);
				if (res.tables_saved > 0) activeTab = 'extracted';
			}
		}
	};

	const startStatusPolling = () => {
		if (statusPollingInterval) return;
		// Kick off an immediate poll so the user sees the progress panel
		// within a few hundred ms instead of waiting 2s. Without this, a
		// fast extraction can complete between extractSchema's return and
		// the first scheduled poll — the panel never appears at all.
		loadExtractionStatus();
		statusPollingInterval = setInterval(loadExtractionStatus, 1000);
	};
	const stopStatusPolling = () => {
		if (statusPollingInterval) {
			clearInterval(statusPollingInterval);
			statusPollingInterval = null;
		}
	};

	// ===================================================================
	// Connection helpers
	// ===================================================================
	const buildConnectionForm = (override?: Partial<ConnectionTestForm>): ConnectionTestForm => {
		const conn = dbsphere?.data?.connection ?? {};
		const form: ConnectionTestForm = {
			db_type: conn.db_type ?? '',
			host: conn.host ?? '',
			port: Number(conn.port ?? 0),
			database: conn.database ?? '',
			username: conn.username ?? '',
			password: conn.password ?? '',
			...override
		};
		if (conn.schema_name) form.schema_name = conn.schema_name;
		if (conn.warehouse) form.warehouse = conn.warehouse;
		if (conn.account) form.account = conn.account;
		if (conn.role) form.role = conn.role;
		if (conn.http_path) form.http_path = conn.http_path;
		if (conn.catalog) form.catalog = conn.catalog;
		if (conn.access_token) form.access_token = conn.access_token;
		if (conn.project_id) form.project_id = conn.project_id;
		if (conn.dataset_id) form.dataset_id = conn.dataset_id;
		if (conn.credentials_json) form.credentials_json = conn.credentials_json;
		if (conn.use_adc) form.use_adc = true;
		if (id) form.dbsphere_id = id;
		return form;
	};

	const testConnectionHandler = async () => {
		if (!dbType) {
			toast.error($i18n.t('Please select a database type.'));
			return;
		}
		testingConnection = true;
		connectionTestResult = null;
		connectionVerified = false;
		tables = [];

		const res = await testDbConnection(localStorage.token, buildConnectionForm()).catch(
			(e) => {
				connectionTestResult = { success: false, message: `${e}` };
				return null;
			}
		);
		if (res) {
			connectionTestResult = res;
			if (res.success) {
				connectionVerified = true;
				toast.success($i18n.t('Connection successful!'));
				await fetchTablesHandler();
				activeTab = 'all';
			} else {
				toast.error(res.message);
			}
		}
		testingConnection = false;
	};

	const fetchTablesHandler = async () => {
		loadingTables = true;
		const res = await getDbTables(localStorage.token, buildConnectionForm()).catch(() => null);
		if (res && res.success) tables = res.tables;
		loadingTables = false;
	};

	// ===================================================================
	// Save (title + description + tool description + access_control)
	// ===================================================================
	const changeHandler = () => {
		settingsDirty = true;
	};

	const saveHandler = async (navigateOnSuccess = false) => {
		if (!dbsphere || !id) return;
		const trimmedName = pendingName.trim();
		if (!trimmedName) {
			toast.error($i18n.t('Please fill in all fields.'));
			return;
		}
		isSavingSettings = true;
		if (tagSelector?.commitChanges) {
			try {
				await tagSelector.commitChanges();
			} catch (e) {
				console.error('Failed to commit tag changes:', e);
			}
		}

		const res = await updateDbSphereById(localStorage.token, id, {
			name: trimmedName,
			description: pendingDescription,
			data: {
				...(dbsphere.data ?? {}),
				allow_data_modifications: allowDataModifications
			},
			meta: {
				...(dbsphere.meta ?? {}),
				tool_description: toolDescription,
				tool_description_model_id: aiModelId
			},
			access_control: dbsphere.access_control
		}).catch((e) => {
			toast.error($i18n.t(`${e}`));
			return null;
		});

		if (res) {
			settingsDirty = false;
			toast.success($i18n.t('Database saved successfully.'));
			dbsphere = res;
			if (navigateOnSuccess) goto('/workspace/database');
		}
		isSavingSettings = false;
	};

	// ===================================================================
	// DBConfigureModal — persist connection details
	// ===================================================================
	const handleDbConfigureSave = async (event: CustomEvent<Record<string, unknown>>) => {
		if (!dbsphere || !id) return;
		const payload = event.detail;
		const next = {
			...(dbsphere.data ?? {}),
			connection: {
				...(dbsphere.data?.connection ?? {}),
				...payload
			},
			allow_data_modifications: Boolean(payload.allow_data_modifications)
		};
		// `password` is only included when the user actually typed a new one
		// (P-H1) — buildConnectionForm() reads from dbsphere.data.connection so
		// the masked value is never written back.
		const res = await updateDbSphereById(localStorage.token, id, {
			name: dbsphere.name,
			description: dbsphere.description,
			data: next,
			meta: dbsphere.meta ?? {},
			access_control: dbsphere.access_control
		}).catch((e) => {
			toast.error($i18n.t(`${e}`));
			return null;
		});
		if (res) {
			dbsphere = res;
			allowDataModifications = Boolean(payload.allow_data_modifications);
			showDbConfigureModal = false;
			// Connection config changed → invalidate any prior verification.
			// User must explicitly Test Connection again before the editor unlocks.
			connectionVerified = false;
			connectionTestResult = null;
			tables = [];
			toast.success($i18n.t('Connection saved.'));
		}
	};

	// ===================================================================
	// Tool Description popover handlers
	// ===================================================================
	const handleToolDescriptionSave = async (
		event: CustomEvent<{ value: string; aiModelId: string }>
	) => {
		toolDescription = event.detail.value;
		aiModelId = event.detail.aiModelId;
		showToolDescriptionPopover = false;
		// Persist immediately. The old behavior only marked the page dirty
		// (changeHandler), so users who didn't also hit "Save & Update" lost the
		// tool description on refresh. saveHandler writes meta.tool_description.
		await saveHandler(false);
	};

	const aiGenerateToolDescription = async () => {
		if (generatingToolDesc || extractedTables.length === 0) return;
		generatingToolDesc = true;
		try {
			const tableList = extractedTables
				.map((t) => t.table_name + (t.description ? ` - ${t.description}` : ''))
				.join('\n');
			const prompt = `이 데이터베이스를 언제 조회해야 하는지 설명을 작성하라.

[데이터베이스]
이름: ${dbsphere.name}
테이블(${extractedTables.length}개): ${tableList}

[규칙]
- 위 테이블에 실제로 존재하는 데이터만 언급하라. 추측하거나 없는 기능을 추가하지 마라
- 어떤 질문이 들어왔을 때 이 데이터베이스를 사용해야 하는지 1~2문장으로 작성하라
- 설명만 출력하라`;
			const body: Record<string, unknown> = { prompt, max_completion_tokens: 2048 };
			if (aiModelId) body.model = aiModelId;
			const res = await fetch(`${WEBUI_BASE_URL}/api/v1/tasks/generate`, {
				method: 'POST',
				headers: {
					Accept: 'application/json',
					'Content-Type': 'application/json',
					authorization: `Bearer ${localStorage.token}`
				},
				body: JSON.stringify(body)
			});
			if (!res.ok) {
				const err = await res.json().catch(() => ({}));
				throw new Error(formatBackendError(err, $i18n) ?? `HTTP ${res.status}`);
			}
			const data = await res.json();
			const content = data?.choices?.[0]?.message?.content ?? '';
			if (content) {
				toolDescription = content.trim();
				changeHandler();
			} else {
				toast.warning($i18n.t('No result generated. Please try again.'));
			}
		} catch (e: unknown) {
			const err = e as { message?: string; detail?: string };
			toast.error(err?.message ?? formatBackendError(err, $i18n) ?? String(e));
		} finally {
			generatingToolDesc = false;
		}
	};

	// ===================================================================
	// Schema extraction handlers (Extract Schema split-button)
	// ===================================================================
	const runExtraction = async (form: ExtractSchemaForm) => {
		if (!id) return;
		extractingSchema = true;
		const res = await extractSchema(localStorage.token, id, form).catch((e) => {
			toast.error($i18n.t(`${e}`));
			return null;
		});
		if (res?.success) {
			toast.success($i18n.t('Schema extraction started.'));
			// Stay on DB All so the progress panel is visible. loadExtractionStatus
			// auto-switches to Extracted on completion.
			startStatusPolling();
		} else if (res) {
			// `message` is an i18n key with `{{var}}` placeholders; `message_vars`
			// supplies the values for interpolation.
			toast.error($i18n.t(res.message, res.message_vars ?? {}));
		}
		extractingSchema = false;
	};

	const handleExtract = async () => {
		// Primary CTA on the Extract Schema button. Honours whatever is
		// currently selected on the DB All tab; falls back to extracting
		// every table if the user has not picked anything.
		const form: ExtractSchemaForm = {
			model_id: extractModelId || null,
			sample_row_count: extractSampleRowCount,
			generate_sample_qa: generateSampleQA && Boolean(extractModelId)
		};
		if (selectedTableNames.length > 0) form.table_names = selectedTableNames;
		await runExtraction(form);
	};

	const handleCancelExtraction = async () => {
		if (!id) return;
		try {
			const res = await cancelSchemaExtraction(localStorage.token, id);
			if (res) {
				// Optimistically reflect "Stopping…" — polling confirms the
				// terminal "cancelled" state once in-flight tables wind down.
				extractionStatus = res;
				toast.info($i18n.t('Stopping schema extraction…'));
				if (!statusPollingInterval) startStatusPolling();
			}
		} catch (e) {
			toast.error(`${e}`);
		}
	};

	const handleDeleteTable = async (
		event: CustomEvent<{ id: string; name: string }>
	) => {
		if (!id) return;
		const name = event.detail.name;
		const res = await deleteExtractedTable(localStorage.token, id, name).catch((e) => {
			toast.error($i18n.t(`${e}`));
			return null;
		});
		if (res?.success) {
			extractedTables = extractedTables.filter((t) => t.table_name !== name);
			toast.success(
				$i18n.t("Table '{{name}}' removed from extracted list.", { name })
			);
		}
	};

	// ===================================================================
	// Memory handlers
	// ===================================================================
	const openMemory = (event: CustomEvent<string>) => {
		const m = memories.find((x) => x.memory_id === event.detail);
		if (!m) return;
		selectedMemory = m;
		memoryModalMode = 'view';
		showMemoryModal = true;
	};
	const createMemory = () => {
		selectedMemory = null;
		memoryModalMode = 'create';
		showMemoryModal = true;
	};
	const deleteMemory = async (event: CustomEvent<string>) => {
		if (!id) return;
		const memoryId = event.detail;
		try {
			await deleteDbSphereMemory(localStorage.token, id, memoryId);
			memories = memories.filter((m) => m.memory_id !== memoryId);
			toast.success($i18n.t('Memory deleted'));
		} catch (e) {
			toast.error((e as string) || $i18n.t('Failed to delete memory'));
		}
	};
	const handleMemorySaved = async (e?: CustomEvent<{ created?: MemoryItem }>) => {
		const created = e?.detail?.created;
		if (created?.memory_id) {
			// 생성 직후 Azure Search 인덱싱 지연(~2초)으로 loadMemories 재조회엔 신규가 안 잡힌다.
			// 생성 응답(MemoryItem)을 목록 맨 앞에 낙관적으로 추가해 바로 표시하고, 카운트(stats)만
			// 갱신한다(목록 재조회는 지연 때문에 생략 — 낙관적 항목 유지, 다음 자연 재조회 시 정합).
			if (!memories.some((m) => m.memory_id === created.memory_id)) {
				memories = [created, ...memories];
			}
			const statsRes = await getDbSphereMemoryStats(localStorage.token, id).catch(() => null);
			if (statsRes && statsRes.success) memoryTotals = statsRes.counts;
		} else {
			// 편집 등: 기존대로 전체 재조회.
			loadMemories();
		}
	};
	const openUnused = () => (showUnusedModal = true);

	// ===================================================================
	// DbConnectionCard event wiring
	// ===================================================================
	const handleTabChange = (event: CustomEvent<DbConnectionTab>) => {
		activeTab = event.detail;
	};
	const handleSelectionChange = (event: CustomEvent<string[]>) => {
		selectedTableNames = event.detail;
	};

	// ===================================================================
	// Navigation
	// ===================================================================
	const goBack = () => goto('/workspace/database');

	onMount(async () => {
		id = $page.params.id;
		try {
			const groups = await getGroups(localStorage.token);
			group_ids = (groups ?? []).map((g: { id: string }) => g.id);
		} catch (e) {
			console.error('Failed to load groups:', e);
		}
		await loadDbSphere();
		await loadExtractedTables();
		loadMemories();
		loadJoinGraph();
		await loadExtractionStatus();
		if (
			extractionStatus?.status === 'running' ||
			extractionStatus?.status === 'pending' ||
			extractionStatus?.status === 'cancelling'
		) {
			startStatusPolling();
		}
	});

	onDestroy(() => {
		stopStatusPolling();
	});
</script>

<div class="cloo-db-detail flex flex-col w-full h-full">
	{#if dbsphere}
		<!-- Modals / panels -->
		<AccessControlModal
			bind:show={showAccessControlModal}
			bind:accessControl={dbsphere.access_control}
			allowPublic={$userPermissions?.sharing?.public_databases || $user?.role === 'admin'}
			onChange={changeHandler}
			accessRoles={['read', 'write']}
		/>

		<DBConfigureModal
			bind:show={showDbConfigureModal}
			initialConnection={dbsphere.data?.connection ?? null}
			initialAllowDataModifications={allowDataModifications}
			isEditing={hasConnection}
			dbsphereId={id}
			saving={isSavingSettings}
			on:save={handleDbConfigureSave}
		/>

		{#if id}
			<MemoryEditModal
				bind:show={showMemoryModal}
				dbsphereId={id}
				mode={memoryModalMode}
				memory={selectedMemory}
				dialect={sqlEditorDialect}
				tables={tableNameList}
				{canWrite}
				on:save={handleMemorySaved}
			/>
			<UnusedMemoryModal
				bind:show={showUnusedModal}
				dbsphereId={id}
				{canWrite}
				on:deleted={loadMemories}
			/>
		{/if}

		<!-- Page body + docked SQL editor panel — Figma 1296:13261.
		     `padding-bottom` reserves space for the SQL Editor's maximized
		     result drawer so the drawer never visually overlaps content. -->
		<div
			class="flex-1 flex min-h-0 overflow-hidden"
			style="padding-bottom: {sqlEditorMaximizedHeight}px"
		>
			<div class="flex-1 min-w-0 overflow-y-auto overflow-x-auto">
			<!-- `min-w-[640px]` pins the inner card layout so opening the SQL
			     editor panel never compresses the DB Info / Connection cards
			     below their natural width. When viewport is too narrow to
			     show both, this main area scrolls horizontally instead of
			     reflowing card content. -->
			<div class="max-w-[860px] min-w-[640px] mx-auto w-full px-8 py-8 flex flex-col gap-4">
				<!-- workspace-read-header: row 1 (back + title + actions) -->
				<div class="flex items-center justify-between gap-3">
					<div class="flex flex-1 items-center gap-2.5 min-w-0">
						<button
							type="button"
							class="p-1 rounded hover:bg-[var(--cloo-surface-hover)]"
							aria-label={$i18n.t('Back')}
							on:click={goBack}
						>
							<ArrowLeft className="size-5" strokeWidth="2" />
						</button>
						<input
							type="text"
							class="flex-1 min-w-0 text-3xl font-semibold text-[var(--cloo-text-primary)] bg-transparent outline-none focus:bg-[var(--cloo-surface-hover)] rounded px-1 truncate"
							placeholder={$i18n.t('Database Name')}
							bind:value={pendingName}
							on:input={changeHandler}
							disabled={!canWrite}
							aria-label={$i18n.t('Database Name')}
						/>
					</div>
					<div class="flex items-center gap-2 shrink-0">
						{#if isOwnerOrAdmin && canWrite}
							<Button kind="outlined" size="md" on:click={() => (showAccessControlModal = true)}>
								<LockClosed slot="prefix" className="size-3.5" strokeWidth="2" />
							</Button>
							<div class="h-5 w-px bg-[var(--cloo-border-divider)]" />
						{/if}
						<Button kind="outlined" size="md" on:click={goBack}>
							{$i18n.t('Cancel')}
						</Button>
						<Button
							kind="filled"
							size="md"
							loading={isSavingSettings}
							disabled={!canWrite || isSavingSettings}
							on:click={() => saveHandler(false)}
						>
							{$i18n.t('Save & Update')}
						</Button>
					</div>
				</div>

				<!-- Description bar (row 2 of workspace-read-header) -->
				<div
					class="rounded-[var(--border-radius-rounded-xl,12px)] bg-[var(--cloo-bg-neutral-default,#f3f4f6)] px-3.5 py-3 flex items-center gap-4"
				>
					<input
						type="text"
						class="flex-1 min-w-0 text-sm text-[var(--cloo-text-default)] bg-transparent outline-none"
						placeholder={$i18n.t('Describe your database and objectives')}
						bind:value={pendingDescription}
						on:input={changeHandler}
						disabled={!canWrite}
						aria-label={$i18n.t('Description')}
					/>
					<div class="shrink-0">
						{#if id}
							<WorkspaceTagSelector
								bind:this={tagSelector}
								resourceType="database"
								resourceId={id}
								on:change={changeHandler}
							/>
						{/if}
					</div>
					{#if toolDescription}
						<div class="h-5 w-px bg-[var(--cloo-border-divider)] shrink-0" />
						<Button
							kind="outlined"
							size="sm"
							on:click={() => (showToolDescriptionPopover = !showToolDescriptionPopover)}
							disabled={!canWrite}
						>
							{$i18n.t('Tool Description')}
						</Button>
					{/if}
				</div>

				<!-- Tool Description editor — inline. Empty: always open (required
				     nudge, not dismissible); set: collapsed, toggled by the bar button. -->
				<ToolDescriptionPopover
					show={!toolDescription || showToolDescriptionPopover}
					dismissible={!!toolDescription}
					bind:value={toolDescription}
					bind:aiModelId
					aiDisabled={extractedTables.length === 0}
					generating={generatingToolDesc}
					on:save={handleToolDescriptionSave}
					on:generate={aiGenerateToolDescription}
					on:close={() => (showToolDescriptionPopover = false)}
				/>

				<!-- Figma 1302:10774 divider — py-2 wrapper around the 1px line so
				     line sits 24px (gap-4 16 + py-2 8) from header/card content. -->
				<div class="w-full py-2">
					<div class="h-px bg-[var(--cloo-border-subtle)] w-full" />
				</div>

				<!-- Card: DB Information — Figma 1272:10276 has only a header row inside
				     the card (no separator). Use body slot directly so Card doesn't
				     emit the implicit `border-b` between header/body. -->
				<Card padding="none">
					<div class="flex items-center px-6 py-3">
						<div class="flex-1 min-w-0">
							<div class="text-base font-semibold text-[var(--cloo-text-primary)]">
								{$i18n.t('DB Information')}
							</div>
							{#if hasConnection}
								<div class="text-xs text-[var(--cloo-text-tertiary)] mt-0.5 truncate">
									{dbType} · {dbsphere.data?.connection?.host}:{dbsphere.data?.connection
										?.port} / {dbsphere.data?.connection?.database}
								</div>
							{/if}
						</div>
						<Button
							kind="outlined"
							size="md"
							on:click={() => (showDbConfigureModal = true)}
							disabled={!canWrite}
						>
							{$i18n.t('Configure')}
						</Button>
					</div>
				</Card>

				<!-- Card: DB Connection (DbConnectionCard) -->
				<DbConnectionCard
					connected={connectionVerified}
					{connectionFailed}
					testing={testingConnection}
					extracting={extractingSchema}
					{extractionStatus}
					editorEnabled={canOpenSqlEditor}
					editorOpen={showSqlEditor}
					{activeTab}
					{counts}
					tables={dbAllRows}
					{extractedTableNames}
					selectedTableIds={selectedTableNames}
					bind:search={searchTables}
					bind:extractModelId
					bind:sampleRowCount={extractSampleRowCount}
					bind:generateSampleQA
					on:tabChange={handleTabChange}
					on:testConnection={testConnectionHandler}
					on:openEditor={() => (showSqlEditor = !showSqlEditor)}
					on:extract={handleExtract}
					on:cancelExtract={handleCancelExtraction}
					on:selectionChange={handleSelectionChange}
				>
					<svelte:fragment slot="extracted">
						<ExtractionTabs
							mode="extracted"
							loading={loadingExtractedTables}
							{canWrite}
							extractedTables={extractedRows}
							{memoryCountByTable}
							{relationshipCount}
							{relationshipsReady}
							on:deleteTable={handleDeleteTable}
							on:jumpToMemory={handleJumpToMemory}
							on:openRelationships={() => (showRelationshipModal = true)}
						/>
					</svelte:fragment>
					<svelte:fragment slot="memory">
						{#if memoryTableFilter}
							<!-- Persistent banner so the table filter doesn't feel
							     hidden when the user opens the Memory tab. -->
							<div
								class="flex items-center justify-between gap-2 mb-3 px-3 py-2 rounded bg-[var(--cloo-color-info-soft,#dbeafe)] text-[var(--cloo-color-info,#155dfc)] text-xs"
							>
								<span class="truncate">
									{$i18n.t('Filtering memories by table')}: <strong>{memoryTableFilter}</strong>
								</span>
								<Button kind="text" size="sm" on:click={clearMemoryTableFilter}>
									{$i18n.t('Clear')}
								</Button>
							</div>
						{/if}
						<ExtractionTabs
							mode="memory"
							loading={loadingMemories}
							{canWrite}
							memoryItems={filteredMemoryRows}
							memoryTotals={memoryTableFilter ? {} : memoryTotals}
							extractedTables={extractedRows}
							{memoryTableFilter}
							{relationshipCount}
							{relationshipsReady}
							on:openMemory={openMemory}
							on:createMemory={createMemory}
							on:deleteMemory={deleteMemory}
							on:cleanupUnused={openUnused}
							on:selectMemoryTable={handleSelectMemoryTable}
							on:openRelationships={() => (showRelationshipModal = true)}
						/>
					</svelte:fragment>
				</DbConnectionCard>
			</div>
		</div>

			{#if id && showSqlEditor}
				<SqlEditorPanel
					bind:show={showSqlEditor}
					bind:maximizedResultHeight={sqlEditorMaximizedHeight}
					dbsphereId={id}
					dialect={sqlEditorDialect}
					schema={sqlEditorSchema}
					databaseName={connDatabaseName}
					schemaName={connSchemaName}
				/>
			{/if}

			<!-- Relationship ERD modal (#4) — triggered from the Relationships chip
			     in ExtractionTabs. Modal has no height prop, so size "full" + an
			     explicit className width/height (AddTextContentModal pattern). -->
			<Modal
				bind:show={showRelationshipModal}
				size="full"
				containerClassName={relationshipFullscreen ? 'p-0' : 'p-3'}
				className="{relationshipFullscreen
					? '!w-screen !h-screen !max-w-none rounded-none'
					: '!w-[90vw] !max-w-[1400px] h-[85vh] rounded-2xl'} bg-white dark:bg-gray-900 flex flex-col overflow-hidden"
			>
				<div
					class="flex items-center justify-between px-4 py-3 border-b border-[var(--cloo-border-default)] shrink-0"
				>
					<h2 class="text-base font-semibold text-[var(--cloo-text-primary)]">
						{$i18n.t('Table relationships')}
					</h2>
					<div class="flex items-center gap-2">
						<button
							type="button"
							class="{relationshipFullscreen
								? 'text-[var(--cloo-color-info)]'
								: 'text-[var(--cloo-text-muted)] hover:text-[var(--cloo-text-default)]'} leading-none"
							aria-label={relationshipFullscreen
								? $i18n.t('Exit fullscreen')
								: $i18n.t('Fullscreen')}
							title={relationshipFullscreen ? $i18n.t('Exit fullscreen') : $i18n.t('Fullscreen')}
							on:click={() => (relationshipFullscreen = !relationshipFullscreen)}
						>
							<ArrowsPointingOut className="size-4" />
						</button>
						<button
							type="button"
							class="text-[var(--cloo-text-muted)] hover:text-[var(--cloo-text-default)] text-lg leading-none"
							aria-label={$i18n.t('Close')}
							on:click={() => (showRelationshipModal = false)}>✕</button
						>
					</div>
				</div>
				<div class="flex-1 min-h-0">
					<RelationshipPanel
						{joinGraph}
						loading={loadingJoinGraph}
						extracting={extractionStatus?.status === 'running' ||
							extractionStatus?.status === 'pending' ||
							extractionStatus?.status === 'cancelling'}
					/>
				</div>
			</Modal>
		</div>
	{:else}
		<div class="w-full h-full flex justify-center items-center">
			<Spinner />
		</div>
	{/if}
</div>

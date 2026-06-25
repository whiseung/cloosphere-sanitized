import { WEBUI_API_BASE_URL } from '$lib/constants';

// Helper to extract error message from API response
const extractErrorMessage = (err: unknown): string => {
	if (typeof err === 'string') return err;
	if (err && typeof err === 'object') {
		const e = err as { detail?: unknown; message?: string };
		if (e.detail) {
			if (Array.isArray(e.detail)) {
				return e.detail.map((d: { msg?: string }) => d.msg || JSON.stringify(d)).join(', ');
			}
			if (typeof e.detail === 'string') return e.detail;
			return JSON.stringify(e.detail);
		}
		if (e.message) return e.message;
	}
	return JSON.stringify(err);
};

export const createNewDbSphere = async (
	token: string,
	name: string,
	description: string,
	accessControl: null | object
) => {
	let error: string | null = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/dbsphere/create`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({
			name: name,
			description: description,
			access_control: accessControl
		})
	})
		.then(async (response) => {
			if (!response.ok) throw await response.json();
			return response.json();
		})
		.catch((err) => {
			error = extractErrorMessage(err);
			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const getDbSpheres = async (token: string = '') => {
	let error: string | null = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/dbsphere/`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.then((json) => {
			return json;
		})
		.catch((err) => {
			error = extractErrorMessage(err);
			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const getDbSphereList = async (token: string = '') => {
	let error: string | null = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/dbsphere/list`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.then((json) => {
			return json;
		})
		.catch((err) => {
			error = extractErrorMessage(err);
			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const getDbSphereById = async (token: string, id: string) => {
	let error: string | null = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/dbsphere/${id}`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.then((json) => {
			return json;
		})
		.catch((err) => {
			error = extractErrorMessage(err);

			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

type DbSphereUpdateForm = {
	name?: string;
	description?: string;
	data?: object;
	meta?: object;
	access_control?: null | object;
};

export const updateDbSphereById = async (token: string, id: string, form: DbSphereUpdateForm) => {
	let error: string | null = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/dbsphere/${id}/update`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({
			name: form?.name ? form.name : undefined,
			description: form?.description ? form.description : undefined,
			data: form?.data ? form.data : undefined,
			meta: form?.meta ?? undefined,
			access_control: form.access_control
		})
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.then((json) => {
			return json;
		})
		.catch((err) => {
			error = extractErrorMessage(err);

			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const getLinkedAgentsByDbSphereId = async (token: string, id: string) => {
	let error: string | null = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/dbsphere/${id}/linked-agents`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err;
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const deleteDbSphereById = async (token: string, id: string) => {
	let error: string | null = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/dbsphere/${id}/delete`, {
		method: 'DELETE',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.then((json) => {
			return json;
		})
		.catch((err) => {
			error = extractErrorMessage(err);

			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export type ConnectionTestForm = {
	db_type: string;
	host: string;
	port: number;
	database: string;
	username: string;
	password: string;
	schema_name?: string;
	warehouse?: string;
	account?: string;
	role?: string;
	// Databricks
	http_path?: string;
	catalog?: string;
	access_token?: string;
	// BigQuery
	project_id?: string;
	dataset_id?: string;
	credentials_json?: string;
	use_adc?: boolean;
	// For resolving masked credentials
	dbsphere_id?: string;
};

export const testDbConnection = async (token: string, form: ConnectionTestForm) => {
	let error: string | null = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/dbsphere/test-connection`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify(form)
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.then((json) => {
			return json;
		})
		.catch((err) => {
			error = extractErrorMessage(err);

			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const testDbConnectionById = async (
	token: string,
	id: string
): Promise<{ success: boolean; message: string }> => {
	let error: string | null = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/dbsphere/${id}/test-connection`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = extractErrorMessage(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export type TableInfo = {
	name: string;
	type: 'TABLE' | 'VIEW';
	schema_name?: string;
};

export type TablesListResponse = {
	success: boolean;
	message: string;
	tables: TableInfo[];
};

export const getDbTables = async (token: string, form: ConnectionTestForm): Promise<TablesListResponse | null> => {
	let error: string | null = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/dbsphere/tables`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify(form)
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.then((json) => {
			return json;
		})
		.catch((err) => {
			error = extractErrorMessage(err);
			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

// Schema extraction types
export type ExtractSchemaForm = {
	model_id?: string | null;
	sample_row_count?: number;
	table_names?: string[];
	generate_sample_qa?: boolean; // Whether to generate sample Q&A pairs (requires model_id)
};

export type ExtractSchemaResponse = {
	success: boolean;
	/** i18n key (English text with {{var}} placeholders). Pass through
	 * `$i18n.t(message, message_vars)` for localization. */
	message: string;
	message_vars?: Record<string, unknown>;
	tables_processed: number;
	tables_saved?: number;
	qa_saved?: number;
	details?: {
		tables: string[];
		model_used: string | null;
		sample_rows: number;
	};
};

export const extractSchema = async (
	token: string,
	id: string,
	form: ExtractSchemaForm
): Promise<ExtractSchemaResponse | null> => {
	let error: string | null = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/dbsphere/${id}/extract-schema`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify(form)
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.then((json) => {
			return json;
		})
		.catch((err) => {
			error = extractErrorMessage(err);
			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

// Extracted table info
export type ExtractedTableInfo = {
	table_name: string;
	schema_name?: string;
	description?: string;
	column_count: number;
	has_relationships: boolean;
	extracted_at?: string;
};

export type ExtractedTablesResponse = {
	success: boolean;
	tables: ExtractedTableInfo[];
	total_count: number;
	last_extracted_at?: number;
};

export const getExtractedTables = async (
	token: string,
	id: string
): Promise<ExtractedTablesResponse | null> => {
	let error: string | null = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/dbsphere/${id}/extracted-tables`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.then((json) => {
			return json;
		})
		.catch((err) => {
			error = extractErrorMessage(err);
			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

// Relationship graph (join_graph) — read-only panel (#4/#5)
export type JoinGraphColumn = {
	name: string;
	data_type?: string;
	is_primary_key: boolean;
	is_foreign_key: boolean;
	foreign_table?: string | null;
	foreign_column?: string | null;
	is_nullable: boolean;
};

export type TableRole = 'fact' | 'dimension' | 'bridge' | 'unclassified';

export type JoinGraphNode = {
	table: string;
	schema_name?: string | null;
	column_count: number;
	columns: JoinGraphColumn[];
	role: TableRole;
	role_confidence?: 'high' | 'likely' | null;
	as_target: number;
	as_source: number;
	self_ref: boolean;
};

export type JoinGraphEdge = {
	source_table: string;
	source_columns: string[];
	target_table: string;
	target_columns: string[];
	relationship_type: 'verified_fk' | 'inferred_name';
	confidence: number;
};

export type RelationshipGraphResponse = {
	success: boolean;
	nodes: JoinGraphNode[];
	edges: JoinGraphEdge[];
	truncated: boolean;
	extracted: boolean;
};

export const getJoinGraph = async (
	token: string,
	id: string
): Promise<RelationshipGraphResponse | null> => {
	let error: string | null = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/dbsphere/${id}/join-graph`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.then((json) => {
			return json;
		})
		.catch((err) => {
			error = extractErrorMessage(err);
			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

// Extraction job status
export type ExtractionJobStatus = {
	status: 'none' | 'pending' | 'running' | 'cancelling' | 'cancelled' | 'completed' | 'failed';
	cancel_requested?: boolean;
	started_at?: number;
	completed_at?: number;
	current_table?: string;
	current_phase?: string;
	tables_total: number;
	tables_processed: number;
	tables_in_progress?: number;
	tables_saved: number;
	qa_saved: number;
};

export type DeleteExtractedTableResponse = {
	success: boolean;
	message: string;
	deleted_counts?: Record<string, number>;
};

export const deleteAllExtractedTables = async (
	token: string,
	id: string
): Promise<DeleteExtractedTableResponse | null> => {
	let error: string | null = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/dbsphere/${id}/extracted-tables`, {
		method: 'DELETE',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = extractErrorMessage(err);
			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const deleteExtractedTable = async (
	token: string,
	id: string,
	tableName: string
): Promise<DeleteExtractedTableResponse | null> => {
	let error: string | null = null;

	const res = await fetch(
		`${WEBUI_API_BASE_URL}/dbsphere/${id}/extracted-tables/${encodeURIComponent(tableName)}`,
		{
			method: 'DELETE',
			headers: {
				Accept: 'application/json',
				'Content-Type': 'application/json',
				authorization: `Bearer ${token}`
			}
		}
	)
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.then((json) => {
			return json;
		})
		.catch((err) => {
			error = extractErrorMessage(err);
			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

// ===========================
// Memory Management Types & APIs
// ===========================

export type MemoryItem = {
	memory_id: string;
	entity_type: string;
	content: string;
	metadata: Record<string, unknown>;
	created_at?: string;
	// 참조(주입) 통계 — sql_memory 에만 채워짐. use_count 는 "주입 이벤트 수"이지
	// LLM 실사용/품질 지표가 아님.
	use_count?: number | null;
	last_used_at?: number | null;
	// 생성자 이메일 — metadata.user_id 해석. 자동저장 few-shot 은 질문한 사용자의 이메일.
	user_email?: string | null;
	// 생성자 표시값 — schema_extraction/ddl_schema 출신은 "system", 그 외는 이메일.
	creator?: string | null;
	// 최종수정자(이메일)·최종수정일(ISO) — 수정 이력 없으면 null.
	last_modified_by?: string | null;
	last_modified_at?: string | null;
};

export type UnusedMemoryItem = {
	memory_id: string;
	content: string;
	sql?: string | null;
	origin?: string | null;
	created_at?: string | null;
};

export type UnusedMemoryResponse = {
	success: boolean;
	memories: UnusedMemoryItem[];
	total_count: number;
	logging_ready: boolean;
	grace_days: number;
};

export type BulkDeleteResponse = {
	success: boolean;
	deleted: number;
	failed: string[];
};

export type MemoryListResponse = {
	success: boolean;
	memories: MemoryItem[];
	total_count: number;
	has_more: boolean;
};

export type MemoryCreateForm = {
	entity_type: string;
	question?: string;
	sql?: string;
	content?: string;
	doc_type?: string;
	title?: string;
	description?: string;
	related_tables?: string[];
	related_columns?: string[];
	use_case?: string;
	tags?: string[];
};

export type MemoryUpdateForm = {
	content?: string;
	metadata?: Record<string, unknown>;
};

export type MemoryStatsResponse = {
	success: boolean;
	counts: Record<string, number>;
	total: number;
	schema_summary?: string;
	table_overview?: string;
};

export const getDbSphereMemories = async (
	token: string,
	id: string,
	type?: string,
	limit?: number
): Promise<MemoryListResponse | null> => {
	let error: string | null = null;

	const params = new URLSearchParams();
	if (type) params.set('type', type);
	if (limit) params.set('limit', String(limit));
	const qs = params.toString() ? `?${params.toString()}` : '';

	const res = await fetch(`${WEBUI_API_BASE_URL}/dbsphere/${id}/memories${qs}`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = extractErrorMessage(err);
			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const getDbSphereMemoryById = async (
	token: string,
	id: string,
	memoryId: string
): Promise<MemoryItem | null> => {
	let error: string | null = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/dbsphere/${id}/memories/${memoryId}`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = extractErrorMessage(err);
			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const createDbSphereMemory = async (
	token: string,
	id: string,
	form: MemoryCreateForm
): Promise<MemoryItem | null> => {
	let error: string | null = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/dbsphere/${id}/memories/create`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify(form)
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = extractErrorMessage(err);
			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const updateDbSphereMemory = async (
	token: string,
	id: string,
	memoryId: string,
	form: MemoryUpdateForm
): Promise<MemoryItem | null> => {
	let error: string | null = null;

	const res = await fetch(
		`${WEBUI_API_BASE_URL}/dbsphere/${id}/memories/${memoryId}/update`,
		{
			method: 'POST',
			headers: {
				Accept: 'application/json',
				'Content-Type': 'application/json',
				authorization: `Bearer ${token}`
			},
			body: JSON.stringify(form)
		}
	)
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = extractErrorMessage(err);
			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const deleteDbSphereMemory = async (
	token: string,
	id: string,
	memoryId: string
): Promise<{ success: boolean } | null> => {
	let error: string | null = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/dbsphere/${id}/memories/${memoryId}`, {
		method: 'DELETE',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = extractErrorMessage(err);
			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const getDbSphereMemoryStats = async (
	token: string,
	id: string
): Promise<MemoryStatsResponse | null> => {
	let error: string | null = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/dbsphere/${id}/memories/stats`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = extractErrorMessage(err);
			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const getUnusedDbSphereMemories = async (
	token: string,
	id: string,
	graceDays?: number
): Promise<UnusedMemoryResponse | null> => {
	let error: string | null = null;

	const qs = graceDays !== undefined ? `?grace_days=${graceDays}` : '';
	const res = await fetch(`${WEBUI_API_BASE_URL}/dbsphere/${id}/memories/unused${qs}`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = extractErrorMessage(err);
			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const bulkDeleteDbSphereMemories = async (
	token: string,
	id: string,
	memoryIds: string[]
): Promise<BulkDeleteResponse | null> => {
	let error: string | null = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/dbsphere/${id}/memories/bulk-delete`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({ memory_ids: memoryIds })
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = extractErrorMessage(err);
			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const updateDbSphereSummary = async (
	token: string,
	id: string,
	form: { schema_summary?: string; table_overview?: string }
): Promise<{ success: boolean } | null> => {
	let error: string | null = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/dbsphere/${id}/memories/summary/update`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify(form)
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = extractErrorMessage(err);
			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const getExtractionStatus = async (
	token: string,
	id: string
): Promise<ExtractionJobStatus | null> => {
	let error: string | null = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/dbsphere/${id}/extraction-status`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.then((json) => {
			return json;
		})
		.catch((err) => {
			error = extractErrorMessage(err);
			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const cancelSchemaExtraction = async (
	token: string,
	id: string
): Promise<ExtractionJobStatus | null> => {
	let error: string | null = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/dbsphere/${id}/extract-schema/cancel`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.then((json) => {
			return json;
		})
		.catch((err) => {
			error = extractErrorMessage(err);
			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

////////////////////////////////
// SQL Editor — execute / confirm / reject
////////////////////////////////

export type SqlPendingPayload = {
	result_id: string;
	sql: string;
	affected_preview: unknown;
	expires_in_s: number;
};

export type SqlExecuteResponse = {
	op: 'READ' | 'WRITE';
	result_id: string | null;
	columns: string[] | null;
	rows: unknown[][] | null;
	row_count: number | null;
	total_row_count: number | null;
	truncated: boolean | null;
	exec_ms: number | null;
	affected_rows: number | null;
	message: string | null;
	pending: SqlPendingPayload | null;
};

export type SqlRejectResponse = {
	success: boolean;
};

export const executeSql = async (
	token: string,
	dbsphereId: string,
	sql: string,
	signal?: AbortSignal
): Promise<SqlExecuteResponse> => {
	let error: string | null = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/dbsphere/${dbsphereId}/sql/execute`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({ sql }),
		signal
	})
		.then(async (response) => {
			if (!response.ok) throw await response.json();
			return response.json();
		})
		.catch((err) => {
			// Surface AbortError as-is so callers can distinguish a user-initiated
			// Stop from a real failure — extractErrorMessage would otherwise
			// collapse it into a string and break the `err.name === 'AbortError'`
			// check in the store.
			if (err instanceof DOMException && err.name === 'AbortError') throw err;
			error = extractErrorMessage(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res as SqlExecuteResponse;
};

export const confirmSqlExecution = async (
	token: string,
	dbsphereId: string,
	resultId: string
): Promise<SqlExecuteResponse> => {
	let error: string | null = null;

	const res = await fetch(
		`${WEBUI_API_BASE_URL}/dbsphere/${dbsphereId}/sql/execute/${resultId}/confirm`,
		{
			method: 'POST',
			headers: {
				Accept: 'application/json',
				'Content-Type': 'application/json',
				authorization: `Bearer ${token}`
			}
		}
	)
		.then(async (response) => {
			if (!response.ok) throw await response.json();
			return response.json();
		})
		.catch((err) => {
			error = extractErrorMessage(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res as SqlExecuteResponse;
};

export const rejectSqlExecution = async (
	token: string,
	dbsphereId: string,
	resultId: string
): Promise<SqlRejectResponse> => {
	let error: string | null = null;

	const res = await fetch(
		`${WEBUI_API_BASE_URL}/dbsphere/${dbsphereId}/sql/execute/${resultId}/reject`,
		{
			method: 'POST',
			headers: {
				Accept: 'application/json',
				'Content-Type': 'application/json',
				authorization: `Bearer ${token}`
			}
		}
	)
		.then(async (response) => {
			if (!response.ok) throw await response.json();
			return response.json();
		})
		.catch((err) => {
			error = extractErrorMessage(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res as SqlRejectResponse;
};

////////////////////////////////
// SQL Editor — .sql files (multi-tab persistence)
////////////////////////////////

export type SqlFile = {
	id: string;
	dbsphere_id: string;
	user_id: string;
	name: string;
	content: string;
	access_control: object | null;
	created_at: number;
	updated_at: number;
};

export type SqlFileForm = {
	name: string;
	content?: string;
};

export type SqlFileUpdateForm = {
	name?: string;
	content?: string;
	expected_updated_at?: number;
};

export type SqlFileConflict = {
	code: 'conflict';
	message: string;
	server: SqlFile | null;
};

export const getSqlFiles = async (
	token: string,
	dbsphereId: string
): Promise<SqlFile[]> => {
	let error: string | null = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/dbsphere/${dbsphereId}/sql/files`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (response) => {
			if (!response.ok) throw await response.json();
			return response.json();
		})
		.catch((err) => {
			error = extractErrorMessage(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return (res ?? []) as SqlFile[];
};

export const getSqlFileById = async (
	token: string,
	dbsphereId: string,
	fileId: string
): Promise<SqlFile> => {
	let error: string | null = null;

	const res = await fetch(
		`${WEBUI_API_BASE_URL}/dbsphere/${dbsphereId}/sql/files/${fileId}`,
		{
			method: 'GET',
			headers: {
				Accept: 'application/json',
				'Content-Type': 'application/json',
				authorization: `Bearer ${token}`
			}
		}
	)
		.then(async (response) => {
			if (!response.ok) throw await response.json();
			return response.json();
		})
		.catch((err) => {
			error = extractErrorMessage(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res as SqlFile;
};

export const createSqlFile = async (
	token: string,
	dbsphereId: string,
	form: SqlFileForm
): Promise<SqlFile> => {
	let error: string | null = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/dbsphere/${dbsphereId}/sql/files`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify(form)
	})
		.then(async (response) => {
			if (!response.ok) throw await response.json();
			return response.json();
		})
		.catch((err) => {
			error = extractErrorMessage(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res as SqlFile;
};

/**
 * PATCH sql file. On 409 conflict, throws an object shaped like SqlFileConflict
 * so the caller can present a merge dialog with the server copy.
 */
export const updateSqlFile = async (
	token: string,
	dbsphereId: string,
	fileId: string,
	form: SqlFileUpdateForm
): Promise<SqlFile> => {
	const response = await fetch(
		`${WEBUI_API_BASE_URL}/dbsphere/${dbsphereId}/sql/files/${fileId}`,
		{
			method: 'PATCH',
			headers: {
				Accept: 'application/json',
				'Content-Type': 'application/json',
				authorization: `Bearer ${token}`
			},
			body: JSON.stringify(form)
		}
	);

	if (response.status === 409) {
		// Preserve server copy for UI merge handling.
		const body = await response.json().catch(() => ({}));
		const detail = (body && (body as { detail?: unknown }).detail) ?? body;
		throw detail as SqlFileConflict;
	}

	if (!response.ok) {
		const err = await response.json().catch(() => ({}));
		throw extractErrorMessage(err);
	}

	return (await response.json()) as SqlFile;
};

export const deleteSqlFile = async (
	token: string,
	dbsphereId: string,
	fileId: string
): Promise<boolean> => {
	let error: string | null = null;

	const res = await fetch(
		`${WEBUI_API_BASE_URL}/dbsphere/${dbsphereId}/sql/files/${fileId}`,
		{
			method: 'DELETE',
			headers: {
				Accept: 'application/json',
				'Content-Type': 'application/json',
				authorization: `Bearer ${token}`
			}
		}
	)
		.then(async (response) => {
			if (!response.ok) throw await response.json();
			return response.json();
		})
		.catch((err) => {
			error = extractErrorMessage(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return Boolean(res);
};

////////////////////////////////
// SQL Editor — allow_data_modifications toggle
////////////////////////////////

export const setAllowDataModifications = async (
	token: string,
	dbsphereId: string,
	allow: boolean
) => {
	let error: string | null = null;

	const res = await fetch(
		`${WEBUI_API_BASE_URL}/dbsphere/${dbsphereId}/sql/allow-modifications`,
		{
			method: 'POST',
			headers: {
				Accept: 'application/json',
				'Content-Type': 'application/json',
				authorization: `Bearer ${token}`
			},
			body: JSON.stringify({ allow })
		}
	)
		.then(async (response) => {
			if (!response.ok) throw await response.json();
			return response.json();
		})
		.catch((err) => {
			error = extractErrorMessage(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

////////////////////////////////
// SQL Editor — admin orphan reconciliation (B10)
////////////////////////////////

export type OrphanPendingItem = {
	result_id: string;
	dbsphere_id: string | null;
	user_id: string | null;
	sql_preview: string;
	op: string;
	created_at: number;
	age_s: number;
};

export type OrphanPendingResponse = {
	items: OrphanPendingItem[];
	threshold_s: number;
};

export const getOrphanPending = async (
	token: string,
	olderThanSeconds = 60,
	limit = 200
): Promise<OrphanPendingResponse> => {
	let error: string | null = null;

	const params = new URLSearchParams({
		older_than_seconds: String(olderThanSeconds),
		limit: String(limit)
	});

	const res = await fetch(
		`${WEBUI_API_BASE_URL}/dbsphere/sql/admin/orphan-pending?${params.toString()}`,
		{
			method: 'GET',
			headers: {
				Accept: 'application/json',
				'Content-Type': 'application/json',
				authorization: `Bearer ${token}`
			}
		}
	)
		.then(async (response) => {
			if (!response.ok) throw await response.json();
			return response.json();
		})
		.catch((err) => {
			error = extractErrorMessage(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res as OrphanPendingResponse;
};

export const reconcileOrphanPending = async (
	token: string,
	dbsphereId: string,
	resultId: string,
	reason = 'orphan'
): Promise<boolean> => {
	let error: string | null = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/dbsphere/sql/admin/reconcile-orphan`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({
			dbsphere_id: dbsphereId,
			result_id: resultId,
			reason
		})
	})
		.then(async (response) => {
			if (!response.ok) throw await response.json();
			return response.json();
		})
		.catch((err) => {
			error = extractErrorMessage(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return Boolean(res);
};

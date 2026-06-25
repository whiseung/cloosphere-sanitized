import { WEBUI_API_BASE_URL } from '$lib/constants';

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

export type KnowledgeGraphSources = {
	glossary_ids?: string[];
	dbsphere_ids?: string[];
	knowledge_ids?: string[];
};

export type KnowledgeGraphOptions = {
	llm_model_id?: string;
	tool_description_model_id?: string;
	sync_mode?: 'manual' | 'nightly' | 'realtime';
};

export type KnowledgeGraphData = {
	sources?: KnowledgeGraphSources;
	options?: KnowledgeGraphOptions;
	stats?: {
		node_count?: number;
		edge_count?: number;
		last_synced_at?: number | null;
	};
};

export type KnowledgeGraph = {
	id: string;
	user_id: string;
	name: string;
	description: string | null;
	data: KnowledgeGraphData | null;
	meta: Record<string, unknown> | null;
	access_control: Record<string, unknown> | null;
	created_at: number;
	updated_at: number;
	user?: { id: string; name?: string; email?: string };
};

export type KGNode = {
	id: string;
	kg_id: string;
	user_id: string;
	node_type: string;
	label: string;
	properties: Record<string, unknown> | null;
	source_ref: Record<string, unknown> | null;
	created_at: number;
	updated_at: number;
};

export type KGNeighborhoodNode = {
	id: string;
	label: string;
	node_type: string;
	depth: number;
};

export type KGSearchResult = {
	id: string;
	label: string;
	node_type: string;
	source_kind: string;
	score: number;
	properties: Record<string, unknown> | null;
};

export type KGSearchResponse = {
	available: boolean;
	results: KGSearchResult[];
};

export type KGEdge = {
	id: string;
	kg_id: string;
	user_id: string;
	src_id: string;
	dst_id: string;
	edge_type: string;
	weight: number | null;
	properties: Record<string, unknown> | null;
	source: string;
	created_at: number;
};

export type KGMapping = {
	edge: KGEdge | null;
	src_node: KGNode | null;
	dst_node: KGNode | null;
};

export type KGGraphNode = {
	id: string;
	label: string;
	node_type: string;
	properties: Record<string, unknown> | null;
};

export type KGGraphEdge = {
	id: string;
	src_id: string;
	dst_id: string;
	edge_type: string;
	weight: number | null;
	properties: Record<string, unknown> | null;
};

export type KGGraphResponse = {
	nodes: KGGraphNode[];
	edges: KGGraphEdge[];
	truncated: boolean;
	total_nodes: number;
	total_edges: number;
};

export type KGCandidate = {
	id: string;
	kg_id: string;
	user_id: string;
	candidate_type: string;
	suggested_label: string;
	target_node_id: string | null;
	properties: {
		confidence?: number;
		reasoning?: string;
		source_column?: string;
		suggested_filter?: string | null;
		model_id?: string;
	} | null;
	status: 'pending' | 'accepted' | 'rejected';
	resolved_glossary_id: string | null;
	resolved_entry_id: string | null;
	created_at: number;
	resolved_at: number | null;
};

export const createKnowledgeGraph = async (
	token: string,
	name: string,
	description: string,
	data: KnowledgeGraphData | null,
	accessControl: null | object
): Promise<KnowledgeGraph> => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/knowledge-graph/create`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({
			name,
			description,
			data,
			access_control: accessControl
		})
	})
		.then(async (r) => {
			if (!r.ok) throw await r.json();
			return r.json();
		})
		.catch((err) => {
			error = extractErrorMessage(err);
			return null;
		});

	if (error) throw error;
	return res;
};

export const getKnowledgeGraphs = async (token: string = ''): Promise<KnowledgeGraph[]> => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/knowledge-graph/`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (r) => {
			if (!r.ok) throw await r.json();
			return r.json();
		})
		.catch((err) => {
			error = extractErrorMessage(err);
			return null;
		});

	if (error) throw error;
	return res ?? [];
};

export const getKnowledgeGraphList = async (token: string = ''): Promise<KnowledgeGraph[]> => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/knowledge-graph/list`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (r) => {
			if (!r.ok) throw await r.json();
			return r.json();
		})
		.catch((err) => {
			error = extractErrorMessage(err);
			return null;
		});

	if (error) throw error;
	return res ?? [];
};

export const getKnowledgeGraphById = async (
	token: string,
	id: string
): Promise<KnowledgeGraph> => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/knowledge-graph/${id}`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (r) => {
			if (!r.ok) throw await r.json();
			return r.json();
		})
		.catch((err) => {
			error = extractErrorMessage(err);
			return null;
		});

	if (error) throw error;
	return res;
};

export const updateKnowledgeGraphById = async (
	token: string,
	id: string,
	form: {
		name?: string;
		description?: string;
		data?: KnowledgeGraphData | null;
		meta?: Record<string, unknown> | null;
		access_control?: object | null;
	}
): Promise<KnowledgeGraph> => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/knowledge-graph/${id}/update`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify(form)
	})
		.then(async (r) => {
			if (!r.ok) throw await r.json();
			return r.json();
		})
		.catch((err) => {
			error = extractErrorMessage(err);
			return null;
		});

	if (error) throw error;
	return res;
};

export const deleteKnowledgeGraphById = async (token: string, id: string): Promise<boolean> => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/knowledge-graph/${id}/delete`, {
		method: 'DELETE',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (r) => {
			if (!r.ok) throw await r.json();
			return r.json();
		})
		.catch((err) => {
			error = extractErrorMessage(err);
			return null;
		});

	if (error) throw error;
	return res === true;
};

export const syncKnowledgeGraph = async (
	token: string,
	id: string
): Promise<{ status: boolean; message: string }> => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/knowledge-graph/${id}/sync`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (r) => {
			if (!r.ok) throw await r.json();
			return r.json();
		})
		.catch((err) => {
			error = extractErrorMessage(err);
			return null;
		});

	if (error) throw error;
	return res;
};

export type KGNodesPage = {
	items: KGNode[];
	total: number;
	limit: number;
	offset: number;
};

export const getKnowledgeGraphNodes = async (
	token: string,
	id: string,
	params: {
		node_type?: string;
		q?: string;
		limit?: number;
		offset?: number;
	} = {}
): Promise<KGNodesPage> => {
	const qs = new URLSearchParams();
	if (params.node_type) qs.set('node_type', params.node_type);
	if (params.q && params.q.trim()) qs.set('q', params.q.trim());
	if (params.limit !== undefined) qs.set('limit', String(params.limit));
	if (params.offset !== undefined) qs.set('offset', String(params.offset));
	const query = qs.toString();

	let error = null;
	const res = await fetch(
		`${WEBUI_API_BASE_URL}/knowledge-graph/${id}/nodes${query ? `?${query}` : ''}`,
		{
			method: 'GET',
			headers: {
				Accept: 'application/json',
				'Content-Type': 'application/json',
				authorization: `Bearer ${token}`
			}
		}
	)
		.then(async (r) => {
			if (!r.ok) throw await r.json();
			return r.json();
		})
		.catch((err) => {
			error = extractErrorMessage(err);
			return null;
		});

	if (error) throw error;
	return res ?? { items: [], total: 0, limit: params.limit ?? 0, offset: params.offset ?? 0 };
};

export type KGEdgeTypeCatalogItem = {
	key: string;
	display_name: string;
	description: string;
	examples?: string[];
	source: 'llm' | 'manual';
	recommendation_reason: string | null;
	category?: string | null;
	src_category?: string | null;
	dst_category?: string | null;
	created_at?: number;
	updated_at?: number;
};

export type KGEdgeTypeCatalog = {
	items: KGEdgeTypeCatalogItem[];
	/** `null` = user 가 한 번도 저장 안 한 상태 (프론트에서 기본값 결정) */
	locked: boolean | null;
	recommend_model_id?: string | null;
};

export const getKnowledgeGraphLinkEdgeTypeCatalog = async (
	token: string,
	id: string,
	linkId: string
): Promise<KGEdgeTypeCatalog> => {
	let error = null;
	const res = await fetch(
		`${WEBUI_API_BASE_URL}/knowledge-graph/${id}/links/${linkId}/edge-types/catalog`,
		{
			method: 'GET',
			headers: {
				Accept: 'application/json',
				'Content-Type': 'application/json',
				authorization: `Bearer ${token}`
			}
		}
	)
		.then(async (r) => {
			if (!r.ok) throw await r.json();
			return r.json();
		})
		.catch((err) => {
			error = extractErrorMessage(err);
			return null;
		});

	if (error) throw error;
	return res ?? { items: [], locked: false };
};

export const putKnowledgeGraphLinkEdgeTypeCatalog = async (
	token: string,
	id: string,
	linkId: string,
	payload: {
		items: Partial<KGEdgeTypeCatalogItem>[];
		locked: boolean;
		recommend_model_id?: string | null;
	}
): Promise<KGEdgeTypeCatalog> => {
	let error = null;
	const res = await fetch(
		`${WEBUI_API_BASE_URL}/knowledge-graph/${id}/links/${linkId}/edge-types/catalog`,
		{
			method: 'PUT',
			headers: {
				Accept: 'application/json',
				'Content-Type': 'application/json',
				authorization: `Bearer ${token}`
			},
			body: JSON.stringify(payload)
		}
	)
		.then(async (r) => {
			if (!r.ok) throw await r.json();
			return r.json();
		})
		.catch((err) => {
			error = extractErrorMessage(err);
			return null;
		});

	if (error) throw error;
	return res ?? { items: [], locked: false };
};

export type KGNodeFilterSlot = {
	kb_id: string;
	slot: string;
};

export type KGLinkNodeFilters = {
	slots: KGNodeFilterSlot[];
};

export const getKnowledgeGraphLinkNodeFilters = async (
	token: string,
	id: string,
	linkId: string
): Promise<KGLinkNodeFilters> => {
	let error = null;
	const res = await fetch(
		`${WEBUI_API_BASE_URL}/knowledge-graph/${id}/links/${linkId}/node-filters`,
		{
			method: 'GET',
			headers: {
				Accept: 'application/json',
				'Content-Type': 'application/json',
				authorization: `Bearer ${token}`
			}
		}
	)
		.then(async (r) => {
			if (!r.ok) throw await r.json();
			return r.json();
		})
		.catch((err) => {
			error = extractErrorMessage(err);
			return null;
		});

	if (error) throw error;
	return res ?? { slots: [] };
};

export const putKnowledgeGraphLinkNodeFilters = async (
	token: string,
	id: string,
	linkId: string,
	payload: KGLinkNodeFilters
): Promise<KGLinkNodeFilters> => {
	let error = null;
	const res = await fetch(
		`${WEBUI_API_BASE_URL}/knowledge-graph/${id}/links/${linkId}/node-filters`,
		{
			method: 'PUT',
			headers: {
				Accept: 'application/json',
				'Content-Type': 'application/json',
				authorization: `Bearer ${token}`
			},
			body: JSON.stringify(payload)
		}
	)
		.then(async (r) => {
			if (!r.ok) throw await r.json();
			return r.json();
		})
		.catch((err) => {
			error = extractErrorMessage(err);
			return null;
		});

	if (error) throw error;
	return res ?? { slots: [] };
};

export type KGEdgeTypeRecommendation = {
	key: string;
	display_name: string;
	description: string;
	recommendation_reason: string | null;
	category?: string | null;
	src_category?: string | null;
	dst_category?: string | null;
};

export const recommendKnowledgeGraphLinkEdgeTypes = async (
	token: string,
	id: string,
	linkId: string,
	body: { model_id?: string; max_candidates?: number } = {}
): Promise<KGEdgeTypeRecommendation[]> => {
	let error = null;
	const res = await fetch(
		`${WEBUI_API_BASE_URL}/knowledge-graph/${id}/links/${linkId}/edge-types/recommend`,
		{
			method: 'POST',
			headers: {
				Accept: 'application/json',
				'Content-Type': 'application/json',
				authorization: `Bearer ${token}`
			},
			body: JSON.stringify(body)
		}
	)
		.then(async (r) => {
			if (!r.ok) throw await r.json();
			return r.json();
		})
		.catch((err) => {
			error = extractErrorMessage(err);
			return null;
		});

	if (error) throw error;
	return (res?.candidates ?? []) as KGEdgeTypeRecommendation[];
};

export const autoGenerateKnowledgeGraphLinkEdgeTypes = async (
	token: string,
	id: string,
	linkId: string,
	body: {
		model_id?: string;
		max_candidates?: number;
		replace_existing?: boolean;
		locked?: boolean;
	} = {}
): Promise<KGEdgeTypeCatalog> => {
	let error = null;
	const res = await fetch(
		`${WEBUI_API_BASE_URL}/knowledge-graph/${id}/links/${linkId}/edge-types/auto-generate`,
		{
			method: 'POST',
			headers: {
				Accept: 'application/json',
				'Content-Type': 'application/json',
				authorization: `Bearer ${token}`
			},
			body: JSON.stringify(body)
		}
	)
		.then(async (r) => {
			if (!r.ok) throw await r.json();
			return r.json();
		})
		.catch((err) => {
			error = extractErrorMessage(err);
			return null;
		});

	if (error) throw error;
	return res ?? { items: [], locked: false };
};

export const getKnowledgeGraphEdgeTypes = async (
	token: string,
	id: string
): Promise<{ edge_type: string; count: number }[]> => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/knowledge-graph/${id}/edge-types`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (r) => {
			if (!r.ok) throw await r.json();
			return r.json();
		})
		.catch((err) => {
			error = extractErrorMessage(err);
			return null;
		});

	if (error) throw error;
	return (res?.items ?? []) as { edge_type: string; count: number }[];
};

export type KGEdgesPage = {
	items: KGEdge[];
	total: number;
	limit: number;
	offset: number;
};

export const getKnowledgeGraphEdges = async (
	token: string,
	id: string,
	params: {
		edge_type?: string;
		q?: string;
		limit?: number;
		offset?: number;
	} = {}
): Promise<KGEdgesPage> => {
	const qs = new URLSearchParams();
	if (params.edge_type) qs.set('edge_type', params.edge_type);
	if (params.q && params.q.trim()) qs.set('q', params.q.trim());
	if (params.limit !== undefined) qs.set('limit', String(params.limit));
	if (params.offset !== undefined) qs.set('offset', String(params.offset));
	const query = qs.toString();

	let error = null;
	const res = await fetch(
		`${WEBUI_API_BASE_URL}/knowledge-graph/${id}/edges${query ? `?${query}` : ''}`,
		{
			method: 'GET',
			headers: {
				Accept: 'application/json',
				'Content-Type': 'application/json',
				authorization: `Bearer ${token}`
			}
		}
	)
		.then(async (r) => {
			if (!r.ok) throw await r.json();
			return r.json();
		})
		.catch((err) => {
			error = extractErrorMessage(err);
			return null;
		});

	if (error) throw error;
	return res ?? { items: [], total: 0, limit: params.limit ?? 0, offset: params.offset ?? 0 };
};

export const getKnowledgeGraphStats = async (
	token: string,
	id: string
): Promise<{ node_count: number; edge_count: number; stats: Record<string, unknown> }> => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/knowledge-graph/${id}/stats`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (r) => {
			if (!r.ok) throw await r.json();
			return r.json();
		})
		.catch((err) => {
			error = extractErrorMessage(err);
			return null;
		});

	if (error) throw error;
	return res;
};

export const getKnowledgeGraphMappings = async (
	token: string,
	id: string,
	edgeType?: string
): Promise<KGMapping[]> => {
	const qs = edgeType ? `?edge_type=${encodeURIComponent(edgeType)}` : '';
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/knowledge-graph/${id}/mappings${qs}`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (r) => {
			if (!r.ok) throw await r.json();
			return r.json();
		})
		.catch((err) => {
			error = extractErrorMessage(err);
			return null;
		});

	if (error) throw error;
	return res ?? [];
};

export const createKnowledgeGraphEdge = async (
	token: string,
	id: string,
	form: {
		src_id: string;
		dst_id: string;
		edge_type: string;
		properties?: Record<string, unknown>;
	}
): Promise<KGEdge> => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/knowledge-graph/${id}/edges`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify(form)
	})
		.then(async (r) => {
			if (!r.ok) throw await r.json();
			return r.json();
		})
		.catch((err) => {
			error = extractErrorMessage(err);
			return null;
		});

	if (error) throw error;
	return res;
};

export const getKnowledgeGraphGraph = async (
	token: string,
	id: string,
	params: {
		max_nodes?: number;
		node_types?: string[];
		edge_types?: string[];
		priority_node_type?: string;
	} = {}
): Promise<KGGraphResponse> => {
	const qs = new URLSearchParams();
	if (params.max_nodes !== undefined) qs.set('max_nodes', String(params.max_nodes));
	if (params.node_types?.length) qs.set('node_types', params.node_types.join(','));
	if (params.edge_types?.length) qs.set('edge_types', params.edge_types.join(','));
	if (params.priority_node_type) qs.set('priority_node_type', params.priority_node_type);
	const query = qs.toString();

	let error = null;
	const res = await fetch(
		`${WEBUI_API_BASE_URL}/knowledge-graph/${id}/graph${query ? `?${query}` : ''}`,
		{
			method: 'GET',
			headers: {
				Accept: 'application/json',
				'Content-Type': 'application/json',
				authorization: `Bearer ${token}`
			}
		}
	)
		.then(async (r) => {
			if (!r.ok) throw await r.json();
			return r.json();
		})
		.catch((err) => {
			error = extractErrorMessage(err);
			return null;
		});

	if (error) throw error;
	return res ?? {
		nodes: [],
		edges: [],
		truncated: false,
		total_nodes: 0,
		total_edges: 0
	};
};

export type KbExtractPreview = {
	knowledge_ids: string[];
	chunks_per_kb: Record<string, number>;
	pending_total: number;
	already_processed_total: number;
	estimated_llm_calls: number;
};

export const previewKnowledgeGraphKbEntities = async (
	token: string,
	id: string,
	form: {
		knowledge_id?: string;
		knowledge_ids?: string[];
		max_chunks?: number | null;
		reset?: boolean;
	}
): Promise<KbExtractPreview> => {
	let error = null;
	const res = await fetch(
		`${WEBUI_API_BASE_URL}/knowledge-graph/${id}/kb/extract/preview`,
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
		.then(async (r) => {
			if (!r.ok) throw await r.json();
			return r.json();
		})
		.catch((err) => {
			error = extractErrorMessage(err);
			return null;
		});

	if (error) throw error;
	return res;
};

export const extractKnowledgeGraphKbEntities = async (
	token: string,
	id: string,
	form: {
		knowledge_id?: string;
		model_id?: string;
		max_chunks?: number | null;
		min_confidence?: number;
		reset?: boolean;
		cleanup_only?: boolean;
	}
): Promise<{ status: boolean; message: string; knowledge_ids: string[] }> => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/knowledge-graph/${id}/kb/extract`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify(form)
	})
		.then(async (r) => {
			if (!r.ok) throw await r.json();
			return r.json();
		})
		.catch((err) => {
			error = extractErrorMessage(err);
			return null;
		});

	if (error) throw error;
	return res;
};

export const getKnowledgeGraphCandidates = async (
	token: string,
	id: string,
	status?: 'pending' | 'accepted' | 'rejected'
): Promise<KGCandidate[]> => {
	const qs = status ? `?status=${status}` : '';
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/knowledge-graph/${id}/candidates${qs}`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (r) => {
			if (!r.ok) throw await r.json();
			return r.json();
		})
		.catch((err) => {
			error = extractErrorMessage(err);
			return null;
		});

	if (error) throw error;
	return res ?? [];
};

export const acceptKnowledgeGraphCandidate = async (
	token: string,
	id: string,
	cid: string,
	form: {
		glossary_id: string;
		term?: string;
		description?: string;
		category?: string;
		filter_expr?: string;
		create_mapping?: boolean;
	}
): Promise<{ status: boolean; entry_id: string; mapping_created: boolean }> => {
	let error = null;
	const res = await fetch(
		`${WEBUI_API_BASE_URL}/knowledge-graph/${id}/candidates/${cid}/accept`,
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
		.then(async (r) => {
			if (!r.ok) throw await r.json();
			return r.json();
		})
		.catch((err) => {
			error = extractErrorMessage(err);
			return null;
		});

	if (error) throw error;
	return res;
};

export const rejectKnowledgeGraphCandidate = async (
	token: string,
	id: string,
	cid: string
): Promise<boolean> => {
	let error = null;
	const res = await fetch(
		`${WEBUI_API_BASE_URL}/knowledge-graph/${id}/candidates/${cid}/reject`,
		{
			method: 'POST',
			headers: {
				Accept: 'application/json',
				'Content-Type': 'application/json',
				authorization: `Bearer ${token}`
			}
		}
	)
		.then(async (r) => {
			if (!r.ok) throw await r.json();
			return r.json();
		})
		.catch((err) => {
			error = extractErrorMessage(err);
			return null;
		});

	if (error) throw error;
	return res === true;
};

export const deleteKnowledgeGraphEdge = async (
	token: string,
	id: string,
	edgeId: string
): Promise<boolean> => {
	let error = null;
	const res = await fetch(
		`${WEBUI_API_BASE_URL}/knowledge-graph/${id}/edges/${encodeURIComponent(edgeId)}`,
		{
			method: 'DELETE',
			headers: {
				Accept: 'application/json',
				'Content-Type': 'application/json',
				authorization: `Bearer ${token}`
			}
		}
	)
		.then(async (r) => {
			if (!r.ok) throw await r.json();
			return r.json();
		})
		.catch((err) => {
			error = extractErrorMessage(err);
			return null;
		});

	if (error) throw error;
	return res === true;
};

export const searchKnowledgeGraph = async (
	token: string,
	id: string,
	params: { q: string; top_k?: number; node_types?: string[] }
): Promise<KGSearchResponse> => {
	const qs = new URLSearchParams();
	qs.set('q', params.q);
	if (params.top_k !== undefined) qs.set('top_k', String(params.top_k));
	if (params.node_types && params.node_types.length > 0) {
		qs.set('node_types', params.node_types.join(','));
	}

	let error = null;
	const res = await fetch(
		`${WEBUI_API_BASE_URL}/knowledge-graph/${id}/search?${qs.toString()}`,
		{
			method: 'GET',
			headers: {
				Accept: 'application/json',
				'Content-Type': 'application/json',
				authorization: `Bearer ${token}`
			}
		}
	)
		.then(async (r) => {
			if (!r.ok) throw await r.json();
			return r.json();
		})
		.catch((err) => {
			error = extractErrorMessage(err);
			return null;
		});

	if (error) throw error;
	return res ?? { available: false, results: [] };
};

export type KGExtractJob = {
	id: string;
	kg_id: string;
	user_id: string;
	kind:
		| 'kb_extract'
		| 'kb_cleanup'
		| 'candidate_extract'
		| 'sync_all'
		| 'link_sync'
		| 'glossary_sync';
	status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled';
	target_id: string | null;
	params: Record<string, unknown> | null;
	progress_current: number;
	progress_total: number;
	progress_label: string | null;
	stats: Record<string, unknown> | null;
	errors: string[] | null;
	created_at: number;
	started_at: number | null;
	finished_at: number | null;
};

export const getKnowledgeGraphJobs = async (
	token: string,
	id: string,
	params: {
		job_status?: 'pending' | 'running' | 'completed' | 'failed';
		kind?: 'kb_extract' | 'kb_cleanup' | 'candidate_extract' | 'sync_all';
		limit?: number;
	} = {}
): Promise<KGExtractJob[]> => {
	const qs = new URLSearchParams();
	if (params.job_status) qs.set('job_status', params.job_status);
	if (params.kind) qs.set('kind', params.kind);
	if (params.limit !== undefined) qs.set('limit', String(params.limit));

	let error = null;
	const res = await fetch(
		`${WEBUI_API_BASE_URL}/knowledge-graph/${id}/jobs${qs.toString() ? '?' + qs.toString() : ''}`,
		{
			method: 'GET',
			headers: {
				Accept: 'application/json',
				'Content-Type': 'application/json',
				authorization: `Bearer ${token}`
			}
		}
	)
		.then(async (r) => {
			if (!r.ok) throw await r.json();
			return r.json();
		})
		.catch((err) => {
			error = extractErrorMessage(err);
			return null;
		});

	if (error) throw error;
	return res ?? [];
};

export type KGActiveJob = {
	id: string;
	kg_id: string;
	kg_name: string | null;
	user_id: string;
	kind: string;
	target_id: string | null;
	status: 'pending' | 'running';
	progress_current: number | null;
	progress_total: number | null;
	progress_label: string | null;
	params: Record<string, unknown> | null;
	stats: Record<string, unknown> | null;
	created_at: number | null;
	updated_at: number | null;
};

export const getActiveKnowledgeGraphJobs = async (token: string): Promise<KGActiveJob[]> => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/knowledge-graph/active-jobs`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (r) => {
			if (!r.ok) throw await r.json();
			return r.json();
		})
		.catch((err) => {
			error = extractErrorMessage(err);
			return null;
		});

	if (error) throw error;
	return res ?? [];
};

export const cancelKnowledgeGraphJob = async (
	token: string,
	kgId: string,
	jobId: string
): Promise<boolean> => {
	let error = null;
	const res = await fetch(
		`${WEBUI_API_BASE_URL}/knowledge-graph/${kgId}/jobs/${jobId}/cancel`,
		{
			method: 'POST',
			headers: {
				Accept: 'application/json',
				'Content-Type': 'application/json',
				authorization: `Bearer ${token}`
			}
		}
	)
		.then(async (r) => {
			if (!r.ok) throw await r.json();
			return r.json();
		})
		.catch((err) => {
			error = extractErrorMessage(err);
			return null;
		});

	if (error) throw error;
	return res === true;
};

// ─── Knowledge Links (지식 연결) ───

export type KnowledgeLink = {
	id: string;
	glossary_id: string | null;
	knowledge_ids: string[];
	status: {
		documents_matched?: number;
		last_matched_at?: number | null;
		doc_entity_map?: Record<string, { entity_node_id: string; entity_label: string; category?: string | null }[]>;
	} | null;
	/** 링크 설정 — dbsphere_ids 외에 edge type 카탈로그도 이 안에 저장된다.
	 *  `edge_types` 는 key→카탈로그 항목 dict (비어 있으면 카탈로그 미설정). */
	config?: {
		dbsphere_ids?: string[];
		edge_types?: Record<string, unknown>;
		edge_types_locked?: boolean;
	} | null;
};

export const getKnowledgeLinks = async (token: string, kgId: string): Promise<KnowledgeLink[]> => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/knowledge-graph/${kgId}/links`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (r) => {
			if (!r.ok) throw await r.json();
			return r.json();
		})
		.catch((err) => {
			error = extractErrorMessage(err);
			return null;
		});

	if (error) throw error;
	return res ?? [];
};

export type LinkSourceCandidate = {
	id: string;
	name: string | null;
	description: string | null;
};

export type LinkSourceCandidatesResponse = {
	knowledge_bases: LinkSourceCandidate[];
	dbspheres: LinkSourceCandidate[];
};

export const getLinkSourceCandidates = async (
	token: string,
	kgId: string,
	glossaryId: string
): Promise<LinkSourceCandidatesResponse> => {
	const qs = new URLSearchParams({ glossary_id: glossaryId });
	let error = null;
	const res = await fetch(
		`${WEBUI_API_BASE_URL}/knowledge-graph/${kgId}/links/source-candidates?${qs.toString()}`,
		{
			method: 'GET',
			headers: {
				Accept: 'application/json',
				'Content-Type': 'application/json',
				authorization: `Bearer ${token}`
			}
		}
	)
		.then(async (r) => {
			if (!r.ok) throw await r.json();
			return r.json();
		})
		.catch((err) => {
			error = extractErrorMessage(err);
			return null;
		});

	if (error) throw error;
	return res ?? { knowledge_bases: [], dbspheres: [] };
};

export const createKnowledgeLink = async (
	token: string,
	kgId: string,
	form: {
		glossary_id: string;
		knowledge_ids: string[];
		dbsphere_ids?: string[];
	}
): Promise<KnowledgeLink> => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/knowledge-graph/${kgId}/links`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify(form)
	})
		.then(async (r) => {
			if (!r.ok) throw await r.json();
			return r.json();
		})
		.catch((err) => {
			error = extractErrorMessage(err);
			return null;
		});

	if (error) throw error;
	return res;
};

export const deleteKnowledgeLink = async (
	token: string,
	kgId: string,
	linkId: string
): Promise<boolean> => {
	let error = null;
	const res = await fetch(
		`${WEBUI_API_BASE_URL}/knowledge-graph/${kgId}/links/${linkId}`,
		{
			method: 'DELETE',
			headers: {
				Accept: 'application/json',
				'Content-Type': 'application/json',
				authorization: `Bearer ${token}`
			}
		}
	)
		.then(async (r) => {
			if (!r.ok) throw await r.json();
			return r.json();
		})
		.catch((err) => {
			error = extractErrorMessage(err);
			return null;
		});

	if (error) throw error;
	return res === true;
};

export const syncKnowledgeLink = async (
	token: string,
	kgId: string,
	linkId: string
): Promise<{ status: boolean; message: string; job_id: string | null }> => {
	let error = null;
	const res = await fetch(
		`${WEBUI_API_BASE_URL}/knowledge-graph/${kgId}/links/${linkId}/sync`,
		{
			method: 'POST',
			headers: {
				Accept: 'application/json',
				'Content-Type': 'application/json',
				authorization: `Bearer ${token}`
			}
		}
	)
		.then(async (r) => {
			if (!r.ok) throw await r.json();
			return r.json();
		})
		.catch((err) => {
			error = extractErrorMessage(err);
			return null;
		});

	if (error) throw error;
	return res;
};

// ─── KG Tool Tester ───

export const testKgTool = async (
	token: string,
	kgId: string,
	toolName: string,
	args: Record<string, unknown>
): Promise<{ tool: string; error: string | null; result: string | null }> => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/knowledge-graph/${kgId}/test-tool`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({ tool_name: toolName, args })
	})
		.then(async (r) => {
			if (!r.ok) throw await r.json();
			return r.json();
		})
		.catch((err) => {
			error = extractErrorMessage(err);
			return null;
		});

	if (error) throw error;
	return res;
};

// ─── Export / Import ───

export const exportKnowledgeGraph = async (
	token: string,
	kgId: string
): Promise<Record<string, unknown>> => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/knowledge-graph/${kgId}/export`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (r) => {
			if (!r.ok) throw await r.json();
			return r.json();
		})
		.catch((err) => {
			error = extractErrorMessage(err);
			return null;
		});

	if (error) throw error;
	return res;
};

export const importKnowledgeGraph = async (
	token: string,
	data: Record<string, unknown>,
	name?: string
): Promise<KnowledgeGraph> => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/knowledge-graph/create/import`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({ name: name ?? null, data })
	})
		.then(async (r) => {
			if (!r.ok) throw await r.json();
			return r.json();
		})
		.catch((err) => {
			error = extractErrorMessage(err);
			return null;
		});

	if (error) throw error;
	return res;
};

// ─── DbSphere Schema Helpers (용어집 DB 추출 UI용) ───

export type DbSphereTableInfo = {
	table_name: string;
	description: string;
	column_count: number;
};

export type DbSphereColumnInfo = {
	name: string;
	data_type: string;
	description: string;
	is_primary_key: boolean;
	is_foreign_key: boolean;
};

export const getDbSphereTables = async (
	token: string,
	dbsphereId: string
): Promise<DbSphereTableInfo[]> => {
	let error = null;
	const res = await fetch(
		`${WEBUI_API_BASE_URL}/knowledge-graph/dbsphere/${dbsphereId}/tables`,
		{
			method: 'GET',
			headers: {
				Accept: 'application/json',
				'Content-Type': 'application/json',
				authorization: `Bearer ${token}`
			}
		}
	)
		.then(async (r) => {
			if (!r.ok) throw await r.json();
			return r.json();
		})
		.catch((err) => {
			error = extractErrorMessage(err);
			return null;
		});

	if (error) throw error;
	return res ?? [];
};

export const getDbSphereColumns = async (
	token: string,
	dbsphereId: string,
	tableName: string
): Promise<DbSphereColumnInfo[]> => {
	let error = null;
	const res = await fetch(
		`${WEBUI_API_BASE_URL}/knowledge-graph/dbsphere/${dbsphereId}/tables/${encodeURIComponent(tableName)}/columns`,
		{
			method: 'GET',
			headers: {
				Accept: 'application/json',
				'Content-Type': 'application/json',
				authorization: `Bearer ${token}`
			}
		}
	)
		.then(async (r) => {
			if (!r.ok) throw await r.json();
			return r.json();
		})
		.catch((err) => {
			error = extractErrorMessage(err);
			return null;
		});

	if (error) throw error;
	return res ?? [];
};

export const getKnowledgeGraphNeighbors = async (
	token: string,
	id: string,
	params: { node_id: string; hops?: number; edge_types?: string[]; limit?: number }
): Promise<KGNeighborhoodNode[]> => {
	const qs = new URLSearchParams();
	qs.set('node_id', params.node_id);
	if (params.hops !== undefined) qs.set('hops', String(params.hops));
	if (params.edge_types && params.edge_types.length > 0) {
		qs.set('edge_types', params.edge_types.join(','));
	}
	if (params.limit !== undefined) qs.set('limit', String(params.limit));

	let error = null;
	const res = await fetch(
		`${WEBUI_API_BASE_URL}/knowledge-graph/${id}/neighbors?${qs.toString()}`,
		{
			method: 'GET',
			headers: {
				Accept: 'application/json',
				'Content-Type': 'application/json',
				authorization: `Bearer ${token}`
			}
		}
	)
		.then(async (r) => {
			if (!r.ok) throw await r.json();
			return r.json();
		})
		.catch((err) => {
			error = extractErrorMessage(err);
			return null;
		});

	if (error) throw error;
	return res ?? [];
};

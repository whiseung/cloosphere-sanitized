import { WEBUI_API_BASE_URL } from '$lib/constants';

// Helper to extract error message from API response
// Exported for use in glossary components — replaces inline
// `typeof e === 'string' ? e : e?.detail ?? `${e}`` duplicates.
export const extractErrorMessage = (err: unknown): string => {
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

export const createNewGlossary = async (
	token: string,
	name: string,
	description: string,
	accessControl: null | object
) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/glossary/create`, {
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

export const getGlossaries = async (token: string = '') => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/glossary/`, {
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

export const getGlossaryList = async (token: string = '') => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/glossary/list`, {
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

export const getGlossaryById = async (token: string, id: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/glossary/${id}`, {
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

type GlossaryUpdateForm = {
	name?: string;
	description?: string;
	data?: object;
	meta?: Record<string, unknown> | null;
	access_control?: null | object;
};

export const updateGlossaryById = async (token: string, id: string, form: GlossaryUpdateForm) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/glossary/${id}/update`, {
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

export type GlossaryEntryDTO = {
	id: string;
	term: string;
	synonyms: string[];
	description: string;
	example: string;
	category?: string | null;
	created_via?: string | null;
	created_at: number;
	updated_at: number;
};

export type GlossaryEntriesPage = {
	entries: GlossaryEntryDTO[];
	total: number;
	skip: number;
	limit: number;
};

export const createGlossaryEntry = async (
	token: string,
	id: string,
	entry: {
		term: string;
		synonyms?: string[];
		description?: string;
		example?: string;
		category?: string | null;
	}
): Promise<GlossaryEntryDTO> => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/glossary/${id}/entries`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify(entry)
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

export const updateGlossaryEntry = async (
	token: string,
	id: string,
	entryId: string,
	patch: Partial<Pick<GlossaryEntryDTO, 'term' | 'synonyms' | 'description' | 'example' | 'category'>>
): Promise<GlossaryEntryDTO> => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/glossary/${id}/entries/${entryId}`, {
		method: 'PUT',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify(patch)
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

export const deleteGlossaryEntry = async (
	token: string,
	id: string,
	entryId: string
) => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/glossary/${id}/entries/${entryId}`, {
		method: 'DELETE',
		headers: {
			Accept: 'application/json',
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

export type GlossaryImportPreview = {
	upload_token: string;
	format: 'xlsx' | 'csv' | 'md';
	md_pattern: 'sectioned' | 'table' | 'h2-dl' | null;
	encoding: string | null;
	headers: string[];
	header_mapping: Record<string, string>;
	sample_entries: Array<{
		term: string;
		synonyms: string[];
		description: string;
		example: string;
		category?: string;
	}>;
	stats: {
		total_rows: number;
		parsed: number;
		skipped_rows: number;
		added: number;
		updated: number;
	};
	base_updated_at: number;
};

export type GlossaryImportCommitResult = {
	success: boolean;
	added: number;
	updated: number;
	skipped: number;
	total: number;
};

export const previewGlossaryImport = async (
	token: string,
	id: string,
	file: File
): Promise<GlossaryImportPreview> => {
	let error: string | null = null;
	const formData = new FormData();
	formData.append('file', file);

	const res = await fetch(`${WEBUI_API_BASE_URL}/glossary/${id}/import/preview`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			authorization: `Bearer ${token}`
		},
		body: formData
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

export type GlossaryImportLLMRule = {
	mapping: Record<string, any>;
	rationale: string;
};

export type GlossaryImportSegment = {
	kind: 'literal' | 'data';
	text: string;
};

export type GlossaryImportLLMSuggestResult = {
	rule: GlossaryImportLLMRule;
	sample_entries: Array<{
		term: string;
		synonyms: string[];
		description: string;
		example: string;
		category?: string;
	}>;
	sample_entries_segments?: Array<Record<string, GlossaryImportSegment[]>>;
};

export const llmSuggestGlossaryImport = async (
	token: string,
	id: string,
	uploadToken: string,
	modelId?: string,
	options: { conservativeDescription?: boolean } = {}
): Promise<GlossaryImportLLMSuggestResult> => {
	let error: string | null = null;
	const body: Record<string, unknown> = {
		upload_token: uploadToken,
		model_id: modelId ?? null
	};
	if (options.conservativeDescription !== undefined) {
		body.conservative_description = options.conservativeDescription;
	}
	const res = await fetch(`${WEBUI_API_BASE_URL}/glossary/${id}/import/llm-suggest`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify(body)
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

export const commitGlossaryImport = async (
	token: string,
	id: string,
	body: {
		upload_token: string;
		mapping: Record<string, string>;
		auto_classify: boolean;
		base_updated_at: number;
		llm_rule?: GlossaryImportLLMRule | null;
	}
): Promise<GlossaryImportCommitResult> => {
	let error: string | null = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/glossary/${id}/import/commit`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify(body)
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

export const bulkDeleteGlossaryEntries = async (
	token: string,
	id: string,
	entryIds: string[]
): Promise<{ success: boolean; deleted_count: number }> => {
	let error: string | null = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/glossary/${id}/entries/bulk-delete`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({ entry_ids: entryIds })
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

export const getGlossaryEntries = async (
	token: string,
	id: string,
	opts: {
		skip?: number;
		limit?: number;
		search?: string;
		sort?: 'name' | 'newest' | 'oldest';
		category?: string;
		uncategorized?: boolean;
		categories?: string[];
		includeUncategorized?: boolean;
		created_via?: string[];
	} = {}
): Promise<GlossaryEntriesPage> => {
	let error = null;
	const params = new URLSearchParams();
	params.set('skip', String(opts.skip ?? 0));
	params.set('limit', String(opts.limit ?? 50));
	if (opts.search) params.set('search', opts.search);
	params.set('sort', opts.sort ?? 'name');
	// 멀티 셀렉트 우선, 없으면 legacy 단일 필터로 fallback.
	// categories 가 있으면 (빈 list 도) 백엔드가 멀티 분기로 진입 — None 과 구분.
	if (opts.categories !== undefined) {
		for (const c of opts.categories) params.append('categories', c);
		if (opts.includeUncategorized) params.set('include_uncategorized', 'true');
	} else if (opts.uncategorized) params.set('uncategorized', 'true');
	else if (opts.category) params.set('category', opts.category);
	if (opts.created_via && opts.created_via.length > 0) {
		for (const cv of opts.created_via) params.append('created_via', cv);
	}

	const res = await fetch(`${WEBUI_API_BASE_URL}/glossary/${id}/entries?${params}`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
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

export const downloadGlossaryImportTemplate = async (token: string): Promise<Blob> => {
	const res = await fetch(`${WEBUI_API_BASE_URL}/glossary/import-template.xlsx`, {
		method: 'GET',
		headers: {
			authorization: `Bearer ${token}`
		}
	});
	if (!res.ok) {
		let detail = `${res.status}`;
		try {
			const body = await res.json();
			detail = extractErrorMessage(body);
		} catch {
			// non-JSON body — fall back to status code
		}
		throw detail;
	}
	return res.blob();
};

export const getGlossaryCategories = async (token: string, id: string): Promise<string[]> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/glossary/${id}/categories`, {
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
			return [];
		});

	if (error) {
		throw error;
	}

	return res;
};

export const renameGlossaryCategory = async (
	token: string,
	id: string,
	from_name: string,
	to_name: string
): Promise<{ success: boolean; updated_count: number }> => {
	let error: string | null = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/glossary/${id}/categories/rename`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({ from_name, to_name })
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

export const deleteGlossaryCategory = async (
	token: string,
	id: string,
	name: string,
	keepEntries: boolean = false
): Promise<{
	success: boolean;
	deleted_count?: number;
	updated_count?: number;
	kept_entries: boolean;
}> => {
	let error: string | null = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/glossary/${id}/categories/delete`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({ name, keep_entries: keepEntries })
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

export const deleteUncategorizedGlossaryEntries = async (
	token: string,
	id: string
): Promise<{ success: boolean; deleted_count: number }> => {
	let error: string | null = null;

	const res = await fetch(
		`${WEBUI_API_BASE_URL}/glossary/${id}/categories/uncategorized`,
		{
			method: 'DELETE',
			headers: {
				Accept: 'application/json',
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

export const getLinkedAgentsByGlossaryId = async (token: string, id: string) => {
	let error: string | null = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/glossary/${id}/linked-agents`, {
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

export const deleteGlossaryById = async (token: string, id: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/glossary/${id}/delete`, {
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

export const copyGlossary = async (
	token: string,
	id: string,
	form: { name?: string; target_group_id?: string | null }
) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/glossary/${id}/copy`, {
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

export const countGlossaryValues = async (
	token: string,
	id: string,
	form: { dbsphere_id: string; table_name: string; column_name: string }
): Promise<{ distinct_count: number }> => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/glossary/${id}/count-values`, {
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

export type GlossaryEntryPreview = {
	id: string;
	term: string;
	synonyms: string[];
	description: string;
	example: string;
	category?: string;
	created_at: number;
	updated_at: number;
};

export type GlossaryExtractJob = {
	id: string;
	status: 'queued' | 'running' | 'succeeded' | 'failed' | 'canceled';
	phase: 'queued' | 'sql' | 'llm' | 'done';
	progress: { current: number; total: number };
	params: Record<string, unknown>;
	started_at: number | null;
	completed_at: number | null;
	queued_at?: number | null;
	error: string | null;
	result: {
		entries: GlossaryEntryPreview[];
		total_values: number;
		skipped: number;
	} | null;
};

export type GlossaryActiveJobSummary = {
	glossary_id: string;
	glossary_name: string;
	status: GlossaryExtractJob['status'];
	phase: GlossaryExtractJob['phase'];
	progress: { current: number; total: number };
	started_at: number | null;
	completed_at: number | null;
};

export const startGlossaryExtractJob = async (
	token: string,
	id: string,
	form: {
		dbsphere_id: string;
		table_name: string;
		column_name: string;
		synonym_column?: string;
		description_column?: string;
		context_columns?: string[];
		model_id?: string;
		generate_enrichment?: boolean;
		llm_fields?: string[];
		batch_size?: number;
		llm_concurrency?: number;
		category?: string;
		custom_instructions?: string;
	}
): Promise<{ job_id: string; status: string }> => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/glossary/${id}/extract-values`, {
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

export const getGlossaryExtractJob = async (
	token: string,
	id: string
): Promise<GlossaryExtractJob | null> => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/glossary/${id}/extract-job`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
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

export const listActiveGlossaryExtractJobs = async (
	token: string
): Promise<GlossaryActiveJobSummary[]> => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/glossary/extract-jobs/active`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (r) => {
			if (!r.ok) throw await r.json();
			return r.json();
		})
		.catch((err) => {
			error = extractErrorMessage(err);
			return [];
		});
	if (error) throw error;
	return res;
};

export const acceptGlossaryExtractEntry = async (
	token: string,
	id: string,
	entryId: string
) => {
	let error = null;
	const res = await fetch(
		`${WEBUI_API_BASE_URL}/glossary/${id}/extract-job/entries/${entryId}/accept`,
		{
			method: 'POST',
			headers: {
				Accept: 'application/json',
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

export const rejectGlossaryExtractEntry = async (
	token: string,
	id: string,
	entryId: string
) => {
	let error = null;
	const res = await fetch(
		`${WEBUI_API_BASE_URL}/glossary/${id}/extract-job/entries/${entryId}/reject`,
		{
			method: 'POST',
			headers: {
				Accept: 'application/json',
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

export const updateGlossaryExtractEntry = async (
	token: string,
	id: string,
	entryId: string,
	patch: Partial<Pick<GlossaryEntryPreview, 'term' | 'synonyms' | 'description' | 'example' | 'category'>>
) => {
	let error = null;
	const res = await fetch(
		`${WEBUI_API_BASE_URL}/glossary/${id}/extract-job/entries/${entryId}`,
		{
			method: 'PUT',
			headers: {
				Accept: 'application/json',
				'Content-Type': 'application/json',
				authorization: `Bearer ${token}`
			},
			body: JSON.stringify(patch)
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

export const acceptAllGlossaryExtractEntries = async (token: string, id: string) => {
	let error = null;
	const res = await fetch(
		`${WEBUI_API_BASE_URL}/glossary/${id}/extract-job/accept-all`,
		{
			method: 'POST',
			headers: {
				Accept: 'application/json',
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

export const discardGlossaryExtractJob = async (token: string, id: string) => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/glossary/${id}/extract-job/discard`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
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

export const cancelGlossaryExtractJob = async (token: string, id: string) => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/glossary/${id}/extract-job/cancel`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
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

/** @deprecated 동기 추출. 비동기 startGlossaryExtractJob 사용 권장. */
export const extractGlossaryValues = startGlossaryExtractJob;

export const syncGlossaryToSearchEngine = async (token: string, id: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/glossary/${id}/sync`, {
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
			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

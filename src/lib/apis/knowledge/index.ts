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

export const createNewKnowledge = async (
	token: string,
	name: string,
	description: string,
	accessControl: null | object
) => {
	let error: string | null = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/knowledge/create`, {
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

export const cloneKnowledgeById = async (token: string, id: string) => {
	// 일반 API 와 다르게 raw error object 를 throw 한다 — 핸들러가
	// ``err.detail.code === 'EMBEDDING_DIM_MISMATCH'`` structured payload
	// 를 직접 검사해야 하기 때문. extractErrorMessage 평탄화는 정보 손실.
	const res = await fetch(`${WEBUI_API_BASE_URL}/knowledge/${id}/clone`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({})
	});
	if (!res.ok) {
		const err = await res.json().catch(() => ({}));
		throw err;
	}
	return res.json();
};

export const getKnowledgeBases = async (token: string = '') => {
	let error: string | null = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/knowledge/`, {
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

export const getKnowledgeBaseList = async (token: string = '') => {
	let error: string | null = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/knowledge/list`, {
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

export const getKnowledgeFiles = async (
	token: string,
	id: string,
	params: {
		skip?: number;
		limit?: number;
		search?: string;
		sort?: 'newest' | 'oldest' | 'name';
	} = {}
) => {
	let error: string | null = null;

	const qs = new URLSearchParams();
	qs.set('skip', String(params.skip ?? 0));
	qs.set('limit', String(params.limit ?? 50));
	if (params.search) qs.set('search', params.search);
	qs.set('sort', params.sort ?? 'newest');

	const res = await fetch(`${WEBUI_API_BASE_URL}/knowledge/${id}/files?${qs.toString()}`, {
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

	return res as {
		files: any[];
		total: number;
		skip: number;
		limit: number;
	};
};

/** 페이지네이션 무관하게 KB 의 전체 파일 ID 를 한 번에 받는 경량 엔드포인트.
 *  전체 선택 / 배치 Extract 에서 사용. search 가 있으면 filename ilike 필터. */
export const getKnowledgeFileIds = async (
	token: string,
	id: string,
	params: { search?: string; status?: string } = {}
): Promise<{ ids: string[]; total: number }> => {
	let error: string | null = null;

	const qs = new URLSearchParams();
	if (params.search) qs.set('search', params.search);
	if (params.status) qs.set('status', params.status);
	const suffix = qs.toString() ? `?${qs.toString()}` : '';

	const res = await fetch(`${WEBUI_API_BASE_URL}/knowledge/${id}/file-ids${suffix}`, {
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
			console.log(err);
			return null;
		});

	if (error) throw error;
	return (res ?? { ids: [], total: 0 }) as { ids: string[]; total: number };
};

export const getKnowledgeById = async (
	token: string,
	id: string,
	includeFiles: boolean = true
) => {
	let error: string | null = null;

	const qs = includeFiles ? '' : '?include_files=false';
	const res = await fetch(`${WEBUI_API_BASE_URL}/knowledge/${id}${qs}`, {
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

type KnowledgeUpdateForm = {
	name?: string;
	description?: string;
	data?: object;
	meta?: object;
	access_control?: null | object;
};

export const updateKnowledgeById = async (token: string, id: string, form: KnowledgeUpdateForm) => {
	let error: string | null = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/knowledge/${id}/update`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({
			name: form?.name ?? undefined,
			description: form?.description ?? undefined,
			data: form?.data ?? undefined,
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

export type DuplicatePolicy = 'overwrite' | 'skip';

export const checkKnowledgeDuplicateFilenames = async (
	token: string,
	id: string,
	filenames: string[]
): Promise<string[]> => {
	let error: string | null = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/knowledge/${id}/files/check-duplicates`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({ filenames })
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err;
			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return (res?.duplicates ?? []) as string[];
};

export const addFileToKnowledgeById = async (
	token: string,
	id: string,
	fileId: string,
	options: { duplicatePolicy?: DuplicatePolicy; batchId?: string; clientSessionId?: string } = {}
) => {
	let error: string | null = null;

	const body: Record<string, unknown> = { file_id: fileId };
	if (options.duplicatePolicy) {
		body.duplicate_policy = options.duplicatePolicy;
	}
	// 배치 업로드 추적 — 백엔드가 file-processing 알림에 echo (벨 전용 진행률 + 발신 세션 식별)
	if (options.batchId) {
		body.batch_id = options.batchId;
	}
	if (options.clientSessionId) {
		body.client_session_id = options.clientSessionId;
	}

	const res = await fetch(`${WEBUI_API_BASE_URL}/knowledge/${id}/file/add`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify(body)
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

export const updateFileFromKnowledgeById = async (token: string, id: string, fileId: string) => {
	let error: string | null = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/knowledge/${id}/file/update`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({
			file_id: fileId
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

export const removeFileFromKnowledgeById = async (token: string, id: string, fileId: string) => {
	let error: string | null = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/knowledge/${id}/file/remove`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({
			file_id: fileId
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

/** 선택된 파일 목록을 백그라운드에서 일괄 삭제. 진행은 Socket.IO
 *  `file-delete-batch:progress` / `file-delete-batch:complete` 로 수신. */
export const batchRemoveFilesFromKnowledgeById = async (
	token: string,
	id: string,
	fileIds: string[]
): Promise<{ status: string; job_id: string; total: number }> => {
	let error: string | null = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/knowledge/${id}/files/batch/remove`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({ file_ids: fileIds })
	})
		.then(async (r) => {
			if (!r.ok) throw await r.json();
			return r.json();
		})
		.catch((err) => {
			error = extractErrorMessage(err);
			console.log(err);
			return null;
		});

	if (error) throw error;
	return res as { status: string; job_id: string; total: number };
};

/** 선택된 파일들의 filter slot (`f_str_*` / `f_int_*` / `f_date_*` / `f_col_*`) 만
 *  비운다. 파일 자체와 chunk / embedding 은 보존되므로 "문서 삭제" 와 명확히 분리된
 *  경량 액션. 인덱싱된 벡터의 slot 도 함께 None 으로 동기화된다. */
export const batchClearFilterMetadataByKnowledgeById = async (
	token: string,
	id: string,
	fileIds: string[]
): Promise<{ cleared: number; files: string[] }> => {
	let error: string | null = null;

	const res = await fetch(
		`${WEBUI_API_BASE_URL}/knowledge/${id}/filter-metadata/batch/clear`,
		{
			method: 'POST',
			headers: {
				Accept: 'application/json',
				'Content-Type': 'application/json',
				authorization: `Bearer ${token}`
			},
			body: JSON.stringify({ file_ids: fileIds })
		}
	)
		.then(async (r) => {
			if (!r.ok) throw await r.json();
			return r.json();
		})
		.catch((err) => {
			error = extractErrorMessage(err);
			console.log(err);
			return null;
		});

	if (error) throw error;
	return res as { cleared: number; files: string[] };
};

export const retryFileInKnowledgeById = async (token: string, id: string, fileId: string) => {
	let error: string | null = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/knowledge/${id}/file/retry`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({
			file_id: fileId
		})
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

// KB 내 처리 실패 파일을 일괄 재시도. file_ids 를 주면 그 중 실패한 것만, 없으면 전체.
// batch_id / client_session_id 는 알림에 echo 되어 조용한 배치로 추적된다.
export const retryFailedFilesInKnowledge = async (
	token: string,
	id: string,
	options: { fileIds?: string[]; batchId?: string; clientSessionId?: string } = {}
): Promise<{ batch_id: string | null; total: number; file_ids: string[] }> => {
	let error: string | null = null;

	const body: Record<string, unknown> = {};
	if (options.fileIds) body.file_ids = options.fileIds;
	if (options.batchId) body.batch_id = options.batchId;
	if (options.clientSessionId) body.client_session_id = options.clientSessionId;

	const res = await fetch(`${WEBUI_API_BASE_URL}/knowledge/${id}/files/retry-failed`, {
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

	if (error) {
		throw error;
	}

	return (res ?? { batch_id: null, total: 0, file_ids: [] }) as {
		batch_id: string | null;
		total: number;
		file_ids: string[];
	};
};

export const resetKnowledgeById = async (token: string, id: string) => {
	let error: string | null = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/knowledge/${id}/reset`, {
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

export const getLinkedAgentsByKnowledgeId = async (token: string, id: string) => {
	let error: string | null = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/knowledge/${id}/linked-agents`, {
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

export const deleteKnowledgeById = async (token: string, id: string) => {
	let error: string | null = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/knowledge/${id}/delete`, {
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

export const setFileMetadata = async (
	token: string,
	knowledgeId: string,
	fileId: string,
	metadata: object
) => {
	let error: string | null = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/knowledge/${knowledgeId}/file/metadata`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({
			file_id: fileId,
			metadata: metadata
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

export const extractFileMetadata = async (
	token: string,
	knowledgeId: string,
	fileId: string,
	modelId: string
): Promise<any & { missing_required?: string[] }> => {
	let error: string | null = null;

	const res = await fetch(
		`${WEBUI_API_BASE_URL}/knowledge/${knowledgeId}/file/extract-metadata`,
		{
			method: 'POST',
			headers: {
				Accept: 'application/json',
				'Content-Type': 'application/json',
				authorization: `Bearer ${token}`
			},
			body: JSON.stringify({
				file_id: fileId,
				model_id: modelId
			})
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

export const extractAllMetadata = async (
	token: string,
	knowledgeId: string,
	modelId: string,
	fileIds: string[] | null = null
) => {
	let error: string | null = null;

	const body: Record<string, unknown> = { model_id: modelId };
	if (fileIds !== null && fileIds.length > 0) {
		body.file_ids = fileIds;
	}

	const res = await fetch(
		`${WEBUI_API_BASE_URL}/knowledge/${knowledgeId}/extract-all-metadata`,
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

export const reindexKnowledgeFiles = async (token: string) => {
	let error: string | null = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/knowledge/reindex`, {
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

import { WEBUI_API_BASE_URL } from '$lib/constants';

export const getModels = async (token: string = '') => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/models/`, {
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
			error = err;
			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const getBaseModels = async (token: string = '') => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/models/base`, {
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
			error = err;
			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const createNewModel = async (token: string, model: object) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/models/create`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify(model)
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err.detail;
			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const getModelLinkedUsages = async (token: string, id: string) => {
	let error = null;

	const searchParams = new URLSearchParams();
	searchParams.append('id', id);

	const res = await fetch(
		`${WEBUI_API_BASE_URL}/models/model/linked-usages?${searchParams.toString()}`,
		{
			method: 'GET',
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
		.catch((err) => {
			error = err;
			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const getConnectionLinkedUsages = async (token: string, ids: string[]) => {
	let error = null;

	const searchParams = new URLSearchParams();
	searchParams.append('ids', ids.join(','));

	const res = await fetch(
		`${WEBUI_API_BASE_URL}/models/connection/linked-usages?${searchParams.toString()}`,
		{
			method: 'GET',
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
		.catch((err) => {
			error = err;
			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const getModelById = async (token: string, id: string) => {
	let error = null;

	const searchParams = new URLSearchParams();
	searchParams.append('id', id);

	const res = await fetch(`${WEBUI_API_BASE_URL}/models/model?${searchParams.toString()}`, {
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
			error = err;

			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const toggleModelById = async (token: string, id: string) => {
	let error = null;

	const searchParams = new URLSearchParams();
	searchParams.append('id', id);

	const res = await fetch(`${WEBUI_API_BASE_URL}/models/model/toggle?${searchParams.toString()}`, {
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
			error = err;

			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const updateModelById = async (token: string, id: string, model: object) => {
	let error = null;

	const searchParams = new URLSearchParams();
	searchParams.append('id', id);

	const res = await fetch(`${WEBUI_API_BASE_URL}/models/model/update?${searchParams.toString()}`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify(model)
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.then((json) => {
			return json;
		})
		.catch((err) => {
			error = err;

			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

// ===== Agent Version History (에이전트 버전관리) =====

export const getAgentVersions = async (token: string, id: string) => {
	let error = null;
	const searchParams = new URLSearchParams();
	searchParams.append('id', id);
	const res = await fetch(
		`${WEBUI_API_BASE_URL}/models/model/versions?${searchParams.toString()}`,
		{
			method: 'GET',
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
		.catch((err) => {
			error = err;
			console.log(err);
			return null;
		});
	if (error) throw error;
	return res;
};

export const getAgentVersion = async (token: string, id: string, version: number) => {
	let error = null;
	const searchParams = new URLSearchParams();
	searchParams.append('id', id);
	searchParams.append('version', `${version}`);
	const res = await fetch(
		`${WEBUI_API_BASE_URL}/models/model/version?${searchParams.toString()}`,
		{
			method: 'GET',
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
		.catch((err) => {
			error = err;
			console.log(err);
			return null;
		});
	if (error) throw error;
	return res;
};

export const restoreAgentVersion = async (token: string, id: string, version: number) => {
	let error = null;
	const searchParams = new URLSearchParams();
	searchParams.append('id', id);
	searchParams.append('version', `${version}`);
	const res = await fetch(
		`${WEBUI_API_BASE_URL}/models/model/version/restore?${searchParams.toString()}`,
		{
			method: 'POST',
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
		.catch((err) => {
			error = err;
			console.log(err);
			return null;
		});
	if (error) throw error;
	return res;
};

export const updateAgentVersionLabel = async (
	token: string,
	id: string,
	version: number,
	label: string | null
) => {
	let error = null;
	const searchParams = new URLSearchParams();
	searchParams.append('id', id);
	searchParams.append('version', `${version}`);
	const res = await fetch(
		`${WEBUI_API_BASE_URL}/models/model/version/label?${searchParams.toString()}`,
		{
			method: 'POST',
			headers: {
				Accept: 'application/json',
				'Content-Type': 'application/json',
				authorization: `Bearer ${token}`
			},
			body: JSON.stringify({ label })
		}
	)
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err;
			console.log(err);
			return null;
		});
	if (error) throw error;
	return res;
};

export const deleteModelById = async (token: string, id: string) => {
	let error = null;

	const searchParams = new URLSearchParams();
	searchParams.append('id', id);

	const res = await fetch(`${WEBUI_API_BASE_URL}/models/model/delete?${searchParams.toString()}`, {
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
			error = err.detail;

			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const deleteAllModels = async (token: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/models/delete/all`, {
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
			error = err;

			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export type OverrideEntry = {
	id: string;
	name: string;
	tokens: number;
	used_today?: number | null; // users tier 한정. groups/org_units 는 null/undefined
};

export type OverrideCounts = {
	users: number;
	groups: number;
	org_units: number;
};

export type ModelUsageCounts = {
	agents: number;
	flows: number;
	evaluations: number;
};

export type ModelUsageItem = {
	id: string;
	name: string;
	kind?: 'arena' | 'auto_eval_judge';
	direct?: boolean;
	via?: { id: string; name: string }[];
};

export type ModelUsageDetail = {
	agents: ModelUsageItem[];
	flows: ModelUsageItem[];
	evaluations: ModelUsageItem[];
};

export const getModelUsagesDetail = async (
	token: string,
	modelId: string
): Promise<ModelUsageDetail> => {
	let error = null;
	// WEBUI_API_BASE_URL은 production에서 '/api/v1' 상대경로 → new URL()이 TypeError 발생.
	// 다른 함수들과 동일하게 URLSearchParams + template string 패턴 사용.
	const searchParams = new URLSearchParams();
	searchParams.append('id', modelId);
	const res = await fetch(`${WEBUI_API_BASE_URL}/models/model/usages/detail?${searchParams.toString()}`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			console.log(err);
			error = err?.detail ?? err;
			return null;
		});
	if (error) throw error;
	return res ?? { agents: [], flows: [], evaluations: [] };
};

export const getModelsUsageCounts = async (
	token: string
): Promise<Record<string, ModelUsageCounts>> => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/models/usages/counts`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			console.log(err);
			error = err?.detail ?? err;
			return null;
		});
	if (error) throw error;
	return res ?? {};
};

export const getModelUsageLimitOverrideCounts = async (
	token: string,
	modelId: string
): Promise<OverrideCounts> => {
	let error = null;
	const searchParams = new URLSearchParams();
	searchParams.append('id', modelId);
	const res = await fetch(`${WEBUI_API_BASE_URL}/models/usage-limit/overrides/counts?${searchParams.toString()}`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			console.log(err);
			error = err.detail;
			return null;
		});
	if (error) throw error;
	return res;
};

export const listModelUsageLimitOverrides = async (
	token: string,
	modelId: string,
	tier: 'users' | 'groups' | 'org_units',
	q: string = '',
	skip: number = 0,
	limit: number = 50
): Promise<OverrideEntry[]> => {
	let error = null;
	const searchParams = new URLSearchParams();
	searchParams.append('id', modelId);
	searchParams.append('tier', tier);
	if (q) searchParams.append('q', q);
	searchParams.append('skip', String(skip));
	searchParams.append('limit', String(limit));
	const res = await fetch(`${WEBUI_API_BASE_URL}/models/usage-limit/overrides/list?${searchParams.toString()}`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			console.log(err);
			error = err.detail;
			return null;
		});
	if (error) throw error;
	return res;
};

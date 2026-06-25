// src/lib/apis/admin/memory.ts
import { WEBUI_API_BASE_URL } from '$lib/constants';

// Retention Policies
export const getRetentionPolicies = async (token: string) => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/admin/memory/retention-policies`, {
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
			error = err.detail;
			return null;
		});
	if (error) throw error;
	return res;
};

export const updateRetentionPolicy = async (token: string, id: string, ttlDays: number | null) => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/admin/memory/retention-policies/${id}`, {
		method: 'PUT',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({ ttl_days: ttlDays })
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err.detail;
			return null;
		});
	if (error) throw error;
	return res;
};

// Audit Logs
export const getMemoryAuditLogs = async (
	token: string,
	params: { event_type?: string; user_id?: string; page?: number; limit?: number } = {}
) => {
	let error = null;
	const query = new URLSearchParams();
	if (params.event_type) query.set('event_type', params.event_type);
	if (params.user_id) query.set('user_id', params.user_id);
	if (params.page) query.set('page', String(params.page));
	if (params.limit) query.set('limit', String(params.limit));

	const res = await fetch(`${WEBUI_API_BASE_URL}/admin/memory/audit-logs?${query}`, {
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
			error = err.detail;
			return null;
		});
	if (error) throw error;
	return res;
};

// Organization Memory
export const getOrgMemories = async (token: string) => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/admin/memory/org`, {
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
			error = err.detail;
			return null;
		});
	if (error) throw error;
	return res;
};

export const createOrgMemory = async (token: string, content: string) => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/admin/memory/org`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({ content })
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err.detail;
			return null;
		});
	if (error) throw error;
	return res;
};

export const deleteOrgMemory = async (token: string, id: string) => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/admin/memory/org/${id}`, {
		method: 'DELETE',
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
			error = err.detail;
			return null;
		});
	if (error) throw error;
	return res;
};

// Admin User Memory Management
export const getUserMemories = async (token: string, userId: string) => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/admin/memory/users/${userId}/memories`, {
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
			error = err.detail;
			return null;
		});
	if (error) throw error;
	return res;
};

export const deleteUserMemory = async (token: string, userId: string, memoryId: string) => {
	let error = null;
	const res = await fetch(
		`${WEBUI_API_BASE_URL}/admin/memory/users/${userId}/memories/${memoryId}`,
		{
			method: 'DELETE',
			headers: {
				Accept: 'application/json',
				authorization: `Bearer ${token}`
			}
		}
	)
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err.detail;
			return null;
		});
	if (error) throw error;
	return res;
};

// Entity Types
export const getEntityTypes = async (token: string) => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/admin/memory/entity-types`, {
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
			error = err.detail;
			return null;
		});
	if (error) throw error;
	return res;
};

export const addEntityType = async (token: string, name: string, description?: string) => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/admin/memory/entity-types`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({ name, description })
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err.detail;
			return null;
		});
	if (error) throw error;
	return res;
};

export const deleteEntityType = async (token: string, id: string) => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/admin/memory/entity-types/${id}`, {
		method: 'DELETE',
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
			error = err.detail;
			return null;
		});
	if (error) throw error;
	return res;
};

// Extraction Config
export const getMemoryExtractionConfig = async (token: string) => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/memories/config`, {
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
			error = err.detail;
			return null;
		});
	if (error) throw error;
	return res;
};

export const updateMemoryExtractionConfig = async (
	token: string,
	config: { MEMORY_EXTRACTION_MODEL?: string; MEMORY_EXTRACTION_CONFIDENCE?: number }
) => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/memories/config`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify(config)
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err.detail;
			return null;
		});
	if (error) throw error;
	return res;
};

// Entities (read-only)
export const getEntities = async (token: string) => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/admin/memory/entities`, {
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
			error = err.detail;
			return null;
		});
	if (error) throw error;
	return res;
};

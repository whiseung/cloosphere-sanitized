import { WEBUI_API_BASE_URL } from '$lib/constants';

// Types
export interface AuditLog {
	id: string;
	user_id: string | null;
	user_email: string | null;
	user_name: string | null;
	resource_type: string;
	resource_id: string | null;
	resource_name: string | null;
	action: string;
	before_state: Record<string, unknown> | null;
	after_state: Record<string, unknown> | null;
	changed_fields: string[] | null;
	access_control_changes: Record<string, unknown> | null;
	ip_address: string | null;
	user_agent: string | null;
	request_path: string | null;
	organization_id: string | null;
	meta: Record<string, unknown> | null;
	created_at: number;
}

export interface AuditLogListResponse {
	items: AuditLog[];
	total: number;
	page: number;
	limit: number;
	total_pages: number;
}

export interface AuditLogStats {
	by_action: Record<string, number>;
	by_resource_type: Record<string, number>;
	total: number;
}

export interface AuditLogQueryParams {
	page?: number;
	limit?: number;
	resource_type?: string;
	resource_id?: string;
	action?: string;
	user_id?: string;
	organization_id?: string;
	from_date?: number;
	to_date?: number;
}

export const getAuditLogs = async (
	token: string,
	params: AuditLogQueryParams = {}
): Promise<AuditLogListResponse> => {
	let error = null;

	const searchParams = new URLSearchParams();
	if (params.page) searchParams.append('page', `${params.page}`);
	if (params.limit) searchParams.append('limit', `${params.limit}`);
	if (params.resource_type) searchParams.append('resource_type', params.resource_type);
	if (params.resource_id) searchParams.append('resource_id', params.resource_id);
	if (params.action) searchParams.append('action', params.action);
	if (params.user_id) searchParams.append('user_id', params.user_id);
	if (params.organization_id) searchParams.append('organization_id', params.organization_id);
	if (params.from_date) searchParams.append('from_date', `${params.from_date}`);
	if (params.to_date) searchParams.append('to_date', `${params.to_date}`);

	const res = await fetch(`${WEBUI_API_BASE_URL}/audit-logs/?${searchParams.toString()}`, {
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
			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const getAuditLogById = async (token: string, id: string): Promise<AuditLog> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/audit-logs/${id}`, {
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
			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const getResourceAuditLogs = async (
	token: string,
	resourceType: string,
	resourceId: string,
	limit: number = 100
): Promise<AuditLog[]> => {
	let error = null;

	const res = await fetch(
		`${WEBUI_API_BASE_URL}/audit-logs/resources/${resourceType}/${resourceId}?limit=${limit}`,
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

export const getUserAuditLogs = async (
	token: string,
	userId: string,
	limit: number = 100
): Promise<AuditLog[]> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/audit-logs/users/${userId}?limit=${limit}`, {
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
			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const getAccessControlChanges = async (
	token: string,
	resourceType?: string,
	limit: number = 100
): Promise<AuditLog[]> => {
	let error = null;

	const searchParams = new URLSearchParams();
	if (resourceType) searchParams.append('resource_type', resourceType);
	searchParams.append('limit', `${limit}`);

	const res = await fetch(
		`${WEBUI_API_BASE_URL}/audit-logs/access-control-changes?${searchParams.toString()}`,
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

export const getAuthLogs = async (
	token: string,
	userId?: string,
	limit: number = 100
): Promise<AuditLog[]> => {
	let error = null;

	const searchParams = new URLSearchParams();
	if (userId) searchParams.append('target_user_id', userId);
	searchParams.append('limit', `${limit}`);

	const res = await fetch(`${WEBUI_API_BASE_URL}/audit-logs/auth?${searchParams.toString()}`, {
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
			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const getAuditLogStats = async (
	token: string,
	fromDate?: number,
	toDate?: number,
	resourceType?: string,
	action?: string,
	userId?: string
): Promise<AuditLogStats> => {
	let error = null;

	const searchParams = new URLSearchParams();
	if (fromDate) searchParams.append('from_date', `${fromDate}`);
	if (toDate) searchParams.append('to_date', `${toDate}`);
	if (resourceType) searchParams.append('resource_type', resourceType);
	if (action) searchParams.append('action', action);
	if (userId) searchParams.append('user_id', userId);

	const res = await fetch(`${WEBUI_API_BASE_URL}/audit-logs/stats?${searchParams.toString()}`, {
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
			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const getAvailableActions = async (token: string, resourceType?: string): Promise<string[]> => {
	let error = null;

	const searchParams = new URLSearchParams();
	if (resourceType) searchParams.append('resource_type', resourceType);
	const qs = searchParams.toString();

	const res = await fetch(`${WEBUI_API_BASE_URL}/audit-logs/actions${qs ? `?${qs}` : ''}`, {
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
			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const getAvailableResourceTypes = async (token: string, action?: string): Promise<string[]> => {
	let error = null;

	const searchParams = new URLSearchParams();
	if (action) searchParams.append('action', action);
	const qs = searchParams.toString();

	const res = await fetch(`${WEBUI_API_BASE_URL}/audit-logs/resource-types${qs ? `?${qs}` : ''}`, {
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
			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

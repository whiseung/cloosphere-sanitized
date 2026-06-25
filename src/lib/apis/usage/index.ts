import { WEBUI_API_BASE_URL } from '$lib/constants';

export interface UsageStats {
	total_tokens: number;
	total_requests: number;
	unique_users: number;
	unique_chats: number;
	unique_models: number;
	avg_tokens_per_request: number;
}

export interface UsageTrendItem {
	date: string;
	tokens: number;
	requests: number;
}

export interface UsageByModelItem {
	model_id: string;
	total_tokens: number;
	request_count: number;
}

export interface UsageByUserItem {
	user_id: string;
	user_name: string;
	user_email: string;
	total_tokens: number;
	request_count: number;
}

export interface UsageByGroupItem {
	group_id: string;
	group_name: string;
	total_tokens: number;
	request_count: number;
	user_count: number;
}

export interface UsageByOrganizationItem {
	organization_id: string;
	organization_name: string;
	total_tokens: number;
	request_count: number;
	user_count: number;
}

export interface UsageByTypeItem {
	message_type: string;
	total_tokens: number;
	request_count: number;
}

export interface UsageByAgentItem {
	agent_id: string;
	agent_name: string;
	total_tokens: number;
	request_count: number;
}

export interface FilterOption {
	id: string;
	name: string;
}

export interface OnlineUsers {
	count: number;
	user_ids: string[];
}

export interface UsageQueryParams {
	from_date?: number;
	to_date?: number;
	granularity?: 'day' | 'hour';
	limit?: number;
	model_id?: string;
	user_id?: string;
	group_id?: string;
	organization_id?: string;
	agent_id?: string;
}

const buildQueryString = (params: UsageQueryParams): string => {
	const searchParams = new URLSearchParams();
	if (params.from_date) searchParams.append('from_date', params.from_date.toString());
	if (params.to_date) searchParams.append('to_date', params.to_date.toString());
	if (params.granularity) searchParams.append('granularity', params.granularity);
	if (params.limit) searchParams.append('limit', params.limit.toString());
	if (params.model_id) searchParams.append('model_id', params.model_id);
	if (params.user_id) searchParams.append('user_id', params.user_id);
	if (params.group_id) searchParams.append('group_id', params.group_id);
	if (params.organization_id) searchParams.append('organization_id', params.organization_id);
	if (params.agent_id) searchParams.append('agent_id', params.agent_id);
	const query = searchParams.toString();
	return query ? `?${query}` : '';
};

// Filter Options APIs
export const getAvailableModels = async (token: string): Promise<FilterOption[]> => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/usage/filters/models`, {
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
			error = err;
			return null;
		});

	if (error) throw error;
	return res;
};

export const getAvailableUsers = async (token: string): Promise<FilterOption[]> => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/usage/filters/users`, {
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
			error = err;
			return null;
		});

	if (error) throw error;
	return res;
};

export const getAvailableGroups = async (token: string): Promise<FilterOption[]> => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/usage/filters/groups`, {
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
			error = err;
			return null;
		});

	if (error) throw error;
	return res;
};

export const getAvailableOrganizations = async (token: string): Promise<FilterOption[]> => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/usage/filters/organizations`, {
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
			error = err;
			return null;
		});

	if (error) throw error;
	return res;
};

export const getAvailableAgents = async (token: string): Promise<FilterOption[]> => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/usage/filters/agents`, {
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
			error = err;
			return null;
		});

	if (error) throw error;
	return res;
};

// Real-time APIs
export const getOnlineUsers = async (token: string): Promise<OnlineUsers> => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/usage/online-users`, {
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
			error = err;
			return null;
		});

	if (error) throw error;
	return res;
};

// Statistics APIs
export const getUsageStats = async (
	token: string,
	params: UsageQueryParams = {}
): Promise<UsageStats> => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/usage/stats${buildQueryString(params)}`, {
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
			error = err;
			return null;
		});

	if (error) throw error;
	return res;
};

export const getUsageTrends = async (
	token: string,
	params: UsageQueryParams = {}
): Promise<UsageTrendItem[]> => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/usage/trends${buildQueryString(params)}`, {
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
			error = err;
			return null;
		});

	if (error) throw error;
	return res;
};

export const getUsageByModel = async (
	token: string,
	params: UsageQueryParams = {}
): Promise<UsageByModelItem[]> => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/usage/by-model${buildQueryString(params)}`, {
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
			error = err;
			return null;
		});

	if (error) throw error;
	return res;
};

export const getUsageByUser = async (
	token: string,
	params: UsageQueryParams = {}
): Promise<UsageByUserItem[]> => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/usage/by-user${buildQueryString(params)}`, {
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
			error = err;
			return null;
		});

	if (error) throw error;
	return res;
};

export const getUsageByGroup = async (
	token: string,
	params: UsageQueryParams = {}
): Promise<UsageByGroupItem[]> => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/usage/by-group${buildQueryString(params)}`, {
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
			error = err;
			return null;
		});

	if (error) throw error;
	return res;
};

export const getUsageByOrganization = async (
	token: string,
	params: UsageQueryParams = {}
): Promise<UsageByOrganizationItem[]> => {
	let error = null;
	const res = await fetch(
		`${WEBUI_API_BASE_URL}/usage/by-organization${buildQueryString(params)}`,
		{
			method: 'GET',
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
			error = err;
			return null;
		});

	if (error) throw error;
	return res;
};

export const getUsageByType = async (
	token: string,
	params: UsageQueryParams = {}
): Promise<UsageByTypeItem[]> => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/usage/by-type${buildQueryString(params)}`, {
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
			error = err;
			return null;
		});

	if (error) throw error;
	return res;
};

export const getUsageByAgent = async (
	token: string,
	params: UsageQueryParams = {}
): Promise<UsageByAgentItem[]> => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/usage/by-agent${buildQueryString(params)}`, {
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
			error = err;
			return null;
		});

	if (error) throw error;
	return res;
};

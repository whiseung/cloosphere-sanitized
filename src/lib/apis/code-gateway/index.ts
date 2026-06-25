import { WEBUI_API_BASE_URL } from '$lib/constants';

export type CodeGatewayProviderConfig = {
	enable: boolean;
	type: string;
	preset?: string;
	name: string;
	api_url: string;
	api_key: string;
	api_version?: string;
	model_ids?: string[];
	deployment_map?: Record<string, string>;
	project_id?: string;
	location?: string;
	service_account_key?: string;
	use_global_gcp_key?: boolean;
};

export type CodeGatewayConfig = {
	enable: boolean;
	providers: Record<string, CodeGatewayProviderConfig>;
	guardrail_ids: string[];
	rate_limit: number;
	allowed_models: string[];
	blocked_file_patterns: string[];
	blocked_file_action: 'block' | 'warn';
	blocked_repos: string[];
	require_repo_metadata: boolean;
};

export const getCodeGatewayConfig = async (token: string): Promise<CodeGatewayConfig> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/code-gateway/config`, {
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

	if (error) throw error;
	return res;
};

// Usage log types
export type CodeGatewayUsageLog = {
	id: string;
	user_id: string;
	user_name: string;
	user_email: string;
	model_id: string;
	provider: string;
	total_tokens: number;
	input_tokens: number;
	output_tokens: number;
	input_preview: string;
	output_preview: string;
	message_count: number | null;
	tools_count: number | null;
	tool_calls: { name: string; call_id?: string; arguments?: string }[];
	token_details: Record<string, unknown>;
	finish_reason: string;
	client_type: string;
	created_at: number;
};

export type CodeGatewayUsageLogListResponse = {
	items: CodeGatewayUsageLog[];
	total: number;
	page: number;
	limit: number;
	total_pages: number;
};

export type CodeGatewayUsageStats = {
	total_requests: number;
	total_tokens: number;
	unique_users: number;
	unique_models: number;
};

export const setCodeGatewayConfig = async (
	token: string,
	config: CodeGatewayConfig
): Promise<CodeGatewayConfig> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/code-gateway/config`, {
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
			error = err;
			return null;
		});

	if (error) throw error;
	return res;
};

// Usage log APIs

export const getCodeGatewayUsageLogs = async (
	token: string,
	params: {
		page?: number;
		limit?: number;
		user_id?: string;
		model_id?: string;
		from_date?: number;
		to_date?: number;
	} = {}
): Promise<CodeGatewayUsageLogListResponse> => {
	let error = null;

	const searchParams = new URLSearchParams();
	if (params.page) searchParams.set('page', String(params.page));
	if (params.limit) searchParams.set('limit', String(params.limit));
	if (params.user_id) searchParams.set('user_id', params.user_id);
	if (params.model_id) searchParams.set('model_id', params.model_id);
	if (params.from_date) searchParams.set('from_date', String(params.from_date));
	if (params.to_date) searchParams.set('to_date', String(params.to_date));

	const qs = searchParams.toString();
	const res = await fetch(`${WEBUI_API_BASE_URL}/code-gateway/usage-logs${qs ? '?' + qs : ''}`, {
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

	if (error) throw error;
	return res;
};

export const getCodeGatewayUsageStats = async (
	token: string,
	params: { from_date?: number; to_date?: number } = {}
): Promise<CodeGatewayUsageStats> => {
	let error = null;

	const searchParams = new URLSearchParams();
	if (params.from_date) searchParams.set('from_date', String(params.from_date));
	if (params.to_date) searchParams.set('to_date', String(params.to_date));

	const qs = searchParams.toString();
	const res = await fetch(
		`${WEBUI_API_BASE_URL}/code-gateway/usage-logs/stats${qs ? '?' + qs : ''}`,
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
			return null;
		});

	if (error) throw error;
	return res;
};

export const getCodeGatewayFilterModels = async (
	token: string
): Promise<{ id: string; name: string }[]> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/code-gateway/usage-logs/filters/models`, {
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

	if (error) throw error;
	return res;
};

export const getCodeGatewayFilterUsers = async (
	token: string
): Promise<{ id: string; name: string }[]> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/code-gateway/usage-logs/filters/users`, {
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

	if (error) throw error;
	return res;
};

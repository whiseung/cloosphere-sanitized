import { WEBUI_API_BASE_URL } from '$lib/constants';

export type UsageBreakdownItem = {
	model_id: string;
	total_tokens: number;
	input_tokens: number;
	output_tokens: number;
};

export type ToolCallItem = {
	name: string;
	call_id?: string;
	arguments?: string;
};

export type ConversationLog = {
	id: string;
	user_id: string;
	user_name: string;
	user_email: string;
	model_id: string;
	agent_id: string;
	agent_name: string;
	source_type: string;
	chat_id: string;
	embed_widget_id: string;
	embed_widget_name: string;
	message_id: string;
	total_tokens: number;
	input_tokens: number;
	output_tokens: number;
	input_preview: string;
	output_preview: string;
	message_count: number | null;
	finish_reason: string;
	usage_breakdown: UsageBreakdownItem[];
	tool_calls: ToolCallItem[];
	token_details: Record<string, unknown>;
	client_type: string;
	created_at: number;
};

export type ConversationLogListResponse = {
	items: ConversationLog[];
	total: number;
	page: number;
	limit: number;
	total_pages: number;
};

export type ConversationLogStats = {
	total_requests: number;
	total_tokens: number;
	unique_users: number;
	unique_models: number;
};

export const getConversationLogs = async (
	token: string,
	params: {
		page?: number;
		limit?: number;
		user_id?: string;
		user_search?: string;
		model_id?: string; // 콤마 구분 다중 값 지원
		source_type?: string; // 콤마 구분 다중 값 지원
		from_date?: number;
		to_date?: number;
	} = {}
): Promise<ConversationLogListResponse> => {
	let error = null;

	const searchParams = new URLSearchParams();
	if (params.page) searchParams.set('page', String(params.page));
	if (params.limit) searchParams.set('limit', String(params.limit));
	if (params.user_id) searchParams.set('user_id', params.user_id);
	if (params.user_search) searchParams.set('user_search', params.user_search);
	if (params.model_id) searchParams.set('model_id', params.model_id);
	if (params.source_type) searchParams.set('source_type', params.source_type);
	if (params.from_date) searchParams.set('from_date', String(params.from_date));
	if (params.to_date) searchParams.set('to_date', String(params.to_date));

	const qs = searchParams.toString();
	const res = await fetch(`${WEBUI_API_BASE_URL}/usage/conversation-logs${qs ? '?' + qs : ''}`, {
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

export const getConversationLogStats = async (
	token: string,
	params: { from_date?: number; to_date?: number; source_type?: string } = {}
): Promise<ConversationLogStats> => {
	let error = null;

	const searchParams = new URLSearchParams();
	if (params.from_date) searchParams.set('from_date', String(params.from_date));
	if (params.to_date) searchParams.set('to_date', String(params.to_date));
	if (params.source_type) searchParams.set('source_type', params.source_type);

	const qs = searchParams.toString();
	const res = await fetch(
		`${WEBUI_API_BASE_URL}/usage/conversation-logs/stats${qs ? '?' + qs : ''}`,
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

export const getConversationLogFilterModels = async (
	token: string,
	params: { source_type?: string } = {}
): Promise<{ id: string; name: string }[]> => {
	let error = null;

	const searchParams = new URLSearchParams();
	if (params.source_type) searchParams.set('source_type', params.source_type);

	const qs = searchParams.toString();
	const res = await fetch(
		`${WEBUI_API_BASE_URL}/usage/conversation-logs/filters/models${qs ? '?' + qs : ''}`,
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

export const getConversationLogFilterUsers = async (
	token: string,
	params: { source_type?: string } = {}
): Promise<{ id: string; name: string }[]> => {
	let error = null;

	const searchParams = new URLSearchParams();
	if (params.source_type) searchParams.set('source_type', params.source_type);

	const qs = searchParams.toString();
	const res = await fetch(
		`${WEBUI_API_BASE_URL}/usage/conversation-logs/filters/users${qs ? '?' + qs : ''}`,
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

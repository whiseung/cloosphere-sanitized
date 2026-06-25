import { WEBUI_API_BASE_URL } from '$lib/constants';

export interface TraceRun {
	id: string;
	trace_id: string;
	parent_run_id: string | null;
	dotted_order: string;
	chat_id: string | null;
	message_id: string | null;
	user_id: string;
	run_type: string;
	name: string;
	status: string;
	inputs: Record<string, any> | null;
	outputs: Record<string, any> | null;
	error: string | null;
	start_time: number;
	end_time: number | null;
	latency_ms: number | null;
	token_usage: {
		prompt_tokens?: number;
		completion_tokens?: number;
		total_tokens?: number;
	} | null;
	model_id: string | null;
	meta: Record<string, any> | null;
	created_at: number;
	updated_at: number;
	children?: TraceRun[];
}

export interface TraceTree {
	trace_id: string;
	chat_id: string | null;
	message_id: string | null;
	user_id: string;
	total_latency_ms: number | null;
	total_tokens: number | null;
	status: string;
	runs: TraceRun[];
}

export interface TraceListResponse {
	traces: TraceRun[];
	total: number;
	page: number;
	limit: number;
	total_pages: number;
}

export interface TraceStats {
	by_type: Record<string, number>;
	by_status: Record<string, number>;
	avg_latency_ms: number | null;
	total_tokens: number;
	total: number;
}

export interface TraceQueryParams {
	page?: number;
	limit?: number;
	chat_id?: string;
	message_id?: string;
	user_id?: string;
	run_type?: string;
	status?: string;
	from_date?: number;
	to_date?: number;
}

/**
 * Get trace tree by trace ID
 */
export const getTraceById = async (token: string, traceId: string): Promise<TraceTree | null> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/traces/${traceId}`, {
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
			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

/**
 * Get trace tree by chat and message ID
 */
export const getTraceByMessage = async (
	token: string,
	chatId: string,
	messageId: string
): Promise<TraceTree | null> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/traces/chat/${chatId}/message/${messageId}`, {
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
			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

/**
 * Get traces by chat ID
 */
export const getTracesByChat = async (
	token: string,
	chatId: string,
	limit: number = 100
): Promise<TraceRun[]> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/traces/chat/${chatId}?limit=${limit}`, {
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
			console.log(err);
			return [];
		});

	if (error) {
		throw error;
	}

	return res;
};

/**
 * Get all traces with pagination
 */
export const getTraces = async (
	token: string,
	params: TraceQueryParams = {}
): Promise<TraceListResponse> => {
	let error = null;

	const queryParams = new URLSearchParams();
	if (params.page) queryParams.set('page', params.page.toString());
	if (params.limit) queryParams.set('limit', params.limit.toString());
	if (params.chat_id) queryParams.set('chat_id', params.chat_id);
	if (params.message_id) queryParams.set('message_id', params.message_id);
	if (params.user_id) queryParams.set('user_id', params.user_id);
	if (params.run_type) queryParams.set('run_type', params.run_type);
	if (params.status) queryParams.set('status', params.status);
	if (params.from_date) queryParams.set('from_date', params.from_date.toString());
	if (params.to_date) queryParams.set('to_date', params.to_date.toString());

	const res = await fetch(`${WEBUI_API_BASE_URL}/traces/?${queryParams.toString()}`, {
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
			console.log(err);
			return { traces: [], total: 0, page: 1, limit: 50, total_pages: 0 };
		});

	if (error) {
		throw error;
	}

	return res;
};

/**
 * Get trace statistics
 */
export const getTraceStats = async (
	token: string,
	params: { from_date?: number; to_date?: number; user_id?: string } = {}
): Promise<TraceStats> => {
	let error = null;

	const queryParams = new URLSearchParams();
	if (params.from_date) queryParams.set('from_date', params.from_date.toString());
	if (params.to_date) queryParams.set('to_date', params.to_date.toString());
	if (params.user_id) queryParams.set('user_id', params.user_id);

	const res = await fetch(`${WEBUI_API_BASE_URL}/traces/stats/summary?${queryParams.toString()}`, {
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
			console.log(err);
			return { by_type: {}, by_status: {}, avg_latency_ms: null, total_tokens: 0, total: 0 };
		});

	if (error) {
		throw error;
	}

	return res;
};

/**
 * Cleanup old traces (admin only)
 */
export const cleanupTraces = async (
	token: string,
	beforeTimestampMs: number
): Promise<{ deleted_count: number; message: string }> => {
	let error = null;

	const res = await fetch(
		`${WEBUI_API_BASE_URL}/traces/cleanup?before_timestamp_ms=${beforeTimestampMs}`,
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
		.catch((err) => {
			error = err.detail;
			console.log(err);
			return { deleted_count: 0, message: '' };
		});

	if (error) {
		throw error;
	}

	return res;
};

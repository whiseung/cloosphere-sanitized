import { WEBUI_API_BASE_URL } from '$lib/constants';

// Types
export interface GuardrailLog {
	id: string;
	user_id: string | null;
	user_email: string | null;
	user_name: string | null;
	chat_id: string | null;
	message_id: string | null;
	guardrail_id: string | null;
	guardrail_name: string | null;
	action: string;
	detection_source: string;
	detection_detail: string | null;
	original_content: string | null;
	processed_content: string | null;
	meta: Record<string, unknown> | null;
	created_at: number;
}

export interface GuardrailLogListResponse {
	items: GuardrailLog[];
	total: number;
	page: number;
	limit: number;
	total_pages: number;
}

export interface GuardrailLogQueryParams {
	page?: number;
	limit?: number;
	action?: string;
	detection_source?: string;
	user_search?: string;
	chat_id?: string;
	source?: string;
	from_date?: number;
	to_date?: number;
}

export const getGuardrailLogs = async (
	token: string,
	params: GuardrailLogQueryParams = {}
): Promise<GuardrailLogListResponse> => {
	let error = null;

	const searchParams = new URLSearchParams();
	if (params.page) searchParams.append('page', `${params.page}`);
	if (params.limit) searchParams.append('limit', `${params.limit}`);
	if (params.action) searchParams.append('action', params.action);
	if (params.detection_source) searchParams.append('detection_source', params.detection_source);
	if (params.user_search) searchParams.append('user_search', params.user_search);
	if (params.chat_id) searchParams.append('chat_id', params.chat_id);
	if (params.source) searchParams.append('source', params.source);
	if (params.from_date) searchParams.append('from_date', `${params.from_date}`);
	if (params.to_date) searchParams.append('to_date', `${params.to_date}`);

	const res = await fetch(
		`${WEBUI_API_BASE_URL}/guardrail-logs/?${searchParams.toString()}`,
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

export const getGuardrailLogById = async (token: string, id: string): Promise<GuardrailLog> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/guardrail-logs/${id}`, {
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

export const getAvailableActions = async (
	token: string,
	params?: { detection_source?: string; source?: string; user_search?: string }
): Promise<string[]> => {
	let error = null;

	const searchParams = new URLSearchParams();
	if (params?.detection_source) searchParams.append('detection_source', params.detection_source);
	if (params?.source) searchParams.append('source', params.source);
	if (params?.user_search) searchParams.append('user_search', params.user_search);
	const qs = searchParams.toString();

	const res = await fetch(`${WEBUI_API_BASE_URL}/guardrail-logs/actions${qs ? `?${qs}` : ''}`, {
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

export const getAvailableDetectionSources = async (token: string): Promise<string[]> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/guardrail-logs/detection-sources`, {
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

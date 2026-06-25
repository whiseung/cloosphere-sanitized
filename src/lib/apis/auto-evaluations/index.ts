import { WEBUI_API_BASE_URL } from '$lib/constants';

export type AutoEvaluationForm = {
	chat_id: string;
	message_id: string;
	model_id: string;
	judge_model_id: string;
	evaluation_type: string;
	user_query?: string;
	assistant_response?: string;
	retrieved_contexts?: object[];
};

export type AutoEvaluation = {
	id: string;
	chat_id: string;
	message_id: string;
	user_id: string;
	model_id: string;
	judge_model_id: string;
	evaluation_type: string;
	user_query?: string;
	assistant_response?: string;
	retrieved_contexts?: object[];
	score?: number;
	reasoning?: string;
	details?: object;
	status: string;
	error_message?: string;
	created_at: number;
	completed_at?: number;
	user?: {
		id: string;
		name: string;
		email: string;
		role: string;
	};
};

export type AutoEvaluationListResponse = {
	items: AutoEvaluation[];
	total: number;
	page: number;
	limit: number;
};

export type AutoEvaluationStats = {
	total_count: number;
	completed_count: number;
	pending_count: number;
	failed_count: number;
	avg_score?: number;
	by_model: Record<string, { count: number; avg_score?: number }>;
	by_type: Record<string, { count: number; avg_score?: number }>;
};

export type AutoEvaluationFilter = {
	model_id?: string;
	evaluation_type?: string;
	status?: string;
	score_min?: number;
	score_max?: number;
	date_from?: number;
	date_to?: number;
	page?: number;
	limit?: number;
	sort_by?: string;
	order?: string;
};

export const getAutoEvaluations = async (
	token: string,
	filters: AutoEvaluationFilter = {}
): Promise<AutoEvaluationListResponse> => {
	let error = null;

	const params = new URLSearchParams();
	if (filters.model_id) params.append('model_id', filters.model_id);
	if (filters.evaluation_type) params.append('evaluation_type', filters.evaluation_type);
	if (filters.status) params.append('status', filters.status);
	if (filters.score_min !== undefined) params.append('score_min', filters.score_min.toString());
	if (filters.score_max !== undefined) params.append('score_max', filters.score_max.toString());
	if (filters.date_from) params.append('date_from', filters.date_from.toString());
	if (filters.date_to) params.append('date_to', filters.date_to.toString());
	if (filters.page) params.append('page', filters.page.toString());
	if (filters.limit) params.append('limit', filters.limit.toString());
	if (filters.sort_by) params.append('sort_by', filters.sort_by);
	if (filters.order) params.append('order', filters.order);

	const queryString = params.toString() ? `?${params.toString()}` : '';

	const res = await fetch(`${WEBUI_API_BASE_URL}/auto-evaluations/${queryString}`, {
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

export const getAutoEvaluationById = async (
	token: string,
	id: string
): Promise<AutoEvaluation | null> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/auto-evaluations/${id}`, {
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

export const getAutoEvaluationStats = async (token: string): Promise<AutoEvaluationStats> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/auto-evaluations/stats`, {
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

export const createAutoEvaluation = async (
	token: string,
	form: AutoEvaluationForm
): Promise<AutoEvaluation> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/auto-evaluations/`, {
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
			error = err.detail;
			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const deleteAutoEvaluation = async (token: string, id: string): Promise<boolean> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/auto-evaluations/${id}`, {
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
		.catch((err) => {
			error = err.detail;
			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res?.success ?? false;
};

export const exportAutoEvaluations = async (
	token: string,
	format: 'json' | 'csv' = 'json'
): Promise<any> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/auto-evaluations/export?format=${format}`, {
		method: 'GET',
		headers: {
			Accept: format === 'csv' ? 'text/csv' : 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			if (format === 'csv') {
				return res.text();
			}
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

export const getAutoEvaluationsByChat = async (
	token: string,
	chatId: string
): Promise<AutoEvaluation[]> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/auto-evaluations/chat/${chatId}`, {
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

	return res ?? [];
};

export const getAutoEvaluationsByMessage = async (
	token: string,
	messageId: string
): Promise<AutoEvaluation[]> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/auto-evaluations/message/${messageId}`, {
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

	return res ?? [];
};

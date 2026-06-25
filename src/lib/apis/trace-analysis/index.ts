import { WEBUI_API_BASE_URL } from '$lib/constants';

export interface TraceAnalysisResponse {
	id: string;
	trace_id: string;
	chat_id: string | null;
	message_id: string | null;
	user_id: string;
	model_id: string;
	user_description: string | null;
	status: 'pending' | 'running' | 'completed' | 'failed';
	error_message: string | null;
	report: string | null;
	file_path: string | null;
	context_summary: {
		agent_name?: string;
		model_id?: string;
		run_count: number;
		error_count: number;
		has_knowledge: boolean;
		has_dbsphere: boolean;
		has_guardrails: boolean;
		has_glossary: boolean;
		analysis_model: string;
	} | null;
	created_at: number;
	completed_at: number | null;
}

export interface TraceAnalysisCreateForm {
	trace_id: string;
	model_id: string;
	user_description: string;
}

/**
 * Start trace analysis
 */
export const createTraceAnalysis = async (
	token: string,
	form: TraceAnalysisCreateForm
): Promise<TraceAnalysisResponse> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/trace-analysis/analyze`, {
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

/**
 * Get analysis status/result by ID (for polling)
 */
export const getTraceAnalysis = async (
	token: string,
	analysisId: string
): Promise<TraceAnalysisResponse | null> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/trace-analysis/${analysisId}`, {
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
 * Get all analyses for a specific trace
 */
export const getAnalysesByTrace = async (
	token: string,
	traceId: string
): Promise<TraceAnalysisResponse[]> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/trace-analysis/by-trace/${traceId}`, {
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

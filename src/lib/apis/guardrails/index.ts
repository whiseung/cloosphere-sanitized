import { WEBUI_API_BASE_URL } from '$lib/constants';

export type GuardrailForm = {
	name: string;
	description?: string;
	pii_types: string[];
	pii_strategy: string;
	custom_patterns: { name: string; pattern: string }[];
	blocked_words: string[];
	apply_to_input: boolean;
	apply_to_output: boolean;
	llm_judge_enabled: boolean;
	llm_judge_model?: string;
	llm_judge_prompt?: string;
	llm_judge_pass_examples: string[];
	llm_judge_block_examples: string[];
	llm_judge_apply_to_input: boolean;
	llm_judge_apply_to_output: boolean;
	access_control?: object | null;
};

export type Guardrail = GuardrailForm & {
	id: string;
	user_id: string;
	created_at: number;
	updated_at: number;
	user?: {
		id: string;
		name: string;
		email: string;
	};
};

export type GuardrailTestResponse = {
	processed_text: string;
	violations: Array<{
		type: string;
		pii_type?: string;
		pattern_name?: string;
		word?: string;
		matched: string;
		start: number;
		end: number;
	}>;
	blocked: boolean;
	message?: string;
};

export const getGuardrails = async (token: string = ''): Promise<Guardrail[]> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/guardrails/`, {
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

export const getGuardrailList = async (token: string = ''): Promise<Guardrail[]> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/guardrails/list`, {
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

export const getGuardrailById = async (token: string, id: string): Promise<Guardrail> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/guardrails/${id}`, {
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

export const createGuardrail = async (token: string, form: GuardrailForm): Promise<Guardrail> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/guardrails/create`, {
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

export const updateGuardrail = async (
	token: string,
	id: string,
	form: GuardrailForm
): Promise<Guardrail> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/guardrails/${id}/update`, {
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

export const getLinkedAgentsByGuardrailId = async (token: string, id: string) => {
	let error: string | null = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/guardrails/${id}/linked-agents`, {
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

	if (error) {
		throw error;
	}

	return res;
};

export const deleteGuardrailById = async (token: string, id: string): Promise<boolean> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/guardrails/${id}/delete`, {
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

	return res;
};

export const testGuardrail = async (
	token: string,
	guardrailId: string | null,
	config: GuardrailForm | null,
	text: string
): Promise<GuardrailTestResponse> => {
	let error = null;

	const body: { guardrail_id?: string; config?: GuardrailForm; text: string } = { text };
	if (guardrailId) {
		body.guardrail_id = guardrailId;
	}
	if (config) {
		body.config = config;
	}

	const res = await fetch(`${WEBUI_API_BASE_URL}/guardrails/test`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify(body)
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

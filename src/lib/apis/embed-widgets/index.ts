import { WEBUI_API_BASE_URL } from '$lib/constants';

const extractErrorMessage = (err: unknown): string => {
	if (typeof err === 'string') return err;
	if (err && typeof err === 'object') {
		const e = err as { detail?: unknown; message?: string };
		if (e.detail) {
			if (Array.isArray(e.detail)) {
				return e.detail.map((d: { msg?: string }) => d.msg || JSON.stringify(d)).join(', ');
			}
			if (typeof e.detail === 'string') return e.detail;
			return JSON.stringify(e.detail);
		}
		if (e.message) return e.message;
	}
	return JSON.stringify(err);
};

export type EmbedWidgetForm = {
	name: string;
	description?: string;
	model_id: string;
	system_prompt?: string;
	config?: Record<string, unknown>;
	is_active?: boolean;
	access_control?: Record<string, unknown>;
};

export type EmbedWidget = EmbedWidgetForm & {
	id: string;
	user_id: string;
	created_at: number;
	updated_at: number;
	user?: { name: string; email: string; profile_image_url: string };
};

export type EmbedAgentSummary = {
	id: string;
	name: string;
	profile_image_url: string;
};

export type EmbedWidgetConfig = {
	id: string;
	name: string;
	model_id: string;
	agents: EmbedAgentSummary[];
	config: Record<string, unknown> | null;
	is_active: boolean;
};

export const getEmbedWidgets = async (token: string) => {
	let error: string | null = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/embed-widgets/`, {
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
			error = extractErrorMessage(err);
			console.log(err);
			return null;
		});

	if (error) throw error;
	return res;
};

export const createEmbedWidget = async (token: string, data: EmbedWidgetForm) => {
	let error: string | null = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/embed-widgets/create`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify(data)
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = extractErrorMessage(err);
			console.log(err);
			return null;
		});

	if (error) throw error;
	return res;
};

export const getEmbedWidgetById = async (token: string, id: string) => {
	let error: string | null = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/embed-widgets/id/${id}`, {
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
			error = extractErrorMessage(err);
			console.log(err);
			return null;
		});

	if (error) throw error;
	return res;
};

export const updateEmbedWidgetById = async (token: string, id: string, data: EmbedWidgetForm) => {
	let error: string | null = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/embed-widgets/id/${id}/update`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify(data)
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = extractErrorMessage(err);
			console.log(err);
			return null;
		});

	if (error) throw error;
	return res;
};

export const deleteEmbedWidgetById = async (token: string, id: string) => {
	let error: string | null = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/embed-widgets/id/${id}/delete`, {
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
			error = extractErrorMessage(err);
			console.log(err);
			return null;
		});

	if (error) throw error;
	return res;
};

export type GuestExchangeRequest = {
	guest_id?: string;
	name?: string;
	email?: string;
	origin_url?: string;
	referrer?: string;
	user_context?: Record<string, unknown>;
};

export type GuestExchangeResponse = {
	token: string;
	user: {
		id: string;
		email: string;
		name: string;
		role: string;
		profile_image_url: string;
	};
};

export const requestGuestToken = async (
	baseUrl: string,
	widgetId: string,
	data: GuestExchangeRequest
): Promise<GuestExchangeResponse> => {
	let error: string | null = null;

	const res = await fetch(`${baseUrl}/api/embed/v1/id/${widgetId}/auth/guest`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json'
		},
		body: JSON.stringify(data)
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = extractErrorMessage(err);
			return null;
		});

	if (error) throw error;
	return res as GuestExchangeResponse;
};

export const getEmbedWidgetConfig = async (baseUrl: string, id: string) => {
	let error: string | null = null;

	const res = await fetch(`${baseUrl}/api/embed/v1/id/${id}/config`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json'
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = extractErrorMessage(err);
			console.log(err);
			return null;
		});

	if (error) throw error;
	return res as EmbedWidgetConfig;
};

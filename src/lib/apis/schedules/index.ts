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

export type ScheduleForm = {
	name: string;
	description?: string;
	target_type: string;
	target_model_id: string;
	prompt: string;
	cron_expression: string;
	timezone: string;
	delivery?: Record<string, unknown>;
	start_at?: number | null;
	end_at?: number | null;
	meta?: Record<string, unknown>;
	access_control?: Record<string, unknown> | null;
};

export type Schedule = ScheduleForm & {
	id: string;
	user_id: string;
	is_active: boolean;
	next_run_at?: number;
	chat_id?: string;
	created_at: number;
	updated_at: number;
	user?: { id: string; name: string; email: string; profile_image_url: string };
};

export type ScheduleTask = {
	id: string;
	schedule_id: string;
	user_id: string;
	status: string;
	worker_id?: string;
	prompt: string;
	result?: Record<string, unknown>;
	error_message?: string;
	chat_id?: string;
	scheduled_at: number;
	started_at?: number;
	completed_at?: number;
	retry_count: number;
	max_retries: number;
	triggered_by_user_id?: string | null;
	schedule_name?: string;
};

export const getSchedules = async (token: string) => {
	let error: string | null = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/schedules/`, {
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

export const createSchedule = async (token: string, data: ScheduleForm) => {
	let error: string | null = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/schedules/create`, {
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

export const getScheduleById = async (token: string, id: string) => {
	let error: string | null = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/schedules/${id}`, {
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

export const updateScheduleById = async (token: string, id: string, data: ScheduleForm) => {
	let error: string | null = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/schedules/${id}/update`, {
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

export const deleteScheduleById = async (token: string, id: string) => {
	let error: string | null = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/schedules/${id}/delete`, {
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

export const toggleSchedule = async (token: string, id: string) => {
	let error: string | null = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/schedules/${id}/toggle`, {
		method: 'POST',
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

export const runScheduleNow = async (token: string, id: string) => {
	let error: string | null = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/schedules/${id}/run`, {
		method: 'POST',
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

export const getScheduleTasks = async (token: string, id: string) => {
	let error: string | null = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/schedules/${id}/tasks`, {
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

export const shareSchedule = async (token: string, id: string, userIds: string[]) => {
	let error: string | null = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/schedules/${id}/share`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({ user_ids: userIds })
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

export const getRecentTasks = async (token: string) => {
	let error: string | null = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/schedules/tasks/recent`, {
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

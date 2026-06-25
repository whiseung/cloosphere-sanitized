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

export type Project = {
	id: string;
	user_id: string;
	name: string;
	type: string;
	description: string | null;
	knowledge_id: string | null;
	instructions: string | null;
	data: { chat_ids?: string[]; file_metadata?: Record<string, any> } | null;
	meta: {
		color?: string;
		icon?: string;
		copied_from?: {
			user_id: string;
			user_name: string;
			project_id: string;
			project_name: string;
			copied_at: number;
		};
	} | null;
	access_control: object | null;
	created_at: number;
	updated_at: number;
	files?: any[];
	user?: any;
};

export const getProjects = async (token: string) => {
	let error: string | null = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/projects/`, {
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

	if (error) {
		throw error;
	}

	return res;
};

export const createNewProject = async (
	token: string,
	name: string,
	description: string | null,
	instructions: string | null,
	accessControl: null | object,
	type: string = 'general'
) => {
	let error: string | null = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/projects/create`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({
			name: name,
			type: type,
			description: description,
			instructions: instructions,
			access_control: accessControl
		})
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

	if (error) {
		throw error;
	}

	return res;
};

export const getProjectById = async (token: string, id: string) => {
	let error: string | null = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/projects/${id}`, {
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

	if (error) {
		throw error;
	}

	return res;
};

type ProjectUpdateForm = {
	name?: string;
	description?: string;
	instructions?: string;
	meta?: object;
	access_control?: null | object;
};

export const updateProjectById = async (token: string, id: string, form: ProjectUpdateForm) => {
	let error: string | null = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/projects/${id}/update`, {
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
			error = extractErrorMessage(err);
			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const deleteProjectById = async (token: string, id: string) => {
	let error: string | null = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/projects/${id}/delete`, {
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

	if (error) {
		throw error;
	}

	return res;
};

export const addFileToProjectById = async (token: string, id: string, fileId: string) => {
	let error: string | null = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/projects/${id}/file/add`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({
			file_id: fileId
		})
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

	if (error) {
		throw error;
	}

	return res;
};

export const removeFileFromProjectById = async (token: string, id: string, fileId: string) => {
	let error: string | null = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/projects/${id}/file/remove`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({
			file_id: fileId
		})
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

	if (error) {
		throw error;
	}

	return res;
};

export const getProjectChatList = async (token: string, id: string) => {
	let error: string | null = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/projects/${id}/chats`, {
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

	if (error) {
		throw error;
	}

	return res;
};

export const addChatToProject = async (token: string, id: string, chatId: string) => {
	let error: string | null = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/projects/${id}/chat/add`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({
			chat_id: chatId
		})
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

	if (error) {
		throw error;
	}

	return res;
};

export const removeChatFromProject = async (token: string, id: string, chatId: string) => {
	let error: string | null = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/projects/${id}/chat/remove`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({
			chat_id: chatId
		})
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

	if (error) {
		throw error;
	}

	return res;
};

export const shareProject = async (
	token: string,
	id: string,
	userIds: string[]
): Promise<{ copied_count: number; copied_project_ids: string[] }> => {
	let error: string | null = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/projects/${id}/share`, {
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

	if (error) {
		throw error;
	}

	return res;
};

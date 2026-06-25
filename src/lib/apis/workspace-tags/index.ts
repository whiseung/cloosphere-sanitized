import { WEBUI_API_BASE_URL } from '$lib/constants';

export type WorkspaceTag = {
	id: string;
	name: string;
	user_id: string;
	created_at: number;
};

export const getWorkspaceTags = async (token: string): Promise<WorkspaceTag[]> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/workspace-tags/`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) {
				try { throw await res.json(); } catch { throw new Error(`HTTP ${res.status}`); }
			}
			return res.json();
		})
		.catch((err) => {
			console.warn('workspace-tags API error:', err);
			return [];
		});

	return res ?? [];
};

export const createWorkspaceTag = async (
	token: string,
	name: string
): Promise<WorkspaceTag | null> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/workspace-tags/create`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({ name })
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err?.detail ?? err;
			return null;
		});

	if (error) throw error;
	return res;
};

export const updateWorkspaceTag = async (
	token: string,
	id: string,
	name: string
): Promise<WorkspaceTag | null> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/workspace-tags/${id}/update`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({ name })
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err?.detail ?? err;
			return null;
		});

	if (error) throw error;
	return res;
};

export const deleteWorkspaceTag = async (token: string, id: string): Promise<boolean> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/workspace-tags/${id}/delete`, {
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
			error = err?.detail ?? err;
			return false;
		});

	if (error) throw error;
	return res;
};

export const getResourceTags = async (
	token: string,
	resourceType: string,
	resourceId: string
): Promise<WorkspaceTag[]> => {
	let error = null;

	const res = await fetch(
		`${WEBUI_API_BASE_URL}/workspace-tags/resource/${resourceType}/${resourceId}`,
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
			if (!res.ok) {
				try { throw await res.json(); } catch { throw new Error(`HTTP ${res.status}`); }
			}
			return res.json();
		})
		.catch((err) => {
			console.warn('workspace-tags API error:', err);
			return [];
		});

	return res ?? [];
};

export const assignTag = async (
	token: string,
	resourceType: string,
	resourceId: string,
	tagId: string
): Promise<WorkspaceTag[]> => {
	let error = null;

	const res = await fetch(
		`${WEBUI_API_BASE_URL}/workspace-tags/resource/${resourceType}/${resourceId}/assign`,
		{
			method: 'POST',
			headers: {
				Accept: 'application/json',
				'Content-Type': 'application/json',
				authorization: `Bearer ${token}`
			},
			body: JSON.stringify({ tag_id: tagId })
		}
	)
		.then(async (res) => {
			if (!res.ok) {
				try { throw await res.json(); } catch { throw new Error(`HTTP ${res.status}`); }
			}
			return res.json();
		})
		.catch((err) => {
			console.warn('workspace-tags API error:', err);
			return [];
		});

	return res ?? [];
};

export const unassignTag = async (
	token: string,
	resourceType: string,
	resourceId: string,
	tagId: string
): Promise<WorkspaceTag[]> => {
	let error = null;

	const res = await fetch(
		`${WEBUI_API_BASE_URL}/workspace-tags/resource/${resourceType}/${resourceId}/unassign/${tagId}`,
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
			if (!res.ok) {
				try { throw await res.json(); } catch { throw new Error(`HTTP ${res.status}`); }
			}
			return res.json();
		})
		.catch((err) => {
			console.warn('workspace-tags API error:', err);
			return [];
		});

	return res ?? [];
};

export const getAssignmentsByType = async (
	token: string,
	resourceType: string
): Promise<Record<string, string[]>> => {
	let error = null;

	const res = await fetch(
		`${WEBUI_API_BASE_URL}/workspace-tags/assignments/${resourceType}`,
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
			if (!res.ok) {
				try { throw await res.json(); } catch { throw new Error(`HTTP ${res.status}`); }
			}
			return res.json();
		})
		.catch((err) => {
			console.warn('workspace-tags API error:', err);
			return {};
		});

	return res ?? {};
};

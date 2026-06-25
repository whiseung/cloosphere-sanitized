import { WEBUI_API_BASE_URL } from '$lib/constants';

// Types
export interface BiDashboard {
	id: string;
	user_id: string;
	name: string;
	description?: string;
	data?: Record<string, any>;
	meta?: Record<string, any>;
	access_control?: Record<string, any>;
	share_id?: string;
	panel_count?: number;
	created_at: number;
	updated_at: number;
}

export interface BiPanel {
	id: string;
	dashboard_id: string;
	user_id: string;
	name: string;
	description?: string;
	dbsphere_id: string;
	data?: Record<string, any>;
	meta?: Record<string, any>;
	created_at: number;
	updated_at: number;
}

export interface BiDashboardDetail extends BiDashboard {
	panels: BiPanel[];
}

export interface SqlResult {
	columns: string[];
	data: Record<string, any>[];
	row_count: number;
}

export interface GenerateSqlResponse {
	sql: string;
	explanation: string;
	result?: SqlResult;
}

// Helper
const apiCall = async (url: string, options: RequestInit) => {
	let error = null;
	const res = await fetch(url, options)
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

const headers = (token: string) => ({
	Accept: 'application/json',
	'Content-Type': 'application/json',
	authorization: `Bearer ${token}`
});

// Dashboard CRUD
export const getDashboards = async (token: string): Promise<BiDashboard[]> => {
	return apiCall(`${WEBUI_API_BASE_URL}/bi-dashboards/`, {
		method: 'GET',
		headers: headers(token)
	});
};

export const getAccessibleDashboards = async (token: string): Promise<BiDashboard[]> => {
	return apiCall(`${WEBUI_API_BASE_URL}/bi-dashboards/accessible`, {
		method: 'GET',
		headers: headers(token)
	});
};

export const getDashboardById = async (
	token: string,
	id: string
): Promise<BiDashboardDetail> => {
	return apiCall(`${WEBUI_API_BASE_URL}/bi-dashboards/${id}`, {
		method: 'GET',
		headers: headers(token)
	});
};

export const createDashboard = async (
	token: string,
	data: { name: string; description?: string }
): Promise<BiDashboard> => {
	return apiCall(`${WEBUI_API_BASE_URL}/bi-dashboards/create`, {
		method: 'POST',
		headers: headers(token),
		body: JSON.stringify(data)
	});
};

export const updateDashboard = async (
	token: string,
	id: string,
	data: { name: string; description?: string; data?: Record<string, any> }
): Promise<BiDashboard> => {
	return apiCall(`${WEBUI_API_BASE_URL}/bi-dashboards/${id}/update`, {
		method: 'POST',
		headers: headers(token),
		body: JSON.stringify(data)
	});
};

export const deleteDashboard = async (token: string, id: string) => {
	return apiCall(`${WEBUI_API_BASE_URL}/bi-dashboards/${id}/delete`, {
		method: 'DELETE',
		headers: headers(token)
	});
};

// Panel CRUD
export const createPanel = async (
	token: string,
	dashboardId: string,
	data: { name: string; dbsphere_id: string; data?: Record<string, any> }
): Promise<BiPanel> => {
	return apiCall(`${WEBUI_API_BASE_URL}/bi-dashboards/${dashboardId}/panels/create`, {
		method: 'POST',
		headers: headers(token),
		body: JSON.stringify(data)
	});
};

export const updatePanel = async (
	token: string,
	dashboardId: string,
	panelId: string,
	data: { name: string; dbsphere_id: string; data?: Record<string, any> }
): Promise<BiPanel> => {
	return apiCall(
		`${WEBUI_API_BASE_URL}/bi-dashboards/${dashboardId}/panels/${panelId}/update`,
		{
			method: 'POST',
			headers: headers(token),
			body: JSON.stringify(data)
		}
	);
};

export const deletePanel = async (token: string, dashboardId: string, panelId: string) => {
	return apiCall(
		`${WEBUI_API_BASE_URL}/bi-dashboards/${dashboardId}/panels/${panelId}/delete`,
		{
			method: 'DELETE',
			headers: headers(token)
		}
	);
};

export const executePanel = async (
	token: string,
	dashboardId: string,
	panelId: string
): Promise<SqlResult> => {
	return apiCall(
		`${WEBUI_API_BASE_URL}/bi-dashboards/${dashboardId}/panels/${panelId}/execute`,
		{
			method: 'POST',
			headers: headers(token)
		}
	);
};

// SQL Generation & Execution
// Auto Build
export const autoBuildDashboard = async (
	token: string,
	data: { name: string; dbsphere_ids: string[]; model_id: string; prompt?: string },
	signal?: AbortSignal
): Promise<{ success: boolean; dashboard_id: string }> => {
	return apiCall(`${WEBUI_API_BASE_URL}/bi-dashboards/auto-build`, {
		method: 'POST',
		headers: headers(token),
		body: JSON.stringify(data),
		...(signal ? { signal } : {})
	});
};

// Auto Build Chat (Multi-turn AI)
export const autoBuildDashboardChat = async (
	token: string,
	messages: Array<{ role: string; content: string }>,
	modelId: string,
	dashboardId: string = '',
	dbsphereIds?: string[]
): Promise<{
	assistant_message: string;
	pending_input?: { question: string; options: string[] };
	panel_definitions?: any[];
	dashboard_id?: string;
	panel_ids?: string[];
	layout_config?: any;
}> => {
	return apiCall(`${WEBUI_API_BASE_URL}/bi-dashboards/auto-build/chat`, {
		method: 'POST',
		headers: headers(token),
		body: JSON.stringify({
			messages,
			model_id: modelId,
			dashboard_id: dashboardId || undefined,
			dbsphere_ids: dbsphereIds || undefined
		})
	});
};

export const generateSql = async (
	token: string,
	data: { dbsphere_id: string; nl_query: string; model_id: string }
): Promise<GenerateSqlResponse> => {
	return apiCall(`${WEBUI_API_BASE_URL}/bi-dashboards/generate-sql`, {
		method: 'POST',
		headers: headers(token),
		body: JSON.stringify(data)
	});
};

export const executeSql = async (
	token: string,
	data: {
		dbsphere_id: string;
		sql: string;
		sql_template?: string;
		from_value?: string;
		to_value?: string;
		filters?: any[];
	}
): Promise<SqlResult> => {
	return apiCall(`${WEBUI_API_BASE_URL}/bi-dashboards/execute-sql`, {
		method: 'POST',
		headers: headers(token),
		body: JSON.stringify(data)
	});
};

// Share & Export
export const shareDashboard = async (
	token: string,
	dashboardId: string,
	data: { access_control?: Record<string, any> | null }
): Promise<{ share_id: string; share_url: string }> => {
	return apiCall(`${WEBUI_API_BASE_URL}/bi-dashboards/${dashboardId}/share`, {
		method: 'POST',
		headers: headers(token),
		body: JSON.stringify(data)
	});
};

export const unshareDashboard = async (
	token: string,
	dashboardId: string
): Promise<{ success: boolean }> => {
	return apiCall(`${WEBUI_API_BASE_URL}/bi-dashboards/${dashboardId}/share`, {
		method: 'DELETE',
		headers: headers(token)
	});
};

export const getSharedDashboard = async (
	token: string,
	shareId: string
): Promise<BiDashboardDetail> => {
	return apiCall(`${WEBUI_API_BASE_URL}/bi-dashboards/shared/${shareId}`, {
		method: 'GET',
		headers: headers(token)
	});
};

export const executeSharedDashboardSql = async (
	token: string,
	shareId: string,
	data: {
		dbsphere_id: string;
		sql: string;
		sql_template?: string;
		from_value?: string;
		to_value?: string;
		filters?: any[];
	}
): Promise<SqlResult> => {
	return apiCall(`${WEBUI_API_BASE_URL}/bi-dashboards/shared/${shareId}/execute-sql`, {
		method: 'POST',
		headers: headers(token),
		body: JSON.stringify(data)
	});
};

export const exportDashboardHtml = async (
	token: string,
	dashboardId: string,
	data: { from_value?: string; to_value?: string; filters?: any[] }
): Promise<Blob> => {
	const res = await fetch(`${WEBUI_API_BASE_URL}/bi-dashboards/${dashboardId}/export-html`, {
		method: 'POST',
		headers: headers(token),
		body: JSON.stringify(data)
	});
	if (!res.ok) {
		const err = await res.json();
		throw err;
	}
	return res.blob();
};
